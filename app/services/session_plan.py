"""
Session plan service.
Maintain per-session playlists of mini-games/rounds with an in-memory cursor.
Legacy storage (single plan) is automatically migrated to the new structure.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from app.config.settings import settings
from .io_utils import read_json, write_json
from app.services.session_store import DEFAULT_SESSION_ID


PLAN_PATH = Path(settings.DATA_DIR) / "session_plan.json"


def _normalize_session_id(session_id: Optional[str]) -> str:
    sid = (session_id or DEFAULT_SESSION_ID).strip()
    return sid or DEFAULT_SESSION_ID


class SessionPlan:
    """Manage ordered playlists of mini-games per session."""

    def __init__(self) -> None:
        self.plans: Dict[str, Dict[str, Any]] = {}
        self.cursors: Dict[str, int] = {}
        self.load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def load(self, path: Optional[Path] = None) -> None:
        """Load plans from disk and migrate legacy structures if required."""
        target = path or PLAN_PATH
        raw = read_json(target) or {}

        # Legacy format: single plan with cursor
        if raw.get("games_sequence") is not None:
            session_id = raw.get("session_id") or DEFAULT_SESSION_ID
            self.plans = {session_id: raw}
            self.cursors = {session_id: 0}
            self.save(path=target)
            return

        sessions = raw.get("sessions") or {}
        cursors = raw.get("cursors") or {}

        self.plans = {}
        self.cursors = {}
        for session_id, plan in sessions.items():
            sid = _normalize_session_id(session_id)
            if not isinstance(plan, dict):
                continue
            self.plans[sid] = plan
            self.cursors[sid] = int(cursors.get(session_id, 0))

    def save(self, path: Optional[Path] = None) -> None:
        """Persist the current plans/cursors mapping."""
        target = path or PLAN_PATH
        payload = {
            "sessions": self.plans,
            "cursors": self.cursors,
        }
        write_json(target, payload)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _ensure_session(self, session_id: Optional[str]) -> str:
        sid = _normalize_session_id(session_id)
        if sid not in self.plans:
            self.plans[sid] = {"session_id": sid, "games_sequence": []}
            self.cursors[sid] = 0
        return sid

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_plan(self, session_id: Optional[str], plan: Dict[str, Any]) -> None:
        sid = self._ensure_session(session_id)
        self.plans[sid] = plan
        self.cursors[sid] = 0
        self.save()

    def current(self, session_id: Optional[str]) -> Optional[Dict[str, Any]]:
        sid = self._ensure_session(session_id)
        cursor = self.cursors.get(sid, 0)
        sequence = self.plans[sid].get("games_sequence", [])
        if 0 <= cursor < len(sequence):
            return sequence[cursor]
        return None

    def next(self, session_id: Optional[str]) -> Optional[Dict[str, Any]]:
        sid = self._ensure_session(session_id)
        self.cursors[sid] = self.cursors.get(sid, 0) + 1
        self.save()
        return self.current(sid)

    def has_next(self, session_id: Optional[str]) -> bool:
        sid = self._ensure_session(session_id)
        cursor = self.cursors.get(sid, 0)
        sequence = self.plans[sid].get("games_sequence", [])
        return cursor < len(sequence)

    def reset(self, session_id: Optional[str]) -> None:
        sid = self._ensure_session(session_id)
        self.cursors[sid] = 0
        self.save()

    def drop(self, session_id: Optional[str]) -> None:
        sid = _normalize_session_id(session_id)
        if sid in self.plans:
            self.plans.pop(sid, None)
        if sid in self.cursors:
            self.cursors.pop(sid, None)
        self.save()


SESSION_PLAN = SessionPlan()
