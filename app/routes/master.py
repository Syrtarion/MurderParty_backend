"""
Master routes (MJ scope).
Provide narrative controls (canon, hints, envelopes, dynamic narration) with
multi-session support. Every endpoint accepts an optional `session_id` query
parameter; when omitted it falls back to the default session for backwards
compatibility.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Header, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.deps.auth import mj_required
from app.config.settings import settings
from app.services.session_store import DEFAULT_SESSION_ID, get_session_state
from app.services.narrative_core import NARRATIVE
from app.services.llm_engine import generate_indice
from app.services.ws_manager import ws_send_type_to_player_safe, ws_broadcast_type_safe
from app.services.narrative_dynamic import generate_dynamic_event
from app.services.envelopes import (
    distribute_envelopes_equitable,
    summary_for_mj,
    reset_envelope_assignments,
    player_envelopes,
    assign_envelope_to_player,
)


router = APIRouter(prefix="/master", tags=["master"], dependencies=[Depends(mj_required)])


def _normalize_session_id(session_id: Optional[str]) -> str:
    sid = (session_id or DEFAULT_SESSION_ID).strip()
    return sid or DEFAULT_SESSION_ID


def _require_bearer(auth: str | None):
    """Optional explicit Bearer token guard."""
    if not auth or not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    if auth.split(" ", 1)[1] != settings.MJ_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")


def _session_players(state) -> list[str]:
    return list(state.players.keys())


def _broadcast_session_event(state, event_type: str, payload: Dict[str, Any], session_id: str) -> None:
    """
    Send an event to every registered player of the session.
    Adds `session_id` to the payload for clients that rely on the global bus.
    """
    enriched = dict(payload)
    enriched.setdefault("session_id", session_id)
    for pid in _session_players(state):
        ws_send_type_to_player_safe(pid, event_type, enriched)
    ws_broadcast_type_safe(event_type, enriched)


# ---------------------------------------------------------------------------
# Canon manual override
# ---------------------------------------------------------------------------
class CulpritPayload(BaseModel):
    culprit: str
    weapon: str
    location: str
    motive: str


@router.post("/choose_culprit")
async def choose_culprit(
    payload: CulpritPayload,
    session_id: Optional[str] = Query(default=None, description="Identifiant de session MurderParty"),
):
    sid = _normalize_session_id(session_id)
    state = get_session_state(sid)

    canon = NARRATIVE.choose_culprit(payload.culprit, payload.weapon, payload.location, payload.motive)
    state.log_event(
        "canon_locked",
        {k: canon.get(k) for k in ("culprit", "weapon", "location", "motive")},
    )
    _broadcast_session_event(state, "canon_locked", {"canon": canon}, sid)
    return canon


# ---------------------------------------------------------------------------
# Hints generation
# ---------------------------------------------------------------------------
class IndicePayload(BaseModel):
    prompt: str = Field(..., description="Consigne spécifique pour l'indice")
    kind: str = Field("ambiguous", description="crucial | red_herrings | ambiguous | decor")


@router.post("/generate_indice")
async def generate_indice_route(
    payload: IndicePayload,
    session_id: Optional[str] = Query(default=None),
):
    sid = _normalize_session_id(session_id)
    state = get_session_state(sid)

    user_prompt = "Donne uniquement l'indice, sans préambule. Limite à 1-2 phrases. " + payload.prompt
    result = generate_indice(user_prompt, payload.kind)
    NARRATIVE.append_clue(payload.kind, {"text": result.get("text", ""), "kind": payload.kind})
    state.log_event("clue_generated", {"kind": payload.kind, "text": result.get("text", "")})
    _broadcast_session_event(state, "clue_generated", {"payload": result}, sid)
    return result


# ---------------------------------------------------------------------------
# Dynamic narration helpers
# ---------------------------------------------------------------------------
class MiniGameResultPayload(BaseModel):
    mode: str = "solo"
    winners: list[str]
    losers: list[str]
    mini_game: Optional[str] = None


class EnvelopeScanPayload(BaseModel):
    player_id: str
    envelope_id: str | int


class StoryEventPayload(BaseModel):
    theme: str
    context: Optional[dict] = None


@router.post("/narrate_mg_end")
async def narrate_after_minigame(
    payload: MiniGameResultPayload,
    session_id: Optional[str] = Query(default=None),
):
    sid = _normalize_session_id(session_id)
    state = get_session_state(sid)

    narrative = generate_dynamic_event(
        theme="mini_game_end",
        context={
            "mode": payload.mode,
            "winners": payload.winners,
            "losers": payload.losers,
            "mini_game": payload.mini_game,
        },
    )
    state.log_event("mini_game_end", {"winners": payload.winners, "losers": payload.losers, "mini_game": payload.mini_game})
    _broadcast_session_event(state, "narration", {"event": "mini_game_end", "text": narrative}, sid)
    return {"ok": True, "narration": narrative}


@router.post("/envelope_scan")
async def envelope_scan(
    payload: EnvelopeScanPayload,
    session_id: Optional[str] = Query(default=None),
):
    sid = _normalize_session_id(session_id)
    state = get_session_state(sid)

    event = generate_dynamic_event("envelope_scan", {"player_id": payload.player_id, "envelope_id": payload.envelope_id})
    state.log_event("envelope_scan", {"player_id": payload.player_id, "envelope_id": payload.envelope_id})
    _broadcast_session_event(state, "narration", {"event": "envelope_scan", "text": event}, sid)
    return {"ok": True, "narration": event}


@router.post("/story_event")
async def story_event(
    payload: StoryEventPayload,
    session_id: Optional[str] = Query(default=None),
):
    sid = _normalize_session_id(session_id)
    state = get_session_state(sid)

    event = generate_dynamic_event(payload.theme, payload.context or {})
    state.log_event("story_event", {"theme": payload.theme, "context": payload.context or {}})
    _broadcast_session_event(state, "narration", {"event": payload.theme, "text": event}, sid)
    return {"ok": True, "narration": event}


# ---------------------------------------------------------------------------
# Envelopes management
# ---------------------------------------------------------------------------
@router.post("/lock_join")
async def lock_join(session_id: Optional[str] = Query(default=None)):
    sid = _normalize_session_id(session_id)
    state = get_session_state(sid)

    try:
        state.state["join_locked"] = True
        state.state["phase_label"] = "ENVELOPES_DISTRIBUTION"
        state.log_event("join_locked", {})
        state.log_event("phase_change", {"phase": "ENVELOPES_DISTRIBUTION"})
        distribution = distribute_envelopes_equitable(game_state=state)
        state.log_event("envelopes_distributed", distribution)
        state.save()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Cannot lock join: {exc}") from exc

    _broadcast_session_event(state, "event", {"kind": "join_locked"}, sid)
    for pid in _session_players(state):
        ws_send_type_to_player_safe(
            pid,
            "event",
            {
                "kind": "envelopes_update",
                "player_id": pid,
                "envelopes": player_envelopes(pid, game_state=state),
                "session_id": sid,
            },
        )

    return {
        "ok": True,
        "join_locked": True,
        "phase": "ENVELOPES_DISTRIBUTION",
        "distribution": distribution,
    }


@router.post("/unlock_join")
async def unlock_join(session_id: Optional[str] = Query(default=None)):
    sid = _normalize_session_id(session_id)
    state = get_session_state(sid)

    try:
        state.state["join_locked"] = False
        state.log_event("join_unlocked", {})
        state.save()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Cannot unlock join: {exc}") from exc

    _broadcast_session_event(state, "event", {"kind": "join_unlocked"}, sid)
    return {"ok": True, "join_locked": False}


@router.get("/envelopes/summary")
async def envelopes_summary(
    include_hints: bool = False,
    session_id: Optional[str] = Query(default=None),
):
    sid = _normalize_session_id(session_id)
    state = get_session_state(sid)
    return summary_for_mj(include_hints=include_hints, game_state=state)


@router.post("/envelopes/reset")
async def envelopes_reset(session_id: Optional[str] = Query(default=None)):
    sid = _normalize_session_id(session_id)
    state = get_session_state(sid)

    res = reset_envelope_assignments(game_state=state)
    _broadcast_session_event(state, "event", {"kind": "envelopes_update"}, sid)
    return res


def _seed_default_path() -> str:
    try:
        if getattr(settings, "STORY_SEED_PATH", None):
            return str(settings.STORY_SEED_PATH)
    except Exception:
        pass
    from pathlib import Path

    return str((Path(__file__).resolve().parents[1] / "data" / "story_seed.json").resolve())


@router.post("/seed/reload")
async def seed_reload(
    path: Optional[str] = None,
    session_id: Optional[str] = Query(default=None),
):
    sid = _normalize_session_id(session_id)
    state = get_session_state(sid)

    seed_path = path or _seed_default_path()
    if not os.path.exists(seed_path):
        raise HTTPException(404, f"Seed file not found: {seed_path}")

    try:
        with open(seed_path, "r", encoding="utf-8") as handle:
            seed = json.load(handle)
        state.state["story_seed"] = seed
        state.log_event(
            "seed_reloaded",
            {"path": seed_path, "envelopes_count": len(seed.get("envelopes", []))},
        )
        state.save()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Seed reload failed: {exc}") from exc

    _broadcast_session_event(state, "event", {"kind": "seed_reloaded"}, sid)
    return {"ok": True, "path": seed_path, "envelopes_count": len(seed.get("envelopes", []))}


class AssignEnvelopePayload(BaseModel):
    envelope_id: str | int
    player_id: str


@router.post("/envelopes/assign")
async def envelopes_assign(
    payload: AssignEnvelopePayload,
    session_id: Optional[str] = Query(default=None),
):
    sid = _normalize_session_id(session_id)
    state = get_session_state(sid)

    res = assign_envelope_to_player(payload.envelope_id, payload.player_id, game_state=state)
    if not res.get("ok"):
        raise HTTPException(404, detail="envelope_not_found")

    try:
        new_envs = player_envelopes(payload.player_id, game_state=state)
        ws_send_type_to_player_safe(
            payload.player_id,
            "event",
            {
                "kind": "envelopes_update",
                "player_id": payload.player_id,
                "envelopes": new_envs,
                "session_id": sid,
            },
        )

        prev_owner = res.get("previous_owner")
        if prev_owner and prev_owner != payload.player_id:
            prev_envs = player_envelopes(prev_owner, game_state=state)
            ws_send_type_to_player_safe(
                prev_owner,
                "event",
                {
                    "kind": "envelopes_update",
                    "player_id": prev_owner,
                    "envelopes": prev_envs,
                    "session_id": sid,
                },
            )
    except Exception as err:
        print(f"[WS] envelopes_assign notify error: {err}")

    return res
