"""
Master route: generate the narrative canon (weapon/location/motive + culprit).
Updated to support multi-session by accepting a session identifier.
"""
from __future__ import annotations

import json
import random
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.deps.auth import mj_required
from app.services.llm_engine import run_llm
from app.services.narrative_core import NARRATIVE
from app.services.session_store import DEFAULT_SESSION_ID, get_session_state
from app.services.game_state import register_event
from app.services.story_seed import StorySeedError, load_story_seed_for_state


router = APIRouter(prefix="/master", tags=["master"], dependencies=[Depends(mj_required)])


class CanonRequest(BaseModel):
    style: Optional[str] = None


def _normalize_session_id(session_id: Optional[str]) -> str:
    sid = (session_id or DEFAULT_SESSION_ID).strip()
    return sid or DEFAULT_SESSION_ID


@router.post("/generate_canon")
async def generate_canon(
    payload: CanonRequest,
    session_id: Optional[str] = Query(default=None, description="Identifiant de session MurderParty"),
):
    """
    Generate the canon with the LLM (weapon/location/motive) and lock a culprit.
    Persist the result both in NarrativeCore and the targeted GameState.
    """
    sid = _normalize_session_id(session_id)
    state = get_session_state(sid)

    try:
        seed = load_story_seed_for_state(state)
    except StorySeedError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    prompt = f"""
Tu es le moteur narratif d'une Murder Party.

Contexte :
Cadre : {seed.get("setting", "Un manoir mysterieux.")}
Situation : {seed.get("context", "Un diner qui tourne mal.")}
Victime : {seed.get("victim", "Une notable locale.")}
Ton : {payload.style or seed.get("tone", "Dramatique, realiste")}.

Genere STRICTEMENT ce JSON :
{{
  "weapon": "<arme du crime>",
  "location": "<lieu du crime>",
  "motive": "<mobile du crime>"
}}
""".strip()

    result = run_llm(prompt)
    text = result.get("text", "").strip()

    try:
        canon = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            canon = json.loads(text[start : end + 1])
        else:
            raise HTTPException(status_code=500, detail="LLM returned invalid JSON")

    if not state.players:
        raise HTTPException(status_code=400, detail="Aucun joueur inscrit pour designer un coupable.")

    culprit_id, culprit_data = random.choice(list(state.players.items()))
    culprit_name = (
        culprit_data.get("character")
        or culprit_data.get("display_name")
        or culprit_id
    )

    canon["culprit_player_id"] = culprit_id
    canon["culprit_name"] = culprit_name
    canon["locked"] = True

    NARRATIVE.canon = canon
    NARRATIVE.save()

    state.state["canon"] = canon
    state.save()

    register_event(
        "canon_generated",
        {"weapon": canon.get("weapon"), "location": canon.get("location"), "motive": canon.get("motive")},
        game_state=state,
    )
    state.log_event(
        "canon_locked",
        {
            "weapon": canon["weapon"],
            "location": canon["location"],
            "motive": canon["motive"],
            "culprit_player_id": culprit_id,
        },
    )

    return {"ok": True, "canon": canon}
