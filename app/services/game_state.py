from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock  # <<< ici
from typing import Dict, Any, Optional
from uuid import uuid4

from app.config.settings import settings
from .io_utils import read_json, write_json

DATA_DIR = Path(settings.DATA_DIR)
PLAYERS_PATH = DATA_DIR / "players.json"
STATE_PATH = DATA_DIR / "game_state.json"
EVENTS_PATH = DATA_DIR / "events.json"

@dataclass
class GameState:
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)  # <<< ici
    players: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    state: Dict[str, Any] = field(default_factory=lambda: {"phase": 1, "started": False, "campaign_id": None, "last_awards": {}})
    events: list[Dict[str, Any]] = field(default_factory=list)

    def load(self) -> None:
        with self._lock:
            self.players = read_json(PLAYERS_PATH) or {}
            self.state = read_json(STATE_PATH) or {"phase": 1, "started": False, "campaign_id": None, "last_awards": {}}
            self.events = read_json(EVENTS_PATH) or []

    def save(self) -> None:
        with self._lock:
            write_json(PLAYERS_PATH, self.players)
            write_json(STATE_PATH, self.state)
            write_json(EVENTS_PATH, self.events)

    def add_player(self, display_name: Optional[str] = None) -> str:
        with self._lock:
            pid = str(uuid4())
            self.players[pid] = {
                "player_id": pid,
                "display_name": display_name or f"Player-{pid[:5]}",
                "joined": True,
                "inventory": [],
                "found_clues": [],
            }
            self.save()  # ok car RLock
            return pid

    def log_event(self, kind: str, payload: Dict[str, Any]) -> None:
        with self._lock:
            self.events.append({"kind": kind, "payload": payload})
            self.save()  # ok car RLock

GAME_STATE = GameState()
GAME_STATE.load()
