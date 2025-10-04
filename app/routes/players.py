from fastapi import APIRouter
from pydantic import BaseModel

from app.services.game_state import GAME_STATE
from app.services.character_service import CHARACTERS

router = APIRouter(prefix="/players", tags=["players"])


class JoinPayload(BaseModel):
    display_name: str | None = None


@router.post("/join")
async def join(payload: JoinPayload):
    """Inscription d'un joueur -> retourne un player_id unique + personnage attribué si disponible."""
    player_id = GAME_STATE.add_player(payload.display_name)

    # Attribution automatique d'un rôle si disponible
    character = CHARACTERS.assign_character(player_id)

    # Persiste quelques infos côté player
    if character:
        GAME_STATE.players[player_id]["character"] = character.get("name")
        GAME_STATE.players[player_id]["character_id"] = character.get("id")
        GAME_STATE.players[player_id]["objectives"] = character.get("objectives", [])
        GAME_STATE.players[player_id]["secrets"] = character.get("secrets", [])
        GAME_STATE.save()

    GAME_STATE.log_event("player_join", {"player_id": player_id, "display_name": payload.display_name, "character": character.get("name") if character else None})

    return {"player_id": player_id, "character": character}
