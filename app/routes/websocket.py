from __future__ import annotations
import json
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi import Depends
from starlette.websockets import WebSocketState

from app.services.ws_manager import WS

router = APIRouter()

@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """
    Protocole minimal :
    1) Le client se connecte à ws://.../ws
    2) Il envoie un message JSON : {"type":"identify","player_id":"..."}
       - S'il n'envoie pas d'identify dans les 20s, la connexion peut rester en pending.
    3) Ensuite, le serveur peut pousser des messages ciblés :
       - {"type":"secret_mission","mission":{...}}
       - {"type":"clue","text":"...","kind":"crucial|ambiguous|red_herring"}
       - {"type":"event","kind":"...","payload":{...}}
    4) Heartbeat : le client peut envoyer {"type":"ping"}; le serveur répond {"type":"pong"}.
    """
    await WS.connect(ws)
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                # ignore invalid
                continue

            mtype: str = msg.get("type")
            if mtype == "identify":
                pid: Optional[str] = (msg.get("player_id") or "").strip()
                if pid:
                    WS.identify(ws, pid)
                    await WS.send_json(ws, {"type": "identified", "player_id": pid})
                else:
                    await WS.send_json(ws, {"type": "error", "error": "missing player_id"})

            elif mtype == "ping":
                await WS.send_json(ws, {"type": "pong"})

            else:
                # Echo back as generic
                await WS.send_json(ws, {"type": "ack", "received": msg})
    except WebSocketDisconnect:
        pass
    finally:
        if ws.client_state != WebSocketState.DISCONNECTED:
            await WS.disconnect(ws)
