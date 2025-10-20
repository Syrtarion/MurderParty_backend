"""
Module routes/master.py
Rôle:
- Endpoints MJ pour piloter la narration: choix du coupable, génération d’indices,
  narration dynamique (mini-jeux, enveloppes, ambiance), timeline complète,
  et verrouillage/déverrouillage des inscriptions.

Sécurité:
- Router protégé par `mj_required`.
- Helper `_require_bearer` disponible mais non utilisé par les routes actuelles
  (on s’appuie sur `mj_required`; `_require_bearer` garde une option de double check).

Intégrations:
- NARRATIVE: lecture/écriture du canon et timeline.
- GAME_STATE: log d'événements + persist.
- generate_indice / generate_dynamic_event: moteurs narratifs LLM.
- WS: diffusion temps réel aux clients.
"""
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, Field
from fastapi.responses import JSONResponse
from typing import Optional
import json, os

from app.deps.auth import mj_required
from app.config.settings import settings
from app.services.narrative_core import NARRATIVE
from app.services.game_state import GAME_STATE
from app.services.llm_engine import generate_indice
from app.services.ws_manager import WS, ws_send_type_to_player_safe
from app.services.narrative_dynamic import generate_dynamic_event

# Enveloppes
from app.services.envelopes import (
    distribute_envelopes_equitable,
    summary_for_mj,
    reset_envelope_assignments,
    player_envelopes,         # helper joueur
    assign_envelope_to_player # bonus
)

router = APIRouter(prefix="/master", tags=["master"], dependencies=[Depends(mj_required)])


# --------------------------------------------------
# Vérification du token MJ (sécurité API)
# --------------------------------------------------
def _require_bearer(auth: str | None):
    """
    Vérifie un token Bearer MJ explicite.
    Non requis si `mj_required` est déjà en place au niveau router.
    """
    if not auth or not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = auth.split(" ", 1)[1]
    if token != settings.MJ_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")


# --------------------------------------------------
# Choix manuel du coupable
# --------------------------------------------------
class CulpritPayload(BaseModel):
    culprit: str
    weapon: str
    location: str
    motive: str


@router.post("/choose_culprit")
async def choose_culprit(payload: CulpritPayload):
    """
    Verrouille manuellement le canon avec un coupable + (arme, lieu, mobile).
    - Log l’événement "canon_locked" + broadcast WS aux clients.
    """
    canon = NARRATIVE.choose_culprit(payload.culprit, payload.weapon, payload.location, payload.motive)
    GAME_STATE.log_event("canon_locked", {k: canon.get(k) for k in ("culprit", "weapon", "location", "motive")})
    await WS.broadcast({"type": "canon_locked", "payload": canon})
    return canon


# --------------------------------------------------
# Génération manuelle d’un indice ponctuel
# --------------------------------------------------
class IndicePayload(BaseModel):
    prompt: str = Field(..., description="Consigne spécifique pour l'indice")
    kind: str = Field("ambiguous", description="crucial | red_herrings | ambiguous | decor")


@router.post("/generate_indice")
async def generate_indice_route(payload: IndicePayload):
    """
    Génère un indice unique basé sur `prompt` + `kind`.
    - Enrichit le canon via `NARRATIVE.append_clue`.
    - Log l’événement et diffuse via WS.
    """
    user_prompt = "Donne uniquement l'indice, sans préambule. Limite à 1–2 phrases. " + payload.prompt
    result = generate_indice(user_prompt, payload.kind)
    NARRATIVE.append_clue(payload.kind, {"text": result.get("text", ""), "kind": payload.kind})
    GAME_STATE.log_event("clue_generated", {"kind": payload.kind, "text": result.get("text", "")})
    await WS.broadcast({"type": "clue_generated", "payload": result})
    return result


# --------------------------------------------------
# NARRATION DYNAMIQUE : mini-jeux, enveloppes, ambiance
# --------------------------------------------------

class MiniGameResultPayload(BaseModel):
    mode: str = "solo"  # "solo" ou "team"
    winners: list[str]
    losers: list[str]
    mini_game: str | None = None


class EnvelopeScanPayload(BaseModel):
    player_id: str
    envelope_id: str | int


