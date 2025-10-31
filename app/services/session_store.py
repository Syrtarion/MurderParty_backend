"""
Session store registry
======================

Expose des helpers pour récupérer un `GameState` dédié à une session
(`sessions/<session_id>/`). Les instances sont mises en cache en mémoire et
initialisées à la demande.
"""
from __future__ import annotations

from threading import RLock
from typing import Dict, Iterable, Optional, Tuple
from uuid import uuid4

from .game_state import GameState, DEFAULT_SESSION_ID, SESSIONS_DIR
from .session_engine import SessionEngine

_SESSIONS: Dict[str, GameState] = {}
_ENGINES: Dict[str, SessionEngine] = {}
_LOCK = RLock()


def get_session_state(session_id: str = DEFAULT_SESSION_ID) -> GameState:
    """
    Retourne l'instance `GameState` associée à `session_id`.
    Crée/charge la session si nécessaire.
    """
    normalized = session_id or DEFAULT_SESSION_ID
    with _LOCK:
        state = _SESSIONS.get(normalized)
        if state is None:
            state = GameState(session_id=normalized)
            state.load()
            _SESSIONS[normalized] = state
        return state


def drop_session_state(session_id: str) -> None:
    """Retire une session du cache (sans supprimer les fichiers)."""
    with _LOCK:
        _SESSIONS.pop(session_id, None)


def list_session_ids() -> list[str]:
    """Retourne la liste des sessions actuellement chargées en mémoire."""
    with _LOCK:
        return list(_SESSIONS.keys())

def _disk_session_ids() -> Iterable[str]:
    if not SESSIONS_DIR.exists():
        return []
    return (path.name for path in SESSIONS_DIR.iterdir() if path.is_dir())

def list_all_session_ids() -> list[str]:
    """Retourne la liste des sessions connues (cache + disque)."""
    ids = set(list_session_ids())
    ids.update(_disk_session_ids())
    return list(ids)


def create_session_state(session_id: str | None = None) -> GameState:
    """Cree une nouvelle session (vide) et la persiste."""
    sid = (session_id or uuid4().hex).strip() or uuid4().hex
    with _LOCK:
        state = GameState(session_id=sid)
        state.reset()
        state.save()
        _SESSIONS[sid] = state
        _ENGINES.pop(sid, None)
        return state


def get_session_engine(session_id: str = DEFAULT_SESSION_ID) -> SessionEngine:
    """Retourne l'orchestrateur de round pour la session."""
    normalized = session_id or DEFAULT_SESSION_ID
    with _LOCK:
        engine = _ENGINES.get(normalized)
        if engine is None:
            state = get_session_state(normalized)
            engine = SessionEngine(game_state=state)
            _ENGINES[normalized] = engine
        return engine


def drop_session_engine(session_id: str) -> None:
    with _LOCK:
        _ENGINES.pop(session_id, None)


def find_session_id_by_join_code(join_code: str | None) -> Optional[str]:
    """Recherche le session_id correspondant à un join_code (insensible à la casse)."""
    code = (join_code or "").strip().upper()
    if not code:
        return None
    with _LOCK:
        for sid, state in _SESSIONS.items():
            stored = str(state.state.get("join_code") or "").upper()
            if stored == code:
                return sid

    for sid in _disk_session_ids():
        state = get_session_state(sid)
        stored = str(state.state.get("join_code") or "").upper()
        if stored == code:
            return sid
    return None


def find_session_by_player_id(player_id: str) -> Optional[Tuple[str, GameState]]:
    """Localise la session contenant le joueur indiqué."""
    pid = (player_id or "").strip()
    if not pid:
        return None
    with _LOCK:
        for sid, state in _SESSIONS.items():
            if pid in state.players:
                return sid, state

    for sid in _disk_session_ids():
        state = get_session_state(sid)
        if pid in state.players:
            return sid, state
    return None


def find_session_by_player_name(name: str) -> Optional[Tuple[str, GameState, dict]]:
    """Recherche un joueur par display_name (case-insensitive) sur l'ensemble des sessions."""
    target = (name or "").strip().lower()
    if not target:
        return None

    def _match(state: GameState) -> Optional[dict]:
        for player in state.players.values():
            if str(player.get("display_name", "")).strip().lower() == target:
                return player
        return None

    with _LOCK:
        for sid, state in _SESSIONS.items():
            player = _match(state)
            if player:
                return sid, state, player

    for sid in _disk_session_ids():
        state = get_session_state(sid)
        player = _match(state)
        if player:
            return sid, state, player
    return None
