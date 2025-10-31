"""
Routes publiques liées aux indices (hints) pour une session.
- Partage d'un indice par le joueur qui l'a découvert.
- Action spéciale du killer pour détruire un indice.
- Lecture de l'historique des indices (filtrable par joueur).

Ces routes sont volontairement sans protection MJ : l'identification se fait
via les `player_id` fournis, comme pour les autres endpoints joueurs.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services.session_store import DEFAULT_SESSION_ID, get_session_state
from app.services.hint_service import deliver_hint, destroy_hint

router = APIRouter(prefix="/session", tags=["session:hints"])


def _normalize_session_id(session_id: Optional[str]) -> str:
    return (session_id or DEFAULT_SESSION_ID).strip() or DEFAULT_SESSION_ID


class HintSharePayload(BaseModel):
    round_index: int
    discoverer_id: str
    tier: str = "major"
    share: bool = True


class HintDestroyPayload(BaseModel):
    hint_id: str
    killer_id: str


@router.post("/{session_id}/hint/share")
async def session_hint_share(session_id: str, payload: HintSharePayload):
    """
    Enregistre la décision de partage/non-partage d'un indice pour un round donné.
    Retourne la trace complète de distribution (tiers, textes par joueur).
    """
    state = get_session_state(_normalize_session_id(session_id))
    try:
        entry = deliver_hint(state, payload.round_index, payload.discoverer_id, payload.tier, payload.share)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "hint": entry}


@router.post("/{session_id}/killer/destroy_hint")
async def session_killer_destroy_hint(session_id: str, payload: HintDestroyPayload):
    """
    Permet au killer de détruire un indice (quota défini dans le story seed).
    """
    state = get_session_state(_normalize_session_id(session_id))
    try:
        entry = destroy_hint(state, payload.hint_id, payload.killer_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "hint": entry}


def _project_for_player(entry: Dict[str, Any], player_id: str) -> Optional[Dict[str, Any]]:
    deliveries: List[Dict[str, Any]] = entry.get("deliveries") or []
    for delivery in deliveries:
        if delivery.get("player_id") == player_id:
            return {
                "hint_id": entry.get("hint_id"),
                "round_index": entry.get("round_index"),
                "discoverer_id": entry.get("discoverer_id"),
                "shared": entry.get("shared"),
                "tier": delivery.get("tier"),
                "text": delivery.get("text"),
                "destroyed": entry.get("destroyed", False),
                "destroyed_at": entry.get("destroyed_at"),
                "destroyed_by": entry.get("destroyed_by"),
                "created_at": entry.get("created_at"),
            }
    return None


@router.get("/{session_id}/hints")
async def session_hints(
    session_id: str,
    player_id: Optional[str] = Query(default=None, description="Filtrer les indices reçus par ce joueur"),
):
    """
    Retourne l'historique des indices pour la session.
    - sans `player_id`: renvoie les entrées complètes (MJ / audit).
    - avec `player_id`: ne renvoie que la vision du joueur (tier + texte qu'il reçoit).
    """
    state = get_session_state(_normalize_session_id(session_id))
    history: List[Dict[str, Any]] = list(state.state.get("hints_history") or [])
    if not player_id:
        # Copie défensive pour éviter les mutations accidentelles côté client.
        safe_history = []
        for entry in history:
            safe_entry = dict(entry)
            deliveries = entry.get("deliveries")
            if isinstance(deliveries, list):
                safe_entry["deliveries"] = [dict(d) for d in deliveries]
            safe_history.append(safe_entry)
        return {"ok": True, "hints": safe_history}

    projected: List[Dict[str, Any]] = []
    for entry in history:
        proj = _project_for_player(entry, player_id)
        if proj:
            projected.append(proj)
    return {"ok": True, "hints": projected}

