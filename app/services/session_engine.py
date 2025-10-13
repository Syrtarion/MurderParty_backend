"""
Service: session_engine.py
Rôle:
- Orchestration "micro" des rounds (intro → active → cooldown) et annonces WS.
- Timer souple intégré (mi-temps + fin) sans forcer la clôture.

I/O:
- session_plan.json (liste ordonnée des rounds)
- GAME_STATE.state["session"] (snapshot moteur de round)

WS:
- Diffuse des "narration" et des "prompt" pour piloter le front MJ/joueurs.

API interne exposée aux routes:
- SESSION.status()
- SESSION.start_next_round()
- SESSION.confirm_start()
- SESSION.finish_current_round(winners, meta)
- SESSION.start_timer(seconds), SESSION.abort_timer()
"""
from __future__ import annotations
import asyncio
import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from app.config.settings import settings
from app.services.game_state import GAME_STATE
from app.services.ws_manager import WS
from app.services.llm_engine import run_llm  # utilise ton LLM (Ollama)

DATA_DIR = Path(settings.DATA_DIR)
SESSION_PLAN_PATH = DATA_DIR / "session_plan.json"

# Phases internes d'un round
ROUND_IDLE = "IDLE"               # aucun round actif
ROUND_INTRO = "INTRO"             # annonce de round (avant lancement physique)
ROUND_ACTIVE = "ACTIVE"           # mini-jeu en cours
ROUND_COOLDOWN = "COOLDOWN"       # fin du mini-jeu, outro, distribution indices


# -------------------- utilitaires --------------------

def _load_plan() -> Dict[str, Any]:
    """Lecture tolérante du plan depuis session_plan.json (retourne structure vide sinon)."""
    try:
        if SESSION_PLAN_PATH.exists():
            return json.loads(SESSION_PLAN_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"rounds": []}


async def _narrate(event: str, text_hint: Optional[str] = None, extra: Optional[Dict[str, Any]] = None) -> str:
    """Génère un court texte narratif FR via le LLM et le diffuse en WS (broadcast)."""
    prompt = (
        "Tu es la voix d'un narrateur immersif pour une murder party. "
        "Parle TOUJOURS en français, en 1 à 3 phrases courtes, sans spoiler ni révéler le coupable. "
        f"Événement: {event}. "
    )
    if text_hint:
        prompt += f"Intention / ambiance à respecter: {text_hint}. "
    if extra:
        prompt += f"Contexte: {json.dumps(extra, ensure_ascii=False)}"

    text = ""
    try:
        r = run_llm(prompt)
        text = (r.get("text") or "").strip()
    except Exception:
        text = "Un silence tendu s'installe."

    if not text:
        text = "Un silence tendu s'installe."

    await WS.broadcast({
        "type": "narration",
        "event": event,
        "text": text
    })
    return text


# -------------------- moteur de session --------------------

