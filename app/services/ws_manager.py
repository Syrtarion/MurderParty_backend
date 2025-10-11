from __future__ import annotations
from typing import Dict, Set, Optional, Any, Iterable
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
        """Associe un WebSocket à un player_id et le retire des 'pending'."""
        with self._lock:
            self.pending.discard(ws)
            bucket = self.clients_by_player.setdefault(player_id, set())
            bucket.add(ws)

    async def _send_json_one(self, ws: WebSocket, payload: Any) -> bool:
        """Envoie à un WS; renvoie True si succès, sinon False (et retire le WS mort)."""
        try:
            data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            await ws.send_text(data)
            return True
        except Exception:
            # RuntimeError ou autre → socket mort/fermé → on le retire
            self._safe_remove(ws)
            return False

    async def send_json(self, ws: WebSocket, payload: Any) -> bool:
        """Alias public si tu veux garder l'API existante."""
        return await self._send_json_one(ws, payload)

    def _snapshot_player(self, player_id: str) -> Set[WebSocket]:
        with self._lock:
            return set(self.clients_by_player.get(player_id, set()))

    def _snapshot_all_identified(self) -> Iterable[WebSocket]:
        with self._lock:
            for bucket in self.clients_by_player.values():
                for ws in bucket:
                    yield ws

    def _snapshot_all(self) -> Iterable[WebSocket]:
        with self._lock:
            for bucket in self.clients_by_player.values():
                for ws in bucket:
                    yield ws
            for ws in self.pending:
                yield ws

    async def send_to_player(self, player_id: str, payload: Any) -> int:
        """Envoie un message à tous les sockets associés à un joueur (succès réels)."""
        conns = self._snapshot_player(player_id)
        success = 0
        for ws in conns:
            if await self._send_json_one(ws, payload):
                success += 1
        return success

    async def broadcast(self, payload: Any) -> int:
        """Diffuse à tous les sockets identifiés (par défaut)."""
        success = 0
        for ws in self._snapshot_all_identified():
            if await self._send_json_one(ws, payload):
                success += 1
        return success

    async def broadcast_all(self, payload: Any) -> int:
        """Diffuse à tous les sockets, y compris 'pending' (rarement nécessaire)."""
        success = 0
        for ws in self._snapshot_all():
            if await self._send_json_one(ws, payload):
                success += 1
        return success

    # ----------------------------
    # Helpers "typés" (type + payload)
    # ----------------------------

    async def send_type_to_player(self, player_id: str, event_type: str, payload: Any) -> int:
        return await self.send_to_player(player_id, {"type": event_type, "payload": payload})

    async def broadcast_type(self, event_type: str, payload: Any) -> int:
        return await self.broadcast({"type": event_type, "payload": payload})

    async def broadcast_all_type(self, event_type: str, payload: Any) -> int:
        return await self.broadcast_all({"type": event_type, "payload": payload})


WS = WSManager()

# =====================================================
# WRAPPERS THREAD-SAFE (utilisables depuis routes sync)
# =====================================================

def _run_async(coro):
    """
    Exécute un coroutine depuis un contexte potentiellement sync:
    - Tente anyio.from_thread.run (si on est dans un worker anyio)
    - Sinon, tente d'utiliser l'event loop courant; sinon en crée un.
    """
    try:
        return anyio.from_thread.run(lambda: coro)  # anyio gère le run du coro
    except RuntimeError:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            # On ne peut pas bloquer, on schedule et on ne renvoie rien de synchrone
            asyncio.create_task(coro)
            return None
        else:
            # Contexte totalement sync (ex: script, test)
            return asyncio.run(coro)

# --- Envois "payload brut" ---
def ws_send_to_player_safe(player_id: str, payload: dict):
    _run_async(WS.send_to_player(player_id, payload))

def ws_broadcast_safe(payload: dict):
    _run_async(WS.broadcast(payload))

def ws_broadcast_all_safe(payload: dict):
    _run_async(WS.broadcast_all(payload))

# --- Envois "typés" (type + payload) ---
def ws_send_type_to_player_safe(player_id: str, event_type: str, payload: dict):
    _run_async(WS.send_type_to_player(player_id, event_type, payload))

def ws_broadcast_type_safe(event_type: str, payload: dict):
    _run_async(WS.broadcast_type(event_type, payload))

def ws_broadcast_all_type_safe(event_type: str, payload: dict):
    _run_async(WS.broadcast_all_type(event_type, payload))
