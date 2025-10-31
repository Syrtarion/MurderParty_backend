"""
Module routes/players.py
Rôle:
- Inscription simplifiée d’un joueur (sans mot de passe ici).

Intégrations:
- Multi-session: chaque inscription cible un `session_id` (direct ou via join_code).
- Persistance des métadonnées minimales (player_id, display_name).
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services.session_store import (
    DEFAULT_SESSION_ID,
    find_session_id_by_join_code,
    get_session_state,
)

router = APIRouter(prefix="/players", tags=["players"])

class JoinPayload(BaseModel):
    display_name: str | None = None

def _resolve_session_id(
    session_id: str | None,
    join_code: str | None,
) -> str:
    sid = (session_id or "").strip()
    if sid:
        return sid
    resolved = find_session_id_by_join_code(join_code)
    if join_code and not resolved:
        raise HTTPException(status_code=404, detail="session_not_found")
    return resolved or DEFAULT_SESSION_ID

@router.post("/join")
async def join(
    payload: JoinPayload,
    session_id: str | None = Query(default=None, description="Identifiant explicite de session"),
    join_code: str | None = Query(default=None, description="Code de session partagé par le MJ"),
):
    """Inscription d'un joueur -> retourne un player_id unique (sans assigner de personnage)."""
    sid = _resolve_session_id(session_id, join_code)
    state = get_session_state(sid)

    player_id = state.add_player(payload.display_name)

    state.save()
    state.log_event(
        "player_join_registered",
        {
            "player_id": player_id,
            "display_name": payload.display_name,
            "character": None,
        },
    )

    return {"player_id": player_id, "character": None, "session_id": sid}
