# app/routes/debug_ws.py
"""
Module routes/debug_ws.py
Rôle:
- Utilitaires de debug pour pousser des messages via WebSocket:
  - Envoi ciblé d'indices à un joueur.
  - Broadcast d'un événement arbitraire.
  - Statut des pairs / fermeture forcée / kick joueur.
"""
from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel
from typing import Dict, Any

from app.services.ws_manager import WS, ws_send_type_to_player_safe
from app.services.envelopes import player_envelopes

router = APIRouter(prefix="/debug/ws", tags=["debug-ws"])

@router.get("/peers")
def ws_peers() -> Dict[str, Any]:
    """Carte des connexions WS (identifiés/pending)."""
    return WS.stats()

class PushEnvPayload(BaseModel):
    player_id: str

@router.post("/push_envelopes")
def push_envelopes(p: PushEnvPayload):
    """(Re)envoie un event 'envelopes_update' ciblé à ce joueur."""
    envs = player_envelopes(p.player_id)
    if envs is None:
        raise HTTPException(404, "player_not_found_or_no_envelopes")
    ws_send_type_to_player_safe(p.player_id, "event", {
        "kind": "envelopes_update",
        "player_id": p.player_id,
        "envelopes": envs,
    })
    return {"ok": True, "sent": len(envs)}

@router.post("/send_clue")
async def send_clue(
    player_id: str = Body(...),
    text: str = Body(...),
    kind: str = Body("crucial"),  # "crucial" | "ambiguous" | "red_herring"
):
    """Envoie un message de type 'clue' à un joueur spécifique via WS."""
    await WS.send_type_to_player(player_id, "clue", {"text": text, "kind": kind})
    return {"ok": True, "sent_to": player_id}

@router.post("/broadcast_event")
async def broadcast_event(payload: Dict[str, Any] = Body(...)):
    """Diffuse un événement arbitraire à tous les clients via WS."""
    await WS.broadcast_type("event", payload)
    return {"ok": True, "broadcast": True}

@router.post("/kick/{player_id}")
async def kick_player(player_id: str):
    """Ferme toutes les sockets d’un joueur (utile après reset partiel)."""
    n = await WS.kick_player(player_id)
    return {"ok": True, "kicked": n, "player_id": player_id}

@router.post("/close_all")
async def close_all():
    """Ferme toutes les sockets (identifiés + pending)."""
    stats = await WS.close_all()
    return {"ok": True, "stats": stats}
