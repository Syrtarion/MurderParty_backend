"""
Session intro preparation.

Provides a helper to generate the narrative intro that kicks off the party.
The generated payload is cached in the session state so that UIs can display
it before the first round starts.
"""
from __future__ import annotations

import time
from typing import Any, Dict

from app.services.game_state import GameState
from app.services.llm_engine import LLMServiceError, run_llm
from app.services.story_seed import load_story_seed_dict, StorySeedError


def _build_intro_prompt(seed: Dict[str, Any]) -> str:
    setting = seed.get("setting", {})
    meta = seed.get("meta", {})
    tone = meta.get("llm_directives", {}).get("tone", "dramatique et immersif")
    location = setting.get("location", "un manoir isolé")
    time_hint = setting.get("time", "une nuit d'orage")
    return (
        "Tu es la voix d'un Maître du Jeu de murder party. "
        "Rédige une introduction immersive en français (3 à 4 phrases maximum), "
        "en installant le suspense sans révéler le coupable. "
        f"Le ton attendu: {tone}. "
        f"Cadre principal: {location} pendant {time_hint}. "
        "Conclue en invitant les joueurs à se préparer pour le premier mini-jeu."
    )


def _run_intro_llm(prompt: str, fallback: str) -> str:
    try:
        result = run_llm(prompt)
        text = (result.get("text") or "").strip()
        return text or fallback
    except LLMServiceError:
        return fallback


def prepare_session_intro(game_state: GameState, *, use_llm: bool = True) -> Dict[str, Any]:
    """
    Generate (or reuse) the global introduction of the party and persists it in the
    session segment of the GameState.
    """
    try:
        seed = load_story_seed_dict()
    except StorySeedError:
        seed = {}

    intro_conf = seed.get("intro") or {}
    fallback_text = intro_conf.get("text") or (
        "Dans la lumière vacillante des chandelles, chaque regard trahit l'inquiétude. "
        "Ce soir, le manoir dévoilera ses secrets; que chacun prenne place."
    )
    title = intro_conf.get("title") or "Prologue"

    if use_llm:
        prompt = _build_intro_prompt(seed)
        intro_text = _run_intro_llm(prompt, fallback_text)
    else:
        intro_text = fallback_text

    session_state = game_state.state.setdefault("session", {})
    intro_payload = {
        "title": title,
        "text": intro_text,
        "prepared_at": time.time(),
        "status": "ready",
    }
    session_state["intro"] = intro_payload
    game_state.save()
    return intro_payload
