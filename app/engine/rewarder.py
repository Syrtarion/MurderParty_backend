from typing import Dict, Any, List, Tuple

from app.services.minigame_catalog import CATALOG
from app.services.minigame_runtime import RUNTIME
from app.services.game_state import GAME_STATE
from app.services.narrative_core import NARRATIVE
from app.services.llm_engine import generate_indice
from app.services.ws_manager import (
    WS,
    ws_send_to_player_safe,   # au lieu de ws_send_to_player
    ws_broadcast_safe,        # au lieu de ws_broadcast
    ws_send_type_to_player_safe,
    ws_broadcast_type_safe,
)



def _rank(scores: Dict[str, int]) -> List[Tuple[str, int]]:
    """Retourne une liste [(participant_id, score), ...] triée par score décroissant."""
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)


def _resolve_recipients(session: Dict[str, Any], target_id: str) -> List[str]:
    """Pour un target (team_id en mode team, player_id en solo), renvoie la liste des player_id à récompenser."""
    if session["mode"] == "team":
        teams = session.get("teams") or {}
        return teams.get(target_id, [])
    else:
        return [target_id]


async def resolve_and_reward(session_id: str) -> Dict[str, Any]:
    """
    Calcule le classement d'une session, applique la reward_policy du mini-jeu,
    génère les indices, les attribue aux destinataires, journalise et broadcast WS.
    Clôture la session ensuite.
    """
    session = RUNTIME.get(session_id)
    assert session, "Unknown session"

    game = CATALOG.get(session["game_id"])
    assert game, "Unknown game in catalog"

    scores = session.get("scores", {})
    ranking = _rank(scores)
    rewards = game.get("reward_policy", [])
    awarded: List[Dict[str, Any]] = []

    for rule in rewards:
        rank_index = rule["rank"] - 1
        if rank_index < len(ranking):
            target_id = ranking[rank_index][0]  # team_id ou player_id selon mode
            kind = rule["clue_kind"]
            count = rule.get("count", 1)

            for _ in range(count):
                prompt = f"Génère un indice {kind} cohérent avec le canon, lié au mini-jeu '{game['id']}'."
                clue = generate_indice(prompt, kind)
                text = clue.get("text", "")

                recipients = _resolve_recipients(session, target_id)

                # Persistance côté canon + journalisation
                NARRATIVE.append_clue(kind, {"text": text, "kind": kind, "to": recipients, "by_session": session_id})
                GAME_STATE.log_event("clue_awarded", {"to": recipients, "kind": kind, "session_id": session_id})

                # Broadcast temps réel (les clients filtrent côté front par leur player_id)
                await WS.broadcast({
                    "type": "clue_awarded",
                    "payload": {"to": recipients, "kind": kind, "text": text}
                })

                awarded.append({"to": recipients, "kind": kind, "text": text})

    RUNTIME.close(session_id)

    return {"session_id": session_id, "awarded": awarded, "ranking": ranking}
