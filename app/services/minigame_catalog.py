"""
Service: minigame_catalog.py
Rôle:
- Charger en mémoire le référentiel des mini-jeux (catalogue statique).
- Exposer `CATALOG.get(id)` et `CATALOG.all()` pour les routes MJ.

Fichier source:
- app/data/minigames.json → {"catalog":[{id,mode,duration_s,scoring,reward_policy}]}

Remarque:
- `reward_policy` sera interprété par le moteur de récompense (engine).
"""
from pathlib import Path
from typing import Dict, Any

from app.config.settings import settings
from .io_utils import read_json

CATALOG_PATH = Path(settings.DATA_DIR) / "minigames.json"


class MinigameCatalog:
    """Catalogue statique des mini-jeux (référentiel).

    Source: app/data/minigames.json
    Exemple d'entrée:
    {
      "id": "quizz_rapide",
      "mode": "team",                 # "solo" | "team"
      "duration_s": 120,
      "scoring": "points_desc",
      "reward_policy": [
        { "rank": 1, "clue_kind": "crucial", "target": "team", "count": 1 },
        { "rank": 2, "clue_kind": "ambiguous", "target": "team", "count": 1 }
      ]
    }
    """

    def __init__(self):
        self.catalog: Dict[str, Dict[str, Any]] = {}
        self.load()

    def load(self) -> None:
        """Charge le JSON et indexe les jeux par id (dict)."""
        raw = read_json(CATALOG_PATH) or {"catalog": []}
        self.catalog = {g["id"]: g for g in raw.get("catalog", [])}

    def get(self, game_id: str) -> Dict[str, Any] | None:
        """Retourne la fiche jeu ou None si id inconnu."""
        return self.catalog.get(game_id)

    def all(self) -> Dict[str, Dict[str, Any]]:
        """Retourne l’intégralité du catalogue (dict id→jeu)."""
        return self.catalog


CATALOG = MinigameCatalog()
