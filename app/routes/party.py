"""
Module routes/party.py
Rôle:
- Gestion du "plan de soirée" (enchaînement des mini-jeux/rounds).
- Charge un plan (séquence d'IDs de jeux) et lance le "prochain round".

Intégrations:
- SESSION_PLAN: stockage du plan courant + curseur.
- CATALOG: validation des IDs jeux utilisés dans le plan.
- RUNTIME: création des sessions de mini-jeux.
- random_teams: tirage d'équipes si mode team.

Sécurité:
- Accès MJ (`mj_required`).

Endpoints:
- POST /party/load_plan: enregistre la séquence des jeux (avec round optionnel).
- POST /party/next_round: crée la session suivante et avance le curseur.

# FIX (Lot A):
- POST /party/start  : (ré)initialise la partie (phase JOIN, inscriptions ouvertes)
- GET  /party/status : snapshot synthétique (phase, lock, joueurs, enveloppes)

# AJOUT (Lot B):
- POST /party/envelopes_hidden : passe en ENVELOPES_HIDDEN (les enveloppes sont cachées physiquement).
- POST /party/roles_assign     : consomme le canon, assigne killer/innocents + missions secondaires et notifie via WS.
"""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from uuid import uuid4
import hashlib

from app.deps.auth import mj_required
from app.config.settings import settings
from app.services.session_plan import SESSION_PLAN
from app.services.minigame_catalog import CATALOG
from app.services.minigame_runtime import RUNTIME
from app.utils.team_utils import random_teams

# Lot A
from app.services.game_state import GAME_STATE
from app.services.ws_manager import WS
from app.services.envelopes import summary_for_mj

# Lot B (canon & rôles)
from app.services.narrative_core import NARRATIVE  # canon LLM stocké ici par master_canon


router = APIRouter(prefix="/party", tags=["party"], dependencies=[Depends(mj_required)])


def _mj(auth: str | None):
    """Vérification Bearer MJ optionnelle (non utilisée par défaut)."""
    if not auth or not auth.startswith("Bearer ") or auth.split(" ", 1)[1] != settings.MJ_TOKEN:
        raise HTTPException(status_code=403, detail="MJ auth required")


# ======================
# Plan / Next Round (C)
# ======================

class PlanPayload(BaseModel):
    session_id: str
    games_sequence: List[dict] = Field(default_factory=list, description="Liste d'objets {id, round?}")


@router.post("/load_plan")
async def load_plan(p: PlanPayload):
    """
    Charge un plan de jeux (séquence d'IDs).
    - Valide que tous les IDs existent dans le catalogue.
    """
    ids = [g.get("id") for g in p.games_sequence]
    missing = [i for i in ids if not CATALOG.get(i)]
    if missing:
        raise HTTPException(400, f"Unknown minigame ids: {missing}")
    SESSION_PLAN.set_plan(p.model_dump())
    return {"ok": True, "loaded": len(p.games_sequence)}


class NextRoundPayload(BaseModel):
    # Pour le mode team sans équipes fournies, on peut tirer automatiquement
    participants: Optional[List[str]] = None
    auto_team_count: Optional[int] = None
    auto_team_size: Optional[int] = None
    seed: Optional[int] = None


@router.post("/next_round")
async def next_round(body: NextRoundPayload):
    """
    Démarre le round suivant selon le plan:
    - Crée une nouvelle session RUNTIME (solo ou team).
    - Incrémente le curseur du plan.
    """
    current = SESSION_PLAN.current()
    if not current:
        raise HTTPException(404, "No current round in plan. Did you load a plan?")
    game_id = current["id"]
    game = CATALOG.get(game_id)
    if not game:
        raise HTTPException(404, "Unknown game in catalog")

    session = {
        "session_id": f"MG-{uuid4().hex[:8]}",
        "game_id": game_id,
        "mode": game["mode"],
        "status": "running",
        "scores": {}
    }

    if game["mode"] == "solo":
        if not body.participants:
            raise HTTPException(400, "participants (player_ids) required for solo mode")
        session["participants"] = body.participants
        session["teams"] = None
    else:
        if not body.participants:
            raise HTTPException(400, "participants (player_ids) required to draw teams")
        teams = random_teams(
            body.participants,
            team_count=body.auto_team_count,
            team_size=body.auto_team_size,
            seed=body.seed
        )
        session["participants"] = list(teams.keys())
        session["teams"] = teams

    RUNTIME.create(session)
    # Avance le curseur du plan (round suivant prêt)
    SESSION_PLAN.next()
    return {"ok": True, "session": session}


# ===========================
# FIX (Lot A): socle & status
# ===========================

@router.post("/start")
async def party_start():
    """
    (Ré)initialise la partie au stade JOIN (inscriptions ouvertes).
    - phase_label = "JOIN"
    - join_locked = False
    - log + persist + WS 'phase_change'
    """
    try:
        GAME_STATE.state.setdefault("phase_label", "JOIN")
        GAME_STATE.state["phase_label"] = "JOIN"
        GAME_STATE.state["join_locked"] = False
        GAME_STATE.log_event("party_started", {"phase": "JOIN", "join_locked": False})
        GAME_STATE.save()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cannot start party: {e}")

    await WS.broadcast_type("event", {"kind": "phase_change", "phase": "JOIN"})
    return {"ok": True, "phase": "JOIN", "join_locked": False}


