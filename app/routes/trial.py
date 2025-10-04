from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.deps.auth import mj_required
from app.services.trial_service import TRIAL, CATEGORIES
from app.services.game_state import GAME_STATE

router = APIRouter(prefix="/trial",tags=["trial"],dependencies=[Depends(mj_required)])


class VotePayload(BaseModel):
    voter_id: str = Field(..., description="player_id du votant")
    category: str = Field(..., description=f"Catégorie: {CATEGORIES}")
    value: str = Field(..., description="Proposition du joueur")


@router.post("/vote")
async def vote(p: VotePayload):
    res = TRIAL.vote(p.voter_id, p.category, p.value)
    GAME_STATE.log_event("vote", {"by": p.voter_id, "category": p.category, "value": p.value})
    return {"ok": True, "record": res}


@router.get("/tally")
async def tally():
    return {"tally": TRIAL.tally()}


@router.post("/verdict")
async def verdict():
    result = TRIAL.finalize()
    GAME_STATE.log_event("verdict", result)
    return result
