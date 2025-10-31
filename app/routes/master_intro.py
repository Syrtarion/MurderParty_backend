"""
Generate public introduction (and canon if missing) for a specific session.
"""
from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps.auth import mj_required
from app.services.narrative_engine import generate_canon_and_intro
from app.services.session_store import DEFAULT_SESSION_ID, get_session_state


router = APIRouter(prefix="/master", tags=["master"], dependencies=[Depends(mj_required)])


def _normalize_session_id(session_id: str | None) -> str:
    sid = (session_id or DEFAULT_SESSION_ID).strip()
    return sid or DEFAULT_SESSION_ID


@router.post("/intro")
async def generate_intro(
    use_llm: bool = True,
    session_id: str | None = Query(default=None),
):
    """
    Trigger canon + intro generation for the target session.
    """
    sid = _normalize_session_id(session_id)
    state = get_session_state(sid)
    try:
        data = generate_canon_and_intro(use_llm=use_llm)
        state.log_event(
            "intro_generated",
            {"location": data.get("location"), "culprit_hint": "hidden"},
        )
        state.state["canon"] = data
        state.save()
        return {
            "ok": True,
            "intro_text": data.get("intro_narrative", ""),
            "public_path": "/public/intro",
            "canon_file": "canon_narratif.json",
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la génération de l'intro: {exc}") from exc
