"""
Service: session_plan.py
Rôle:
- Charger et gérer un plan de partie (séquence ordonnée de mini-jeux/rounds).
- Conserver un curseur interne pour savoir "quel round jouer maintenant".

Structure attendue:
{
  "session_id": "...",
  "games_sequence": [ { "id": "quizz_rapide", "round": 1, ... }, ... ]
}

API:
- set_plan(plan)    → remplace le plan courant et remet le curseur à 0
- current()         → retourne l'entrée au curseur
- next()            → avance le curseur et retourne la nouvelle entrée
- has_next()        → booléen
- reset()           → remet le curseur à 0
"""
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
        """Charge le plan depuis JSON (ou structure vide)."""
        p = path or PLAN_PATH
        data = read_json(p)
        self.plan = data or {"session_id": None, "games_sequence": []}
        self.cursor = 0

    def save(self, path: Optional[Path] = None) -> None:
        """Persiste le plan courant (idempotent)."""
        p = path or PLAN_PATH
        write_json(p, self.plan)

    def set_plan(self, plan: Dict[str, Any]) -> None:
        """Remplace le plan et réinitialise le curseur."""
        # plan = {"session_id": str, "games_sequence": [{"id": str, "round": int, ...}]}
        self.plan = plan
        self.cursor = 0
        self.save()

    def current(self) -> Optional[Dict[str, Any]]:
        """Retourne l'entrée pointée par le curseur (ou None si fin de plan)."""
        if 0 <= self.cursor < len(self.plan.get("games_sequence", [])):
            return self.plan["games_sequence"][self.cursor]
        return None

    def next(self) -> Optional[Dict[str, Any]]:
        """Avance le curseur et retourne la nouvelle entrée courante."""
        self.cursor += 1
        return self.current()

    def has_next(self) -> bool:
        """True si au moins un élément reste après le curseur."""
        return self.cursor < len(self.plan.get("games_sequence", []))

    def reset(self) -> None:
        """Repositionne le curseur en début de plan."""
        self.cursor = 0


SESSION_PLAN = SessionPlan()
