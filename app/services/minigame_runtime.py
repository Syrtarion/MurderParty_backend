from pathlib import Path
from typing import Dict, Any

from app.config.settings import settings
from .io_utils import read_json, write_json

RUNTIME_PATH = Path(settings.DATA_DIR) / "minigame_sessions.json"


class MinigameRuntime:
    """Registre dynamique des sessions de mini-jeux.

    Structure du fichier JSON:
    {
      "active": [ { session... } ],
      "history": [ { session... } ]
    }
    """

    def __init__(self):
        self.state: Dict[str, Any] = {"active": [], "history": []}
        self.load()

    def load(self) -> None:
        self.state = read_json(RUNTIME_PATH) or {"active": [], "history": []}

    def save(self) -> None:
        write_json(RUNTIME_PATH, self.state)

    def create(self, session: Dict[str, Any]) -> str:
        self.state["active"].append(session)
        self.save()
        return session["session_id"]

    def update_scores(self, session_id: str, scores: Dict[str, int]):
        for s in self.state["active"]:
            if s["session_id"] == session_id:
                s.setdefault("scores", {}).update(scores)
                self.save()
                return s
        return None

    def close(self, session_id: str):
        for i, s in enumerate(self.state["active"]):
            if s["session_id"] == session_id:
                s["status"] = "closed"
                self.state["history"].append(s)
                del self.state["active"][i]
                self.save()
                return s
        return None

    def get(self, session_id: str):
        for s in self.state["active"]:
            if s["session_id"] == session_id:
                return s
        return None


RUNTIME = MinigameRuntime()
