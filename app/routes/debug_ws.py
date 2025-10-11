# app/routes/debug_ws.py
from fastapi import APIRouter, Body
from typing import Optional, Dict, Any
from app.services.ws_manager import (
    ws_send_type_to_player_safe,
    ws_broadcast_type_safe,
)

router = APIRouter(prefix="/debug/ws", tags=["debug-ws"])

@router.post("/send_clue")
def send_clue(
    player_id: str = Body(...),
    text: str = Body(...),
    kind: str = Body("crucial"),  # "crucial" | "ambiguous" | "red_herring"
):
    ws_send_type_to_player_safe(player_id, "clue", {"text": text, "kind": kind})
    return {"ok": True, "sent_to": player_id}

@router.post("/broadcast_event")
def broadcast_event(payload: Dict[str, Any] = Body(...)):
    # Exemple payload: {"kind": "round_advance", "step": 2}
    ws_broadcast_type_safe("event", payload)
    return {"ok": True, "broadcast": True}
