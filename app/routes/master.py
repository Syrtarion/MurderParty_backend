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
from app.deps.auth import mj_required
from app.config.settings import settings
from app.services.narrative_core import NARRATIVE
from app.services.game_state import GAME_STATE
from app.services.llm_engine import generate_indice
from app.services.ws_manager import WS
from app.services.narrative_dynamic import generate_dynamic_event

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
# Verrouiller la phase JOIN (plus de créations de joueurs)
# --------------------------------------------------
@router.post("/lock_join")
async def lock_join():
    """
    Verrouille la phase d'inscription (empêche /auth/register).
    - Log + persist + broadcast WS d’un event 'join_locked'.
    """
    try:
        GAME_STATE.state["join_locked"] = True
        GAME_STATE.log_event("join_locked", {})
        GAME_STATE.save()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cannot lock join: {e}")
    await WS.broadcast_type("event", {"kind": "join_locked"})
    return {"ok": True, "join_locked": True}

@router.post("/unlock_join")
async def unlock_join():
    """
    Rouvre la phase d'inscription.
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
