"""
Module routes/game.py
Rôle:
- Endpoints publics relatifs à l’état de la partie et au ping du LLM.

Intégrations:
- GAME_STATE: snapshot (players/state/events).
- NARRATIVE: canon narratif courant (plutôt côté MJ mais exposé ici).
- generate_indice: test de vivacité LLM (diagnostic).
- settings: pour exposer le modèle/provider testés.

# FIX (Lot A):
- /game/state retourne:
  - phase_label, join_locked
  - players: [{player_id, name, character_id}]
  - si ?player_id=... -> bloc "me" avec envelopes [{num,id}]
"""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from typing import Any, Dict, List, Optional, Literal

from app.services.game_state import GAME_STATE
from app.services.narrative_core import NARRATIVE
from app.services.llm_engine import generate_indice
from app.config.settings import settings

router = APIRouter(prefix="/game", tags=["game"])

def _public_player_view(p: Dict[str, Any]) -> Dict[str, Any]:
    """Vue publique d'un joueur (pas de password_hash, etc.)."""
    return {
        "player_id": p["player_id"],
        "name": p.get("display_name", ""),
        "character_id": p.get("character_id"),
        "character_name": p.get("character"),
    }

@router.get("/state")
def get_state(player_id: Optional[str] = Query(default=None, description="Optionnel, pour inclure 'me'")):
    """
    Etat public du jeu (Lot A):
    - phase_label, join_locked
    - players : [ {player_id, name, character_id}, ... ]
    - me (optionnel si player_id fourni) : { player_id, name, character_id, envelopes: [{num,id}] }
    """
    phase = GAME_STATE.state.get("phase_label", "JOIN")
    join_locked = bool(GAME_STATE.state.get("join_locked", False))

    players_public: List[Dict[str, Any]] = [
        _public_player_view(p) for p in GAME_STATE.players.values()
    ]

    payload: Dict[str, Any] = {
        "phase_label": phase,
        "join_locked": join_locked,
        "players": players_public,
    }

    if player_id:
        me = GAME_STATE.players.get(player_id)
        if not me:
            raise HTTPException(status_code=404, detail="Player not found")
        payload["me"] = {
            "player_id": me["player_id"],
            "name": me.get("display_name", ""),
            "character_id": me.get("character_id"),
            "character_name": me.get("character"),
            "envelopes": me.get("envelopes", []),  # vue minimale {num,id}
            "role": me.get("role"),
            "mission": me.get("mission"),
        }

    return JSONResponse(content=payload)


def _format_event(entry: Dict[str, Any], fallback_idx: int) -> Dict[str, Any]:
    kind = entry.get("kind") or "event"
    payload = entry.get("payload") or {}
    event_type = kind
    targets: List[str] = []
    channel = entry.get("scope") or "system"

    if kind == "ws_dispatch":
        event_type = payload.get("event_type") or "event"
        targets = list(payload.get("targets") or [])
        channel = payload.get("channel") or channel
        payload = payload.get("payload") or {}

    ts = entry.get("ts")
    event_id = entry.get("id") or f"{int((ts or 0) * 1000)}-{fallback_idx}"

    return {
        "id": event_id,
        "type": event_type,
        "payload": payload,
        "ts": ts,
        "scope": entry.get("scope"),
        "targets": targets,
        "channel": channel,
    }


def _event_visible_for_player(entry: Dict[str, Any], player_id: Optional[str]) -> bool:
    scope = entry.get("scope") or ""
    if scope.startswith("admin") or scope.startswith("mj"):
        return False

    if entry.get("kind") == "ws_dispatch":
        payload = entry.get("payload") or {}
        targets = payload.get("targets") or []
        channel = payload.get("channel") or ""
        if targets:
            return bool(player_id) and player_id in targets
        # broadcast / broadcast_all restent visibles
        return channel in ("broadcast", "broadcast_all", "", None)

    return True


@router.get("/events")
def get_events(
    player_id: Optional[str] = Query(None, description="Filtre les événements privés de ce joueur"),
    audience: Literal["player", "admin"] = Query("player", description="admin = lecture complète sans filtre"),
    limit: int = Query(200, ge=1, le=500, description="Nombre maximum d'événements retournés"),
    since_ts: Optional[float] = Query(None, description="Ne retourner que les événements avec ts strictement supérieur"),
):
    """
    Flux d'événements consolidés.
    - audience=player : masque les scopes admin/MJ et ne renvoie les dispatch privés que si `player_id` est fourni.
    - audience=admin  : renvoie tout le journal tel quel (utilisation MJ / audit).
    """
    events = GAME_STATE.events_snapshot()
    events.sort(key=lambda e: e.get("ts", 0) or 0)

    filtered: List[Dict[str, Any]] = []
    for idx, entry in enumerate(events):
        ts = entry.get("ts", 0) or 0
        if since_ts is not None and ts <= since_ts:
            continue

        if audience == "player":
            if not _event_visible_for_player(entry, player_id):
                continue
        formatted = _format_event(entry, idx)
        filtered.append(formatted)

    if limit:
        filtered = filtered[-limit:]

    return {
        "ok": True,
        "count": len(filtered),
        "events": filtered,
        "latest_ts": filtered[-1]["ts"] if filtered else since_ts,
    }

@router.get("/canon")
async def get_canon():
    """Canon narratif courant (attention: privé côté MJ)."""
    return NARRATIVE.canon

@router.get("/test_llm")
async def test_llm():
    """
    Ping du modèle LLM en français (diagnostic rapide).
    - Retourne ok + modèle/provider + réponse courte.
    - Utile pour vérifier config (Ollama/LLM local).
    """
    try:
        result = generate_indice(
            "Dis simplement 'Bonjour, je suis prêt à générer des indices pour la murder party.'",
            "decor",
        )
        return {
            "ok": True,
            "model": settings.LLM_MODEL,
            "provider": settings.LLM_PROVIDER,
            "response": result.get("text", ""),
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "model": settings.LLM_MODEL}
