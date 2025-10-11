# app/services/game_state.py
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Dict, Any, Optional
from uuid import uuid4
import time
import json

from app.config.settings import settings
from .io_utils import read_json, write_json

DATA_DIR = Path(settings.DATA_DIR)
PLAYERS_PATH = DATA_DIR / "players.json"
STATE_PATH = DATA_DIR / "game_state.json"
EVENTS_PATH = DATA_DIR / "events.json"


@dataclass
class GameState:
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)
    players: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    state: Dict[str, Any] = field(default_factory=lambda: {
        "phase": 1,
        "started": False,
        "campaign_id": None,
        "last_awards": {}
    })
    events: list[Dict[str, Any]] = field(default_factory=list)

    # -----------------------------
    # Gestion fichiers de session
    # -----------------------------
    def load(self) -> None:
        with self._lock:
            self.players = read_json(PLAYERS_PATH) or {}
            self.state = read_json(STATE_PATH) or {
                "phase": 1,
                "started": False,
                "campaign_id": None,
                "last_awards": {}
            }
            self.events = read_json(EVENTS_PATH) or []

    def save(self) -> None:
        with self._lock:
            write_json(PLAYERS_PATH, self.players)
            write_json(STATE_PATH, self.state)
            write_json(EVENTS_PATH, self.events)

    # -----------------------------
    # Gestion des joueurs
    # -----------------------------
    def add_player(self, display_name: Optional[str] = None) -> str:
        """Ajoute un joueur et log immédiatement l'événement."""
        with self._lock:
            pid = str(uuid4())
            pdata = {
                "player_id": pid,
                "display_name": display_name or f"Player-{pid[:5]}",
                "joined": True,
                "inventory": [],
                "found_clues": [],
            }
            self.players[pid] = pdata
            self._log_event_nolock("player_join", {"player_id": pid, "display_name": pdata["display_name"]})
            self.save()
            return pid

    # -----------------------------
    # Gestion des événements
    # -----------------------------
    def _log_event_nolock(self, kind: str, payload: Dict[str, Any], scope: str = "system") -> None:
        """Enregistre un événement interne (sans verrou)."""
        if not isinstance(self.events, list):
            self.events = []
        self.events.append({
            "kind": kind,
            "scope": scope,
            "payload": payload,
            "ts": time.time()
        })

    def log_event(self, kind: str, payload: Dict[str, Any], scope: str = "system") -> None:
        """Enregistre un événement avec verrou (sécurisé)."""
        with self._lock:
            self._log_event_nolock(kind, payload, scope)
            self.save()


# -----------------------------
# Outils externes
# -----------------------------
def save_json(path: Path, data: dict) -> None:
    """Sauvegarde JSON robuste."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        raise RuntimeError(f"Erreur lors de la sauvegarde JSON : {e}")


# -----------------------------
# Singleton global
# -----------------------------
_instance = None

def get_game_state() -> GameState:
    """Garantit un seul GameState partagé dans tout le backend."""
    global _instance
    if _instance is None:
        _instance = GameState()
        _instance.load()
    return _instance


GAME_STATE = get_game_state()


# -----------------------------
# Helper d’enregistrement global
# -----------------------------
def register_event(kind: str, details: dict | None = None, scope: str = "system") -> dict:
    """
    Helper pour enregistrer un événement globalement dans app/data/events.json.
    Utilisé par les endpoints (intro, canon, narration, épilogue...).
    """
    event = {
        "kind": kind,
        "scope": scope,
        "payload": details or {},
        "ts": time.time()
    }

    # Chargement et écriture directe du fichier JSON
    try:
        if EVENTS_PATH.exists():
            existing = json.loads(EVENTS_PATH.read_text(encoding="utf-8"))
        else:
            existing = []
    except Exception:
        existing = []

    existing.append(event)
    EVENTS_PATH.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")

    # Log console pour debug
    print(f"[EVENT REGISTERED] {kind} (scope={scope}) → {details or {}}")

    # Ajout en mémoire
    GAME_STATE.log_event(kind, details or {}, scope)
    return event
