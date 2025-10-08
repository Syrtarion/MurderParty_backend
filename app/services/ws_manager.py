from __future__ import annotations
from typing import Dict, Set, Optional, Any
from dataclasses import dataclass, field
from threading import RLock
import json
import anyio
import asyncio
from starlette.websockets import WebSocket


# =====================================================
# GESTIONNAIRE WEBSOCKET PRINCIPAL
# =====================================================

@dataclass
class WSManager:
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)
    # player_id -> set of WebSocket
    clients_by_player: Dict[str, Set[WebSocket]] = field(default_factory=dict)
    # anonymous sockets waiting for identify
    pending: Set[WebSocket] = field(default_factory=set)

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        with self._lock:
            self.pending.add(ws)

    def _safe_remove(self, ws: WebSocket) -> None:
        with self._lock:
            self.pending.discard(ws)
            for pid, conns in list(self.clients_by_player.items()):
                if ws in conns:
                    conns.discard(ws)
                    if not conns:
                        del self.clients_by_player[pid]

    async def disconnect(self, ws: WebSocket) -> None:
        self._safe_remove(ws)
        try:
            await ws.close()
        except Exception:
            pass

    def identify(self, ws: WebSocket, player_id: str) -> None:
        with self._lock:
            self.pending.discard(ws)
            bucket = self.clients_by_player.setdefault(player_id, set())
            bucket.add(ws)

    async def send_json(self, ws: WebSocket, payload: Any) -> None:
        try:
            await ws.send_text(json.dumps(payload, ensure_ascii=False))
        except RuntimeError:
            self._safe_remove(ws)
        except Exception:
            self._safe_remove(ws)

    async def send_to_player(self, player_id: str, payload: Any) -> int:
        """Envoie un message à tous les sockets associés à un joueur."""
        with self._lock:
            conns = list(self.clients_by_player.get(player_id, set()))
        count = 0
        for ws in conns:
            await self.send_json(ws, payload)
            count += 1
        return count

    async def broadcast(self, payload: Any) -> int:
        """Diffuse à tous les sockets (connectés et en attente)."""
        with self._lock:
            conns = [ws for bucket in self.clients_by_player.values() for ws in bucket]
            conns += list(self.pending)
        count = 0
        for ws in conns:
            await self.send_json(ws, payload)
            count += 1
        return count


WS = WSManager()


# =====================================================
# WRAPPERS CLASSIQUES (hérités de ta version initiale)
# =====================================================
try:
    def ws_send_to_player(player_id: str, payload: Any) -> None:
        anyio.from_thread.run(WS.send_to_player, player_id, payload)

    def ws_broadcast(payload: Any) -> None:
        anyio.from_thread.run(WS.broadcast, payload)
except Exception:
    def ws_send_to_player(player_id: str, payload: Any) -> None:
        pass

    def ws_broadcast(payload: Any) -> None:
        pass


# =====================================================
# WRAPPERS SÛRS POUR ROUTES FASTAPI (thread-safe)
# =====================================================
def ws_broadcast_safe(payload: dict):
    """
    Wrapper sûr pour exécuter ws_broadcast depuis une route sync.
    Évite l'erreur "This function can only be run from an AnyIO worker thread".
    """
    try:
        anyio.from_thread.run(WS.broadcast, payload)
    except RuntimeError:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(WS.broadcast(payload))
        else:
            loop.run_until_complete(WS.broadcast(payload))


def ws_send_to_player_safe(player_id: str, payload: dict):
    """
    Wrapper sûr pour exécuter ws_send_to_player depuis une route sync.
    """
    try:
        anyio.from_thread.run(WS.send_to_player, player_id, payload)
    except RuntimeError:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(WS.send_to_player(player_id, payload))
        else:
            loop.run_until_complete(WS.send_to_player(player_id, payload))
