"""
Mini-game reward engine.
Resolves one mini-game session, applies its reward policy and dispatches clues.
Supports multi-session by optionally receiving the parent GameState and the
`murder_session_id` used to tie data together.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.services.minigame_catalog import CATALOG
from app.services.minigame_runtime import RUNTIME
from app.services.game_state import GAME_STATE, GameState
from app.services.narrative_core import NARRATIVE
from app.services.llm_engine import generate_indice
from app.services.ws_manager import WS


def _rank(scores: Dict[str, int]) -> List[Tuple[str, int]]:
    """Return participants sorted by score (descending)."""
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


def _resolve_recipients(session: Dict[str, Any], target_id: str) -> List[str]:
    """
    Resolve the player ids that should receive a reward for the given target.
    In team mode the target is a team identifier.
    """
    if session.get("mode") == "team":
        teams = session.get("teams") or {}
        return teams.get(target_id, [])
    return [target_id]


async def resolve_and_reward(
    session_id: str,
    murder_session_id: Optional[str] = None,
    game_state: GameState | None = None,
) -> Dict[str, Any]:
    """
    Resolve a mini-game session: compute ranking, generate clues via the LLM,
    log them and broadcast WebSocket events. The runtime entry is closed at the end.
    """
    state = game_state or GAME_STATE

    session = RUNTIME.get(session_id, murder_session_id)
    if not session:
        raise AssertionError("Unknown mini-game session")

    game = CATALOG.get(session["game_id"])
    if not game:
        raise AssertionError("Unknown mini-game in catalog")

    scores = session.get("scores", {})
    ranking = _rank(scores)
    rewards = game.get("reward_policy", [])
    awarded: List[Dict[str, Any]] = []

    for rule in rewards:
        rank_index = rule["rank"] - 1
        if rank_index >= len(ranking):
            continue
        target_id = ranking[rank_index][0]
        kind = rule["clue_kind"]
        count = rule.get("count", 1)

        for _ in range(count):
            prompt = (
                f"Genere un indice {kind} coherant avec le canon, lie au mini-jeu '{game['id']}'. "
                "Retourne seulement l'indice en francais."
            )
            clue = generate_indice(prompt, kind) or {}
            text = clue.get("text", "")
            recipients = _resolve_recipients(session, target_id)

            NARRATIVE.append_clue(
                kind,
                {"text": text, "kind": kind, "to": recipients, "by_session": session_id},
            )
            state.log_event(
                "clue_awarded",
                {"to": recipients, "kind": kind, "session_id": session_id},
            )

            await WS.broadcast(
                {
                    "type": "clue_awarded",
                    "payload": {"to": recipients, "kind": kind, "text": text},
                }
            )

            awarded.append({"to": recipients, "kind": kind, "text": text})

    RUNTIME.close(session_id, murder_session_id)
    return {"session_id": session_id, "awarded": awarded, "ranking": ranking}
