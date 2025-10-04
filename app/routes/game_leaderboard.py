from fastapi import APIRouter
from app.services.game_state import GAME_STATE

router = APIRouter(prefix="/game", tags=["game"])

@router.get("/leaderboard")
async def leaderboard():
    """Retourne le classement des joueurs par score_total décroissant."""
    players = [
        {
            "player_id": pid,
            "name": pdata.get("display_name"),
            "character": pdata.get("character"),
            "score_total": pdata.get("score_total", 0)
        }
        for pid, pdata in GAME_STATE.players.items()
    ]
    players_sorted = sorted(players, key=lambda p: p["score_total"], reverse=True)
    return {"leaderboard": players_sorted}
