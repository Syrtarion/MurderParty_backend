"""
Minigame runtime registry.
Tracks active mini-game sessions in memory (and on disk) alongside a history.
Each entry can be associated with a parent MurderParty session via the
`murder_session_id` field to support multi-session orchestration.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from app.config.settings import settings
from .io_utils import read_json, write_json


RUNTIME_PATH = Path(settings.DATA_DIR) / "minigame_sessions.json"


class MinigameRuntime:
    """
    Persisted structure:
    {
      "active":  [ { session... } ],
      "history": [ { session... } ]
    }
    """

    def __init__(self) -> None:
        self.state: Dict[str, Any] = {"active": [], "history": []}
        self.load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def load(self) -> None:
        """Load state from disk or initialise an empty structure."""
        self.state = read_json(RUNTIME_PATH) or {"active": [], "history": []}

    def save(self) -> None:
        """Flush current state to disk."""
        write_json(RUNTIME_PATH, self.state)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _match_session(self, session: Dict[str, Any], session_id: str, murder_session_id: Optional[str]) -> bool:
        if session.get("session_id") != session_id:
            return False
        if murder_session_id is None:
            return True
        return session.get("murder_session_id") == murder_session_id

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def create(self, session: Dict[str, Any]) -> str:
        """Append a new active session and persist the change."""
        self.state.setdefault("active", []).append(session)
        self.save()
        return session["session_id"]

    def update_scores(
        self,
        session_id: str,
        scores: Dict[str, int],
        murder_session_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Merge score updates for an active session."""
        for session in self.state.get("active", []):
            if self._match_session(session, session_id, murder_session_id):
                session.setdefault("scores", {}).update(scores)
                self.save()
                return session
        return None

    def close(
        self,
        session_id: str,
        murder_session_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Move an active session to history and mark it closed."""
        active = self.state.get("active", [])
        for index, session in enumerate(active):
            if self._match_session(session, session_id, murder_session_id):
                session["status"] = "closed"
                self.state.setdefault("history", []).append(session)
                del active[index]
                self.save()
                return session
        return None

    def get(self, session_id: str, murder_session_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Return the active session matching ids if present."""
        for session in self.state.get("active", []):
            if self._match_session(session, session_id, murder_session_id):
                return session
        return None


RUNTIME = MinigameRuntime()
