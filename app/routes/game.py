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
from typing import Any, Dict, List, Optional

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
