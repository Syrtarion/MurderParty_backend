from fastapi import APIRouter
import time

from app.config.settings import settings
from app.services.llm_engine import generate_indice

router = APIRouter(prefix="/health", tags=["health"])

@router.get("")
async def health():
    return {"ok": True, "service": settings.APP_NAME}

@router.get("/llm")
async def health_llm():
    t0 = time.perf_counter()
    try:
        r = generate_indice("Réponds: pong.", kind="decor")
        dt = time.perf_counter() - t0
        return {
            "ok": True,
            "provider": settings.LLM_PROVIDER,
            "model": settings.LLM_MODEL,
            "latency_s": round(dt, 3),
            "sample": r.get("text", "")[:120]
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
