"""
Admin reset routes.

Provide a MJ-only endpoint to reset either every runtime asset or a single
session. Configuration files are preserved. Resetting a specific session only
removes its dedicated storage under ``app/data/sessions/<session_id>/`` and
clears cached orchestrators.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps.auth import mj_required
from app.services.game_state import DEFAULT_SESSION_ID, GAME_STATE, SESSIONS_DIR
from app.services.narrative_core import NARRATIVE
from app.services.session_plan import SESSION_PLAN
from app.services.session_store import (
    drop_session_engine,
    drop_session_state,
    list_all_session_ids,
)


router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(mj_required)],
)

DATA_DIR = Path("app/data")

# Default payload written into runtime files when performing a full reset.
RESET_FILES = {
    "game_state.json": {
        "state": {"phase": 0, "started": False, "campaign_id": None, "last_awards": {}},
        "players": {},
        "events": [],
    },
    "players.json": {},
    "events.json": [],
    "minigame_sessions.json": {},
    "trial_state.json": {},
    "characters_assigned.json": {},
    "canon_narratif.json": {},
}


def _remove_session_from_disk(session_id: str) -> None:
    target_dir = SESSIONS_DIR / session_id
    if target_dir.exists():
        shutil.rmtree(target_dir, ignore_errors=True)


@router.post("/reset_game")
async def reset_game(
    session_id: Optional[str] = Query(
        default=None, description="Identifiant de session � nettoyer"
    ),
):
    """
    Reset runtime data.

    * Without ``session_id``: wipe every runtime file, all session directories,
      cached orchestrators, and in-memory canon.
    * With ``session_id``: only clear the requested session (cache + files).
      Useful for the MJ dashboard reset button.
    """
    if session_id:
        sid = session_id.strip()
        if not sid:
            raise HTTPException(status_code=400, detail="Invalid session_id")

        drop_session_engine(sid)
        drop_session_state(sid)
        _remove_session_from_disk(sid)
        SESSION_PLAN.drop(sid)

        if sid == DEFAULT_SESSION_ID:
            GAME_STATE.reset()
            GAME_STATE.session_id = DEFAULT_SESSION_ID
            GAME_STATE.save()

        return {"ok": True, "session_reset": sid}

    # Full reset across every session.
    for fname, default_content in RESET_FILES.items():
        fpath = DATA_DIR / fname
        try:
            with open(fpath, "w", encoding="utf-8") as handle:
                json.dump(default_content, handle, ensure_ascii=False, indent=2)
        except Exception:
            # Keep best-effort behaviour to avoid blocking on transient IO errors.
            continue

    for sid in list_all_session_ids():
        drop_session_engine(sid)
        drop_session_state(sid)

    if SESSIONS_DIR.exists():
        shutil.rmtree(SESSIONS_DIR, ignore_errors=True)

    SESSION_PLAN.plans.clear()
    SESSION_PLAN.cursors.clear()
    SESSION_PLAN.save()

    GAME_STATE.reset()
    GAME_STATE.session_id = DEFAULT_SESSION_ID
    GAME_STATE.save()
    NARRATIVE.canon = {}

    return {
        "ok": True,
        "message": "Runtime reset complet effectu� (configuration conserv�e).",
    }
