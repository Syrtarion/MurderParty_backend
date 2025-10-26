"""
Service: game_state.py
Rôle:
- Stocker l'état global de la partie (players, state, events) et le persister.
- Fournir un singleton `GAME_STATE` partagé par l’ensemble du backend.

Fichiers:
- players.json   : dictionnaire {player_id: {...}}
- game_state.json: clés de pilotage (phase, flags, story_seed éventuel…)
- events.json    : liste chronologique d'événements (trace globale)

Notes:
- RLock interne pour protéger la consistance lors d'appels concurrents.
- `register_event()` écrit sur disque + log en mémoire + print console (debug).
"""
# app/services/game_state.py
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Dict, Any, Optional, Iterable
from uuid import uuid4
import time
import json

from app.config.settings import settings
from .io_utils import read_json, write_json

DATA_DIR = Path(settings.DATA_DIR)
PLAYERS_PATH = DATA_DIR / "players.json"
STATE_PATH = DATA_DIR / "game_state.json"
EVENTS_PATH = DATA_DIR / "events.json"
MAX_AUDIT_EVENTS = 2000


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
        """Charge players/state/events depuis le disque (ou valeurs par défaut)."""
        with self._lock:
            self.players = read_json(PLAYERS_PATH) or {}
            self.state = read_json(STATE_PATH) or {
                "phase": 1,
                "started": False,
                "campaign_id": None,
                "last_awards": {}
            }
            self.events = read_json(EVENTS_PATH) or []
            self._normalize_events()

    def save(self) -> None:
        """Persiste players/state/events sur disque (synchronisation simple)."""
        with self._lock:
            self._trim_events()
            write_json(PLAYERS_PATH, self.players)
            write_json(STATE_PATH, self.state)
            write_json(EVENTS_PATH, self.events)

    # -----------------------------
    # Gestion des joueurs
    # -----------------------------
    def add_player(self, display_name: Optional[str] = None) -> str:
        """Ajoute un joueur et log immédiatement l'événement (idempotent pour l’audit)."""
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
    def _trim_events(self) -> None:
        """Bornage du journal en mémoire pour éviter la dérive."""
        if isinstance(self.events, list) and len(self.events) > MAX_AUDIT_EVENTS:
            overflow = len(self.events) - MAX_AUDIT_EVENTS
            if overflow > 0:
                del self.events[:overflow]

    def _normalize_events(self) -> None:
        """Assure une structure cohérente (id/ts/kind) pour chaque entrée."""
        if not isinstance(self.events, list):
            self.events = []
            return
        normalized: list[Dict[str, Any]] = []
        for entry in self.events:
            if not isinstance(entry, dict):
                continue
            entry = entry.copy()
            entry.setdefault("id", str(uuid4()))
            entry.setdefault("ts", time.time())
            entry.setdefault("kind", "unknown")
            entry.setdefault("payload", {})
            entry.setdefault("scope", "system")
            normalized.append(entry)
        self.events = normalized
        self._trim_events()

    def _log_event_nolock(self, kind: str, payload: Dict[str, Any], scope: str = "system") -> None:
        """Enregistre un événement interne (sans verrou) – utilitaire privé."""
        if not isinstance(self.events, list):
            self.events = []
        entry = {
            "id": str(uuid4()),
            "kind": kind,
            "scope": scope,
            "payload": payload,
            "ts": time.time()
        }
        self.events.append(entry)
        self._trim_events()

    def log_event(self, kind: str, payload: Dict[str, Any], scope: str = "system") -> None:
        """Enregistre un événement avec verrou (thread-safe) puis sauvegarde."""
        with self._lock:
            self._log_event_nolock(kind, payload, scope)
            self.save()

    def log_ws_dispatch(
        self,
        event_type: str,
        payload: Dict[str, Any],
        targets: Optional[Iterable[str]] = None,
        channel: str = "broadcast",
    ) -> None:
        """
        Historise un message WebSocket envoyé (pour future relecture côté clients distants).
        - `targets`: Iterable d'identifiants joueurs, sinon None => broadcast global.
        - `channel`: étiquette libre pour faciliter le filtrage (ex: "broadcast", "player").
        """
        target_list = list(targets) if targets else []
        entry = {
            "event_type": event_type,
            "payload": payload,
            "targets": target_list,
            "channel": channel,
        }
        # scope encode la nature du dispatch pour faciliter la recherche ultérieure.
        scope_label = f"ws:{channel}"
        self.log_event("ws_dispatch", entry, scope=scope_label)

    def events_snapshot(self) -> list[Dict[str, Any]]:
        """Retourne une copie immuable des événements courants."""
        with self._lock:
            return [event.copy() for event in self.events]


# -----------------------------
# Outils externes
# -----------------------------
def save_json(path: Path, data: dict) -> None:
    """Sauvegarde JSON robuste (utilisé ponctuellement pour d'autres fichiers)."""
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
    """Garantit une unique instance `GameState` pour tout le backend (lazy-load)."""
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
    Helper centralisé pour enregistrer un événement dans app/data/events.json
    + Log en mémoire via GAME_STATE.log_event pour un accès immédiat aux endpoints.
    """
    event = {
        "id": str(uuid4()),
        "kind": kind,
        "scope": scope,
        "payload": details or {},
        "ts": time.time()
    }

    # Chargement et écriture directe du fichier JSON (append)
    try:
        if EVENTS_PATH.exists():
            existing = json.loads(EVENTS_PATH.read_text(encoding="utf-8"))
        else:
            existing = []
    except Exception:
        existing = []

    existing.append(event)
    EVENTS_PATH.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")

    # Log console pour debug (traçabilité)
    print(f"[EVENT REGISTERED] {kind} (scope={scope}) → {details or {}}")

    # Ajout en mémoire (events du runtime) pour lecture immédiate
    GAME_STATE.log_event(kind, details or {}, scope)
    return event
