from fastapi import APIRouter, Depends
from app.deps.auth import mj_required
from app.services.game_state import GAME_STATE
from app.services.narrative_core import NARRATIVE
from pathlib import Path
import json

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(mj_required)]
)

DATA_DIR = Path("app/data")

RESET_FILES = {
    "game_state.json": {
        "state": {"phase": 0, "started": False, "campaign_id": None, "last_awards": {}},
        "players": {},
        "events": []
    },
    "players.json": {},
    "events.json": [],
    "minigame_sessions.json": {},
    "trial_state.json": {},
    "characters_assigned.json": {},
    "canon_narratif.json": {}
}

@router.post("/reset_game")
async def reset_game():
    """
    Réinitialise complètement la partie :
    - Vide joueurs, scores, events, sessions
    - Réinitialise canon narratif
    - Préserve les fichiers de configuration (characters.json, minigames.json, session_plan.json, story_seed.json)
    """
    for fname, default_content in RESET_FILES.items():
        fpath = DATA_DIR / fname
        try:
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump(default_content, f, ensure_ascii=False, indent=2)
        except Exception:
            continue

    # Reset mémoire pour les services
    GAME_STATE.players = {}
    GAME_STATE.state = {
        "phase": 0,
        "started": False,
        "campaign_id": None,
        "last_awards": {}
    }
    GAME_STATE.events = []
    NARRATIVE.canon = {}

    return {
        "ok": True,
        "message": "Tous les fichiers de partie ont été réinitialisés (config préservée)."
    }
