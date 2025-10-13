"""
Service: ws_manager.py
Rôle:
- Gérer l’ensemble des connexions WebSocket (mapping player_id → sockets).
- Offrir des helpers d’envoi ciblé/broadcast + wrappers thread-safe utilisables
  depuis du code synchrone (routes FastAPI sync).

Conception:
- Stocke *plusieurs* sockets par player_id (multi-onglets / multi-devices).
- Maintient un pool de sockets "pending" tant que le client n'a pas envoyé "identify".
- Snapshots (copies immuables) pour éviter l’erreur "set changed size during iteration".

API principale:
- WS.connect(ws) / WS.disconnect(ws) / WS.identify(ws, player_id)
- WS.send_to_player(player_id, payload) / WS.broadcast(payload) / WS.broadcast_all(payload)
- Helpers typés: send_type_to_player, broadcast_type, ...
- Wrappers sync: ws_send_to_player_safe, ws_broadcast_safe, etc.
"""
from __future__ import annotations
from typing import Dict, Set, Any
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
        """Accepte la connexion WS et la place dans 'pending' jusqu'à identification."""
        await ws.accept()
        with self._lock:
            self.pending.add(ws)

    def _safe_remove(self, ws: WebSocket) -> None:
        """Retire la socket de tous les ensembles (pending ou identifiés)."""
        with self._lock:
            self.pending.discard(ws)
            for pid, conns in list(self.clients_by_player.items()):
                if ws in conns:
                    conns.discard(ws)
                    if not conns:
                        del self.clients_by_player[pid]

    async def disconnect(self, ws: WebSocket) -> None:
        """Ferme proprement la connexion et nettoie les registres."""
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
            # socket mort/fermée → on la retire silencieusement
            self._safe_remove(ws)
            return False

    async def send_json(self, ws: WebSocket, payload: Any) -> bool:
        """Envoi simple d’un JSON à un seul WS."""
        return await self._send_json_one(ws, payload)

    # ---------- SNAPSHOTS (listes immuables pour éviter "set changed size") ----------

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

    # ---------- ENVOIS ----------

    async def send_to_player(self, player_id: str, payload: Any) -> int:
        """Envoie un message à tous les sockets associés à un joueur (succès réels)."""
        conns = self._snapshot_player(player_id)
        success = 0
        for ws in conns:  # itère sur le snapshot
            if await self._send_json_one(ws, payload):
                success += 1
        return success

    async def broadcast(self, payload: Any) -> int:
        """Diffuse à tous les sockets identifiés (par défaut)."""
        conns = self._snapshot_all_identified()
        success = 0
        for ws in conns:  # itère sur le snapshot
            if await self._send_json_one(ws, payload):
                success += 1
        return success

    async def broadcast_all(self, payload: Any) -> int:
        """Diffuse à tous les sockets, y compris 'pending' (rarement nécessaire)."""
        conns = self._snapshot_all()
        success = 0
        for ws in conns:  # itère sur le snapshot
            if await self._send_json_one(ws, payload):
                success += 1
        return success

    # ---------- Helpers "typés" (type + payload) ----------

    async def send_type_to_player(self, player_id: str, event_type: str, payload: Any) -> int:
        """Ajoute un champ 'type' au payload et envoie au joueur."""
        return await self.send_to_player(player_id, {"type": event_type, "payload": payload})

    async def broadcast_type(self, event_type: str, payload: Any) -> int:
        """Ajoute 'type' et diffuse à tout le monde identifié."""
        return await self.broadcast({"type": event_type, "payload": payload})

    async def broadcast_all_type(self, event_type: str, payload: Any) -> int:
        """Ajoute 'type' et diffuse à tout le monde (y compris pending)."""
        return await self.broadcast_all({"type": event_type, "payload": payload})


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
