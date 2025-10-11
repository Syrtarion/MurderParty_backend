from __future__ import annotations
import json
import random
import time
import asyncio
from typing import Dict, List, Literal, Optional

from app.services.llm_engine import run_llm
from app.services.narrative_core import NARRATIVE
from app.services.game_state import GAME_STATE, register_event
from app.services.ws_manager import WS

Scope = Literal["private", "public", "broadcast", "admin"]

def _now() -> float: return time.time()

def _canon() -> Dict:
    NARRATIVE.canon.setdefault("timeline", [])
    return NARRATIVE.canon

def _fire_and_forget(coro):
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(coro)
    except RuntimeError:
        asyncio.run(coro)

def _append_timeline(event: str, text: str, scope: Scope = "public", extra: Optional[Dict] = None):
    entry = {"ts": _now(), "event": event, "text": text.strip(), "scope": scope, "extra": (extra or {})}
    _canon()["timeline"].append(entry)
    NARRATIVE.save()
    payload = {"type": "narration", "scope": scope, "payload": {"event": event, "text": text, "extra": extra or {}}}
    if scope in ("public", "broadcast"):
        _fire_and_forget(WS.broadcast(payload))
    elif scope == "private" and extra and extra.get("to"):
        _fire_and_forget(WS.send_to_player(extra["to"], payload))

def _safe_json_extract(text: str) -> Optional[Dict]:
    if not text: return None
    try: return json.loads(text)
    except json.JSONDecodeError:
        s, e = text.find("{"), text.rfind("}")
        if s >= 0 and e > s:
            try: return json.loads(text[s:e+1])
            except Exception: return None
    return None

def _default_clue(kind: str, source: str) -> Dict:
    base = {"text": "Un détail attire votre attention, mais son sens reste flou.", "type": "ambiguous", "source": source, "correlation_key": None}
    if kind == "crucial":
        base["text"] = "Un élément concret semble relier plusieurs pistes, sans certitude absolue."
        base["type"] = "crucial"
    elif kind == "fake":
        base["text"] = "Un objet trompeur semble détourner votre attention."
        base["type"] = "fake"
    return base

def _player_ids() -> List[str]: return list(GAME_STATE.players.keys())

def add_clue_to_player(player_id: str, clue: Dict, notify_ws: bool = True):
    player = GAME_STATE.players.get(player_id)
    if not player: return
    player.setdefault("found_clues", [])
    clue_id = f"clue_{int(_now()*1000)}_{random.randint(100,999)}"
    record = {"id": clue_id, "text": clue.get("text",""), "type": clue.get("type","ambiguous"), "source": clue.get("source","unknown"), "correlation_key": clue.get("correlation_key"), "ts": _now()}
    player["found_clues"].append(record)
    GAME_STATE.save()
    if notify_ws:
        _fire_and_forget(WS.send_to_player(player_id, {"type":"clue","scope":"private","payload":record}))
    _check_player_correlations(player_id)

def _check_player_correlations(player_id: str):
    player = GAME_STATE.players.get(player_id)
    if not player: return
    clues = player.get("found_clues", [])
    counter = {}
    for c in clues:
        key = c.get("correlation_key")
        if key: counter[key] = counter.get(key, 0) + 1
    unlocked = set(player.get("unlocked_correlations", []))
    for key, count in counter.items():
        if count >= 2 and key not in unlocked:
            unlocked.add(key)
            player.setdefault("unlocked_correlations", []).append(key)
            GAME_STATE.save()
            _fire_and_forget(WS.send_to_player(player_id, {
                "type":"narration","scope":"private",
                "payload":{"event":"correlation_unlocked","text":f"Tu recoupes plusieurs indices : « {key.replace('_',' ')} » devient plus clair.","key":key}
            }))
            register_event("correlation_unlocked", {"player_id": player_id, "key": key})

