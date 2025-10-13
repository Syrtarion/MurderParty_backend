"""
Service: mission_service.py
Rôle:
- Assigner des missions secrètes à tous les joueurs (coupable vs autres).
- Utiliser `story_seed.json` (missions/coupable_missions) ou fallback LLM.

Logique:
- Le coupable (depuis NARRATIVE.canon) reçoit une mission 'primary' (points plus élevés).
- Les autres piochent dans `missions` mélangées (type 'secondary').
- Enregistrement dans `GAME_STATE.players[pid]["secret_mission"]` + logs.

Robustesse:
- Fallback LLM JSON si aucune mission coupable n'est définie.
- Exceptions explicites si pas de joueurs / pas assez de missions.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Dict, Any
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
    """Charge le fichier story_seed.json (ou dict vide en cas de souci)."""
    if SEED_PATH.exists():
        try:
            with open(SEED_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


@dataclass
class MissionService:
    """Assigne des missions secrètes à tous les joueurs en fonction du rôle (coupable/autres)."""
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)

    def assign_missions(self) -> Dict[str, Dict[str, Any]]:
        """
        Assigne des missions secrètes à tous les joueurs.
        - Le coupable reçoit une mission spéciale (type=primary).
        - Les autres joueurs reçoivent des missions uniques (type=secondary).
        """
        with self._lock:
            players = GAME_STATE.players
            if not players:
                raise RuntimeError("Aucun joueur disponible pour l'attribution des missions.")

            # Récupère le canon narratif
            from app.services.narrative_core import NARRATIVE
            canon = NARRATIVE.canon or {}
            culprit_pid = canon.get("culprit_player_id")

            seed = load_seed()
            pool_culprit = list(seed.get("culprit_missions", []))
            pool_others = list(seed.get("missions", []))

            if not pool_others:
                raise RuntimeError("Le fichier story_seed.json ne contient pas de missions secondaires valides.")

            # Mélange les missions pour éviter toute prédictibilité
            random.shuffle(pool_others)

            assigned: Dict[str, Dict[str, Any]] = {}

            for pid, p in players.items():
                player_name = p.get("character") or p.get("display_name") or pid

                # Coupable
                if pid == culprit_pid:
                    if pool_culprit:
                        mission = random.choice(pool_culprit)
                        pool_culprit.remove(mission)
                        mission.setdefault("type", "primary")
                        mission.setdefault("points", DEFAULT_CULPRIT_POINTS)
                    else:
                        # Fallback via LLM si pas de mission prévue
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
Réponds uniquement en JSON: {{
  "type":"primary",
  "text":"<mission>",
  "points":{DEFAULT_CULPRIT_POINTS}
}}
"""
                        try:
                            r = run_llm(prompt)
                            mission = json.loads(r.get("text", "{}"))
                        except Exception:
                            mission = {
                                "type": "primary",
                                "text": "Brouille les pistes et détourne les soupçons de toi, quel qu’en soit le prix.",
                                "points": DEFAULT_CULPRIT_POINTS,
                            }
                # Autres joueurs
                else:
                    if not pool_others:
                        raise RuntimeError("Pas assez de missions secondaires pour tous les joueurs.")
                    mission = pool_others.pop()
                    mission.setdefault("type", "secondary")
                    mission.setdefault("points", DEFAULT_OTHER_POINTS)

                # Enregistre la mission dans le joueur
                p["secret_mission"] = mission
                assigned[pid] = mission

            # Persistance et log
            GAME_STATE.save()
            GAME_STATE.log_event("missions_assigned", {"count": len(assigned)})

            return assigned


# Instance globale
MISSION_SVC = MissionService()