@router.get("/status")
def party_status():
    """
    Snapshot synthétique d'état :
    - phase_label, join_locked
    - players_count
    - envelopes: total / assigned / left
    (Pas de détail d'enveloppes ici)
    """
    phase = GAME_STATE.state.get("phase_label", "JOIN")
    join_locked = bool(GAME_STATE.state.get("join_locked", False))
    players_count = len(GAME_STATE.players)

    env_summary = summary_for_mj(include_hints=False)
    env_total = env_summary.get("total", 0)
    env_assigned = env_summary.get("assigned", 0)
    env_left = env_summary.get("left", 0)

    return JSONResponse(content={
        "ok": True,
        "phase_label": phase,
        "join_locked": join_locked,
        "players_count": players_count,
        "envelopes": {
            "total": env_total,
            "assigned": env_assigned,
            "left": env_left
        }
    })


# ===========================
# AJOUT (Lot B): phases/roles
# ===========================

def _stable_choice(items: List[str], salt: str = "canon") -> str:
    """
    Choix déterministe (pas de random pur) pour des tests reproductibles.
    Se base sur l'ordre des players + phase courante + sel.
    """
    if not items:
        return ""
    h = hashlib.sha256()
    players = sorted(GAME_STATE.players.keys())
    h.update(("|".join(players) + "|" + (GAME_STATE.state.get("phase_label") or "") + "|" + salt).encode("utf-8"))
    idx = int(h.hexdigest(), 16) % len(items)
    return items[idx]


def _ensure_canon_in_game_state() -> Dict[str, Any]:
    """
    S'assure qu'un canon est disponible dans GAME_STATE.state["canon"].
    - source privilégiée : NARRATIVE.canon (écrit par /master/generate_canon)
    - sinon -> erreur 409 (le MJ doit d'abord générer le canon)
    """
    canon = GAME_STATE.state.get("canon")
    if isinstance(canon, dict) and canon.get("weapon"):
        return canon

    canon = getattr(NARRATIVE, "canon", None)
    if isinstance(canon, dict) and canon.get("weapon"):
        GAME_STATE.state["canon"] = canon
        GAME_STATE.save()
        return canon

    raise HTTPException(status_code=409, detail="Canon absent. Générez d'abord via /master/generate_canon.")


@router.post("/envelopes_hidden")
async def envelopes_hidden():
    """
    Phase: ENVELOPES_HIDDEN
    - Pré-requis: distribution ok / enveloppes cachées physiquement.
    - Met à jour la phase + broadcast WS 'phase_change' & 'envelopes_hidden'.
    """
    try:
        GAME_STATE.state["phase_label"] = "ENVELOPES_HIDDEN"
        GAME_STATE.log_event("phase_change", {"phase": "ENVELOPES_HIDDEN"})
        GAME_STATE.save()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cannot set ENVELOPES_HIDDEN: {e}")

    await WS.broadcast_type("event", {"kind": "phase_change", "phase": "ENVELOPES_HIDDEN"})
    await WS.broadcast_type("event", {"kind": "envelopes_hidden"})
    return {"ok": True, "phase": "ENVELOPES_HIDDEN"}


@router.post("/roles_assign")
async def roles_assign():
    """
    Phase: ROLES_ASSIGNED
    - Pré-requis: un canon narratif existe (via /master/generate_canon).
    - Assigne 1 tueur + missions secondaires à tous les joueurs.
    - Envoie des WS ciblés:
        • role_reveal
        • secret_mission
    - Broadcast non-spoilant: 'roles_assigned' + 'phase_change'
    """
    # 0) joueurs présents ?
    if not GAME_STATE.players:
        raise HTTPException(400, "No players registered")

    # 1) s'assurer d'un canon disponible dans GAME_STATE
    canon = _ensure_canon_in_game_state()

    # 2) choisir le killer :
    #    - priorité : culprit_player_id choisi par /master/generate_canon
    #    - sinon : choix déterministe stable parmi les joueurs
    pids_sorted = sorted(GAME_STATE.players.keys())
    culprit_pid = canon.get("culprit_player_id")
    if not culprit_pid or culprit_pid not in pids_sorted:
        culprit_pid = _stable_choice(pids_sorted, "killer") or pids_sorted[0]

    # 3) attribuer rôles + missions
    per_player: Dict[str, Any] = {}
    for pid in pids_sorted:
        role = "killer" if pid == culprit_pid else "innocent"
        if role == "killer":
            mission = {
                "title": "Échapper aux soupçons",
                "text": "Sème le doute sur un autre invité sans te faire remarquer."
            }
        else:
            mission = {
                "title": "Observer discrètement",
                "text": "Récolte 2 indices qui disculpent un autre joueur et partage-les."
            }
        GAME_STATE.players[pid]["role"] = role
        GAME_STATE.players[pid]["mission"] = mission
        per_player[pid] = {"role": role, "mission": mission}

    # 4) mise à jour phase + logs
    try:
        GAME_STATE.state["phase_label"] = "ROLES_ASSIGNED"
        GAME_STATE.log_event("roles_assigned", {"killer_player_id": culprit_pid})
        GAME_STATE.log_event("phase_change", {"phase": "ROLES_ASSIGNED"})
        GAME_STATE.save()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cannot assign roles/missions: {e}")

    # 5) WS ciblés (pas de spoiler en broadcast)
    from app.services.ws_manager import ws_send_type_to_player_safe  # import local pour éviter cycles
    for pid, data in per_player.items():
        ws_send_type_to_player_safe(pid, "role_reveal", {"role": data["role"]})
        ws_send_type_to_player_safe(pid, "secret_mission", data["mission"])

    # 6) broadcast de signal
    await WS.broadcast_type("event", {"kind": "roles_assigned"})
    await WS.broadcast_type("event", {"kind": "phase_change", "phase": "ROLES_ASSIGNED"})

    return {
        "ok": True,
        "phase": "ROLES_ASSIGNED",
        "killer_player_id": culprit_pid,
        "canon": canon,
        "players": list(GAME_STATE.players.values()),
    }
