# app/routes/websocket.py
"""
Module routes/websocket.py
Rôle:
- Point d'entrée WebSocket unique (ws://.../ws) pour la communication temps réel.
- Gère l'identification du client (player_id) et un protocole minimal (ping/pong).

Protocole client accepté (tolérant) :
1) Connexion → le client ouvre ws://<host>/ws
2) Identification (2 formats supportés) :
   a) {"type":"identify","player_id":"<id>"}
   b) {"type":"identify","payload":{"player_id":"<id>"}}
   - Sans identify valide, la connexion reste "pending" côté WS manager.
3) Réception push serveur (exemples):
   - {"type":"secret_mission","mission":{...}}
   - {"type":"clue","text":"...","kind":"crucial|ambiguous|red_herring"}
   - {"type":"event","kind":"...","payload":{...}}
4) Heartbeat:
   - Client → {"type":"ping"}
   - Serveur → {"type":"pong"}

Intégrations:
- WS (ws_manager): centralise les connexions, envoi ciblé/broadcast, mapping ws→player_id.

Robustesse:
- Messages non-JSON ignorés (continue).
- En cas de déconnexion, on appelle `WS.disconnect(ws)` pour nettoyer l'état.
"""
from __future__ import annotations
import json
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.services.ws_manager import WS

router = APIRouter()

@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """
    Boucle de réception/traitement des messages WS côté serveur.
    - Identifie la socket quand le client envoie {"type":"identify", ...}.
    - Répond aux pings avec {"type":"pong"}.
    - Accuse réception pour les autres types avec {"type":"ack", "received": ...}.
    """
    await WS.connect(ws)  # Enregistre la socket côté manager (état "pending")
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                # Message invalide (non-JSON) → on l'ignore proprement
                continue

            mtype: str = msg.get("type")
            if mtype == "identify":
                # Deux formats acceptés :
                #  - top-level: {"type":"identify","player_id":"..."}
                #  - payload  : {"type":"identify","payload":{"player_id":"..."}}
                payload = msg.get("payload") or {}
                pid: Optional[str] = (msg.get("player_id") or payload.get("player_id") or "").strip()
                if pid:
                    WS.identify(ws, pid)
                    # Ack d'identification : cohérent avec l'existant
                    await WS.send_json(ws, {"type": "identified", "player_id": pid})
                else:
                    await WS.send_json(ws, {"type": "error", "error": "missing player_id"})

            elif mtype == "ping":
                # Heartbeat de vivacité
                await WS.send_json(ws, {"type": "pong"})

            else:
                # Par défaut: accusé de réception générique
                await WS.send_json(ws, {"type": "ack", "received": msg})
    except WebSocketDisconnect:
        # Déconnexion "propre" déclenchée côté client
        pass
    finally:
        # Nettoyage
        if ws.client_state != WebSocketState.DISCONNECTED:
            await WS.disconnect(ws)
        else:
            # Si déjà fermé côté client, on nettoie quand même nos registres
            await WS.disconnect(ws)
