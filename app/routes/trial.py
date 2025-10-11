from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.deps.auth import mj_required
from app.services.trial_service import TRIAL, CATEGORIES
from app.services.game_state import GAME_STATE, register_event

router = APIRouter(prefix="/trial", tags=["trial"], dependencies=[Depends(mj_required)])


class VotePayload(BaseModel):
    voter_id: str = Field(..., description="player_id du votant")
    category: str = Field(..., description=f"Catégorie: {CATEGORIES}")
    value: str = Field(..., description="Proposition du joueur")


@router.post("/vote")
async def vote(p: VotePayload):
    res = TRIAL.vote(p.voter_id, p.category, p.value)
    register_event("vote", {"by": p.voter_id, "category": p.category, "value": p.value})
    return {"ok": True, "record": res}


@router.get("/tally")
async def tally():
    return {"tally": TRIAL.tally()}


@router.post("/verdict")
async def verdict():
    result = TRIAL.finalize()
    register_event("trial_verdict", {"result": "success", "detail": result})
    return result


@router.get("/leaderboard")
async def trial_leaderboard():
    players = [
        {
            "player_id": pid,
            "name": pdata.get("character") or pdata.get("display_name") or pid,
            "score_total": pdata.get("score_total", 0)
        }
        for pid, pdata in GAME_STATE.players.items()
    ]
    players_sorted = sorted(players, key=lambda p: p["score_total"], reverse=True)
    return {"ok": True, "leaderboard": players_sorted}