@dataclass
class SessionEngine:
    _timer_task: Optional[asyncio.Task] = field(default=None, init=False, repr=False)

    # === état courant ===
    def _state(self) -> Dict[str, Any]:
        """Retourne (et initialise si besoin) le sous-état 'session' dans GAME_STATE.state."""
        sess = GAME_STATE.state.setdefault("session", {})
        sess.setdefault("round_index", 0)  # 0 = pas encore commencé
        sess.setdefault("round_phase", ROUND_IDLE)
        sess.setdefault("round_results", {})  # { round_id: { winners: [...], meta: {...} } }
        sess.setdefault("plan_hash", None)
        return sess

    def status(self) -> Dict[str, Any]:
        """Snapshot synthétique pour UI MJ: phase, manche courante/suivante, timer actif."""
        sess = self._state()
        plan = _load_plan()
        rounds = plan.get("rounds", [])
        idx = sess.get("round_index", 0)
        current = rounds[idx-1] if 1 <= idx <= len(rounds) else None
        next_r = rounds[idx] if idx < len(rounds) else None
        return {
            "phase": sess["round_phase"],
            "round_index": idx,
            "current_round": current,
            "next_round": next_r,
            "total_rounds": len(rounds),
            "has_timer": bool(self._timer_task and not self._timer_task.done())
        }

    # === cycle ===
    async def start_next_round(self) -> Dict[str, Any]:
        """Passe au round suivant, annonce l'intro et met en phase INTRO. Ne démarre PAS le jeu physique."""
        plan = _load_plan()
        rounds = plan.get("rounds", [])
        if not rounds:
            return {"ok": False, "error": "session_plan.json sans rounds"}

        sess = self._state()
        # Empêche d'avancer si une manche est déjà en cours de lancement/jeu
        if sess["round_phase"] in (ROUND_INTRO, ROUND_ACTIVE):
            return {"ok": False, "error": f"Round en cours (phase={sess['round_phase']})."}

        # stop timer précédent si encore actif (sécurité)
        await self.abort_timer()

        # incrémente l'index de manche
        sess["round_index"] += 1
        idx = sess["round_index"]
        if idx > len(rounds):
            # plus de rounds → annonce de fin de session
            await _narrate("session_end", "La suite s'éclaircit : l'heure des accusations approche.")
            return {"ok": True, "done": True, "message": "Plus de rounds dans le plan."}

        # phase INTRO + narration d'ouverture
        r = rounds[idx-1]
        sess["round_phase"] = ROUND_INTRO
        GAME_STATE.save()

        hint = None
        nar = r.get("narration") or {}
        hint = nar.get("intro") or f"Préparez-vous pour le mini-jeu '{r.get('mini_game','?')}'."
        await _narrate("round_intro", hint, {"round_index": idx, "mini_game": r.get("mini_game")})

        # Prompt UI MJ pour démarrer la manche côté "physique"
        await WS.broadcast({
            "type": "prompt",
            "kind": "start_minigame",
            "round_index": idx,
            "mini_game": r.get("mini_game"),
            "theme": r.get("theme")
        })
        return {"ok": True, "round_index": idx, "phase": ROUND_INTRO, "round": r}

    async def confirm_start(self) -> Dict[str, Any]:
        """Marque la manche comme DÉMARRÉE (le MJ humain a lancé le mini-jeu réel)."""
        sess = self._state()
        if sess["round_phase"] != ROUND_INTRO:
            return {"ok": False, "error": "Aucun round en phase INTRO."}
        sess["round_phase"] = ROUND_ACTIVE
        GAME_STATE.save()

        idx = sess["round_index"]
        plan = _load_plan()
        r = plan.get("rounds", [])[idx-1]

        await _narrate("round_start", f"Le mini-jeu '{r.get('mini_game','?')}' commence.")

        # Timer souple si présent dans le plan
        max_sec = (r.get("max_seconds") or r.get("duration_seconds") or None)
        if max_sec:
            await self.start_timer(max_sec, {
                "round_index": idx,
                "mini_game": r.get("mini_game")
            })
        return {"ok": True, "phase": ROUND_ACTIVE}

    async def finish_current_round(self, winners: Optional[list] = None, meta: Optional[dict] = None) -> Dict[str, Any]:
        """Clôture la manche en cours (scores déjà calculés ailleurs)."""
        sess = self._state()
        if sess["round_phase"] != ROUND_ACTIVE:
            return {"ok": False, "error": "Aucun round actif à clôturer."}

        # Arrête un timer éventuellement en cours
        await self.abort_timer()

        # Enregistre les résultats et passe en COOLDOWN
        idx = sess["round_index"]
        rr = sess["round_results"]
        rr[str(idx)] = {"winners": winners or [], "meta": meta or {}}
        sess["round_phase"] = ROUND_COOLDOWN
        GAME_STATE.save()

        plan = _load_plan()
        r = plan.get("rounds", [])[idx-1]

        # Outro + prompt pour préparer la suite
        nar = r.get("narration") or {}
        hint = nar.get("outro") or "Le silence retombe. Les regards s'échangent."
        await _narrate("round_end", hint, {"round_index": idx})
        await WS.broadcast({"type": "prompt", "kind": "next_round_ready", "round_index": idx})
        return {"ok": True, "phase": ROUND_COOLDOWN}

    # ---------------- timers souples ----------------
    async def start_timer(self, seconds: int, context: Optional[Dict[str, Any]] = None) -> None:
        """Démarre un timer non bloquant avec alerte mi-temps et fin (broadcast)."""
        await self.abort_timer()

        async def _runner():
            # Mi-temps si durée suffisante
            try:
                if seconds >= 60:
                    await asyncio.sleep(max(1, seconds // 2))
                    await WS.broadcast({
                        "type": "narration",
                        "event": "half_time",
                        "text": "La moitié du temps s'est écoulée.",
                        "context": context or {}
                    })
                    remain = seconds - (seconds // 2)
                    await asyncio.sleep(remain)
                else:
                    await asyncio.sleep(seconds)
                # Fin timer → notification non bloquante
                await WS.broadcast({
                    "type": "narration",
                    "event": "timer_end",
                    "text": "Le temps imparti est écoulé.",
                    "context": context or {}
                })
            except asyncio.CancelledError:
                return

        self._timer_task = asyncio.create_task(_runner())

    async def abort_timer(self) -> None:
        """Annule un timer en cours si nécessaire."""
        if self._timer_task and not self._timer_task.done():
            self._timer_task.cancel()
            try:
                await self._timer_task
            except asyncio.CancelledError:
                pass
        self._timer_task = None


SESSION = SessionEngine()
