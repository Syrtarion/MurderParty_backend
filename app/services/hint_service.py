from __future__ import annotations

import time
from typing import Any, Dict, List
from uuid import uuid4

from app.services.game_state import GameState
from app.services.story_seed import StorySeedError, load_story_seed_for_state
from app.services.ws_manager import ws_send_type_to_player_safe, ws_broadcast_type_safe


def _get_prepared_round(game_state: GameState, round_index: int) -> Dict[str, Any]:
    session = game_state.state.get("session") or {}
    prepared_rounds = session.get("prepared_rounds") or {}
    prepared = prepared_rounds.get(str(round_index))
    if not isinstance(prepared, dict):
        raise ValueError("Round not prepared")
    return prepared


def _get_hints_map(prepared: Dict[str, Any]) -> Dict[str, str]:
    assets = prepared.get("llm_assets") or {}
    hints_container = assets.get("hints") or {}
    hints_map = hints_container.get("hints") if isinstance(hints_container, dict) else None
    if not isinstance(hints_map, dict) or not hints_map:
        raise ValueError("No hints available for this round")
    return {str(k): str(v) for k, v in hints_map.items()}


def _load_sharing_rules(game_state: GameState, round_index: int) -> Dict[str, Any]:
    try:
        seed = load_story_seed_for_state(game_state)
    except StorySeedError:
        return {}
    rounds = seed.get("rounds") or []
    if 1 <= round_index <= len(rounds):
        round_conf = rounds[round_index - 1] or {}
        return (((round_conf.get("llm") or {}).get("hint_policy") or {}).get("sharing_rules") or {})
    return {}


def _resolve_other_tier(
    discoverer_tier: str,
    share: bool,
    hints_map: Dict[str, str],
    sharing_rules: Dict[str, Any],
) -> str:
    if share:
        return discoverer_tier

    candidate_keys = [f"discoverer_{discoverer_tier}_others"]
    if discoverer_tier == "major":
        candidate_keys.append("discoverer_major_others")
    elif discoverer_tier == "vague":
        candidate_keys.append("discoverer_vague_others")

    for key in candidate_keys:
        candidate = sharing_rules.get(key)
        if isinstance(candidate, str) and candidate in hints_map:
            return candidate

    for fallback in ("vague", "minor", "misleading"):
        if fallback in hints_map:
            return fallback

    return discoverer_tier


def _get_destroy_quota(game_state: GameState) -> int:
    try:
        seed = load_story_seed_for_state(game_state)
    except StorySeedError:
        return 0
    killer_rules = (seed.get("rules") or {}).get("killer") or {}
    quota = killer_rules.get("destroy_quota")
    try:
        return int(quota)
    except (TypeError, ValueError):
        return 0


def deliver_hint(
    game_state: GameState,
    round_index: int,
    discoverer_id: str,
    tier: str,
    share: bool,
) -> Dict[str, Any]:
    players = list(game_state.players.keys())
    if discoverer_id not in players:
        raise ValueError("Unknown discoverer")

    prepared = _get_prepared_round(game_state, round_index)
    hints_map = _get_hints_map(prepared)

    if tier not in hints_map:
        raise ValueError("Requested tier not available")

    sharing_rules = _load_sharing_rules(game_state, round_index)
    other_tier = _resolve_other_tier(tier, share, hints_map, sharing_rules)

    deliveries: List[Dict[str, Any]] = []
    for player_id in players:
        deliver_tier = tier if (share or player_id == discoverer_id) else other_tier
        text = hints_map.get(deliver_tier) or hints_map.get(tier) or ""
        deliveries.append({
            "player_id": player_id,
            "tier": deliver_tier,
            "text": text,
        })

    hint_id = uuid4().hex
    entry = {
        "hint_id": hint_id,
        "round_index": round_index,
        "discoverer_id": discoverer_id,
        "source_tier": tier,
        "shared": share,
        "deliveries": deliveries,
        "other_tier": other_tier,
        "destroyed": False,
        "created_at": time.time(),
    }

    hints_history = game_state.state.setdefault("hints_history", [])
    hints_history.append(entry)
    game_state.save()
    game_state.log_event("hint_delivered", {
        "hint_id": hint_id,
        "round_index": round_index,
        "discoverer_id": discoverer_id,
        "shared": share,
    })

    for delivery in deliveries:
        ws_send_type_to_player_safe(delivery["player_id"], "hint_delivered", {
            "session_id": game_state.session_id,
            "hint_id": hint_id,
            "round_index": round_index,
            "tier": delivery["tier"],
            "text": delivery["text"],
            "discoverer_id": discoverer_id,
            "shared": share,
        })

    ws_broadcast_type_safe("event", {
        "kind": "hint_delivered",
        "session_id": game_state.session_id,
        "hint_id": hint_id,
        "round_index": round_index,
        "discoverer_id": discoverer_id,
        "shared": share,
    })

    return entry


def destroy_hint(game_state: GameState, hint_id: str, killer_id: str) -> Dict[str, Any]:
    hints_history = game_state.state.get("hints_history") or []
    target = None
    for entry in hints_history:
        if entry.get("hint_id") == hint_id:
            target = entry
            break

    if not target:
        raise ValueError("Hint not found")

    if target.get("destroyed"):
        raise ValueError("Hint already destroyed")

    canon = game_state.state.get("canon") or {}
    culprit_id = canon.get("culprit_player_id")
    if culprit_id and killer_id != culprit_id:
        raise ValueError("Only the killer can destroy hints")

    quota = _get_destroy_quota(game_state)
    actions = game_state.state.setdefault("killer_actions", {"destroy_used": 0})
    used = int(actions.get("destroy_used", 0))
    if quota and used >= quota:
        raise ValueError("Destroy quota reached")

    target["destroyed"] = True
    target["destroyed_at"] = time.time()
    target["destroyed_by"] = killer_id
    actions["destroy_used"] = used + 1

    game_state.save()
    game_state.log_event("hint_destroyed", {
        "hint_id": hint_id,
        "killer_id": killer_id,
    })

    ws_broadcast_type_safe("event", {
        "kind": "hint_destroyed",
        "session_id": game_state.session_id,
        "hint_id": hint_id,
        "killer_id": killer_id,
    })

    return target
