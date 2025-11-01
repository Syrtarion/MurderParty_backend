"""
Service: game_state.py
Rôle :
- Stocker l'état de la partie pour une session donnée (players, state, events) et le persister.
- Fournir un singleton `GAME_STATE` partagé par défaut (session `"default"`), avec gestion
  multi-sessions via le répertoire `sessions/<session_id>/`.

Stockage (par session) :
- `sessions/<session_id>/players.json`
- `sessions/<session_id>/game_state.json`
- `sessions/<session_id>/events.ndjson` (journal append-only)

Compatibilité :
- À la première lecture, si aucun fichier session n'existe encore, le service recharge les anciens
  fichiers globaux (`players.json`, `game_state.json`, `events.json`) puis migre automatiquement
  vers la nouvelle arborescence.
"""
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
LEGACY_PLAYERS_PATH = DATA_DIR / "players.json"
LEGACY_STATE_PATH = DATA_DIR / "game_state.json"
LEGACY_EVENTS_PATH = DATA_DIR / "events.json"
SESSIONS_DIR = DATA_DIR / "sessions"
DEFAULT_SESSION_ID = "default"
PLAYERS_FILENAME = "players.json"
STATE_FILENAME = "game_state.json"
EVENTS_FILENAME = "events.ndjson"
MAX_AUDIT_EVENTS = 2000


def _default_state() -> Dict[str, Any]:
    return {
        "phase": 1,
        "started": False,
        "campaign_id": settings.DEFAULT_CAMPAIGN,
        "last_awards": {},
        "phase_label": "WAITING_START",
        "join_locked": False,
        "session": {},
        "join_code": None,
        "hints_history": [],
        "killer_actions": {"destroy_used": 0},
    }


def _ensure_sessions_dir() -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def _read_events_ndjson(path: Path) -> list[Dict[str, Any]]:
    if not path.exists():
        return []
    events: list[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception:
        return []
    return events


def _write_events_ndjson(path: Path, events: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for event in events:
            fh.write(json.dumps(event, ensure_ascii=False))
            fh.write("\n")


@dataclass
class GameState:
    session_id: str = field(default=DEFAULT_SESSION_ID)
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)
    players: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    state: Dict[str, Any] = field(default_factory=_default_state)
    events: list[Dict[str, Any]] = field(default_factory=list)

    # -----------------------------
    # Gestion session / chemins
    # -----------------------------
    def _session_dir(self) -> Path:
        _ensure_sessions_dir()
        base = SESSIONS_DIR / self.session_id
        base.mkdir(parents=True, exist_ok=True)
        return base

    def _players_path(self) -> Path:
        return self._session_dir() / PLAYERS_FILENAME

    def _state_path(self) -> Path:
        return self._session_dir() / STATE_FILENAME

    def _events_path(self) -> Path:
        return self._session_dir() / EVENTS_FILENAME

    # -----------------------------
    # Chargement / Sauvegarde
    # -----------------------------
    def load(self, session_id: Optional[str] = None) -> None:
        """Charge players/state/events depuis le disque (ou valeurs par défaut)."""
        with self._lock:
            if session_id:
                self.session_id = session_id

            players = read_json(self._players_path())
            state = read_json(self._state_path())
            events = _read_events_ndjson(self._events_path())

            migrated = False
            if not players and not state and not events and self.session_id == DEFAULT_SESSION_ID:
                players = read_json(LEGACY_PLAYERS_PATH)
                state = read_json(LEGACY_STATE_PATH)
                events = self._read_legacy_events()
                migrated = bool(players or state or events)

            self.players = players or {}
            self.state = state or _default_state()
            self.events = events or []
            self._normalize_events()

            if migrated:
                self.save()

    def save(self) -> None:
        """Persiste players/state/events sur disque."""
        with self._lock:
            self._trim_events()
            write_json(self._players_path(), self.players)
            write_json(self._state_path(), self.state)
            _write_events_ndjson(self._events_path(), self.events)

    def reset(self) -> None:
        """Reinitialise l'etat (players/state/events) sans charger le disque."""
        with self._lock:
            self.players = {}
            self.state = _default_state()
            self.events = []

    # -----------------------------
    # Sessions
    # -----------------------------
    def use_session(self, session_id: str) -> None:
        """Change de session et recharge les données correspondantes."""
        self.load(session_id=session_id)

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

    def _log_event_nolock(self, kind: str, payload: Dict[str, Any], scope: str = "system") -> Dict[str, Any]:
        """Enregistre un événement interne (sans verrou) – utilitaire privé."""
        if not isinstance(self.events, list):
            self.events = []
        entry = {
            "id": str(uuid4()),
            "kind": kind,
            "scope": scope,
            "payload": payload,
            "ts": time.time(),
        }
        self.events.append(entry)
        self._trim_events()
        return entry

    def log_event(self, kind: str, payload: Dict[str, Any], scope: str = "system") -> Dict[str, Any]:
        """Enregistre un événement avec verrou (thread-safe) puis sauvegarde."""
        with self._lock:
            entry = self._log_event_nolock(kind, payload, scope)
            self.save()
            return entry

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
        entry_payload = {
            "event_type": event_type,
            "payload": payload,
            "targets": target_list,
            "channel": channel,
        }
        scope_label = f"ws:{channel}"
        self.log_event("ws_dispatch", entry_payload, scope=scope_label)

    def events_snapshot(self) -> list[Dict[str, Any]]:
        """Retourne une copie immuable des événements courants."""
        with self._lock:
            return [event.copy() for event in self.events]

    def _read_legacy_events(self) -> list[Dict[str, Any]]:
        try:
            legacy = read_json(LEGACY_EVENTS_PATH)
            if isinstance(legacy, list):
                return legacy
        except Exception:
            pass
        return []

# -----------------------------
# Outils externes
# -----------------------------
def save_json(path: Path, data: dict) -> None:
    """Sauvegarde JSON robuste (utilisé ponctuellement pour d'autres fichiers)."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        raise RuntimeError(f"Erreur lors de la sauvegarde JSON : {exc}")


# -----------------------------
# Singleton global
# -----------------------------
_instance: Optional[GameState] = None


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
def register_event(
    kind: str,
    details: dict | None = None,
    scope: str = "system",
    game_state: GameState | None = None,
) -> Dict[str, Any]:
    """
    Helper centralisé pour enregistrer un événement dans le journal courant.
    Renvoie l'événement consigné.
    """
    target = game_state or GAME_STATE
    entry = target.log_event(kind, details or {}, scope)
    print(f"[EVENT REGISTERED] {kind} (scope={scope}) -> {details or {}}")
    return entry
