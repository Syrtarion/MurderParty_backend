"""

Module routes/game.py

RÃ´le:

- Endpoints publics relatifs Ã  lâÃ©tat de la partie et au ping du LLM.



IntÃ©grations:

- GAME_STATE: snapshot (players/state/events).

- NARRATIVE: canon narratif courant (plutÃ´t cÃ´tÃ© MJ mais exposÃ© ici).

- generate_indice: test de vivacitÃ© LLM (diagnostic).

- settings: pour exposer le modÃ¨le/provider testÃ©s.



# FIX (Lot A):

- /game/state retourne:

  - phase_label, join_locked

  - players: [{player_id, name, character_id}]

  - si ?player_id=... -> bloc "me" avec envelopes [{num,id}]

"""

from fastapi import APIRouter, HTTPException, Query

from fastapi.responses import JSONResponse

from typing import Any, Dict, List, Optional, Literal, Tuple


from app.services.session_store import (
    DEFAULT_SESSION_ID,
    find_session_by_player_id,
    find_session_id_by_join_code,
    get_session_state,
)

from app.services.game_state import GameState

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


def _event_visible_for_player(entry: Dict[str, Any], player_id: Optional[str]) -> bool:
    """
    Visibility rules for player audiences:
      - admin scoped events are hidden from players
      - private events are visible only to listed targets
      - public events are always visible
    """
    scope = entry.get("scope") or entry.get("audience")
    if scope == "admin":
        return False
    if scope == "private":
        if not player_id:
            return False
        targets = entry.get("targets") or []
        return player_id in targets
    if scope == "player" and player_id:
        targets = entry.get("targets") or []
        if targets and player_id not in targets:
            return False
    return True


def _format_event(entry: Dict[str, Any], index: int) -> Dict[str, Any]:
    """
    Ensure each event has a stable identifier and timestamp before returning it to clients.
    """
    formatted = dict(entry)
    formatted.setdefault("id", entry.get("id") or f"event-{index}")
    if formatted.get("ts") is None:
        formatted["ts"] = index
    return formatted


def _resolve_session_state(
    session_id: Optional[str],
    join_code: Optional[str],
    player_id: Optional[str] = None,
) -> tuple[str, GameState]:
    sid = (session_id or "").strip()
    if sid:
        state = get_session_state(sid)
        if player_id and player_id not in state.players:
            fallback = find_session_by_player_id(player_id)
            if fallback:
                sid, state = fallback
        return sid, state
    resolved = find_session_id_by_join_code(join_code)
    if join_code and not resolved:
        raise HTTPException(status_code=404, detail="session_not_found")
    if resolved:
        return resolved, get_session_state(resolved)
    if player_id:
        found = find_session_by_player_id(player_id)
        if found:
            sid_found, state = found
            return sid_found, state
    return DEFAULT_SESSION_ID, get_session_state(DEFAULT_SESSION_ID)




@router.get("/state")
def get_state(
    player_id: Optional[str] = Query(default=None, description="Optionnel, pour inclure 'me'"),
    session_id: Optional[str] = Query(default=None, description="Identifiant de session"),
    join_code: Optional[str] = Query(default=None, description="Code de session partagé par le MJ"),
):
    """
    Etat public du jeu (Lot A):
    - phase_label, join_locked
    - players : [ {player_id, name, character_id}, ... ]
    - me (optionnel si player_id fourni) : { player_id, name, character_id, envelopes: [{num,id}] }
    """
    sid, state = _resolve_session_state(session_id, join_code, player_id)

    phase = state.state.get("phase_label", "JOIN")
    join_locked = bool(state.state.get("join_locked", False))

    players_public: List[Dict[str, Any]] = [
        _public_player_view(p) for p in state.players.values()
    ]

    payload: Dict[str, Any] = {
        "phase_label": phase,
        "join_locked": join_locked,
        "players": players_public,
        "session_id": sid,
        "join_code": state.state.get("join_code"),
    }

    if player_id:
        me = state.players.get(player_id)
        if not me:
            raise HTTPException(status_code=404, detail="Player not found")
        payload["me"] = {
            "player_id": me["player_id"],
            "name": me.get("display_name", ""),
            "character_id": me.get("character_id"),
            "character_name": me.get("character"),
            "envelopes": me.get("envelopes", []),
            "role": me.get("role"),
            "mission": me.get("mission"),
        }

    return JSONResponse(content=payload)


@router.get("/events")
def get_events(
    player_id: Optional[str] = Query(None, description="Filtre les événements privés de ce joueur"),
    audience: Literal["player", "admin"] = Query("player", description="admin = lecture complète sans filtre"),
    limit: int = Query(200, ge=1, le=500, description="Nombre maximum d'événements retournés"),
    since_ts: Optional[float] = Query(None, description="Ne retourner que les événements avec ts strictement supérieur"),
    session_id: Optional[str] = Query(default=None, description="Identifiant de session"),
    join_code: Optional[str] = Query(default=None, description="Code de session partagé par le MJ"),
):
    """
    Flux d'événements consolidés.
    - audience=player : masque les scopes admin/MJ et ne renvoie les dispatch privés que si `player_id` est fourni.
    - audience=admin  : renvoie tout le journal tel quel (utilisation MJ / audit).
    """
    sid, state = _resolve_session_state(session_id, join_code, player_id)

    events = state.events_snapshot()
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
        "session_id": sid,
    }


@router.get("/canon")

async def get_canon():

    """Canon narratif courant (attention: privÃ© cÃ´tÃ© MJ)."""

    return NARRATIVE.canon



@router.get("/test_llm")

async def test_llm():

    """

    Ping du modÃ¨le LLM en franÃ§ais (diagnostic rapide).

    - Retourne ok + modÃ¨le/provider + rÃ©ponse courte.

    - Utile pour vÃ©rifier config (Ollama/LLM local).

    """

    try:

        result = generate_indice(

            "Dis simplement 'Bonjour, je suis prÃªt Ã  gÃ©nÃ©rer des indices pour la murder party.'",

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

