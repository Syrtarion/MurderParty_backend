"""
Service: mj_engine.py
Rôle:
- Orchestrateur "macro" des phases MJ (ouverture, enveloppes, rôles, session active).
- Diffuse les changements de phase via WS et consigne dans GAME_STATE.

Phases:
- WAITING_START → WAITING_PLAYERS → ENVELOPES_DISTRIBUTION → ROLES_ASSIGNED → SESSION_ACTIVE → ACCUSATION_OPEN → ENDED

I/O:
- story_seed.json (enveloppes à répartir)
- characters.json (attribution simple si dispo)
- story_seed.json (lecture de rounds et enveloppes)

Notes:
- Méthodes `players_ready()` et `envelopes_done()` envoient des WS ciblés/collectifs.
- `_assign_envelopes_equitable()` → distribution round-robin + WS perso.
- `_assign_characters_if_available()` → pick naïf depuis characters.json.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Any, Optional
import json
import random

from app.services.game_state import GAME_STATE
from app.services.narrative_core import NARRATIVE
from app.services.ws_manager import WS
from app.config.settings import settings
from app.services.story_seed import StorySeedError, load_story_seed_for_state

DATA_DIR = Path(settings.DATA_DIR)

# --- Phases de la partie (états globaux) ---
WAITING_START = "WAITING_START"
WAITING_PLAYERS = "WAITING_PLAYERS"
ENVELOPES_DISTRIBUTION = "ENVELOPES_DISTRIBUTION"
ROLES_ASSIGNED = "ROLES_ASSIGNED"
SESSION_ACTIVE = "SESSION_ACTIVE"
ACCUSATION_OPEN = "ACCUSATION_OPEN"
ENDED = "ENDED"

CHARACTERS_PATH = DATA_DIR / "characters.json"


def _load_json(path: Path, default: Any) -> Any:
    """Lecture JSON tolérante (retourne `default` en cas d'erreur)."""
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


@dataclass
class MJEngine:
    """Moteur de régie automatique (le jeu fait MJ).

    Il orchestre les phases d'ouverture de partie avant les rounds:
      1) WAITING_PLAYERS (après /party/start)
      2) ENVELOPES_DISTRIBUTION (après /party/players_ready)
      3) ROLES_ASSIGNED (après /party/envelopes_done)
      4) SESSION_ACTIVE (prêt à suivre session_plan.json)
    """

    def phase(self) -> str:
        """Retourne l'étiquette de phase courante (ou WAITING_START par défaut)."""
        return GAME_STATE.state.get("phase_label", WAITING_START)

    def set_phase(self, phase: str) -> None:
        """Met à jour la phase côté GAME_STATE et persiste immédiatement."""
        GAME_STATE.state["phase_label"] = phase
        GAME_STATE.save()

    async def start_party(self) -> Dict[str, Any]:
        """Initialise la soirée et passe en attente des joueurs (+ broadcast phase)."""
        self.set_phase(WAITING_PLAYERS)
        GAME_STATE.log_event("phase_change", {"phase": WAITING_PLAYERS})
        await WS.broadcast({
            "type": "event",
            "kind": "phase_change",
            "phase": WAITING_PLAYERS,
            "text": "La partie démarre. Les invités peuvent arriver."
        })
        return {"ok": True, "phase": WAITING_PLAYERS}

    async def players_ready(self) -> Dict[str, Any]:
        """Signal explicite: tous les joueurs sont arrivés → distribution des enveloppes (équitable)."""
        if not GAME_STATE.players:
            return {"ok": False, "error": "Aucun joueur inscrit."}

        self.set_phase(ENVELOPES_DISTRIBUTION)
        GAME_STATE.log_event("phase_change", {"phase": ENVELOPES_DISTRIBUTION})
        await WS.broadcast({
            "type": "event",
            "kind": "phase_change",
            "phase": ENVELOPES_DISTRIBUTION,
            "text": "Tous les invités sont là. Distribution des enveloppes à cacher."
        })

        # Distribuer les enveloppes à cacher (équitablement)
        assigned = await self._assign_envelopes_equitable()
        return {"ok": True, "phase": ENVELOPES_DISTRIBUTION, "assigned_envelopes": assigned}

    async def envelopes_done(self) -> Dict[str, Any]:
        """Fin de la distribution des enveloppes → attribue des personnages (si dispo) puis passe à ROLES_ASSIGNED/SESSION_ACTIVE."""
        # Attribution de personnages (si un catalogue existe)
        roles = await self._assign_characters_if_available()

        self.set_phase(ROLES_ASSIGNED)
        GAME_STATE.log_event("phase_change", {"phase": ROLES_ASSIGNED})
        await WS.broadcast({
            "type": "event",
            "kind": "phase_change",
            "phase": ROLES_ASSIGNED,
            "text": "Les rôles sont attribués. La partie peut commencer."
        })

        # Flag: prêt à suivre le session_plan
        self.set_phase(SESSION_ACTIVE)
        GAME_STATE.log_event("phase_change", {"phase": SESSION_ACTIVE})
        await WS.broadcast({
            "type": "event",
            "kind": "phase_change",
            "phase": SESSION_ACTIVE,
            "text": "Prêt pour le premier round. Le système annoncera le mini-jeu quand il sera temps."
        })
        return {"ok": True, "phase": SESSION_ACTIVE, "assigned_roles": roles}

    def status(self) -> Dict[str, Any]:
        """Resume utile pour le front MJ (phase, joueurs, presence d'un plan)."""
        players = GAME_STATE.players or {}
        phase = self.phase()
        try:
            seed = load_story_seed_for_state(GAME_STATE)
            rounds = seed.get("rounds") or []
        except StorySeedError:
            rounds = []
        return {
            "phase": phase,
            "players_count": len(players),
            "players": list(players.keys()),
            "has_session_plan": bool(rounds),
            "next_round_id": 1 if rounds else None,
        }

    # ----------------- Helpers internes -----------------

    async def _assign_envelopes_equitable(self) -> Dict[str, List[int]]:
        """Répartit équitablement les enveloppes à cacher entre les joueurs (round-robin) et notifie via WS."""
        try:
            seed = load_story_seed_for_state(GAME_STATE)
        except StorySeedError:
            seed = {}
        envelopes = seed.get("envelopes", [])
        if not envelopes:
            # Pas d'enveloppes configurées → on log seulement
            GAME_STATE.state["envelopes_to_hide"] = {}
            GAME_STATE.save()
            return {}

        players_ids = list(GAME_STATE.players.keys())
        if not players_ids:
            return {}

        # Round-robin: distribution régulière
        distribution: Dict[str, List[int]] = {pid: [] for pid in players_ids}
        for idx, env in enumerate(envelopes):
            eid = env.get("id", idx + 1)
            pid = players_ids[idx % len(players_ids)]
            distribution[pid].append(int(eid))

        GAME_STATE.state["envelopes_to_hide"] = distribution
        GAME_STATE.save()
        GAME_STATE.log_event("envelopes_assigned", {"by_player": distribution})

        # Push WS par joueur
        for pid, lst in distribution.items():
            if not lst:
                continue
            await WS.send_to_player(pid, {
                "type": "envelopes_to_hide",
                "envelopes": lst
            })
        return distribution

    async def _assign_characters_if_available(self) -> Dict[str, Any]:
        """Attribue des personnages uniques depuis characters.json (si présent)."""
        if not CHARACTERS_PATH.exists():
            return {}
        try:
            catalog = json.loads(CHARACTERS_PATH.read_text(encoding="utf-8"))
            # Le catalogue peut être une liste ou un dict {characters:[...]}
            if isinstance(catalog, dict) and "characters" in catalog:
                pool = list(catalog["characters"])
            else:
                pool = list(catalog)
        except Exception:
            pool = []

        random.shuffle(pool)
        assigned: Dict[str, Any] = {}
        for pid, pdata in GAME_STATE.players.items():
            if pdata.get("character"):
                continue  # déjà attribué
            if not pool:
                break
            char = pool.pop()
            # Normalisation minimale
            name = char.get("name") or char.get("title") or char.get("id") or "Personnage"
            pdata["character"] = name
            pdata["character_id"] = char.get("id", name.lower().replace(" ", "_"))
            if desc := char.get("description"):
                pdata["character_desc"] = desc
            assigned[pid] = {
                "character": pdata["character"],
                "character_id": pdata["character_id"]
            }
            # Push WS ciblé (ne casse pas si WS indisponible)
            try:
                await WS.send_to_player(pid, {
                    "type": "character_assigned",
                    "character": {
                        "id": pdata["character_id"],
                        "name": pdata["character"],
                        "description": pdata.get("character_desc")
                    }
                })
            except Exception:
                pass

        GAME_STATE.save()
        if assigned:
            GAME_STATE.log_event("characters_assigned", {"count": len(assigned)})
        return assigned


MJ = MJEngine()
