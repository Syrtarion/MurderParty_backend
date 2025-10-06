from __future__ import annotations
from typing import Dict, Set, Optional, Any
from dataclasses import dataclass, field
from threading import RLock
import json

from starlette.websockets import WebSocket


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
            # remove from any player sets
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
            # closed socket
            self._safe_remove(ws)
        except Exception:
            self._safe_remove(ws)

    async def send_to_player(self, player_id: str, payload: Any) -> int:
        """Send payload to all sockets registered for player_id. Returns number of deliveries."""
        with self._lock:
            conns = list(self.clients_by_player.get(player_id, set()))
        count = 0
        for ws in conns:
            await self.send_json(ws, payload)
            count += 1
        return count

    async def broadcast(self, payload: Any) -> int:
        with self._lock:
            conns = [ws for bucket in self.clients_by_player.values() for ws in bucket]
            conns += list(self.pending)
        count = 0
        for ws in conns:
            await self.send_json(ws, payload)
            count += 1
        return count


WS = WSManager()

# Convenience helpers usable from sync contexts (via background tasks)
try:
    import anyio

    def ws_send_to_player(player_id: str, payload: Any) -> None:
        anyio.from_thread.run(WS.send_to_player, player_id, payload)

    def ws_broadcast(payload: Any) -> None:
        anyio.from_thread.run(WS.broadcast, payload)
except Exception:
    # Fallback no-op if anyio not present
    def ws_send_to_player(player_id: str, payload: Any) -> None:
        pass

    def ws_broadcast(payload: Any) -> None:
        pass
