"""
Engine: rewarder.py
Rôle:
- Résoudre une session de mini-jeu et distribuer des récompenses (indices) selon
  la `reward_policy` définie dans le catalogue du mini-jeu.

Flux principal (resolve_and_reward):
1) Récupère la session active (RUNTIME.get) et la fiche mini-jeu (CATALOG.get).
2) Calcule le classement `ranking` à partir des `scores`.
3) Pour chaque règle de reward_policy (par rang, type d'indice, quantité):
   - Identifie la cible (team_id en mode "team", sinon player_id).
   - Génère un indice via `generate_indice` (LLM).
   - Persiste l'indice dans le canon (`NARRATIVE.append_clue`) + log (`GAME_STATE.log_event`).
   - Diffuse un WS broadcast avec le contenu pour que les clients filtrent côté front.
4) Clôture la session dans le runtime (RUNTIME.close).
5) Retourne {session_id, awarded, ranking}.

Conception:
- `_resolve_recipients` mappe une cible (équipe ou joueur) vers une liste de player_ids.
- Les clients côté front se chargent d’afficher uniquement les indices qui les concernent.
- Le moteur n’augmente pas ici de score de joueurs: il ne gère que les indices.
"""
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
    """
    Pour un target (team_id en mode team, player_id en solo), renvoie la liste des player_id à récompenser.
    - mode 'team'  → on cherche les membres de l'équipe cible dans session['teams'].
    - mode 'solo'  → la cible est déjà un player_id.
    """
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

    Retour:
    - 'awarded': liste des récompenses distribuées [{to:[pid...], kind, text}, ...]
    - 'ranking': classement final [(participant_id, score), ...]
    """
    # --- 1) Récupération des contextes (session + fiche mini-jeu) ---
    session = RUNTIME.get(session_id)
    assert session, "Unknown session"

    game = CATALOG.get(session["game_id"])
    assert game, "Unknown game in catalog"

    # --- 2) Classement & règles ---
    scores = session.get("scores", {})
    ranking = _rank(scores)                  # ex: [("team_A", 42), ("team_B", 36)]
    rewards = game.get("reward_policy", [])  # ex: [{"rank":1,"clue_kind":"crucial","count":1}, ...]
    awarded: List[Dict[str, Any]] = []

    # --- 3) Application des règles de récompense ---
    for rule in rewards:
        rank_index = rule["rank"] - 1
        if rank_index < len(ranking):
            target_id = ranking[rank_index][0]  # team_id ou player_id selon mode
            kind = rule["clue_kind"]
            count = rule.get("count", 1)

            for _ in range(count):
                # Prompt minimal: le LLM génère un indice court FR en respectant le canon
                prompt = f"Génère un indice {kind} cohérent avec le canon, lié au mini-jeu '{game['id']}'."
                clue = generate_indice(prompt, kind)
                text = clue.get("text", "")

                recipients = _resolve_recipients(session, target_id)

                # 3.a) Persistance côté canon + log runtime
                NARRATIVE.append_clue(kind, {"text": text, "kind": kind, "to": recipients, "by_session": session_id})
                GAME_STATE.log_event("clue_awarded", {"to": recipients, "kind": kind, "session_id": session_id})

                # 3.b) Diffusion temps réel (les clients filtrent par player_id)
                await WS.broadcast({
                    "type": "clue_awarded",
                    "payload": {"to": recipients, "kind": kind, "text": text}
                })

                awarded.append({"to": recipients, "kind": kind, "text": text})

    # --- 4) Clôture de la session ---
    RUNTIME.close(session_id)

    # --- 5) Résultat consolidé ---
    return {"session_id": session_id, "awarded": awarded, "ranking": ranking}
