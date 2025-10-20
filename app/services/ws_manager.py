# app/services/ws_manager.py
"""
Service: ws_manager.py
- Mapping player_id -> sockets ET socket -> player_id (ws_to_player).
- Identification idempotente (déplacement de socket si player change).
- Snapshots immuables pour éviter "set changed size during iteration".
- Helpers sync pour envois typés & bruts.
- Admin: stats(), kick_player(), close_all().
"""
from __future__ import annotations
from typing import Dict, Set, Any
from dataclasses import dataclass, field
from threading import RLock
import json
import anyio
import asyncio
from starlette.websockets import WebSocket

@dataclass
class WSManager:
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)
    # player_id -> set(WebSocket)
    clients_by_player: Dict[str, Set[WebSocket]] = field(default_factory=dict)
    # anonymous sockets waiting for identify
    pending: Set[WebSocket] = field(default_factory=set)
    # reverse map: socket -> player_id
    ws_to_player: Dict[WebSocket, str] = field(default_factory=dict)

    async def connect(self, ws: WebSocket) -> None:
        """Accepte la connexion WS et place dans 'pending'."""
        await ws.accept()
        with self._lock:
            self.pending.add(ws)

    def _unlink_ws_from_current_player(self, ws: WebSocket) -> None:
        """Retire 'ws' des structures où il se trouve (pending et/ou player)."""
        with self._lock:
            self.pending.discard(ws)
            prev_pid = self.ws_to_player.pop(ws, None)
            if prev_pid:
                bucket = self.clients_by_player.get(prev_pid)
                if bucket and ws in bucket:
                    bucket.discard(ws)
                    if not bucket:
                        self.clients_by_player.pop(prev_pid, None)

    async def disconnect(self, ws: WebSocket) -> None:
        """Ferme proprement la connexion et nettoie les registres."""
        self._unlink_ws_from_current_player(ws)
        try:
            await ws.close()
        except Exception:
            pass

    def identify(self, ws: WebSocket, player_id: str) -> None:
        """
        Associe un WebSocket à un player_id.
        - S'il était déjà associé à un autre player, on le déplace proprement.
        - Retire de 'pending'.
        """
        with self._lock:
            # enlever des emplacements actuels
            self.pending.discard(ws)
            prev_pid = self.ws_to_player.get(ws)
            if prev_pid and prev_pid != player_id:
                bucket_prev = self.clients_by_player.get(prev_pid)
                if bucket_prev and ws in bucket_prev:
                    bucket_prev.discard(ws)
                    if not bucket_prev:
                        self.clients_by_player.pop(prev_pid, None)

            # associer au nouveau player
            bucket = self.clients_by_player.setdefault(player_id, set())
            bucket.add(ws)
            self.ws_to_player[ws] = player_id

    async def _send_json_one(self, ws: WebSocket, payload: Any) -> bool:
        """Envoie à un WS; renvoie True si succès, sinon False (et retire le WS mort)."""
        try:
            data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            await ws.send_text(data)
            return True
        except Exception:
            self._unlink_ws_from_current_player(ws)
            return False

    async def send_json(self, ws: WebSocket, payload: Any) -> bool:
        return await self._send_json_one(ws, payload)

    # ---------- snapshots immuables ----------
    def _snapshot_player(self, player_id: str) -> list[WebSocket]:
        with self._lock:
            return list(self.clients_by_player.get(player_id, set()))

    def _snapshot_all_identified(self) -> list[WebSocket]:
        with self._lock:
            result: list[WebSocket] = []
            for bucket in self.clients_by_player.values():
                result.extend(list(bucket))
            return result

    def _snapshot_all(self) -> list[WebSocket]:
        with self._lock:
            result: list[WebSocket] = []
            for bucket in self.clients_by_player.values():
                result.extend(list(bucket))
            result.extend(list(self.pending))
            return result

    # ---------- envois ----------
    async def send_to_player(self, player_id: str, payload: Any) -> int:
        conns = self._snapshot_player(player_id)
        success = 0
        for ws in conns:
            if await self._send_json_one(ws, payload):
                success += 1
        print(f"[WS] send_to_player pid={player_id} success={success}/{len(conns)}")
        return success

    async def broadcast(self, payload: Any) -> int:
        conns = self._snapshot_all_identified()
        success = 0
        for ws in conns:
            if await self._send_json_one(ws, payload):
                success += 1
        return success

    async def broadcast_all(self, payload: Any) -> int:
        conns = self._snapshot_all()
        success = 0
        for ws in conns:
            if await self._send_json_one(ws, payload):
                success += 1
        return success

    # ---------- helpers typés ----------
    async def send_type_to_player(self, player_id: str, event_type: str, payload: Any) -> int:
        return await self.send_to_player(player_id, {"type": event_type, "payload": payload})

    async def broadcast_type(self, event_type: str, payload: Any) -> int:
        return await self.broadcast({"type": event_type, "payload": payload})

    async def broadcast_all_type(self, event_type: str, payload: Any) -> int:
        return await self.broadcast_all({"type": event_type, "payload": payload})

    # ---------- admin ----------
    def stats(self) -> dict:
        with self._lock:
            identified = {pid: len(conns) for pid, conns in self.clients_by_player.items()}
            return {
                "identified": identified,
                "identified_total": sum(identified.values()),
                "pending_total": len(self.pending),
            }

    async def kick_player(self, player_id: str) -> int:
        """Ferme toutes les sockets d’un joueur et nettoie les mappings."""
        conns = self._snapshot_player(player_id)
        for ws in conns:
            await self.disconnect(ws)
        return len(conns)

    async def close_all(self) -> dict:
        """Ferme TOUTES les sockets (identified + pending)."""
        conns = self._snapshot_all()
        for ws in conns:
            await self.disconnect(ws)
        return self.stats()


