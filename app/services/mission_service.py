from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Dict, Any, Optional
import json
import random

from app.config.settings import settings
from app.services.game_state import GAME_STATE
from app.services.llm_engine import run_llm

DATA_DIR = Path(settings.DATA_DIR)
SEED_PATH = DATA_DIR / "story_seed.json"

DEFAULT_CULPRIT_POINTS = 50
DEFAULT_OTHER_POINTS = 10


def load_seed() -> dict:
    """Charge le fichier story_seed.json."""
    if SEED_PATH.exists():
        try:
            with open(SEED_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


@dataclass
class MissionService:
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)

    def assign_missions(self) -> Dict[str, Dict[str, Any]]:
        """
        Assigne des missions secrètes à tous les joueurs.
        - Le coupable reçoit une mission spéciale
        - Les autres joueurs reçoivent une mission unique depuis story_seed.json["missions"]
        """
        with self._lock:
            players = GAME_STATE.players
            if not players:
                raise RuntimeError("No players to assign missions to")

            from app.services.narrative_core import NARRATIVE
            canon = NARRATIVE.canon
            culprit_pid = canon.get("culprit_player_id")

            seed = load_seed()
            pool_culprit = seed.get("culprit_missions", [])
            pool_others = seed.get("missions", [])

            # Shuffle missions to avoid predictability
            random.shuffle(pool_others)

            assigned: Dict[str, Dict[str, Any]] = {}

            for pid, p in players.items():
                player_name = p.get("character") or p.get("display_name") or pid

                if pid == culprit_pid:
                    # Mission du coupable : pioche dans pool_culprit si dispo, sinon via LLM
                    if pool_culprit:
                        mission = random.choice(pool_culprit)
                        pool_culprit.remove(mission)
                        mission.setdefault("type", "primary")
                        mission.setdefault("points", DEFAULT_CULPRIT_POINTS)
                    else:
                        # fallback LLM
                        context = (
                            f"Cadre: {seed.get('setting','')}. "
                            f"Contexte: {seed.get('context','')}. "
                            f"Victime: {seed.get('victim','')}."
                        )
                        prompt = f"""
Tu écris une mission secrète en français pour le joueur coupable d'une murder party.
Mission courte (1-2 phrases), immersive, directive.
Ne révèle pas le crime ni les réponses du canon.
Contexte: {context}
Personnage: {player_name}
Retour: JSON avec {{ "type":"primary","text":"...","points":{DEFAULT_CULPRIT_POINTS} }}
"""
                        r = run_llm(prompt)
                        try:
                            mission = json.loads(r.get("text", "{}"))
                        except Exception:
                            mission = {
                                "type": "primary",
                                "text": "Ton objectif est de brouiller les pistes et semer le doute.",
                                "points": DEFAULT_CULPRIT_POINTS,
                            }
                else:
                    if not pool_others:
                        raise RuntimeError("Pas assez de missions annexes pour tous les joueurs non coupables")
                    mission = pool_others.pop()
                    mission.setdefault("type", "secondary")
                    mission.setdefault("points", DEFAULT_OTHER_POINTS)

                # Sauvegarde dans le joueur
                p["secret_mission"] = mission
                assigned[pid] = mission

            # Save and log
            GAME_STATE.save()
            GAME_STATE.log_event("missions_assigned", {"count": len(assigned)})

            return assigned


MISSION_SVC = MissionService()
