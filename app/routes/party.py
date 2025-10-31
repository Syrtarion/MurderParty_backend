"""
Party routes (MJ scope).
Handle macro phases (start, envelopes, roles) and the legacy mini-game plan loader.
Every endpoint now accepts a session identifier so multiple parties can run
concurrently on the same backend.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import uuid4
import random

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.deps.auth import mj_required
from app.services.session_store import DEFAULT_SESSION_ID, get_session_state, get_session_engine
from app.services.session_plan import SESSION_PLAN
from app.services.minigame_catalog import CATALOG
from app.services.minigame_runtime import RUNTIME
from app.utils.team_utils import random_teams
from app.services.envelopes import summary_for_mj
from app.services.character_service import CHARACTERS
from app.services.narrative_core import NARRATIVE
from app.services.ws_manager import WS, ws_send_type_to_player_safe, ws_broadcast_type_safe
from app.services.narrative_engine import generate_canon_and_intro  # fallback offline


router = APIRouter(prefix="/party", tags=["party"], dependencies=[Depends(mj_required)])


def _normalize_session_id(session_id: Optional[str]) -> str:
    sid = (session_id or DEFAULT_SESSION_ID).strip()
    return sid or DEFAULT_SESSION_ID


class PlanPayload(BaseModel):
    session_id: str
    games_sequence: List[dict] = Field(default_factory=list, description="Liste d'objets {id, round?}")


@router.post("/load_plan")
async def load_plan(payload: PlanPayload):
    """Store a mini-game plan for the provided session."""
    ids = [item.get("id") for item in payload.games_sequence]
    missing = [game_id for game_id in ids if not CATALOG.get(game_id)]
    if missing:
        raise HTTPException(400, f"Unknown minigame ids: {missing}")
    SESSION_PLAN.set_plan(payload.session_id, payload.model_dump())
    return {"ok": True, "loaded": len(payload.games_sequence)}


class NextRoundPayload(BaseModel):
    participants: Optional[List[str]] = None
    auto_team_count: Optional[int] = None
    auto_team_size: Optional[int] = None
    seed: Optional[int] = None


@router.post("/next_round")
async def next_round(
    body: NextRoundPayload,
    session_id: Optional[str] = Query(default=None, description="Identifiant de session MurderParty"),
):
    """
    Start the next mini-game session according to the stored plan.
    Creates a runtime entry in `minigame_runtime`.
    """
    sid = _normalize_session_id(session_id)
    current = SESSION_PLAN.current(sid)
    if not current:
        raise HTTPException(404, "No current round in plan. Did you load a plan?")

    game_id = current.get("id")
    game = CATALOG.get(game_id)
    if not game:
        raise HTTPException(404, "Unknown game in catalog")

    session = {
        "session_id": f"MG-{uuid4().hex[:8]}",
        "game_id": game_id,
        "mode": game["mode"],
        "status": "running",
        "scores": {},
        "murder_session_id": sid,
    }

    if game["mode"] == "solo":
        if not body.participants:
            raise HTTPException(400, "participants (player_ids) required for solo mode")
        session["participants"] = body.participants
        session["teams"] = None
    else:
        if not body.participants:
            raise HTTPException(400, "participants (player_ids) required to draw teams")
        teams_payload = random_teams(
            players=body.participants,
            team_count=body.auto_team_count,
            team_size=body.auto_team_size,
            seed=body.seed,
        )
        session["participants"] = list(teams_payload.keys())
        session["teams"] = teams_payload

    RUNTIME.create(session)
    SESSION_PLAN.next(sid)
    return {"ok": True, "session": session}


@router.post("/start")
async def party_start(
    session_id: Optional[str] = Query(default=None),
):
    """Initialise the party state (phase JOIN)."""
    sid = _normalize_session_id(session_id)
    state = get_session_state(sid)
    try:
        state.state["phase_label"] = "JOIN"
        state.state["join_locked"] = False
        if not state.state.get("join_code"):
            state.state["join_code"] = sid[:6].upper()
        state.state.pop("session", None)
        state.log_event("party_started", {"phase": "JOIN", "join_locked": False})
        state.save()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Cannot start party: {exc}") from exc

    await WS.broadcast_type("event", {"kind": "phase_change", "phase": "JOIN"})
    return {"ok": True, "phase": "JOIN", "join_locked": False}


@router.post("/launch")
async def party_launch(
    session_id: Optional[str] = Query(default=None),
    use_llm_intro: bool = Query(default=True, description="Utiliser le LLM pour générer l'introduction"),
):
    """Prépare l'introduction LLM après attribution des rôles et diffuse l'événement WS associé."""
    sid = _normalize_session_id(session_id)
    state = get_session_state(sid)
    phase = state.state.get("phase_label")
    if phase != "ROLES_ASSIGNED":
        raise HTTPException(status_code=409, detail="Les rôles ne sont pas encore assignés.")

    missing_roles = [pid for pid, pdata in state.players.items() if not pdata.get("role")]
    if missing_roles:
        raise HTTPException(status_code=409, detail=f"Rôles manquants pour: {', '.join(missing_roles)}")

    engine = get_session_engine(sid)
    try:
        intro_payload = engine.prepare_intro(use_llm=use_llm_intro)
        confirm_result = await engine.confirm_intro(use_llm_rounds=True)
    except Exception as exc:
        failure_payload = {
            "title": "Prologue",
            "text": "La soirée peut commencer, prenez place autour de la table.",
            "prepared_at": None,
            "status": "error",
            "error": str(exc),
        }
        session_snapshot = state.state.setdefault("session", {})
        session_snapshot["intro"] = failure_payload
        state.save()
        state.log_event("session_intro_failed", {"error": str(exc)})
        ws_broadcast_type_safe(
            "event",
            {
                "kind": "session_intro_failed",
                "session_id": sid,
                "error": str(exc),
            },
        )
        raise HTTPException(status_code=500, detail="Echec génération intro") from exc

    intro_confirmed = confirm_result.get("intro") or intro_payload
    response = {
        "ok": confirm_result.get("ok", True),
        "intro": intro_confirmed,
        "prepared_round": confirm_result.get("prepared_round"),
    }
    if confirm_result.get("already_confirmed"):
        response["already_confirmed"] = True
    return response


@router.get("/status")
def party_status(session_id: Optional[str] = Query(default=None)):
    """Return a condensed view of the party status for the MJ dashboard."""
    sid = _normalize_session_id(session_id)
    state = get_session_state(sid)

    phase = state.state.get("phase_label", "JOIN")
    join_locked = bool(state.state.get("join_locked", False))
    players_count = len(state.players)

    env_summary = summary_for_mj(include_hints=False, game_state=state)
    env_total = env_summary.get("total", 0)
    env_assigned = env_summary.get("assigned", 0)
    env_left = env_summary.get("left", 0)

    session_snapshot = state.state.get("session", {}) if isinstance(state.state, dict) else {}
    intro_info = session_snapshot.get("intro", {}) if isinstance(session_snapshot, dict) else {}
    intro_payload = {
        "status": intro_info.get("status", "pending"),
        "prepared_at": intro_info.get("prepared_at"),
        "confirmed_at": intro_info.get("confirmed_at"),
        "title": intro_info.get("title"),
        "text": intro_info.get("text"),
        "error": intro_info.get("error"),
    }

    players_payload = []
    for pid, pdata in state.players.items():
        players_payload.append({
            "player_id": pid,
            "name": pdata.get("display_name", ""),
            "character_name": pdata.get("character"),
            "character_id": pdata.get("character_id"),
            "role": pdata.get("role"),
            "envelopes": len(pdata.get("envelopes", [])),
        })

    return JSONResponse(
        content={
            "ok": True,
            "phase_label": phase,
            "join_locked": join_locked,
            "players_count": players_count,
            "players": players_payload,
            "session_id": sid,
            "join_code": state.state.get("join_code"),
            "intro": intro_payload,
            "envelopes": {
                "total": env_total,
                "assigned": env_assigned,
                "left": env_left,
            },
        }
    )


def _get_or_create_canon(sid: str, state) -> Dict[str, Any]:
    """
    Return a canon dictionary. The priority is:
      1. Canon attached to the GameState.
      2. Canon loaded by NarrativeCore (shared file).
      3. Local generation via `generate_canon_and_intro`.
    """
    canon = state.state.get("canon")
    if isinstance(canon, dict) and canon.get("weapon"):
        return canon

    if isinstance(NARRATIVE.canon, dict) and NARRATIVE.canon.get("weapon"):
        state.state["canon"] = NARRATIVE.canon
        state.save()
        return NARRATIVE.canon

    generated = generate_canon_and_intro(use_llm=True)
    state.state["canon"] = generated
    state.save()
    return generated


@router.post("/envelopes_hidden")
async def envelopes_hidden(session_id: Optional[str] = Query(default=None)):
    """Mark the envelopes phase as completed."""
    sid = _normalize_session_id(session_id)
    state = get_session_state(sid)
    try:
        state.state["phase_label"] = "ENVELOPES_HIDDEN"
        state.log_event("phase_change", {"phase": "ENVELOPES_HIDDEN"})
        state.save()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Cannot set ENVELOPES_HIDDEN: {exc}") from exc

    await WS.broadcast_type("event", {"kind": "phase_change", "phase": "ENVELOPES_HIDDEN"})
    await WS.broadcast_type("event", {"kind": "envelopes_hidden"})
    return {"ok": True, "phase": "ENVELOPES_HIDDEN"}


@router.post("/roles_assign")
async def roles_assign(session_id: Optional[str] = Query(default=None)):
    """
    Assign killer / innocents and secondary missions to each player.
    Emits player-targeted WS events `role_reveal` and `secret_mission`.
    """
    sid = _normalize_session_id(session_id)
    state = get_session_state(sid)

    if not state.players:
        raise HTTPException(400, "No players registered")

    canon = _get_or_create_canon(sid, state)
    player_ids = sorted(state.players.keys())
    culprit_pid = canon.get("culprit_player_id")
    if culprit_pid not in player_ids:
        culprit_pid = random.choice(player_ids)
        canon["culprit_player_id"] = culprit_pid

    seed = state.state.get("story_seed") or {}
    missions_pool: List[Dict[str, Any]] = list(seed.get("missions") or [])
    culprit_missions: List[Dict[str, Any]] = list(seed.get("culprit_missions") or [])
    if missions_pool:
        random.shuffle(missions_pool)
    if culprit_missions:
        random.shuffle(culprit_missions)
    per_player: Dict[str, Dict[str, Any]] = {}

    for pid in player_ids:
        player = state.players.get(pid) or {}
        if not player.get("character_id"):
            assigned = CHARACTERS.assign_character(pid, game_state=state)
            if assigned:
                player["character"] = assigned.get("name")
                player["character_id"] = assigned.get("id")

    for pid in player_ids:
        role = "killer" if pid == culprit_pid else "innocent"
        if role == "killer":
            mission = (culprit_missions or missions_pool or [None]).pop(0) if (culprit_missions or missions_pool) else None
        else:
            mission = (missions_pool or [None]).pop(0) if missions_pool else None

        if not mission:
            mission = {
                "title": "Observer discretement",
                "text": "Recueille deux indices pertinents et partage-les avec tes allies.",
            }
        else:
            mission = dict(mission)

        state.players[pid]["role"] = role
        state.players[pid]["mission"] = mission
        per_player[pid] = {"role": role, "mission": mission}

    killer_entry = state.players.get(culprit_pid, {})
    canon["culprit_player_id"] = culprit_pid
    canon["culprit_name"] = (
        killer_entry.get("character")
        or killer_entry.get("display_name")
        or killer_entry.get("player_id")
    )
    state.state["canon"] = canon
    try:
        NARRATIVE.canon = canon
        NARRATIVE.save()
    except Exception:
        pass

    try:
        state.state["phase_label"] = "ROLES_ASSIGNED"
        state.log_event("roles_assigned", {"killer_player_id": culprit_pid})
        state.log_event("phase_change", {"phase": "ROLES_ASSIGNED"})
        state.save()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Cannot assign roles/missions: {exc}") from exc

    for pid, payload in per_player.items():
        state.log_event("ws_role_reveal_sent", {"player_id": pid, "role": payload["role"]})
        state.log_event(
            "ws_mission_sent",
            {"player_id": pid, "mission_title": payload["mission"].get("title")},
        )
        ws_send_type_to_player_safe(pid, "role_reveal", {"role": payload["role"]})
        ws_send_type_to_player_safe(pid, "secret_mission", payload["mission"])

    await WS.broadcast_type("event", {"kind": "roles_assigned"})
    await WS.broadcast_type("event", {"kind": "phase_change", "phase": "ROLES_ASSIGNED"})

    return {
        "ok": True,
        "phase": "ROLES_ASSIGNED",
        "killer_player_id": culprit_pid,
        "canon": canon,
        "players": list(state.players.values()),
    }
