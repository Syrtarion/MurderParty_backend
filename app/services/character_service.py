from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Dict, Any, Optional

from app.config.settings import settings
from .io_utils import read_json, write_json

DATA_DIR = Path(settings.DATA_DIR)
CHAR_PATH = DATA_DIR / "characters.json"
ASSIGN_PATH = DATA_DIR / "characters_assigned.json"


@dataclass
class CharacterService:
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)
    characters: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # mapping player_id -> character_id
    assigned: Dict[str, str] = field(default_factory=dict)

    def load(self) -> None:
        with self._lock:
            raw = read_json(CHAR_PATH) or {"characters": []}
            # index by id
            self.characters = {c["id"]: c for c in raw.get("characters", [])}
            self.assigned = read_json(ASSIGN_PATH) or {}

    def save(self) -> None:
        with self._lock:
            write_json(ASSIGN_PATH, self.assigned)

    def list_available(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            used = set(self.assigned.values())
            return {cid: c for cid, c in self.characters.items() if cid not in used}

    def assign_character(self, player_id: str) -> Optional[Dict[str, Any]]:
        """Attribue le premier rôle disponible au joueur. Retourne le personnage, ou None si aucun dispo."""
        with self._lock:
            if player_id in self.assigned:
                cid = self.assigned[player_id]
                return self.characters.get(cid)

            for cid, char in self.list_available().items():
                self.assigned[player_id] = cid
                self.save()
                return char
            return None

    def get_assigned(self, player_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            cid = self.assigned.get(player_id)
            if not cid:
                return None
            return self.characters.get(cid)


CHARACTERS = CharacterService()
CHARACTERS.load()