WS = WSManager()

# =====================================================
# WRAPPERS THREAD-SAFE (utilisables depuis routes sync)
# =====================================================

def _run_async(coro):
    """
    Exécute une coroutine depuis un contexte potentiellement synchrone.
    - Essaie anyio.from_thread.run si on est dans un worker anyio (run_in_threadpool).
    - Sinon, utilise la loop courante si elle tourne, ou crée une loop.
    - Enveloppe la coroutine pour éviter 'cannot reuse already awaited coroutine'.
    """
    import anyio as _anyio
    import asyncio as _asyncio

    async def _runner():
        return await coro  # évite 'cannot reuse already awaited coroutine'

    try:
        # cas FastAPI sync -> anyio.to_thread.run_sync(...): on est dans un thread anyio
        return _anyio.from_thread.run(_runner)
    except RuntimeError:
        # pas de worker anyio -> on tente la loop actuelle, sinon on en crée une
        try:
            loop = _asyncio.get_event_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            _asyncio.create_task(coro)  # fire-and-forget
            return None
        else:
            return _asyncio.run(_runner())

# --- Envois "payload brut" ---
def ws_send_to_player_safe(player_id: str, payload: dict):
    """Wrapper synchrone: envoi ciblé vers player_id."""
    _run_async(WS.send_to_player(player_id, payload))

def ws_broadcast_safe(payload: dict):
    """Wrapper synchrone: broadcast à tous les identifiés."""
    _run_async(WS.broadcast(payload))

def ws_broadcast_all_safe(payload: dict):
    """Wrapper synchrone: broadcast y compris 'pending'."""
    _run_async(WS.broadcast_all(payload))

# --- Envois "typés" (type + payload) ---
def ws_send_type_to_player_safe(player_id: str, event_type: str, payload: dict):
    """Wrapper synchrone: envoi typé à un joueur."""
    _run_async(WS.send_type_to_player(player_id, event_type, payload))

def ws_broadcast_type_safe(event_type: str, payload: dict):
    """Wrapper synchrone: broadcast typé à tous les identifiés."""
    _run_async(WS.broadcast_type(event_type, payload))

def ws_broadcast_all_type_safe(event_type: str, payload: dict):
    """Wrapper synchrone: broadcast typé à tous (y compris pending)."""
    _run_async(WS.broadcast_all_type(event_type, payload))

# --- (Alias pratique) ---
def ws_send_envelopes_update(player_id: str, envelopes: list[dict]):
    """
    Alias pratique : envoie un event 'event' avec kind='envelopes_update' ciblé joueur.
    Utilisé par master.py après distribution / réassignation.
    """
    ws_send_type_to_player_safe(player_id, "event", {
        "kind": "envelopes_update",
        "player_id": player_id,
        "envelopes": envelopes,
    })
