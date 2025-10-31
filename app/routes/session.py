"""
Module routes/session.py
Rôle:
- Gestion des sessions (création) et pilotage micro des rounds.
- Délégue au `SessionEngine` spécifique à chaque session.

Sécurité:
- Accès MJ uniquement (`mj_required`).

Endpoints principaux:
- POST /session                 -> crée une nouvelle session (renvoie session_id/join_code)
- GET  /session/status          -> snapshot (phase, round, timers) d'une session
- POST /session/start_next      -> passe au prochain round (annonce + WS)
- POST /session/confirm_start   -> confirme le démarrage effectif du mini-jeu
- POST /session/result          -> enregistre les résultats (winners + meta)
- POST /session/abort_timer     -> stoppe le timer "souple" en cours
"""
from __future__ import annotations

from typing import List, Dict, Any, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel

from app.deps.auth import mj_required
from app.services.session_store import (
    DEFAULT_SESSION_ID,
    create_session_state,
    get_session_engine,
    get_session_state,
)
from app.services.story_seed import load_story_seed_dict, StorySeedError
from app.services.round_preparation import prepare_round_assets
from app.services.ws_manager import ws_broadcast_type_safe

router = APIRouter(prefix="/session", tags=["session"], dependencies=[Depends(mj_required)])


class SessionCreatePayload(BaseModel):
    campaign_id: Optional[str] = None
    session_id: Optional[str] = None


class SessionCreateResponse(BaseModel):
    session_id: str
    join_code: str
    players_max: Optional[int] = None


@router.post("", response_model=SessionCreateResponse)
async def create_session(payload: SessionCreatePayload):
    """Crée une session vide et renvoie ses attributs."""
    sid = payload.session_id or uuid4().hex
    state = create_session_state(sid)
    if payload.campaign_id:
        state.state["campaign_id"] = payload.campaign_id
    join_code = state.state.get("join_code") or sid[:6].upper()
    state.state["join_code"] = join_code
    state.save()
    try:
        seed = load_story_seed_dict()
        players_max = seed.get("meta", {}).get("players_max")
    except StorySeedError:
        players_max = None
    return SessionCreateResponse(session_id=state.session_id, join_code=join_code, players_max=players_max)


def _normalize_session_id(session_id: Optional[str]) -> str:
    return (session_id or DEFAULT_SESSION_ID).strip() or DEFAULT_SESSION_ID


@router.get("/status")
async def session_status(session_id: Optional[str] = Query(default=None, description="Identifiant de session")):
    engine = get_session_engine(_normalize_session_id(session_id))
    return engine.status()


@router.post("/start_next")
async def session_start_next(
    session_id: Optional[str] = Query(default=None),
    auto_prepare_round: bool = Query(default=True, description="Préparer automatiquement la manche suivante"),
    use_llm_rounds: bool = Query(default=True, description="Utiliser le LLM pour préparer le round"),
):
    engine = get_session_engine(_normalize_session_id(session_id))
    return await engine.begin_next_round(
        auto_prepare_round=auto_prepare_round,
        use_llm_rounds=use_llm_rounds,
    )


@router.post("/confirm_start")
async def session_confirm_start(session_id: Optional[str] = Query(default=None)):
    engine = get_session_engine(_normalize_session_id(session_id))
    return await engine.confirm_start()


class ResultPayload(BaseModel):
    winners: Optional[List[str]] = []
    meta: Optional[Dict[str, Any]] = {}


@router.post("/result")
async def session_result(payload: ResultPayload, session_id: Optional[str] = Query(default=None)):
    engine = get_session_engine(_normalize_session_id(session_id))
    winners = payload.winners or []
    meta = payload.meta or {}
    return await engine.finish_current_round(winners=winners, meta=meta)


@router.post("/abort_timer")
async def session_abort_timer(session_id: Optional[str] = Query(default=None)):
    engine = get_session_engine(_normalize_session_id(session_id))
    await engine.abort_timer()
    return {"ok": True}

class PrepareRoundResponse(BaseModel):
    ok: bool
    round_index: int
    prepared: Dict[str, Any]


class IntroConfirmResponse(BaseModel):
    ok: bool
    already_confirmed: Optional[bool] = None
    intro: Dict[str, Any]
    prepared_round: Optional[Dict[str, Any]] = None
    round: Optional[Dict[str, Any]] = None


@router.post("/{session_id}/round/{round_number}/prepare", response_model=PrepareRoundResponse)
async def session_prepare_round(
    session_id: str,
    round_number: int,
    use_llm: bool = Query(default=True, description="Utiliser le LLM pour générer les textes"),
):
    """
    Pré-génère narration, énigme et indices pour la manche indiquée (1-based).
    Stocke le résultat dans l'état de session et diffuse un événement WS dédié.
    """
    normalized = _normalize_session_id(session_id)
    state = get_session_state(normalized)
    if round_number < 1:
        raise HTTPException(status_code=400, detail="round_number must be >= 1")

    try:
        prepared = prepare_round_assets(state, round_number, use_llm=use_llm)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    state.log_event("round_prepared", {"round_index": round_number})
    ws_broadcast_type_safe(
        "event",
        {
            "kind": "round_prepared",
            "session_id": normalized,
            "round_index": round_number,
            "prepared": prepared,
        },
    )
    return PrepareRoundResponse(ok=True, round_index=round_number, prepared=prepared)


@router.post("/{session_id}/intro/confirm", response_model=IntroConfirmResponse)
async def session_intro_confirm(
    session_id: str,
    use_llm_rounds: bool = Query(default=True, description="Utiliser le LLM pour préparer le round 1 si besoin"),
):
    normalized = _normalize_session_id(session_id)
    engine = get_session_engine(normalized)
    try:
        result = await engine.confirm_intro(use_llm_rounds=use_llm_rounds)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return IntroConfirmResponse(
        ok=result.get("ok", True),
        already_confirmed=result.get("already_confirmed"),
        intro=result.get("intro") or {},
        prepared_round=result.get("prepared_round"),
        round=result.get("round"),
    )
