"""
Service: minigame_runtime.py
Rôle:
- Suivre les sessions de mini-jeux (état actif + historique) et persister.

Structure fichier:
{
  "active":  [ { session... } ],
  "history": [ { session... } ]
}

Méthodes clés:
- create(session)       → enregistre une nouvelle session (active)
- update_scores(id, s)  → met à jour les scores d'une session active
- close(id)             → marque 'closed' et bascule en history
- get(id)               → retrouve une session active
"""
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
        """Charge l'état depuis le disque (ou crée une structure vide)."""
        self.state = read_json(RUNTIME_PATH) or {"active": [], "history": []}

    def save(self) -> None:
        """Écrit l'état courant sur disque (idempotent)."""
        write_json(RUNTIME_PATH, self.state)

    def create(self, session: Dict[str, Any]) -> str:
        """Ajoute une session dans 'active' et retourne son session_id."""
        self.state["active"].append(session)
        self.save()
        return session["session_id"]

    def update_scores(self, session_id: str, scores: Dict[str, int]):
        """Fusionne des scores pour une session active donnée, sinon None."""
        for s in self.state["active"]:
            if s["session_id"] == session_id:
                s.setdefault("scores", {}).update(scores)
                self.save()
                return s
        return None

    def close(self, session_id: str):
        """Bascule une session 'active' en 'history' et marque 'closed'."""
        for i, s in enumerate(self.state["active"]):
            if s["session_id"] == session_id:
                s["status"] = "closed"
                self.state["history"].append(s)
                del self.state["active"][i]
                self.save()
                return s
        return None

    def get(self, session_id: str):
        """Retourne la session active correspondante, ou None si introuvable."""
        for s in self.state["active"]:
            if s["session_id"] == session_id:
                return s
        return None


RUNTIME = MinigameRuntime()
