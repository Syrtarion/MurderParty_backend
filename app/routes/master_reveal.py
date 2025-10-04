from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.deps.auth import mj_required
from app.services.game_state import GAME_STATE
from app.services.narrative_core import NARRATIVE
from app.services.mission_service import MISSION_SVC

router = APIRouter(
    prefix="/master",
    tags=["master"],
    dependencies=[Depends(mj_required)]
)

class RevealPayload(BaseModel):
    notify_players: bool = True  # si True, log/broadcast (WS) que missions sont prêtes


@router.post("/reveal_culprit")
async def reveal_culprit(p: RevealPayload):
    """
    Révèle au joueur désigné qu'il est le coupable et assigne les missions secrètes
    à tous les joueurs (tirées de story_seed.json sans doublon).
    """
    canon = NARRATIVE.canon
    culprit_pid = canon.get("culprit_player_id")
    if not culprit_pid:
        raise HTTPException(status_code=400, detail="No culprit assigned in canon")

    if culprit_pid not in GAME_STATE.players:
        raise HTTPException(status_code=400, detail="Culprit player not present in players list")

    # Marque le joueur comme coupable (interne seulement)
    GAME_STATE.players[culprit_pid]["is_culprit"] = True

    # Assigne les missions secrètes (coupable + autres, depuis story_seed.json)
    try:
        assigned = MISSION_SVC.assign_missions()
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Log event
    GAME_STATE.log_event("culprit_revealed", {"culprit_player_id": culprit_pid})
    if p.notify_players:
        GAME_STATE.log_event("missions_ready", {"count": len(assigned)})

    # ⚠️ On ne renvoie pas l'identité du coupable
    return {
        "ok": True,
        "missions_assigned_count": len(assigned),
        "message": "Missions secrètes assignées, prêtes à être envoyées aux joueurs."
    }
