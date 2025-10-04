from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config.settings import settings
from .io_utils import read_json, write_json

PLAN_PATH = Path(settings.DATA_DIR) / "session_plan.json"

class SessionPlan:
    """Gestion d'un plan de partie (playlist de mini-jeux)."""

    def __init__(self):
        self.plan: Dict[str, Any] = {}
        self.cursor: int = 0  # index de la prochaine manche à jouer
        self.load()

    def load(self, path: Optional[Path] = None) -> None:
        p = path or PLAN_PATH
        data = read_json(p)
        self.plan = data or {"session_id": None, "games_sequence": []}
        self.cursor = 0

    def save(self, path: Optional[Path] = None) -> None:
        p = path or PLAN_PATH
        write_json(p, self.plan)

    def set_plan(self, plan: Dict[str, Any]) -> None:
        # plan = {"session_id": str, "games_sequence": [{"id": str, "round": int, ...}]}
        self.plan = plan
        self.cursor = 0
        self.save()

    def current(self) -> Optional[Dict[str, Any]]:
        if 0 <= self.cursor < len(self.plan.get("games_sequence", [])):
            return self.plan["games_sequence"][self.cursor]
        return None

    def next(self) -> Optional[Dict[str, Any]]:
        self.cursor += 1
        return self.current()

    def has_next(self) -> bool:
        return self.cursor < len(self.plan.get("games_sequence", []))

    def reset(self) -> None:
        self.cursor = 0


SESSION_PLAN = SessionPlan()