class StoryEventPayload(BaseModel):
    theme: str
    context: dict | None = None


@router.post("/narrate_mg_end")
async def narrate_after_minigame(p: MiniGameResultPayload):
    """Crée la narration et distribue les indices après un mini-jeu."""
    try:
        result = generate_dynamic_event("mini_game_end", p.dict())
        return {"ok": True, "detail": result}
    except Exception as e:
        # La route renvoie une 500 "lisible" pour le front MJ
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/narrate_envelope")
async def narrate_after_envelope(p: EnvelopeScanPayload):
    """Génère la narration et l’indice global après le scan d’une enveloppe."""
    try:
        result = generate_dynamic_event("envelope_scanned", p.dict())
        return {"ok": True, "detail": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/narrate_auto")
async def narrate_auto_event(p: StoryEventPayload):
    """Déclenche une narration automatique (transition, ambiance, etc.)."""
    try:
        result = generate_dynamic_event("narration_trigger", p.dict())
        return {"ok": True, "detail": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/timeline", tags=["admin"])
async def get_full_timeline():
    """
    Retourne l'intégralité du canon narratif (timeline complète).
    Accessible via /master/timeline
    """
    canon = NARRATIVE.canon or {}
    timeline = canon.get("timeline", [])
    meta = {
        "count": len(timeline),
        "last_event": timeline[-1]["event"] if timeline else None,
    }
    return JSONResponse(content={"ok": True, "meta": meta, "timeline": timeline})


# --------------------------------------------------
# Verrouiller / Déverrouiller la phase JOIN
# --------------------------------------------------
@router.post("/lock_join")
async def lock_join():
    """
    Verrouille la phase d'inscription (empêche /auth/register) ET lance la distribution équitable.
    - Met à jour la phase -> ENVELOPES_DISTRIBUTION (les enveloppes doivent être cachées ensuite).
    - Distribution: lit d’abord le GAME_STATE; si aucune enveloppe, lit le story_seed.json (disque).
    - Log + persist.
    - Diffuse en WS :
        • events globaux: 'join_locked', 'phase_change', 'envelopes_update'
        • + ciblé: 'envelopes_update' avec la liste {num,id} pour CHAQUE joueur.
    """
    try:
        # 1) verrou + phase
        GAME_STATE.state["join_locked"] = True
        GAME_STATE.state["phase_label"] = "ENVELOPES_DISTRIBUTION"
        GAME_STATE.log_event("join_locked", {})
        GAME_STATE.log_event("phase_change", {"phase": "ENVELOPES_DISTRIBUTION"})

        # 2) distribution (équitable & idempotent, vue joueur = num/id uniquement)
        distribution_summary = distribute_envelopes_equitable()
        GAME_STATE.log_event("envelopes_distributed", distribution_summary)

        # 3) persist
        GAME_STATE.save()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cannot lock/distribute: {e}")

    # 4) broadcast temps réel (global)
    await WS.broadcast_type("event", {"kind": "join_locked"})
    await WS.broadcast_type("event", {"kind": "phase_change", "phase": "ENVELOPES_DISTRIBUTION"})
    await WS.broadcast_type("event", {"kind": "envelopes_update"})

    # 5) ciblé par joueur : liste complète des enveloppes (num,id) -> MAJ instantanée côté front joueur
    try:
        for pid in list(GAME_STATE.players.keys()):
            envs = player_envelopes(pid)
            ws_send_type_to_player_safe(pid, "event", {
                "kind": "envelopes_update",
                "player_id": pid,
                "envelopes": envs,
            })
    except Exception as e:
        # Ne bloque pas la réponse HTTP — log
        print(f"[WS] envelopes_update ciblé: {e}")

    return {
        "ok": True,
        "join_locked": True,
        "phase": "ENVELOPES_DISTRIBUTION",
        "distribution": distribution_summary,
    }


@router.post("/unlock_join")
async def unlock_join():
    """
    Rouvre la phase d'inscription (sans changer la phase courante).
    - Log + persist + broadcast WS d’un event 'join_unlocked'.
    """
    try:
        GAME_STATE.state["join_locked"] = False
        GAME_STATE.log_event("join_unlocked", {})
        GAME_STATE.save()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cannot unlock join: {e}")
    await WS.broadcast_type("event", {"kind": "join_unlocked"})
    return {"ok": True, "join_locked": False}


# --------------------------------------------------
# Diagnostics & maintenance enveloppes / seed
# --------------------------------------------------
@router.get("/envelopes/summary")
async def envelopes_summary(include_hints: bool = False):
    """
    Vue MJ: résumé enveloppes. PRIORITÉ: GAME_STATE (mémoire). Si rien en mémoire,
    retombe sur le story_seed du disque (géré dans summary_for_mj()).
    """
    return summary_for_mj(include_hints=include_hints)

@router.post("/envelopes/reset")
async def envelopes_reset():
    """
    Réinitialise assigned_player_id=None pour TOUTES les enveloppes du seed en mémoire,
    resynchronise la vue joueur, sauvegarde + notifie les fronts.
    """
    res = reset_envelope_assignments()
    await WS.broadcast_type("event", {"kind": "envelopes_update"})
    return res

def _seed_default_path() -> str:
    """
    FIX: fallback = app/data/story_seed.json
    Essaie d’abord settings.STORY_SEED_PATH si dispo (pour override via .env),
    sinon utilise le chemin par défaut unique du repo: app/data/story_seed.json.
    """
    try:
        if getattr(settings, "STORY_SEED_PATH", None):
            return str(settings.STORY_SEED_PATH)
    except Exception:
        pass
    # FIX: utiliser un chemin robuste basé sur ce fichier pour atteindre app/data/...
    from pathlib import Path
    app_dir = Path(__file__).resolve().parents[1]  # -> .../app/
    return str((app_dir / "data" / "story_seed.json").resolve())

@router.post("/seed/reload")
async def seed_reload(path: Optional[str] = None):
    """
    Recharge le story_seed depuis le disque dans GAME_STATE.state["story_seed"], sans redémarrer.
    - path optionnel: si omis, utilise _seed_default_path()
    """
    seed_path = path or _seed_default_path()
    if not os.path.exists(seed_path):
        raise HTTPException(404, f"Seed file not found: {seed_path}")
    try:
        with open(seed_path, "r", encoding="utf-8") as f:
            seed = json.load(f)
        GAME_STATE.state["story_seed"] = seed
        GAME_STATE.log_event("seed_reloaded", {"path": seed_path, "envelopes_count": len(seed.get("envelopes", []))})
        GAME_STATE.save()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Seed reload failed: {e}")

    await WS.broadcast_type("event", {"kind": "seed_reloaded"})
    return {"ok": True, "path": seed_path, "envelopes_count": len(seed.get("envelopes", []))}

# --------------------------------------------------
# BONUS — Réassigner une enveloppe à un joueur (live)
# --------------------------------------------------
class AssignEnvelopePayload(BaseModel):
    envelope_id: str | int
    player_id: str

@router.post("/envelopes/assign")
async def envelopes_assign(p: AssignEnvelopePayload):
    """
    BONUS MJ:
    (Ré)assigne une enveloppe à un joueur.
    - Met à jour le seed en mémoire
    - Resynchronise la vue joueur
    - Notifie EN LIVE:
        • nouveau propriétaire => event 'envelopes_update' avec sa liste
        • ancien propriétaire (si existait) => event 'envelopes_update' avec SA nouvelle liste
    """
    res = assign_envelope_to_player(p.envelope_id, p.player_id)
    if not res.get("ok"):
        raise HTTPException(404, detail="envelope_not_found")

    # notifications ciblées
    try:
        # nouveau propriétaire
        new_envs = player_envelopes(p.player_id)
        ws_send_type_to_player_safe(p.player_id, "event", {
            "kind": "envelopes_update",
            "player_id": p.player_id,
            "envelopes": new_envs,
        })

        # ancien propriétaire (si différent et existait)
        prev_owner = res.get("previous_owner")
        if prev_owner and prev_owner != p.player_id:
            prev_envs = player_envelopes(prev_owner)
            ws_send_type_to_player_safe(prev_owner, "event", {
                "kind": "envelopes_update",
                "player_id": prev_owner,
                "envelopes": prev_envs,
            })
    except Exception as e:
        print(f"[WS] envelopes_assign notify error: {e}")

    return res
