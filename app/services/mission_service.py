"""
Mission service with multi-session support.
Assigns secret missions to players depending on their role (culprit vs others).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Dict, Optional
import json
import random

from app.config.settings import settings
from app.services.game_state import GAME_STATE, GameState
from app.services.llm_engine import run_llm
from app.services.story_seed import load_story_seed_dict, StorySeedError

DEFAULT_CULPRIT_POINTS = 50
DEFAULT_OTHER_POINTS = 10


def load_seed(campaign: Optional[str] = None) -> dict:
    try:
        return load_story_seed_dict(campaign=campaign)
    except StorySeedError:
        return {}


@dataclass
class MissionService:
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)

    def _resolve_state(self, game_state: Optional[GameState]) -> GameState:
        return game_state or GAME_STATE

    def assign_missions(self, game_state: Optional[GameState] = None) -> Dict[str, Dict[str, Any]]:
        """
        Assign secret missions to every player in the session.
        Culprit receives a primary mission; others receive secondary missions.
        """
        with self._lock:
            state = self._resolve_state(game_state)
            players = state.players
            if not players:
                raise RuntimeError("Aucun joueur disponible pour l'attribution des missions.")

            canon = state.state.get("canon") or {}
            culprit_pid = canon.get("culprit_player_id")

            campaign = state.state.get("campaign_id") or settings.DEFAULT_CAMPAIGN
            seed = load_seed(campaign)
            if seed and not state.state.get("story_seed"):
                state.state["story_seed"] = seed
            pool_culprit = list(seed.get("culprit_missions", []))
            pool_others = list(seed.get("missions", []))

            if not pool_others:
                raise RuntimeError("Le fichier story_seed.json ne contient pas de missions secondaires valides.")

            random.shuffle(pool_others)
            assigned: Dict[str, Dict[str, Any]] = {}

            for pid, player in players.items():
                display = player.get("character") or player.get("display_name") or pid

                if pid == culprit_pid:
                    mission = self._assign_culprit_mission(pool_culprit, seed, display)
                else:
                    if not pool_others:
                        raise RuntimeError("Pas assez de missions secondaires pour tous les joueurs.")
                    mission = dict(pool_others.pop())
                    mission.setdefault("type", "secondary")
                    mission.setdefault("points", DEFAULT_OTHER_POINTS)

                player["secret_mission"] = mission
                assigned[pid] = mission

            state.save()
            state.log_event("missions_assigned", {"count": len(assigned)})
            return assigned

    def _assign_culprit_mission(self, pool_culprit: list, seed: dict, player_name: str) -> Dict[str, Any]:
        if pool_culprit:
            mission = dict(random.choice(pool_culprit))
            pool_culprit.remove(mission)
            mission.setdefault("type", "primary")
            mission.setdefault("points", DEFAULT_CULPRIT_POINTS)
            return mission

        context = (
            f"Cadre: {seed.get('setting', '')}. "
            f"Contexte: {seed.get('context', '')}. "
            f"Victime: {seed.get('victim', '')}."
        )
        prompt = f"""
Tu écris une mission secrète en français pour le joueur COUPABLE d'une murder party.
Elle doit être immersive, directive et tenir en 1-2 phrases.
Ne révèle jamais explicitement le crime ni le canon.
Contexte: {context}
Personnage: {player_name}
Réponds uniquement en JSON:
{{
  "type":"primary",
  "text":"<mission>",
  "points":{DEFAULT_CULPRIT_POINTS}
}}
"""
        try:
            response = run_llm(prompt)
            return json.loads(response.get("text", "{}"))
        except Exception:
            return {
                "type": "primary",
                "text": "Brouille les pistes et détourne les soupçons de toi, quel qu'en soit le prix.",
                "points": DEFAULT_CULPRIT_POINTS,
            }


MISSION_SVC = MissionService()
