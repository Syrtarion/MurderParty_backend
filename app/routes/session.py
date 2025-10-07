from __future__ import annotations
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.deps.auth import mj_required
from app.services.session_engine import SESSION

router = APIRouter(prefix="/session", tags=["session"], dependencies=[Depends(mj_required)])


@router.get("/status")
async def session_status():
    """Retourne l'état courant de la session (phase, round, timer, etc.)."""
    return SESSION.status()


@router.post("/start_next")
async def session_start_next():
    """Passe au round suivant (annonce intro + WS prompt pour démarrer le mini-jeu)."""
    return await SESSION.start_next_round()


@router.post("/confirm_start")
async def session_confirm_start():
    """Confirme que le mini-jeu courant est lancé (phase ACTIVE)."""
    return await SESSION.confirm_start()


class ResultPayload(BaseModel):
    winners: Optional[List[str]] = []
    meta: Optional[Dict[str, Any]] = {}


@router.post("/result")
async def session_result(payload: ResultPayload):
    """Signale la fin du mini-jeu (scores + gagnants). 
    N'atteint pas le round suivant. 
    Utilise ensuite /session/start_next pour avancer.
    Exemple payload:
    {
      "winners": ["player_id1", "player_id2"],
      "meta": {"score": {"p1": 10, "p2": 5}}
    }
    """
    winners = payload.winners or []
    meta = payload.meta or {}
    return await SESSION.finish_current_round(winners=winners, meta=meta)


@router.post("/abort_timer")
async def session_abort_timer():
    """Annule le timer souple en cours (utile si le mini-jeu se termine avant la limite)."""
    await SESSION.abort_timer()
    return {"ok": True}
