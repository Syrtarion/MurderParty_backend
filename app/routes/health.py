"""
Module routes/health.py
Rôle:
- Endpoints de santé (service OK + ping LLM).

Intégrations:
- settings: nom d’app + paramètres LLM.
- generate_indice: ping rapide du provider / modèle (latence, échantillon).
"""
from fastapi import APIRouter
import time

from app.config.settings import settings
from app.services.llm_engine import generate_indice

router = APIRouter(prefix="/health", tags=["health"])

@router.get("")
async def health():
    """Renvoie un OK minimal avec le nom de service configuré."""
    return {"ok": True, "service": settings.APP_NAME}

@router.get("/llm")
async def health_llm():
    """
    Vérifie la disponibilité du LLM en mesurant une latence simple.
    - Prompt court ("Réponds: pong.") pour minimiser le temps de calcul.
    - Retourne provider, modèle, latence en secondes et un aperçu (sample).
    """
    t0 = time.perf_counter()
    try:
        r = generate_indice("Réponds: pong.", kind="decor")
        dt = time.perf_counter() - t0
        return {
            "ok": True,
            "provider": settings.LLM_PROVIDER,
            "model": settings.LLM_MODEL,
            "latency_s": round(dt, 3),
            "sample": r.get("text", "")[:120]  # ← coupe l’aperçu
        }
    except Exception as e:
        dt = time.perf_counter() - t0
        return {
            "ok": False,
            "provider": settings.LLM_PROVIDER,
            "model": settings.LLM_MODEL,
            "latency_s": round(dt, 3),
            "error": str(e)
        }
