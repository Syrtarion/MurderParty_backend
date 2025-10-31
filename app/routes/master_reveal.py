"""
Reveal culprit and dispatch secret missions for a given session.
"""
from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps.auth import mj_required
from app.services.session_store import DEFAULT_SESSION_ID, get_session_state
from app.services.narrative_core import NARRATIVE
from app.services.mission_service import MISSION_SVC
from app.services.ws_manager import ws_send_to_player_safe


router = APIRouter(prefix="/master", tags=["master"], dependencies=[Depends(mj_required)])


def _normalize_session_id(session_id: str | None) -> str:
    sid = (session_id or DEFAULT_SESSION_ID).strip()
    return sid or DEFAULT_SESSION_ID


@router.post("/reveal_culprit")
async def reveal_culprit(session_id: str | None = Query(default=None)):
    sid = _normalize_session_id(session_id)
    state = get_session_state(sid)

    canon = state.state.get("canon") or NARRATIVE.canon
    culprit_pid = canon.get("culprit_player_id") if isinstance(canon, dict) else None
    if not culprit_pid:
        raise HTTPException(status_code=400, detail="Aucun coupable défini dans le canon narratif.")
    if culprit_pid not in state.players:
        raise HTTPException(status_code=400, detail="Le joueur coupable n'est pas présent dans la partie.")

    state.players[culprit_pid]["is_culprit"] = True
    try:
        assigned = MISSION_SVC.assign_missions(game_state=state)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erreur d'attribution des missions : {exc}") from exc

    for pid, mission in assigned.items():
        ws_send_to_player_safe(pid, {"type": "secret_mission", "mission": mission, "session_id": sid})

    state.log_event("culprit_revealed", {"culprit_player_id": culprit_pid})
    state.log_event("missions_ready", {"count": len(assigned)})

    for pid in state.players.keys():
        ws_send_to_player_safe(
            pid,
            {
                "type": "event",
                "kind": "missions_ready",
                "payload": {"count": len(assigned), "session_id": sid},
            },
        )

    culprit_entry = state.players[culprit_pid]
    return {
        "ok": True,
        "culprit_player_id": culprit_pid,
        "culprit_name": culprit_entry.get("character") or culprit_entry.get("display_name"),
        "missions_assigned_count": len(assigned),
    }
