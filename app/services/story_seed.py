from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, List

from pydantic import ValidationError

from app.config.settings import settings
from app.models.story_seed import StorySeed
from app.services.game_state import GAME_STATE, GameState


class StorySeedError(RuntimeError):
    """Raised when the story seed cannot be loaded or validated."""


def _campaigns_dir() -> Path:
    data_dir = Path(str(settings.DATA_DIR)).expanduser().resolve()
    return data_dir / "campaigns"


def _candidate_paths(campaign: Optional[str]) -> List[Path]:
    explicit = getattr(settings, "STORY_SEED_PATH", None)
    if explicit:
        return [Path(str(explicit)).expanduser().resolve()]

    data_dir = Path(str(settings.DATA_DIR)).expanduser().resolve()
    campaigns_dir = _campaigns_dir()
    slugs = []
    if campaign:
        slugs.append(campaign)
    default_campaign = getattr(settings, "DEFAULT_CAMPAIGN", None)
    if default_campaign and default_campaign not in slugs:
        slugs.append(default_campaign)

    candidates: List[Path] = [
        campaigns_dir / slug / "story_seed.json" for slug in slugs
    ]
    candidates.append(data_dir / "story_seed.json")
    return candidates


def get_story_seed_path(campaign: Optional[str] = None) -> Path:
    """
    Determine the path of the active story_seed file.
    Priority:
      1) settings.STORY_SEED_PATH if provided,
      2) app/data/story_seed.json within the project.
    """
    candidates = _candidate_paths(campaign)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    # Return the first candidate even if it does not exist to surface a precise error later.
    return candidates[0]


def load_story_seed(campaign: Optional[str] = None, path: Optional[Path] = None) -> StorySeed:
    """
    Load the story seed as a typed model.
    Raises StorySeedError if the file is missing or invalid.
    """
    story_seed_path = path or get_story_seed_path(campaign=campaign)
    try:
        raw = json.loads(story_seed_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise StorySeedError(f"story_seed.json not found at {story_seed_path}") from exc
    except json.JSONDecodeError as exc:
        raise StorySeedError(f"story_seed.json is not valid JSON ({exc})") from exc

    if not isinstance(raw, dict):
        raise StorySeedError("story_seed.json must contain a JSON object at the root.")

    # Ensure meta/version defaults for legacy seeds
    meta = raw.setdefault("meta", {})
    meta.setdefault("version", "1.0")
    if "timing_policy" not in meta:
        meta["timing_policy"] = {}

    try:
        return StorySeed.model_validate(raw)
    except ValidationError as exc:
        raise StorySeedError(f"story_seed.json does not match the expected schema: {exc}") from exc


def load_story_seed_dict(campaign: Optional[str] = None, path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Load the story seed and return it as a Python dict (deep copy).
    """
    model = load_story_seed(campaign=campaign, path=path)
    return model.to_dict()


def load_story_seed_for_state(
    game_state: Optional[GameState] = None,
    *,
    refresh: bool = False,
    cache: bool = True,
) -> Dict[str, Any]:
    """
    Helper that returns the active story seed for the provided GameState.
    Falls back to the global GAME_STATE when no override is given.
    When refresh=False it reuses the cached seed stored in state.state["story_seed"].
    """
    state = game_state or GAME_STATE
    if not refresh:
        cached = state.state.get("story_seed")
        if isinstance(cached, dict) and cached:
            return cached

    campaign = state.state.get("campaign_id") or settings.DEFAULT_CAMPAIGN
    seed = load_story_seed_dict(campaign=campaign)
    if cache and seed:
        state.state["story_seed"] = seed
    return seed
