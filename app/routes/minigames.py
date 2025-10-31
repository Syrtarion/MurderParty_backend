"""
Mini-games routes (MJ only).
Handles creation, score submission and resolution of mini-game sessions while
linking each entry to a MurderParty session via `session_id`.
"""
from __future__ import annotations

from typing import Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.deps.auth import mj_required
from app.services.session_store import DEFAULT_SESSION_ID, get_session_state
from app.services.minigame_catalog import CATALOG
from app.services.minigame_runtime import RUNTIME
from app.utils.team_utils import random_teams
from app.engine.rewarder import resolve_and_reward


router = APIRouter(prefix="/minigames", tags=["minigames"], dependencies=[Depends(mj_required)])


def _normalize_session_id(session_id: Optional[str]) -> str:
    sid = (session_id or DEFAULT_SESSION_ID).strip()
    return sid or DEFAULT_SESSION_ID


class CreateSessionPayload(BaseModel):
    game_id: str = Field(..., description="ID du mini-jeu (catalogue)")
    mode: str = Field(..., pattern="^(solo|team)$")
    participants: List[str]
    teams: Optional[Dict[str, List[str]]] = None
    auto_team_count: Optional[int] = Field(None, description="Nombre d'équipes si génération auto")
    auto_team_size: Optional[int] = Field(None, description="Taille estimée d'équipe si count absent")
    seed: Optional[int] = Field(None, description="Seed pour tirer les équipes de manière déterministe")


@router.post("/create")
async def create_session(
    payload: CreateSessionPayload,
    session_id: Optional[str] = Query(default=None, description="Identifiant de session MurderParty"),
):
    """Create a mini-game runtime session linked to the given MurderParty session."""
    game = CATALOG.get(payload.game_id)
    if not game:
        raise HTTPException(404, "Unknown mini-game id")
    if game["mode"] != payload.mode:
        raise HTTPException(400, f"Catalog mode is '{game['mode']}', got '{payload.mode}'")

    host_session_id = _normalize_session_id(session_id)
    session = {
        "session_id": f"MG-{uuid4().hex[:8]}",
        "game_id": payload.game_id,
        "mode": payload.mode,
        "status": "running",
        "scores": {},
        "murder_session_id": host_session_id,
    }

    if payload.mode == "solo":
        session["participants"] = payload.participants
        session["teams"] = None
    else:
        if payload.teams is not None:
            session["participants"] = list(payload.teams.keys())
            session["teams"] = payload.teams
        else:
            teams = random_teams(
                players=payload.participants,
                team_count=payload.auto_team_count,
                team_size=payload.auto_team_size,
                seed=payload.seed,
            )
            session["participants"] = list(teams.keys())
            session["teams"] = teams

    RUNTIME.create(session)
    return session


class SubmitScoresPayload(BaseModel):
    session_id: str
    scores: Dict[str, int]


@router.post("/submit_scores")
async def submit_scores(
    payload: SubmitScoresPayload,
    session_id: Optional[str] = Query(default=None, description="Identifiant de session MurderParty"),
):
    """Update scores for a running mini-game session."""
    host_session_id = _normalize_session_id(session_id)
    updated = RUNTIME.update_scores(payload.session_id, payload.scores, murder_session_id=host_session_id)
    if not updated:
        raise HTTPException(404, "Unknown session")
    return {"ok": True, "session": updated}


class ResolvePayload(BaseModel):
    session_id: str


@router.post("/resolve")
async def resolve(
    payload: ResolvePayload,
    session_id: Optional[str] = Query(default=None, description="Identifiant de session MurderParty"),
):
    """
    Resolve a mini-game session: distribute rewards and broadcast updates.
    """
    host_session_id = _normalize_session_id(session_id)
    state = get_session_state(host_session_id)
    result = await resolve_and_reward(payload.session_id, host_session_id, state)
    return result
