from fastapi import APIRouter, Header, HTTPException, Query, Depends
from app.config.settings import settings
from app.services.game_state import GAME_STATE
from app.services.minigame_runtime import RUNTIME
from app.deps.auth import mj_required

router = APIRouter(
    prefix="/master",
    tags=["master"],
    dependencies=[Depends(mj_required)]
)

def _mj(auth: str | None):
    if not auth or not auth.startswith("Bearer ") or auth.split(" ",1)[1] != settings.MJ_TOKEN:
        raise HTTPException(status_code=403, detail="MJ auth required")

@router.get("/events")
async def list_events(
    limit: int = Query(100, ge=1, le=1000),
    authorization: str | None = Header(default=None, alias="Authorization"),
):
    _mj(authorization)
    return {"events": GAME_STATE.events[-limit:]}

@router.get("/sessions/active")
async def sessions_active(authorization: str | None = Header(default=None, alias="Authorization")):
    _mj(authorization)
    return {"active": RUNTIME.state.get("active", [])}

@router.get("/sessions/history")
async def sessions_history(
    limit: int = Query(100, ge=1, le=1000),
    authorization: str | None = Header(default=None, alias="Authorization"),
):
    _mj(authorization)
    history = RUNTIME.state.get("history", [])
    return {"history": history[-limit:]}
