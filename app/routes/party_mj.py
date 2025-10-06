from __future__ import annotations
from fastapi import APIRouter, Depends

from app.deps.auth import mj_required
from app.services.mj_engine import MJ

router = APIRouter(prefix="/party", tags=["party"], dependencies=[Depends(mj_required)])


@router.post("/start")
async def party_start():
    """Démarre la partie et passe en attente des joueurs (WAITING_PLAYERS)."""
    return await MJ.start_party()


@router.post("/players_ready")
async def party_players_ready():
    """Confirme que tous les joueurs sont arrivés → distribution des enveloppes (équitable)."""
    return await MJ.players_ready()


@router.post("/envelopes_done")
async def party_envelopes_done():
    """Fin de la phase enveloppes → attribution de personnages → prêt pour SESSION_ACTIVE."""
    return await MJ.envelopes_done()


@router.get("/status")
async def party_status():
    """Retourne l'état courant du moteur MJ + quelques infos utiles."""
    return MJ.status()
