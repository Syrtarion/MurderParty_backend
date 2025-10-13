"""
Module routes/party_mj.py
Rôle:
- Contrôles "macro" du MJ sur le déroulé de la soirée (phases).
- Démarre la partie, ouvre/ferme l'inscription, chaîne enveloppes → personnages.

Intégrations:
- MJ (services.mj_engine): moteur d'état côté MJ (phases, transitions).
- GAME_STATE: gestion du `join_locked`, log/persist.
- WS: diffusions d'événements "phase_change" et "join_unlocked".

Endpoints:
- POST /party/start: set phase WAITING_PLAYERS, ouvre inscriptions.
- POST /party/players_ready: fin arrivée, lancer distribution enveloppes.
- POST /party/envelopes_done: fin enveloppes, attribuer personnages → phase suivante.
- GET  /party/status: état synthétique côté MJ.

Notes:
- Les fonctions `players_ready` / `envelopes_done` déléguent au moteur MJ (async).
"""
from __future__ import annotations
from fastapi import APIRouter, Depends

from app.deps.auth import mj_required
from app.services.mj_engine import MJ

router = APIRouter(prefix="/party", tags=["party"], dependencies=[Depends(mj_required)])

@router.post("/start")
async def party_start():
    """
    Démarre la partie :
      - phase_label = WAITING_PLAYERS
      - join_locked = False (ouverture des inscriptions)
      - broadcast d’un événement 'phase_change' + 'join_unlocked'
    """
    # phase moteur
    from app.services.mj_engine import MJ, WAITING_PLAYERS
    MJ.set_phase(WAITING_PLAYERS)

    # ouverture des inscriptions côté état global
    from app.services.game_state import GAME_STATE
    GAME_STATE.state["join_locked"] = False
    GAME_STATE.log_event("phase_change", {"phase": WAITING_PLAYERS})
    GAME_STATE.save()

    # diffusion WebSocket
    from app.services.ws_manager import WS
    await WS.broadcast({
        "type": "event",
        "kind": "phase_change",
        "phase": WAITING_PLAYERS,
        "text": "La partie démarre. Les invités peuvent arriver."
    })
    await WS.broadcast_type("event", {"kind": "join_unlocked"})

    return {"ok": True, "phase": WAITING_PLAYERS, "join_locked": False}

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
    """Retourne l'état courant du moteur MJ + quelques infos utiles (phases, flags)."""
    return MJ.status()
