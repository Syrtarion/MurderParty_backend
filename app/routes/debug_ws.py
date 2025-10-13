"""
Module routes/debug_ws.py
Rôle:
- Utilitaires de debug pour pousser des messages via WebSocket:
  - Envoi ciblé d'indices à un joueur.
  - Broadcast d'un événement arbitraire.

Avertissement:
- ROUTER_ENABLED = True (à mettre False en prod).
- Destiné aux tests sur tablette MJ / clients Web pendant le dev.

Intégrations:
- `WS` (ws_manager): interface d’envoi `send_type_to_player` et `broadcast_type`.
"""
# app/routes/debug_ws.py
from fastapi import APIRouter, Body
from typing import Dict, Any
from app.services.ws_manager import WS  # ← on utilise l'instance directe

# Flag d’activation (mets False en prod)
ROUTER_ENABLED = True

router = APIRouter(prefix="/debug/ws", tags=["debug-ws"])

@router.post("/send_clue")
async def send_clue(
    player_id: str = Body(...),
    text: str = Body(...),
    kind: str = Body("crucial"),  # "crucial" | "ambiguous" | "red_herring"
):
    """
    Envoie un message de type 'clue' à un joueur spécifique via WS.
    - `kind` catégorise l’indice (affichage côté client).
    """
    await WS.send_type_to_player(player_id, "clue", {"text": text, "kind": kind})
    return {"ok": True, "sent_to": player_id}

@router.post("/broadcast_event")
async def broadcast_event(payload: Dict[str, Any] = Body(...)):
    """
    Diffuse un événement arbitraire à tous les clients connectés via WS.
    - `payload` doit contenir au minimum un champ 'type' côté client.
    """
    await WS.broadcast_type("event", payload)
    return {"ok": True, "broadcast": True}
