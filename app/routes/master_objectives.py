"""
Module routes/master_objectives.py
Rôle:
- Permet au MJ d'attribuer des points d'objectifs aux joueurs (récompenses).
- Utilise le service `objective_service.award_objective`.

Sécurité:
- Accès restreint via `mj_required`.

Comportement:
- Lève 404 (ValueError) si le `player_id` est inconnu.
- `points` par défaut à 10, surchargeable dans la requête.
"""
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
    """
    Attribue des points d'objectif à un joueur et retourne l'état mis à jour.
    """
    try:
        result = award_objective(p.player_id, p.objective, p.points)
        return {"ok": True, "updated": result}
    except ValueError as e:
        # ex. joueur introuvable → ValueError levée côté service
        raise HTTPException(status_code=404, detail=str(e))
