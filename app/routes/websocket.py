# app/routes/websocket.py
"""
WebSocket endpoints.

- /ws : canal joueur historique (identification player_id, ping/pong, ACK générique).
- /ws/session/{session_id} : nouveau flux MJ pour suivre l'état d'une session
  (phase courante, timer mock, score updates).
"""
from __future__ import annotations

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.services.session_engine import ROUND_ACTIVE
from app.services.session_store import DEFAULT_SESSION_ID, get_session_engine
from app.services.ws_manager import WS

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """
    Boucle d'écoute legacy pour les clients joueurs.
    - Identification via {"type":"identify","player_id": "..."}.
    - Ping/pong pour heartbeat.
    - ACK générique pour les autres types.
    """
    await WS.connect(ws)
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                # Message non JSON -> ignore
                continue

            mtype: str = msg.get("type")
            if mtype == "identify":
                payload = msg.get("payload") or {}
                pid: Optional[str] = (msg.get("player_id") or payload.get("player_id") or "").strip()
                if pid:
                    WS.identify(ws, pid)
                    await WS.send_json(ws, {"type": "identified", "player_id": pid})
                else:
                    await WS.send_json(ws, {"type": "error", "error": "missing player_id"})
            elif mtype == "ping":
                await WS.send_json(ws, {"type": "pong"})
            else:
                await WS.send_json(ws, {"type": "ack", "received": msg})
    except WebSocketDisconnect:
        pass
    finally:
        if ws.client_state != WebSocketState.DISCONNECTED:
            await WS.disconnect(ws)
        else:
            await WS.disconnect(ws)


def _normalize_session_id(session_id: Optional[str]) -> str:
    return (session_id or DEFAULT_SESSION_ID).strip() or DEFAULT_SESSION_ID


@router.websocket("/ws/session/{session_id}")
async def websocket_session_stream(ws: WebSocket, session_id: str):
    """
    Flux minimal pour les dashboards MJ.
    Diffuse périodiquement :
      - la phase courante (type=phase)
      - un tick timer mock (type=timer_tick)
      - les events score_update du journal (type=score_update)
    """
    normalized = _normalize_session_id(session_id)
    engine = get_session_engine(normalized)
    await ws.accept()
    last_event_index = len(engine.game_state.events)

    async def _send_json(payload: dict):
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        await ws.send_text(text)

    await _send_json({"type": "session_state", "session_id": normalized, "payload": engine.status()})

    try:
        while True:
            await asyncio.sleep(1.0)
            status = engine.status()
            await _send_json(
                {
                    "type": "phase",
                    "session_id": normalized,
                    "phase": status["round_phase"],
                    "round_index": status["round_index"],
                }
            )
            await _send_json(
                {
                    "type": "timer_tick",
                    "session_id": normalized,
                    "active": status["round_phase"] == ROUND_ACTIVE,
                    "has_timer": status.get("has_timer", False),
                }
            )

            events = engine.game_state.events
            if len(events) > last_event_index:
                for event in events[last_event_index:]:
                    if event.get("kind") == "score_update":
                        await _send_json(
                            {
                                "type": "score_update",
                                "session_id": normalized,
                                "payload": event.get("payload", {}),
                            }
                        )
                last_event_index = len(events)
    except WebSocketDisconnect:
        pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass
