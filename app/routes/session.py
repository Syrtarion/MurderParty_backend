"""
Routes de gestion de session (scope MJ).

Objectifs :
- Création de sessions et lecture de leur état courant.
- Pilotage du cycle de rounds (préparation, lancement, clôture).
- Gestion des équipes et soumission de scores.
- Exposition d'un squelette d'API conforme au plan Lot C (endpoints /session/{id}/...).

Les anciens endpoints (/session/status, /session/start_next, etc.) sont conservés
pour compatibilité mais délèguent aux nouveaux helpers.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from pydantic import BaseModel, Field

from app.deps.auth import mj_required
from app.services.round_preparation import prepare_round_assets
from app.services.session_engine import (
    ROUND_ACTIVE,
    ROUND_COOLDOWN,
    ROUND_IDLE,
    ROUND_INTRO,
)
from app.services.session_store import (
    DEFAULT_SESSION_ID,
    create_session_state,
    get_session_engine,
    get_session_state,
)
from app.services.story_seed import StorySeedError, load_story_seed_for_state
from app.services.ws_manager import ws_broadcast_type_safe
from app.utils.team_utils import random_teams

router = APIRouter(prefix="/session", tags=["session"], dependencies=[Depends(mj_required)])


# ---------------------------------------------------------------------------
# Modèles Pydantic
# ---------------------------------------------------------------------------
class SessionCreatePayload(BaseModel):
    campaign_id: Optional[str] = Field(None, description="Campagne/story seed à utiliser")
    session_id: Optional[str] = Field(None, description="Identifiant imposé (sinon auto)")


class SessionCreateResponse(BaseModel):
    session_id: str
    join_code: str
    players_max: Optional[int] = None


class SessionStateResponse(BaseModel):
    session_id: str
    join_code: Optional[str]
    players: Dict[str, Any]
    state: Dict[str, Any]
    events_count: int


class TeamDrawPayload(BaseModel):
    participants: Optional[List[str]] = Field(
        None, description="Liste de player_ids à répartir (défaut: tous les joueurs inscrits)"
    )
    auto_team_count: Optional[int] = Field(
        None, ge=1, description="Nombre d'équipes si génération automatique"
    )
    auto_team_size: Optional[int] = Field(
        None, ge=1, description="Taille cible d'équipe si team_count absent"
    )
    team_prefix: str = Field("T", min_length=1, max_length=8)


class TeamDrawResponse(BaseModel):
    session_id: str
    teams: Dict[str, List[str]]
    participants: List[str]


class RoundStartPayload(BaseModel):
    action: str = Field(
        "intro",
        pattern="^(intro|confirm)$",
        description="intro -> lance l'introduction, confirm -> passe la manche en ACTIVE",
    )
    auto_prepare_round: bool = Field(
        True, description="Préparer le round avec les assets LLM avant l'intro"
    )
    use_llm_rounds: bool = Field(
        True, description="Utiliser le LLM pour générer les assets si préparation demandée"
    )


class RoundStartResponse(BaseModel):
    ok: bool
    phase: str
    round_index: int
    payload: Dict[str, Any]


class RoundEndPayload(BaseModel):
    winners: Optional[List[str]] = Field(default=None, description="Liste de player_ids gagnants")
    meta: Optional[Dict[str, Any]] = Field(
        default=None, description="Métadonnées (scores, durée, etc.)"
    )
    auto_advance: bool = Field(
        False,
        description="Enchaîner automatiquement vers la manche suivante (intro)",
    )
    auto_prepare_round: bool = Field(
        True, description="Si auto_advance, préparer la manche suivante via LLM"
    )
    use_llm_rounds: bool = Field(
        True, description="Si auto_advance+préparation, utiliser le LLM"
    )


class RoundEndResponse(BaseModel):
    ok: bool
    phase: str
    round_index: int
    result: Dict[str, Any]
    auto_advance: Optional[Dict[str, Any]] = None


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


class SessionSubmitPayload(BaseModel):
    scores: Dict[str, Any] = Field(default_factory=dict, description="Tableau de scores ou points")
    notes: Optional[str] = Field(None, description="Commentaires MJ")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Infos additionnelles")
    finalize: bool = Field(False, description="Marque la session comme finalisée")


class SessionSubmitResponse(BaseModel):
    ok: bool
    submissions_count: int
    finalize: bool


# ---------------------------------------------------------------------------
# Helpers internes
# ---------------------------------------------------------------------------
def _normalize_session_id(session_id: Optional[str]) -> str:
    return (session_id or DEFAULT_SESSION_ID).strip() or DEFAULT_SESSION_ID


def _session_state_snapshot(session_id: str) -> SessionStateResponse:
    state = get_session_state(session_id)
    return SessionStateResponse(
        session_id=state.session_id,
        join_code=state.state.get("join_code"),
        players=state.players,
        state=state.state,
        events_count=len(state.events),
    )


# ---------------------------------------------------------------------------
# Endpoints principaux
# ---------------------------------------------------------------------------
@router.post("", response_model=SessionCreateResponse)
async def create_session(
    payload: SessionCreatePayload = Body(default_factory=SessionCreatePayload),
) -> SessionCreateResponse:
    """Crée une nouvelle session et renvoie son identifiant + join code."""
    sid = payload.session_id or uuid4().hex
    state = create_session_state(sid)
    if payload.campaign_id:
        state.state["campaign_id"] = payload.campaign_id
    join_code = state.state.get("join_code") or sid[:6].upper()
    state.state["join_code"] = join_code
    state.save()
    try:
        seed = load_story_seed_for_state(state, refresh=True)
        players_max = seed.get("meta", {}).get("players_max")
    except StorySeedError:
        players_max = None
    return SessionCreateResponse(session_id=state.session_id, join_code=join_code, players_max=players_max)


@router.get("/{session_id}/state", response_model=SessionStateResponse)
async def session_state(session_id: str) -> SessionStateResponse:
    """Retourne un snapshot brut (players/state/events_count) de la session."""
    normalized = _normalize_session_id(session_id)
    return _session_state_snapshot(normalized)


@router.post("/{session_id}/teams/draw", response_model=TeamDrawResponse)
async def session_draw_teams(session_id: str, payload: TeamDrawPayload) -> TeamDrawResponse:
    """Génère ou enregistre une répartition d'équipes pour la session."""
    normalized = _normalize_session_id(session_id)
    state = get_session_state(normalized)

    participants = payload.participants or list(state.players.keys())
    if not participants:
        raise HTTPException(status_code=400, detail="Aucun participant à répartir.")

    teams = random_teams(
        participants,
        team_count=payload.auto_team_count,
        team_size=payload.auto_team_size,
        team_prefix=payload.team_prefix,
    )
    session_data = state.state.setdefault("session", {})
    session_data["participants"] = participants
    session_data["teams"] = teams
    state.save()
    state.log_event("teams_drawn", {"team_count": len(teams), "participants": len(participants)})
    ws_broadcast_type_safe(
        "event",
        {"kind": "teams_drawn", "session_id": normalized, "team_count": len(teams)},
    )
    return TeamDrawResponse(session_id=normalized, teams=teams, participants=participants)


@router.post("/{session_id}/round/{round_number}/prepare", response_model=PrepareRoundResponse)
async def session_prepare_round(
    session_id: str,
    round_number: int,
    use_llm: bool = Query(default=True, description="Utiliser le LLM pour générer les textes"),
) -> PrepareRoundResponse:
    """
    Pré-génère narration, énigme et indices pour la manche (1-based).
    Stocke le résultat dans l'état de session et diffuse un évènement WS.
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


async def _run_round_intro(
    engine,
    round_number: int,
    auto_prepare_round: bool,
    use_llm_rounds: bool,
) -> Dict[str, Any]:
    status = engine.status()
    expected = status["round_index"] + 1
    if round_number != expected:
        raise HTTPException(
            status_code=409,
            detail=f"Round {round_number} inattendu (prochain attendu: {expected}).",
        )
    result = await engine.begin_next_round(
        auto_prepare_round=auto_prepare_round,
        use_llm_rounds=use_llm_rounds,
    )
    return result


async def _run_round_confirm(engine, round_number: int) -> Dict[str, Any]:
    status = engine.status()
    if status["round_phase"] != ROUND_INTRO or status["round_index"] != round_number:
        raise HTTPException(
            status_code=409,
            detail=f"Impossible de confirmer (phase={status['round_phase']}, round_index={status['round_index']}).",
        )
    return await engine.confirm_start()


@router.post("/{session_id}/round/{round_number}/start", response_model=RoundStartResponse)
async def session_round_start(session_id: str, round_number: int, payload: RoundStartPayload) -> RoundStartResponse:
    """Lance l'intro d'une manche ou confirme son démarrage effectif."""
    normalized = _normalize_session_id(session_id)
    engine = get_session_engine(normalized)

    if payload.action == "intro":
        result = await _run_round_intro(
            engine,
            round_number=round_number,
            auto_prepare_round=payload.auto_prepare_round,
            use_llm_rounds=payload.use_llm_rounds,
        )
        status = engine.status()
        return RoundStartResponse(
            ok=bool(result.get("ok")),
            phase=status["round_phase"],
            round_index=status["round_index"],
            payload=result,
        )

    # action == "confirm"
    result = await _run_round_confirm(engine, round_number)
    status = engine.status()
    return RoundStartResponse(
        ok=bool(result.get("ok", True)),
        phase=status["round_phase"],
        round_index=status["round_index"],
        payload=result,
    )


@router.post("/{session_id}/round/{round_number}/end", response_model=RoundEndResponse)
async def session_round_end(session_id: str, round_number: int, payload: RoundEndPayload) -> RoundEndResponse:
    """Clôture une manche (scores / meta) et, optionnellement, enchaîne sur la suivante."""
    normalized = _normalize_session_id(session_id)
    engine = get_session_engine(normalized)
    status = engine.status()
    if status["round_index"] != round_number or status["round_phase"] != ROUND_ACTIVE:
        raise HTTPException(
            status_code=409,
            detail=f"Aucun round actif à clôturer (phase={status['round_phase']}, index={status['round_index']}).",
        )

    result = await engine.finish_current_round(
        winners=payload.winners or [],
        meta=payload.meta or {},
    )
    state = get_session_state(normalized)
    state.log_event(
        "round_closed",
        {
            "round_index": round_number,
            "winners": (payload.winners or []),
        },
    )
    ws_broadcast_type_safe(
        "event",
        {"kind": "round_closed", "session_id": normalized, "round_index": round_number},
    )

    auto_payload: Optional[Dict[str, Any]] = None
    if payload.auto_advance:
        auto_payload = await _run_round_intro(
            engine,
            round_number=round_number + 1,
            auto_prepare_round=payload.auto_prepare_round,
            use_llm_rounds=payload.use_llm_rounds,
        )

    status_after = engine.status()
    return RoundEndResponse(
        ok=True,
        phase=status_after["round_phase"],
        round_index=status_after["round_index"],
        result=result,
        auto_advance=auto_payload,
    )


@router.post("/{session_id}/submit", response_model=SessionSubmitResponse)
async def session_submit(session_id: str, payload: SessionSubmitPayload) -> SessionSubmitResponse:
    """Enregistre une soumission de scores/notes pour la session."""
    normalized = _normalize_session_id(session_id)
    state = get_session_state(normalized)
    session_data = state.state.setdefault("session", {})
    submissions = session_data.setdefault("submissions", [])
    submissions.append(
        {
            "scores": payload.scores,
            "notes": payload.notes,
            "metadata": payload.metadata,
            "finalize": payload.finalize,
        }
    )
    if payload.finalize:
        session_data["finalized"] = True
    state.save()
    state.log_event(
        "session_submitted",
        {"scores_count": len(payload.scores), "finalize": payload.finalize},
    )
    ws_broadcast_type_safe(
        "event",
        {"kind": "session_submitted", "session_id": normalized, "finalize": payload.finalize},
    )
    return SessionSubmitResponse(ok=True, submissions_count=len(submissions), finalize=payload.finalize)


@router.post("/{session_id}/intro/confirm", response_model=IntroConfirmResponse)
async def session_intro_confirm(
    session_id: str,
    use_llm_rounds: bool = Query(default=True, description="Utiliser le LLM pour préparer le round 1 si besoin"),
) -> IntroConfirmResponse:
    """Confirme l'intro de session (transition vers round 1)."""
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


