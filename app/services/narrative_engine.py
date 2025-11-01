from __future__ import annotations

"""
Service: narrative_engine.py

Role:
- Generate a minimal canon (culprit, weapon, location, motive) from the active story seed.
- Produce an introduction narrative (LLM or offline fallback).
- Persist the result into app/data/canon_narratif.json.

Integrations:
- run_llm(): Ollama (or configured LLM) for the intro narrative.
- save_json(): shared helper to write JSON payloads on disk.
"""

import json
import random
from pathlib import Path
from typing import Dict

from app.services.llm_engine import run_llm
from app.services.game_state import save_json
from app.services.story_seed import StorySeedError, load_story_seed_dict

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
CANON_PATH = DATA_DIR / "canon_narratif.json"


def _load_seed() -> Dict[str, object]:
    """Load the active story seed (default campaign)."""
    try:
        return load_story_seed_dict()
    except StorySeedError as exc:
        raise RuntimeError(f"Unable to load story_seed.json: {exc}") from exc


def generate_random_canon(seed_data: Dict[str, object]) -> Dict[str, object]:
    """
    Select a culprit, weapon, location and motive while respecting the seed constraints.
    """
    characters = seed_data.get("characters") or []
    constraints = seed_data.get("canon_constraints") or {}

    if not characters:
        raise ValueError("story_seed does not define any characters.")

    culprit = random.choice(characters)

    possible_weapons = constraints.get("possible_weapons") or ["Un chandelier"]
    possible_locations = constraints.get("possible_locations") or ["le salon"]
    possible_motives = constraints.get("possible_motives") or ["jalousie"]

    weapon = random.choice(possible_weapons)
    location = random.choice(possible_locations)
    motive = random.choice(possible_motives)

    canon = {
        "culprit": culprit.get("name") or culprit.get("id"),
        "weapon": weapon,
        "location": location,
        "motive": motive,
        "timestamp": None,
    }
    return canon


def generate_intro_narrative(canon: Dict[str, object], seed_data: Dict[str, object], use_llm: bool = True) -> str:
    """
    Produce an intro narrative based on the generated canon.
    """
    setting = seed_data.get("setting") or {}
    meta = seed_data.get("meta") or {}

    context = (
        f"L'histoire se deroule dans {setting.get('location', 'un lieu inconnu')} "
        f"pendant {setting.get('epoch', 'une epoque indefinie')}. "
        f"Le ton doit etre {meta.get('llm_directives', {}).get('tone', 'mysterieux et dramatique')}."
    )

    prompt = (
        f"{context}\n\n"
        f"Un crime vient d'etre commis au {canon['location']}. "
        f"La victime est retrouvée morte, probablement tuee par {canon['weapon']}. "
        f"Le mobile suppose est : {canon['motive']}. "
        f"Le principal suspect pour l'instant est {canon['culprit']}.\n\n"
        "Ecris une introduction narrative en francais, immersive, courte (5 phrases max), "
        "qui pose l'ambiance sans reveler trop d'elements du mystere."
    )

    if use_llm:
        result = run_llm(prompt)
        text = (result.get("text") or "").strip()
        if text:
            return text
        return "[Erreur LLM] Aucune reponse recue."

    return (
        "Un orage gronde au-dessus du manoir. "
        f"Au matin, le corps d'Henri Delmare est retrouve dans la {canon['location'].lower()}. "
        f"Une trace de {canon['weapon'].lower()} laisse presager un drame. "
        f"Les invites, deconcertes, cherchent a comprendre le mobile de cette affaire : "
        f"{canon['motive'].lower()}. "
        f"Les soupcons commencent a se porter sur {canon['culprit']}."
    )


def generate_canon_and_intro(use_llm: bool = True) -> Dict[str, object]:
    """
    Generate the canon and accompanying intro narrative, then persist the payload.
    """
    seed = _load_seed()
    canon = generate_random_canon(seed)
    intro_text = generate_intro_narrative(canon, seed, use_llm=use_llm)

    canon["intro_narrative"] = intro_text
    save_json(CANON_PATH, canon)
    return canon


if __name__ == "__main__":
    print(">> Generation du canon narratif...")
    data = generate_canon_and_intro(use_llm=False)
    print(json.dumps(data, indent=2, ensure_ascii=False))
