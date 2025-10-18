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
"""
from fastapi import APIRouter, Header, HTTPException
from fastapi import Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import List, Optional

from app.deps.auth import mj_required
from app.config.settings import settings
from app.services.session_plan import SESSION_PLAN
from app.services.minigame_catalog import CATALOG
from app.services.minigame_runtime import RUNTIME
from app.utils.team_utils import random_teams
from app.services.game_state import GAME_STATE            # FIX
from app.services.ws_manager import WS                    # FIX
from app.services.envelopes import summary_for_mj         # FIX
from uuid import uuid4

router = APIRouter(prefix="/party", tags=["party"], dependencies=[Depends(mj_required)])

def _mj(auth: str | None):
    """Vérification Bearer MJ optionnelle (non utilisée par défaut)."""
    if not auth or not auth.startswith("Bearer ") or auth.split(" ",1)[1] != settings.MJ_TOKEN:
        raise HTTPException(status_code=403, detail="MJ auth required")

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
        teams = random_teams(body.participants, team_count=body.auto_team_count, team_size=body.auto_team_size, seed=body.seed)
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
    env_total    = env_summary.get("total", 0)
    env_assigned = env_summary.get("assigned", 0)
    env_left     = env_summary.get("left", 0)

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