# ---------------------------------------------------------------------------
# Endpoints legacy (compatibilité)
# ---------------------------------------------------------------------------
@router.get("/status")
async def session_status(
    session_id: Optional[str] = Query(default=None, description="Identifiant de session"),
):
    engine = get_session_engine(_normalize_session_id(session_id))
    return engine.status()


@router.post("/start_next")
async def session_start_next(
    session_id: Optional[str] = Query(default=None),
    auto_prepare_round: bool = Query(
        default=True, description="Préparer automatiquement la manche suivante"
    ),
    use_llm_rounds: bool = Query(default=True, description="Utiliser le LLM pour préparer le round"),
):
    normalized = _normalize_session_id(session_id)
    engine = get_session_engine(normalized)
    return await _run_round_intro(
        engine,
        round_number=engine.status()["round_index"] + 1,
        auto_prepare_round=auto_prepare_round,
        use_llm_rounds=use_llm_rounds,
    )


@router.post("/confirm_start")
async def session_confirm_start(session_id: Optional[str] = Query(default=None)):
    normalized = _normalize_session_id(session_id)
    engine = get_session_engine(normalized)
    status = engine.status()
    if status["round_phase"] != ROUND_INTRO:
        raise HTTPException(status_code=409, detail="Aucun round en phase INTRO.")
    return await _run_round_confirm(engine, status["round_index"])


class ResultPayload(BaseModel):
    winners: Optional[List[str]] = []
    meta: Optional[Dict[str, Any]] = {}


@router.post("/result")
async def session_result(payload: ResultPayload, session_id: Optional[str] = Query(default=None)):
    normalized = _normalize_session_id(session_id)
    engine = get_session_engine(normalized)
    status = engine.status()
    if status["round_phase"] != ROUND_ACTIVE:
        raise HTTPException(status_code=409, detail="Aucun round actif à clôturer.")
    return await engine.finish_current_round(
        winners=payload.winners or [],
        meta=payload.meta or {},
    )


@router.post("/abort_timer")
async def session_abort_timer(session_id: Optional[str] = Query(default=None)):
    normalized = _normalize_session_id(session_id)
    engine = get_session_engine(normalized)
    await engine.abort_timer()
    return {"ok": True}
