"""
Envelope utilities shared across MJ routes.
The helpers expose both MJ views (summary, reset, distribution) and player views.
All public functions accept an optional GameState override so that multi-session
scenarios can target the right in-memory store; by default the global singleton
is used which preserves legacy behaviour.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple
import json
import heapq
import re
from pathlib import Path

from app.services.game_state import GAME_STATE, GameState


IMPORTANCE_ORDER = {"high": 0, "medium": 1, "low": 2}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _resolve_state(game_state: GameState | None = None) -> GameState:
    return game_state or GAME_STATE


def _normalize_id(value: Any) -> str:
    return str(value) if value is not None else ""


def _players_list(game_state: GameState | None = None) -> List[Dict[str, Any]]:
    state = _resolve_state(game_state)
    return list(state.players.values())


def _app_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _seed_default_path() -> str:
    """
    Resolve the default story seed path with optional override from settings.
    Priority:
      1. settings.STORY_SEED_PATH (if provided)
      2. app/data/story_seed.json
    """
    try:
        from app.config.settings import settings  # type: ignore

        target = getattr(settings, "STORY_SEED_PATH", None)
        if target:
            return str(Path(str(target)).expanduser().resolve())
    except Exception:
        pass
    return str((_app_root() / "data" / "story_seed.json").resolve())


def _load_seed_from_disk() -> Dict[str, Any]:
    path = _seed_default_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle) or {}
    except Exception:
        return {}


def _get_seed_live(game_state: GameState | None = None) -> Dict[str, Any]:
    """
    Reading priority:
      1. story_seed already present in memory for the target GameState,
      2. fallback to the JSON file on disk.
    """
    state = _resolve_state(game_state)
    seed_mem = state.state.get("story_seed")
    if isinstance(seed_mem, dict) and seed_mem:
        return seed_mem
    return _load_seed_from_disk()


def _envs_from_seed(game_state: GameState | None = None) -> List[Dict[str, Any]]:
    seed = _get_seed_live(game_state)
    envs = seed.get("envelopes") or []
    for env in envs:
        env["id"] = _normalize_id(env.get("id"))
    return envs


def _bucket_by_importance(envs: Iterable[Dict[str, Any]]):
    high: List[Dict[str, Any]] = []
    medium: List[Dict[str, Any]] = []
    low: List[Dict[str, Any]] = []
    for env in envs:
        if env.get("assigned_player_id"):
            continue
        imp = str(env.get("importance", "medium")).lower()
        rank = IMPORTANCE_ORDER.get(imp, 1)
        if rank == 0:
            high.append(env)
        elif rank == 1:
            medium.append(env)
        else:
            low.append(env)
    return high, medium, low


def _count_per_player(envs: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for env in envs:
        player_id = env.get("assigned_player_id")
        if not player_id:
            continue
        counts[player_id] = counts.get(player_id, 0) + 1
    return counts


def _sync_players_envelopes_from_seed(game_state: GameState | None = None) -> None:
    """Update players[pid].envelopes view based on the current seed content."""
    state = _resolve_state(game_state)
    envs = _envs_from_seed(game_state)

    by_player: Dict[str, List[str]] = {}
    for env in envs:
        player_id = env.get("assigned_player_id")
        if not player_id:
            continue
        env_id = _normalize_id(env.get("id"))
        by_player.setdefault(player_id, []).append(env_id)

    def _env_sort_key(env_id: str):
        match = re.search(r"(\d+)$", env_id)
        return (0, int(match.group(1))) if match else (1, env_id)

    for pid in by_player:
        by_player[pid].sort(key=_env_sort_key)

    for pid, player in state.players.items():
        ids = by_player.get(pid, [])
        player["envelopes"] = [{"num": idx + 1, "id": env_id} for idx, env_id in enumerate(ids)]


# ---------------------------------------------------------------------------
# Public helpers (MJ)
# ---------------------------------------------------------------------------
def reset_envelope_assignments(game_state: GameState | None = None) -> Dict[str, Any]:
    """
    MJ utility: reset assigned_player_id for every envelope in memory, resync the
    player view and persist the GameState.
    """
    state = _resolve_state(game_state)
    seed = state.state.get("story_seed")
    if not isinstance(seed, dict) or not seed:
        seed = _load_seed_from_disk()
        state.state["story_seed"] = seed

    envs = seed.get("envelopes") or []
    for env in envs:
        if "assigned_player_id" in env:
            env["assigned_player_id"] = None

    _sync_players_envelopes_from_seed(game_state)
    state.save()
    return {"ok": True, "reset": len(envs)}


def summary_for_mj(
    include_hints: bool = False,
    game_state: GameState | None = None,
) -> Dict[str, Any]:
    """
    Build a diagnostic summary for the MJ dashboard.
    Prefer in-memory data; fall back to disk when memory is empty.
    """
    state = _resolve_state(game_state)
    source = "memory"
    seed_path = None

    mem_seed = state.state.get("story_seed")
    envs = None
    if isinstance(mem_seed, dict) and mem_seed.get("envelopes"):
        envs = mem_seed.get("envelopes") or []
    else:
        envs = _load_seed_from_disk().get("envelopes") or []
        source = "disk"
        seed_path = _seed_default_path()

    total = len(envs)
    assigned = len([env for env in envs if env.get("assigned_player_id")])
    left = total - assigned
    per_player = _count_per_player(envs)
    high, medium, low = _bucket_by_importance(envs)

    payload: Dict[str, Any] = {
        "ok": True,
        "source": source,
        "total": total,
        "assigned": assigned,
        "left": left,
        "per_player": per_player,
        "buckets": {
            "high": len(high),
            "medium": len(medium),
            "low": len(low),
        },
    }
    if seed_path:
        payload["seed_path"] = seed_path

    if include_hints:
        payload["hints"] = {
            "high": high,
            "medium": medium,
            "low": low,
        }

    return payload


def distribute_envelopes_equitable(game_state: GameState | None = None) -> Dict[str, Any]:
    """
    Fairly distribute every non-assigned envelope across players by selecting the
    least-served player at each step (min-heap). Existing assignments are preserved.
    """
    state = _resolve_state(game_state)
    players = _players_list(game_state)
    if not players:
        return {"assigned": 0, "left": 0, "per_player": {}}

    seed = state.state.get("story_seed")
    if not isinstance(seed, dict) or not seed:
        seed = _load_seed_from_disk()
        state.state["story_seed"] = seed

    envs = seed.get("envelopes") or []
    for env in envs:
        env["id"] = _normalize_id(env.get("id"))

    to_assign = [env for env in envs if not env.get("assigned_player_id")]
    if not to_assign:
        _sync_players_envelopes_from_seed(game_state)
        state.save()
        left = len([env for env in envs if not env.get("assigned_player_id")])
        return {"assigned": 0, "left": left, "per_player": _count_per_player(envs)}

    def _env_sort_key(env: Dict[str, Any]):
        importance = str(env.get("importance", "medium")).lower()
        rank = IMPORTANCE_ORDER.get(importance, 1)
        tail = str(env.get("id"))
        match = re.search(r"(\d+)$", tail)
        id_key = (0, int(match.group(1))) if match else (1, tail)
        return (rank, id_key)

    to_assign.sort(key=_env_sort_key)
    counts = _count_per_player(envs)

    heap: List[Tuple[int, int, str]] = []
    for index, player in enumerate(players):
        pid = player["player_id"]
        heapq.heappush(heap, (counts.get(pid, 0), index, pid))

    assigned_now = 0
    for env in to_assign:
        count, tie_break, pid = heapq.heappop(heap)
        env["assigned_player_id"] = pid
        assigned_now += 1
        heapq.heappush(heap, (count + 1, tie_break, pid))

    _sync_players_envelopes_from_seed(game_state)
    state.save()

    left = len([env for env in envs if not env.get("assigned_player_id")])
    return {"assigned": assigned_now, "left": left, "per_player": _count_per_player(envs)}


# ---------------------------------------------------------------------------
# Player-facing helpers
# ---------------------------------------------------------------------------
def player_envelopes(player_id: str, game_state: GameState | None = None) -> List[Dict[str, Any]]:
    """
    Return the ordered list of envelopes assigned to the player.
    Uses the cached view in game_state.players when available.
    """
    state = _resolve_state(game_state)
    player = state.players.get(player_id)
    if player and isinstance(player.get("envelopes"), list):
        return [{"num": int(env.get("num")), "id": _normalize_id(env.get("id"))} for env in player["envelopes"]]

    envs = _envs_from_seed(game_state)
    owned = [env for env in envs if env.get("assigned_player_id") == player_id]

    def _env_sort_key(env_id: str):
        match = re.search(r"(\d+)$", env_id)
        return (0, int(match.group(1))) if match else (1, env_id)

    ordered = sorted((_normalize_id(env.get("id")) for env in owned), key=_env_sort_key)
    return [{"num": idx + 1, "id": env_id} for idx, env_id in enumerate(ordered)]


def assign_envelope_to_player(
    envelope_id: str | int,
    player_id: str,
    game_state: GameState | None = None,
) -> Dict[str, Any]:
    """
    (Re)assign a specific envelope to a player in memory and persist the change.
    Returns the previous owner if any.
    """
    state = _resolve_state(game_state)
    seed = state.state.get("story_seed")
    if not isinstance(seed, dict) or not seed:
        seed = _load_seed_from_disk()
        state.state["story_seed"] = seed

    envs = seed.get("envelopes") or []
    target_id = _normalize_id(envelope_id)

    previous_owner = None
    found = None
    for env in envs:
        if _normalize_id(env.get("id")) == target_id:
            previous_owner = env.get("assigned_player_id")
            env["assigned_player_id"] = player_id
            found = env
            break

    if not found:
        return {"ok": False, "reason": "envelope_not_found"}

    _sync_players_envelopes_from_seed(game_state)
    state.save()

    return {
        "ok": True,
        "envelope_id": target_id,
        "previous_owner": previous_owner,
        "new_owner": player_id,
    }
