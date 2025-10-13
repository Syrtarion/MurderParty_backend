"""
Module routes/trial.py
Rôle:
- Orchestrage du "procès" de fin de partie (votes, dépouillement, verdict).
- Permet aussi d'afficher un leaderboard final basé sur `score_total`.

Sécurité:
- Toutes les routes sont protégées par `mj_required` (réservées au MJ).

Intégrations:
- TRIAL (trial_service): moteur de vote et de calcul du verdict.
- CATEGORIES: liste des catégories de vote autorisées (ex: coupable, mobile...).
- GAME_STATE / register_event: pour consigner les événements dans la timeline.

Endpoints:
- POST /trial/vote      → enregistre un vote
- GET  /trial/tally     → renvoie le décompte de votes
- POST /trial/verdict   → calcule et renvoie le verdict final
- GET  /trial/leaderboard → classement joueurs par score_total (décroissant)

Remarques:
- `VotePayload.category` doit appartenir à `CATEGORIES`.
- `register_event(...)` écrit un événement de type "vote" ou "trial_verdict" (audit).
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.deps.auth import mj_required
from app.services.trial_service import TRIAL, CATEGORIES
from app.services.game_state import GAME_STATE, register_event

router = APIRouter(prefix="/trial", tags=["trial"], dependencies=[Depends(mj_required)])


class VotePayload(BaseModel):
    voter_id: str = Field(..., description="player_id du votant")
    category: str = Field(..., description=f"Catégorie: {CATEGORIES}")
    value: str = Field(..., description="Proposition du joueur")


@router.post("/vote")
async def vote(p: VotePayload):
    """
    Enregistre un vote pour une catégorie donnée.
    - `voter_id`: player_id de l'émetteur du vote
    - `category`: doit être dans `CATEGORIES`
    - `value`: proposition du joueur (ex: identifiant du suspect)
    """
    res = TRIAL.vote(p.voter_id, p.category, p.value)
    # Trace timeline pour audit (affichage MJ / historique)
    register_event("vote", {"by": p.voter_id, "category": p.category, "value": p.value})
    return {"ok": True, "record": res}


@router.get("/tally")
async def tally():
    """
    Retourne le décompte des votes (agrégat par catégorie/valeur).
    - Utilisé par l'interface MJ pour suivre la tendance des votes.
    """
    return {"tally": TRIAL.tally()}


@router.post("/verdict")
async def verdict():
    """
    Fige le procès et calcule le verdict final (via `TRIAL.finalize()`).
    - Enregistre un event 'trial_verdict' dans la timeline.
    - Retourne la structure complète du verdict (dépend du service).
    """
    result = TRIAL.finalize()
    register_event("trial_verdict", {"result": "success", "detail": result})
    return result


@router.get("/leaderboard")
async def trial_leaderboard():
    """
    Retourne un classement des joueurs par `score_total` décroissant.
    - Utilisé en fin de partie pour afficher les résultats globaux.
    """
    players = [
        {
            "player_id": pid,
            "name": pdata.get("character") or pdata.get("display_name") or pid,
            "score_total": pdata.get("score_total", 0)
        }
        for pid, pdata in GAME_STATE.players.items()
    ]
    players_sorted = sorted(players, key=lambda p: p["score_total"], reverse=True)
    return {"ok": True, "leaderboard": players_sorted}