def _prompt_mini_game_bundle(canon: Dict, mode: str) -> str:
    return f"""
Tu es le moteur narratif d'une murder party. Réponds UNIQUEMENT en JSON strict.
Canon actuel :
- Lieu : {canon.get('location')}
- Arme : {canon.get('weapon')}
- Mobile : {canon.get('motive')}
- Coupable : {canon.get('culprit')} (ne jamais le révéler)
Un mini-jeu vient de se terminer (mode: {mode}).
Tâches :
1) Narration (2 phrases, FR, sans spoiler).
2) Deux indices :
   - winner_clue : crucial
   - loser_clue : ambiguous
Format strict :
{{
  "narration": "…",
  "winner_clue": {{"text":"…","type":"crucial","correlation_key":"…"}},
  "loser_clue":  {{"text":"…","type":"ambiguous","correlation_key":"…"}}
}}
""".strip()

def _prompt_envelope_event(canon: Dict, envelope_id: str|int) -> str:
    return f"""
Tu es le narrateur d'une murder party. Réponds en JSON strict.
Une enveloppe (id {envelope_id}) vient d'être découverte. Indice diffusé à tous.
Canon :
- Lieu : {canon.get('location')}
- Arme : {canon.get('weapon')}
- Mobile : {canon.get('motive')}
- Coupable : {canon.get('culprit')} (ne pas révéler)
Format :
{{ "narration":"…", "public_clue": {{"text":"…","type":"crucial|ambiguous|fake","correlation_key":"…"}} }}
""".strip()

def _llm_json(prompt: str) -> Optional[Dict]:
    res = run_llm(prompt)
    return _safe_json_extract(res.get("text", ""))

def handle_mini_game_result(context: Dict):
    winners = context.get("winners", [])
    losers = context.get("losers", [])
    mode = context.get("mode", "solo")
    mini_game = context.get("mini_game", "unknown")
    canon = _canon()
    data = _llm_json(_prompt_mini_game_bundle(canon, mode)) or {}
    narration = data.get("narration", "Une tension sourde parcourt la pièce.")
    winner_clue = data.get("winner_clue", _default_clue("crucial", "mini_game"))
    loser_clue = data.get("loser_clue", _default_clue("ambiguous", "mini_game"))
    _append_timeline("mini_game_end", narration, scope="public", extra={"mini_game": mini_game, "mode": mode})
    register_event("mini_game_end", {"mini_game": mini_game, "mode": mode, "winners": winners, "losers": losers})
    for pid in winners: add_clue_to_player(pid, winner_clue)
    for pid in losers:  add_clue_to_player(pid, loser_clue)

def handle_envelope_scanned(context: Dict):
    envelope_id = context.get("envelope_id")
    player_id = context.get("player_id")
    canon = _canon()
    data = _llm_json(_prompt_envelope_event(canon, envelope_id)) or {}
    narration = data.get("narration", f"Une enveloppe n°{envelope_id} a été trouvée.")
    clue = data.get("public_clue", _default_clue("ambiguous", "envelope"))
    clue["source"] = "envelope"; clue["envelope_id"] = envelope_id
    _append_timeline("envelope_found", narration, scope="broadcast", extra={"envelope_id": envelope_id, "by": player_id})
    register_event("envelope_found", {"envelope_id": envelope_id, "by": player_id})
    for pid in _player_ids(): add_clue_to_player(pid, clue)

def handle_story_event(context: Dict):
    theme = context.get("theme", "transition")
    canon = _canon()
    prompt = f"""
Tu es un narrateur immersif pour une murder party.
Contexte : {canon.get('location')} / {canon.get('weapon')} / {canon.get('motive')}
Thème : {theme}
Écris 2 phrases max en français, atmosphériques, sans révéler le coupable.
""".strip()
    res = run_llm(prompt)
    text = (res.get("text") or "").strip() or "L’atmosphère devient plus lourde, emplie de tension silencieuse."
    _append_timeline("narration_auto", text, scope="broadcast", extra={"theme": theme})
    register_event("narration_auto", {"theme": theme})

def generate_dynamic_event(event_type: str, context: Dict):
    if event_type == "mini_game_end":
        handle_mini_game_result(context)
    elif event_type == "envelope_scanned":
        handle_envelope_scanned(context)
    elif event_type == "narration_trigger":
        handle_story_event(context)
    else:
        _append_timeline("unknown_event", f"Événement '{event_type}' inconnu.", scope="admin", extra=context)
        register_event("unknown_event", {"type": event_type, "context": context})
