from fastapi import APIRouter, Header, HTTPException
from fastapi import Depends
from app.deps.auth import mj_required
from pydantic import BaseModel, Field
from app.config.settings import settings
from app.services.narrative_core import NARRATIVE
from app.services.game_state import GAME_STATE
from app.services.llm_engine import generate_indice
from app.services.ws_manager import WS

router = APIRouter(prefix="/master", tags=["master"], dependencies=[Depends(mj_required)])


def _require_bearer(auth: str | None):
    if not auth or not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = auth.split(" ", 1)[1]
    if token != settings.MJ_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")


class CulpritPayload(BaseModel):
    culprit: str
    weapon: str
    location: str
    motive: str


@router.post("/choose_culprit")
async def choose_culprit(payload: CulpritPayload):
    canon = NARRATIVE.choose_culprit(payload.culprit, payload.weapon, payload.location, payload.motive)
    GAME_STATE.log_event("canon_locked", {k: canon.get(k) for k in ("culprit", "weapon", "location", "motive")})
    await manager.broadcast({"type": "canon_locked", "payload": canon})
    return canon


class IndicePayload(BaseModel):
    prompt: str = Field(..., description="Consigne spécifique pour l'indice")
    kind: str = Field("ambiguous", description="crucial | red_herrings | ambiguous | decor")


@router.post("/generate_indice")
async def generate_indice_route(payload: IndicePayload):
    user_prompt = "Donne uniquement l'indice, sans préambule. Limite à 1–2 phrases. " + payload.prompt
    result = generate_indice(user_prompt, payload.kind)
    NARRATIVE.append_clue(payload.kind, {"text": result.get("text", ""), "kind": payload.kind})
    GAME_STATE.log_event("clue_generated", {"kind": payload.kind, "text": result.get("text", "")})
    await manager.broadcast({"type": "clue_generated", "payload": result})
    return result
