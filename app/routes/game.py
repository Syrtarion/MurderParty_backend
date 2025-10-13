"""
Module routes/game.py
Rôle:
- Endpoints publics relatifs à l’état de la partie et au ping du LLM.

Intégrations:
- GAME_STATE: snapshot (players/state/events).
- NARRATIVE: canon narratif courant (plutôt côté MJ mais exposé ici).
- generate_indice: test de vivacité LLM (diagnostic).
- settings: pour exposer le modèle/provider testés.
"""
from fastapi import APIRouter
from app.services.game_state import GAME_STATE
from app.services.narrative_core import NARRATIVE
from app.services.llm_engine import generate_indice
from app.config.settings import settings

router = APIRouter(prefix="/game", tags=["game"])


@router.get("/state")
async def get_state():
    """État courant du jeu (joueurs, phase, derniers événements)."""
    return {
        "players": GAME_STATE.players,
        "state": GAME_STATE.state,
        "events": GAME_STATE.events[-100:],  # ← protection simple: derniers 100
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
