"""
Service: character_service.py
Role:
- Manage character attribution and envelope assignment for players.
- Two operating modes:
  1) Seed mode: read/write directly in GAME_STATE.state["story_seed"].
  2) Legacy mode: fall back to characters.json / characters_assigned.json files.

Concurrency:
- Guarded by an RLock to avoid race conditions when several routes trigger assignments.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any, Dict, List, Optional

from app.config.settings import settings
from .io_utils import read_json, write_json
from app.services.game_state import GAME_STATE, GameState


DATA_DIR = Path(settings.DATA_DIR)
CHAR_PATH = DATA_DIR / "characters.json"
ASSIGN_PATH = DATA_DIR / "characters_assigned.json"


@dataclass
class CharacterService:
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)

    # Legacy cache (files)
    characters: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    assigned: Dict[str, str] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _resolve_state(self, game_state: GameState | None = None) -> GameState:
        """Return the effective GameState to use (override or global singleton)."""
        return game_state or GAME_STATE

    def _seed(self, game_state: GameState | None = None) -> Optional[Dict[str, Any]]:
        """Return the active story_seed when running in seed mode."""
        state = self._resolve_state(game_state)
        seed = state.state.get("story_seed")
        return seed if isinstance(seed, dict) else None

    def _use_seed(self, game_state: GameState | None = None) -> bool:
        """True when the application is operating with story_seed as the source of truth."""
        return self._seed(game_state) is not None

    # ------------------------------------------------------------------
    # Load / Save
    # ------------------------------------------------------------------
    def load(self) -> None:
        """Load legacy files. No-op when running in seed mode."""
        with self._lock:
            if self._use_seed():
                return
            raw = read_json(CHAR_PATH) or {"characters": []}
            self.characters = {c["id"]: c for c in raw.get("characters", [])}
            self.assigned = read_json(ASSIGN_PATH) or {}

    def save(self, game_state: GameState | None = None) -> None:
        """Persist current assignments depending on the active mode."""
        with self._lock:
            if self._use_seed(game_state):
                self._resolve_state(game_state).save()
            else:
                write_json(ASSIGN_PATH, self.assigned)

    # ------------------------------------------------------------------
    # Characters
    # ------------------------------------------------------------------
    def list_available(self, game_state: GameState | None = None) -> Dict[str, Dict[str, Any]]:
        """Return available characters (not yet assigned)."""
        with self._lock:
            if self._use_seed(game_state):
                seed = self._seed(game_state) or {}
                chars: List[Dict[str, Any]] = seed.get("characters") or []
                free: Dict[str, Dict[str, Any]] = {}
                for ch in chars:
                    if not isinstance(ch, dict):
                        continue
                    cid = str(ch.get("id") or "")
                    if cid and not ch.get("assigned_player_id"):
                        free[cid] = ch
                return free
            used = set(self.assigned.values())
            return {cid: c for cid, c in self.characters.items() if cid not in used}

    def get_assigned(
        self,
        player_id: str,
        game_state: GameState | None = None,
    ) -> Optional[Dict[str, Any]]:
        """Return the character already assigned to player_id, if any."""
        with self._lock:
            if self._use_seed(game_state):
                seed = self._seed(game_state) or {}
                chars: List[Dict[str, Any]] = seed.get("characters") or []
                for ch in chars:
                    if isinstance(ch, dict) and ch.get("assigned_player_id") == player_id:
                        return ch
                return None
            cid = self.assigned.get(player_id)
            if not cid:
                return None
            return self.characters.get(cid)

    def assign_character(
        self,
        player_id: str,
        game_state: GameState | None = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Assign a character to the player if possible.
        Returns the character dict, or None when nothing is available.
        """
        with self._lock:
            current = self.get_assigned(player_id, game_state=game_state)
            if current:
                return current

            if self._use_seed(game_state):
                free = self.list_available(game_state=game_state)
                if not free:
                    return None
                cid, ch = next(iter(free.items()))
                ch["assigned_player_id"] = player_id
                self.save(game_state=game_state)
                return ch

            free = self.list_available()
            if not free:
                return None
            cid, ch = next(iter(free.items()))
            self.assigned[player_id] = cid
            self.save()
            return ch

    # ------------------------------------------------------------------
    # Envelopes
    # ------------------------------------------------------------------
    def assign_envelopes(
        self,
        player_id: str,
        count: int = 1,
        game_state: GameState | None = None,
    ) -> List[Dict[str, Any]]:
        """
        Assign `count` envelopes (seed mode only). Returns the list of envelopes just assigned.
        Legacy mode is not supported for envelope distribution.
        """
        with self._lock:
            if not self._use_seed(game_state):
                return []

            seed = self._seed(game_state) or {}
            envs: List[Dict[str, Any]] = seed.get("envelopes") or []
            given: List[Dict[str, Any]] = []

            for env in envs:
                if not isinstance(env, dict):
                    continue
                if env.get("assigned_player_id"):
                    continue
                env["assigned_player_id"] = player_id
                given.append(env)
                if len(given) >= count:
                    break

            if given:
                self.save(game_state=game_state)
            return given


# Global instance (loaded at import time)
CHARACTERS = CharacterService()
CHARACTERS.load()
