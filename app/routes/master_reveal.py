from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.deps.auth import mj_required
from app.services.game_state import GAME_STATE
from app.services.narrative_core import NARRATIVE
from app.services.mission_service import MISSION_SVC
from app.services.ws_manager import WS

router = APIRouter(
    prefix="/master",
    tags=["master"],
    dependencies=[Depends(mj_required)]
)

class RevealPayload(BaseModel):
    notify_players: bool = True


@router.post("/reveal_culprit")
async def reveal_culprit(p: RevealPayload):
    canon = NARRATIVE.canon
    culprit_pid = canon.get("culprit_player_id")
    if not culprit_pid:
        raise HTTPException(status_code=400, detail="No culprit assigned in canon")

    if culprit_pid not in GAME_STATE.players:
        raise HTTPException(status_code=400, detail="Culprit player not present in players list")

    # Mark culprit internally
    GAME_STATE.players[culprit_pid]["is_culprit"] = True

    # Assign missions via seed pools (unique per player)
    assigned = MISSION_SVC.assign_missions()

    # Push missions to players via WS (best-effort)
    for pid, mission in assigned.items():
        await WS.send_to_player(pid, {"type": "secret_mission", "mission": mission})

    GAME_STATE.log_event("culprit_revealed", {"culprit_player_id": culprit_pid})
    if p.notify_players:
        await WS.broadcast({"type": "event", "kind": "missions_ready", "payload": {"count": len(assigned)}})
        GAME_STATE.log_event("missions_ready", {"count": len(assigned)})

    return {"ok": True, "missions_assigned_count": len(assigned)}
