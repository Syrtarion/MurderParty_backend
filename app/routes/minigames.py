"""
Module routes/minigames.py
Rôle:
- Gestion des sessions de mini-jeux (création, scores, résolution/récompenses).
- Repose sur:
  - `minigame_catalog.CATALOG` (définitions des jeux),
  - `minigame_runtime.RUNTIME` (état des sessions),
  - `team_utils.random_teams` (tirage aléatoire d'équipes),
  - `engine.rewarder.resolve_and_reward` (distribution des points/récompenses).

Sécurité:
- Router protégé MJ (`mj_required`).

Flux principaux:
- POST /create: valide le jeu et ouvre une session (solo/team, équipes auto/manuelles).
- POST /submit_scores: met à jour les scores de session.
- POST /resolve: calcule le classement et distribue les récompenses (async).
"""
from fastapi import APIRouter, Header, HTTPException
from fastapi import Depends
from app.deps.auth import mj_required
from pydantic import BaseModel, Field
from typing import Dict, List, Optional
from uuid import uuid4

from app.config.settings import settings
from app.services.minigame_catalog import CATALOG
from app.services.minigame_runtime import RUNTIME
from app.utils.team_utils import random_teams
from app.engine.rewarder import resolve_and_reward

router = APIRouter(prefix="/minigames", tags=["minigames"], dependencies=[Depends(mj_required)])

def _mj(auth: str | None):
    """
    Garde-fou supplémentaire si besoin d'un double-check Bearer MJ au niveau route.
    (Non utilisé par défaut car `mj_required` protège déjà le router.)
    """
    if not auth or not auth.startswith("Bearer ") or auth.split(" ", 1)[1] != settings.MJ_TOKEN:
        raise HTTPException(status_code=403, detail="MJ auth required")

class CreateSessionPayload(BaseModel):
    game_id: str = Field(..., description="ID du mini-jeu (catalog)")
    mode: str = Field(..., pattern="^(solo|team)$")
    participants: List[str]
    teams: Optional[Dict[str, List[str]]] = None
    auto_team_count: Optional[int] = Field(None, description="Nombre d'équipes (si teams non fourni)")
    auto_team_size: Optional[int] = Field(None, description="Taille approx. d'équipe (si team_count absent)")
    seed: Optional[int] = Field(None, description="Pour rejouer le tirage aléatoire")

@router.post("/create")
async def create_session(p: CreateSessionPayload):
    """
    Crée une session de mini-jeu et l'enregistre dans le runtime.
    - Mode solo: `participants` = liste de player_ids.
    - Mode team: `teams` fourni OU tirage auto selon `auto_team_*`.
    """
    game = CATALOG.get(p.game_id)
    if not game:
        raise HTTPException(404, "Unknown mini-game id")
    if game["mode"] != p.mode:
        raise HTTPException(400, f"Catalog mode is '{game['mode']}', got '{p.mode}'")

    session = {
        "session_id": f"MG-{uuid4().hex[:8]}",
        "game_id": p.game_id,
        "mode": p.mode,
        "status": "running",
        "scores": {}
    }

    if p.mode == "solo":
        session["participants"] = p.participants
        session["teams"] = None
    else:
        if p.teams is not None:
            # Équipes explicites fournies
            session["participants"] = list(p.teams.keys())
            session["teams"] = p.teams
        else:
            # Tirage d'équipes (équitable approximatif)
            teams = random_teams(players=p.participants, team_count=p.auto_team_count, team_size=p.auto_team_size, seed=p.seed)
            session["participants"] = list(teams.keys())
            session["teams"] = teams

    RUNTIME.create(session)
    return session

class SubmitScoresPayload(BaseModel):
    session_id: str
    scores: dict[str, int]

@router.post("/submit_scores")
async def submit_scores(p: SubmitScoresPayload):
    """
    Met à jour les scores d'une session en cours (RUNTIME.update_scores).
    - Renvoie 404 si la session n'existe pas.
    """
    s = RUNTIME.update_scores(p.session_id, p.scores)
    if not s:
        raise HTTPException(404, "Unknown session")
    return {"ok": True, "session": s}

class ResolvePayload(BaseModel):
    session_id: str

@router.post("/resolve")
async def resolve(p: ResolvePayload):
    """
    Termine la session et déclenche la distribution des récompenses.
    - `resolve_and_reward` est async car il peut émettre des WS/IO disques.
    """
    result = await resolve_and_reward(p.session_id)
    return result
