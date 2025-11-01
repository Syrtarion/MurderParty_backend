"""
Round preparation pipeline.
Generates narration, riddles and hint packs for a given round ahead of time.
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from app.services.game_state import GameState
from app.services.llm_engine import LLMServiceError, run_llm
from app.services.story_seed import StorySeedError, load_story_seed_for_state

ROUND_KIND_LLM_ENIGME = "llm_enigme"


def _llm_json(prompt: str, fallback: Dict[str, Any]) -> Dict[str, Any]:
    try:
        result = run_llm(prompt)
        text = (result.get("text") or "").strip()
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        return fallback
    except (LLMServiceError, json.JSONDecodeError, ValueError):
        return fallback


def _llm_text(prompt: str, fallback: str) -> str:
    try:
        result = run_llm(prompt)
        text = (result.get("text") or "").strip()
        return text or fallback
    except LLMServiceError:
        return fallback


def _build_intro_prompt(seed: dict, round_conf: dict, intro_seed: Optional[str]) -> str:
    base = seed.get("setting", {})
    meta = seed.get("meta", {})
    theme = round_conf.get("theme") or round_conf.get("code") or "round"
    return (
        "Tu es la voix d'un narrateur immersif pour une murder party. "
        "Parle en français, 2 à 3 phrases, sans spoiler le coupable ni le canon. "
        f"Thème du round: {theme}. "
        f"Ambiance souhaitée: {intro_seed or 'Installe un suspense feutré.'} "
        f"Cadre: {base.get('location', '')}. "
        f"Ton général attendu: {meta.get('llm_directives', {}).get('tone', 'mystérieux et dramatique')}."
    )


def _build_outro_prompt(seed: dict, round_conf: dict, outro_seed: Optional[str]) -> str:
    base = seed.get("setting", {})
    return (
        "Tu es la voix d'un narrateur immersif clôturant un mini-jeu de murder party. "
        "Ecris 2 phrases en français qui concluent la manche sans révéler le coupable. "
        f"Mini-jeu: {round_conf.get('theme') or round_conf.get('code') or 'round'}. "
        f"Ambiance attendue: {outro_seed or 'Tension qui retombe mais laisse un doute persistant.'} "
        f"Cadre: {base.get('location', '')}."
    )


def _build_riddle_prompt(seed: dict, round_conf: dict) -> str:
    meta = seed.get("meta", {})
    llm_conf = round_conf.get("llm", {})
    difficulty = llm_conf.get("difficulty", "medium")
    return (
        "Tu es un maître du jeu qui prépare une énigme pour un mini-jeu de murder party. "
        f"Le round se déroule sur le thème '{round_conf.get('theme', 'mystère')}'. "
        f"Le ton de la murder party: {meta.get('llm_directives', {}).get('tone', 'dramatique et immersif')}. "
        f"Difficulté souhaitée: {difficulty}. L'énigme doit avoir une réponse unique et solvable. "
        "Format JSON strict:\n"
        "{\n"
        '  "title": "<titre court>",\n'
        '  "question": "<énoncé en 2 phrases max>",\n'
        '  "answer": "<réponse attendue>",\n'
        '  "solution_hint": "<indice optionnel discret>"\n'
        "}\n"
    )


def _build_hints_prompt(seed: dict, round_conf: dict, tiers: List[str]) -> str:
    meta = seed.get("meta", {})
    tiers_fmt = ", ".join(tiers)
    return (
        "Tu génères un pack d'indices cohérents pour un mini-jeu de murder party. "
        f"Thème: {round_conf.get('theme', 'mystère')}. "
        f"Ton global: {meta.get('llm_directives', {}).get('tone', 'dramatique et immersif')}. "
        f"Tiers d'indices à produire: {tiers_fmt}. "
        "Chaque indice doit tenir en 1 à 2 phrases, en français, sans nommer explicitement le coupable. "
        "Format JSON strict: {\"hints\": {\"tier\": \"texte\", ...}}."
    )


def _prepare_llm_assets(seed: dict, round_conf: dict, use_llm: bool) -> Dict[str, Any]:
    llm_conf = round_conf.get("llm") or {}
    tiers = llm_conf.get("hint_policy", {}).get("tiers") or ["major", "minor", "vague", "misleading"]
    assets: Dict[str, Any] = {}

    if round_conf.get("kind") == ROUND_KIND_LLM_ENIGME:
        if use_llm:
            riddle = _llm_json(
                _build_riddle_prompt(seed, round_conf),
                {
                    "title": "Énigme du manoir",
                    "question": "Quel objet oublié pourrait ouvrir le secret du bureau verrouillé ?",
                    "answer": "La cle retrouvée dans la bibliothèque",
                    "solution_hint": "La poussière sur le tapis dissimule le passage.",
                },
            )
        else:
            riddle = {
                "title": "Énigme du manoir",
                "question": "Quel objet oublié pourrait ouvrir le secret du bureau verrouillé ?",
                "answer": "La cle retrouvée dans la bibliothèque",
                "solution_hint": "La poussière sur le tapis dissimule le passage.",
            }
        assets["riddle"] = riddle

        if use_llm:
            hints = _llm_json(
                _build_hints_prompt(seed, round_conf, tiers),
                {
                    "hints": {tier: f"Indice {tier}: a toi d'observer les détails du manoir." for tier in tiers},
                },
            )
        else:
            hints = {"hints": {tier: f"Indice {tier}: Observe attentivement la salle principale." for tier in tiers}}
        assets["hints"] = hints

    return assets


def prepare_round_assets(game_state: GameState, round_index: int, *, use_llm: bool = True) -> Dict[str, Any]:
    """
    Generate narration, riddles and hints for the given round index (1-based).
    Returns the prepared payload that can be stored in the session state.
    """
    if round_index < 1:
        raise ValueError("round_index must be >= 1")

    try:
        seed = load_story_seed_for_state(game_state)
    except StorySeedError as exc:
        raise RuntimeError(str(exc)) from exc

    rounds = seed.get("rounds") or []
    if round_index > len(rounds):
        raise ValueError(f"Round index {round_index} is out of range (total rounds={len(rounds)}).")

    round_conf = rounds[round_index - 1]
    narration_conf = round_conf.get("narration") or {}
    intro_seed = narration_conf.get("intro_seed")
    outro_seed = narration_conf.get("outro_seed")

    if use_llm:
        intro_text = _llm_text(_build_intro_prompt(seed, round_conf, intro_seed), intro_seed or "La tension monte dans le manoir.")
        outro_text = _llm_text(_build_outro_prompt(seed, round_conf, outro_seed), outro_seed or "Les regards s'échangent en quête de vérité.")
    else:
        intro_text = intro_seed or "La tension monte dans le manoir."
        outro_text = outro_seed or "Les regards s'échangent en quête de vérité."

    assets = {
        "round_index": round_index,
        "round_id": round_conf.get("id"),
        "code": round_conf.get("code"),
        "kind": round_conf.get("kind"),
        "mode": round_conf.get("mode"),
        "theme": round_conf.get("theme"),
        "prepared_at": time.time(),
        "narration": {
            "intro_seed": intro_seed,
            "intro_text": intro_text,
            "outro_seed": outro_seed,
            "outro_text": outro_text,
        },
        "llm_assets": _prepare_llm_assets(seed, round_conf, use_llm),
    }

    # Persist in memory immediately to keep state consistent
    sess = game_state.state.setdefault("session", {})
    prepared_map = sess.setdefault("prepared_rounds", {})
    prepared_map[str(round_index)] = assets
    game_state.save()
    return assets
