from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import ValidationError

from app.config.settings import settings
from app.models.story_seed import StorySeed


class StorySeedError(RuntimeError):
    """Raised when the story seed cannot be loaded or validated."""


def get_story_seed_path() -> Path:
    """
    Determine the path of the active story_seed file.
    Priority:
      1) settings.STORY_SEED_PATH if provided,
      2) app/data/story_seed.json within the project.
    """
    explicit = getattr(settings, "STORY_SEED_PATH", None)
    if explicit:
        return Path(str(explicit)).expanduser().resolve()
    data_dir = Path(str(settings.DATA_DIR)).expanduser().resolve()
    return data_dir / "story_seed.json"


def load_story_seed(path: Optional[Path] = None) -> StorySeed:
    """
    Load the story seed as a typed model.
    Raises StorySeedError if the file is missing or invalid.
    """
    story_seed_path = path or get_story_seed_path()
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


def load_story_seed_dict(path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Load the story seed and return it as a Python dict (deep copy).
    """
    model = load_story_seed(path=path)
    return model.to_dict()
