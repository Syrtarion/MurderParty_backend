from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.deps.auth import mj_required
from app.services.objective_service import award_objective

router = APIRouter(
    prefix="/master",
    tags=["master"],
    dependencies=[Depends(mj_required)]
)

class AwardPayload(BaseModel):
    player_id: str = Field(..., description="player_id du joueur")
    objective: str = Field(..., description="Objectif accompli")
    points: int = Field(10, description="Points attribués (par défaut 10)")

@router.post("/award_objective")
async def award_objective_route(p: AwardPayload):
    try:
        result = award_objective(p.player_id, p.objective, p.points)
        return {"ok": True, "updated": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
