from fastapi import APIRouter, Header, HTTPException
from fastapi import Depends
from app.deps.auth import mj_required
from pydantic import BaseModel, Field
from typing import List, Optional

from app.config.settings import settings
from app.services.session_plan import SESSION_PLAN
from app.services.minigame_catalog import CATALOG
from app.services.minigame_runtime import RUNTIME
from app.utils.team_utils import random_teams
from uuid import uuid4

router = APIRouter(prefix="/party", tags=["party"], dependencies=[Depends(mj_required)])

def _mj(auth: str | None):
    if not auth or not auth.startswith("Bearer ") or auth.split(" ",1)[1] != settings.MJ_TOKEN:
        raise HTTPException(status_code=403, detail="MJ auth required")

class PlanPayload(BaseModel):
    session_id: str
    games_sequence: List[dict] = Field(default_factory=list, description="Liste d'objets {id, round?}")

@router.post("/load_plan")
async def load_plan(p: PlanPayload):
    # Validation minimale : ids existants dans le catalogue
    ids = [g.get("id") for g in p.games_sequence]
    missing = [i for i in ids if not CATALOG.get(i)]
    if missing:
        raise HTTPException(400, f"Unknown minigame ids: {missing}")
    SESSION_PLAN.set_plan(p.model_dump())
    return {"ok": True, "loaded": len(p.games_sequence)}

class NextRoundPayload(BaseModel):
    # pour le mode team sans teams fournies, on peut auto-tirer depuis une liste de joueurs
    participants: Optional[List[str]] = None
    auto_team_count: Optional[int] = None
    auto_team_size: Optional[int] = None
    seed: Optional[int] = None

@router.post("/next_round")
async def next_round(body: NextRoundPayload):
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
    # avance le curseur
    SESSION_PLAN.next()
    return {"ok": True, "session": session}
