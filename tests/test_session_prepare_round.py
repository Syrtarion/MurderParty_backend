import asyncio

from app.routes.session import session_prepare_round
from app.services.session_engine import SessionEngine
from app.services.session_store import create_session_state, drop_session_state, get_session_state


def test_prepare_round_assets_without_llm():
    session_id = "testprep"
    state = create_session_state(session_id)
    try:
        response = asyncio.run(session_prepare_round(session_id=session_id, round_number=1, use_llm=False))
        assert response.ok is True
        prepared = response.prepared
        assert prepared["round_index"] == 1
        assert prepared["narration"]["intro_text"]
        assert prepared["narration"]["outro_text"]

        stored = get_session_state(session_id).state["session"]["prepared_rounds"][str(1)]
        assert stored["round_index"] == 1
        assert stored["narration"]["intro_text"] == prepared["narration"]["intro_text"]

        engine = SessionEngine(game_state=state)
        status = engine.status()
        assert status["prepared_round"] is None

        state.state["session"]["round_index"] = 1
        updated_status = engine.status()
        assert updated_status["prepared_round"]["round_index"] == 1
    finally:
        drop_session_state(session_id)
