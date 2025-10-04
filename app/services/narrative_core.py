from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock  # <<< ici
from typing import Any, Dict, List
import re

from app.config.settings import settings
from .io_utils import read_json, write_json

DATA_DIR = Path(settings.DATA_DIR)
CANON_PATH = DATA_DIR / "canon_narratif.json"

DEFAULT_CANON = {
    "locked": False,
    "culprit": None,
    "weapon": None,
    "location": None,
    "motive": None,
    "clues": {"crucial": [], "red_herrings": [], "ambiguous": [], "decor": []},
}

@dataclass
class NarrativeCore:
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)  # <<< ici
    canon: Dict[str, Any] = field(default_factory=lambda: DEFAULT_CANON.copy())

    def load(self) -> None:
        with self._lock:
            data = read_json(CANON_PATH)
            self.canon = data or DEFAULT_CANON.copy()

    def save(self) -> None:
        with self._lock:
            write_json(CANON_PATH, self.canon)

    def choose_culprit(self, culprit: str, weapon: str, location: str, motive: str) -> Dict[str, Any]:
        with self._lock:
            if self.canon.get("locked"):
                return self.canon
            self.canon.update({
                "culprit": culprit,
                "weapon": weapon,
                "location": location,
                "motive": motive,
                "locked": True,
            })
            self.save()  # ok car RLock
            return self.canon

    def append_clue(self, kind: str, clue: Dict[str, Any]) -> None:
        with self._lock:
            bucket = self.canon.setdefault("clues", {}).setdefault(kind, [])
            bucket.append(clue)
            self.save()  # ok car RLock


NARRATIVE = NarrativeCore()
NARRATIVE.load()


# ---- contexte & anti-spoiler helpers ----
def get_canon_summary() -> dict:
    c = NARRATIVE.canon
    return {
        "locked": c.get("locked", False),
        "culprit": c.get("culprit"),
        "weapon": c.get("weapon"),
        "location": c.get("location"),
        "motive": c.get("motive"),
        "last_clues": {
            "crucial": c.get("clues", {}).get("crucial", [])[-3:],
            "red_herrings": c.get("clues", {}).get("red_herrings", [])[-3:],
            "ambiguous": c.get("clues", {}).get("ambiguous", [])[-3:],
            "decor": c.get("clues", {}).get("decor", [])[-3:],
        }
    }


def get_sensitive_terms() -> List[str]:
    c = NARRATIVE.canon
    terms = []
    for k in ("culprit", "weapon", "location", "motive"):
        v = c.get(k)
        if isinstance(v, str) and v:
            terms.append(v)
    culprit = c.get("culprit")
    if isinstance(culprit, str) and culprit:
        parts = culprit.split()
        terms.extend(parts)
        terms.append(culprit)
    out, seen = [], set()
    for t in terms:
        tl = t.strip().lower()
        if tl and tl not in seen:
            out.append(t)
            seen.add(tl)
    return out


CONFESSION_PATTERNS: List[re.Pattern] = [
    re.compile(r"\\b(je suis|c'?est|j'avoue|confesse)\\b.*\\b(coupable|meurtrier|meurtrière)\\b", re.IGNORECASE),
    re.compile(r"\\b([A-ZÉÈÀÂÎÔÛ][a-zéèàâêîôû\\-]+)\\b.*\\b(a tué|a assassiné|est le coupable)\\b", re.IGNORECASE),
]
