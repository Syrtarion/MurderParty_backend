# app/services/roles_engine.py
from __future__ import annotations
from typing import Dict, Any, List
import hashlib

from app.services.game_state import GAME_STATE

def _stable_choice(items: List[str], salt: str) -> str:
    if not items:
        return ""
    h = hashlib.sha256()
    players = sorted(GAME_STATE.players.keys())
    h.update( ("|".join(players) + "|" + (GAME_STATE.state.get("phase_label") or "") + "|" + salt).encode("utf-8") )
    idx = int(h.hexdigest(), 16) % len(items)
    return items[idx]

def canon_ready() -> bool:
    canon = GAME_STATE.state.get("canon")
    return isinstance(canon, dict) and bool(canon.get("weapon")) and bool(canon.get("location")) and bool(canon.get("motive"))

def ensure_canon_from_narrative() -> Dict[str, Any] | None:
    """
    Si master_canon a déjà écrit un canon dans NARRATIVE (ou si tu le recopies dans GAME_STATE.state["canon"]),
    tu peux le retrouver ici. Par défaut, on regarde GAME_STATE.state["canon"].
    """
    canon = GAME_STATE.state.get("canon")
    return canon if isinstance(canon, dict) else None

def assign_roles_and_missions() -> Dict[str, Any]:
    """
    Assigne "killer"/"innocent" + une mission secondaire à chaque joueur, et stocke dans GAME_STATE.
    - Le killer est choisi de façon déterministe parmi les players présents (pas au hasard pur).
    - Les missions sont minimales (placeholder) pour l’instant.
    """
    players = list(GAME_STATE.players.values())
    if not players:
        return {"killer_player_id": None, "per_player": {}}

    pids = sorted([p["player_id"] for p in players])
    killer_pid = _stable_choice(pids, "killer")
    if killer_pid not in pids:
        killer_pid = pids[0]

    per_player: Dict[str, Any] = {}
    for p in players:
        pid = p["player_id"]
        role = "killer" if pid == killer_pid else "innocent"
        if role == "killer":
            mission = {"title": "Échapper aux soupçons", "text": "Sème le doute sur un autre invité sans te faire remarquer."}
        else:
            mission = {"title": "Observer discrètement", "text": "Récolte 2 indices qui disculpent un autre joueur et partage-les."}
        # Persist in GAME_STATE
        GAME_STATE.players[pid]["role"] = role
        GAME_STATE.players[pid]["mission"] = mission
        per_player[pid] = {"role": role, "mission": mission}

    return {"killer_player_id": killer_pid, "per_player": per_player}
