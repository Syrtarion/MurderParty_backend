from fastapi import APIRouter, Depends, HTTPException

from app.deps.auth import mj_required
from app.services.game_state import GAME_STATE
from app.services.narrative_core import NARRATIVE
from app.services.mission_service import MISSION_SVC
from app.services.ws_manager import ws_send_to_player_safe, ws_broadcast_safe

router = APIRouter(
    prefix="/master",
    tags=["master"],
    dependencies=[Depends(mj_required)]
)

@router.post("/reveal_culprit")
async def reveal_culprit():
    """
    Désigne le coupable, attribue les missions uniques à chaque joueur,
    et notifie les participants via WebSocket.
    """
    canon = NARRATIVE.canon
    culprit_pid = canon.get("culprit_player_id")
    if not culprit_pid:
        raise HTTPException(status_code=400, detail="Aucun coupable défini dans le canon narratif.")

    if culprit_pid not in GAME_STATE.players:
        raise HTTPException(status_code=400, detail="Le joueur coupable n'est pas présent dans la partie.")

    # Marquer le coupable
    GAME_STATE.players[culprit_pid]["is_culprit"] = True

    # Attribution des missions (pool unique, via story_seed.json)
    try:
        assigned = MISSION_SVC.assign_missions()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur d'attribution des missions : {e}")

    # Envoi des missions secrètes à chaque joueur (thread-safe)
    for pid, mission in assigned.items():
        ws_send_to_player_safe(pid, {"type": "secret_mission", "mission": mission})

    # Log de l’événement principal
    GAME_STATE.log_event("culprit_revealed", {"culprit_player_id": culprit_pid})

    # Diffusion d’un signal global (missions prêtes)
    ws_broadcast_safe({
        "type": "event",
        "kind": "missions_ready",
        "payload": {"count": len(assigned)}
    })
    GAME_STATE.log_event("missions_ready", {"count": len(assigned)})

    return {
        "ok": True,
        "culprit_player_id": culprit_pid,
        "culprit_name": GAME_STATE.players[culprit_pid].get("character") or GAME_STATE.players[culprit_pid].get("display_name"),
        "missions_assigned_count": len(assigned)
    }
