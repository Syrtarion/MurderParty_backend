"""
Service: trial_service.py
Rôle:
- Gérer le vote de "procès" (qui/quoi/où/pourquoi) et calculer un verdict collectif.
- Allouer des points individuels si les votes d’un joueur correspondent au canon.

Données persistées:
- trial_state.json : {"votes": {cat: {voter_id: {value, ts}}}, "history": [...]}

Paramètres:
- CATEGORIES = ["culprit", "weapon", "location", "motive"]
- WEIGHTS: pondère l’impact de chaque catégorie sur le score collectif.

API:
- TRIAL.vote(voter_id, category, value)  → enregistre un vote
- TRIAL.tally()                          → histogrammes {cat: {val: count}}
- TRIAL.finalize()                       → calcule verdict + met à jour scores joueurs
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Dict, Any
from time import time

from app.config.settings import settings
from .io_utils import read_json, write_json
from .narrative_core import NARRATIVE
from .game_state import GAME_STATE

DATA_DIR = Path(settings.DATA_DIR)
TRIAL_PATH = DATA_DIR / "trial_state.json"

CATEGORIES = ["culprit", "weapon", "location", "motive"]
WEIGHTS = {"culprit": 0.5, "weapon": 0.2, "location": 0.15, "motive": 0.15}


@dataclass
class TrialState:
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)
    votes: Dict[str, Dict[str, Dict[str, Any]]] = field(
        default_factory=lambda: {cat: {} for cat in CATEGORIES}
    )
    history: list[Dict[str, Any]] = field(default_factory=list)

    def load(self) -> None:
        """Charge votes + historique depuis disk (tolérant aux fichiers vides)."""
        with self._lock:
            data = read_json(TRIAL_PATH) or {}
            self.votes = data.get("votes", {cat: {} for cat in CATEGORIES})
            self.history = data.get("history", [])

    def save(self) -> None:
        """Persiste l’état courant (votes + history)."""
        with self._lock:
            write_json(TRIAL_PATH, {"votes": self.votes, "history": self.history})

    def vote(self, voter_id: str, category: str, value: str) -> Dict[str, Any]:
        """Enregistre/écrase le vote du joueur pour une catégorie donnée."""
        if category not in CATEGORIES:
            raise ValueError(f"Invalid category {category}")
        with self._lock:
            payload = {"value": value, "ts": time()}
            self.votes[category][voter_id] = payload
            self.save()
            return payload

    def tally(self) -> Dict[str, Dict[str, int]]:
        """Calcule des histogrammes {cat: {val: count}} triés par fréquence desc."""
        res: Dict[str, Dict[str, int]] = {}
        with self._lock:
            for cat in CATEGORIES:
                counts: Dict[str, int] = {}
                for v in self.votes.get(cat, {}).values():
                    val = (v.get("value") or "").strip()
                    if not val:
                        continue
                    counts[val] = counts.get(val, 0) + 1
                # tri desc par occurrences
                res[cat] = dict(sorted(counts.items(), key=lambda kv: kv[1], reverse=True))
        return res

    def finalize(self) -> Dict[str, Any]:
        """
        Calcule le verdict collectif, met à jour les scores individuels,
        déplace l’agrégat dans l’historique, et réinitialise les votes.
        """
        with self._lock:
            counts = self.tally()
            verdicts: Dict[str, Any] = {}
            canon = NARRATIVE.canon

            # --- score collectif pondéré ---
            total_weight = 0.0
            score_weight = 0.0

            for cat in CATEGORIES:
                winner = next(iter(counts.get(cat, {}).keys()), None)
                canon_val = (canon.get(cat) or "").strip()
                success = (winner or "").casefold() == canon_val.casefold() if winner and canon_val else False
                verdicts[cat] = {"winner": winner, "canon": canon_val, "success": success}

                total_weight += WEIGHTS[cat]
                if success:
                    score_weight += WEIGHTS[cat]

            # --- mise à jour des scores individuels ---
            updated_players = []
            for pid, pdata in GAME_STATE.players.items():
                gained = 0
                for cat in CATEGORIES:
                    vote_val = (self.votes.get(cat, {}).get(pid, {}).get("value") or "").strip()
                    canon_val = (canon.get(cat) or "").strip()
                    if vote_val and canon_val and vote_val.casefold() == canon_val.casefold():
                        gained += int(WEIGHTS[cat] * 100)  # ex: 50 pts pour 'culprit'
                if gained:
                    pdata["score_total"] = pdata.get("score_total", 0) + gained
                    updated_players.append({"player_id": pid, "score_total": pdata["score_total"]})
            GAME_STATE.save()

            # --- résultat & reset ---
            result = {
                "verdicts": verdicts,
                "collective_score": score_weight * len(CATEGORIES),
                "collective_total": total_weight * len(CATEGORIES),
                "success_rate": round(score_weight / total_weight, 3) if total_weight else 0,
                "updated_players": updated_players,
            }
            self.history.append(result)
            self.votes = {cat: {} for cat in CATEGORIES}
            self.save()
            return result


TRIAL = TrialState()
TRIAL.load()
