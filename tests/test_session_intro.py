from app.services.game_state import GameState
from app.services.session_intro import prepare_session_intro


def test_prepare_session_intro_persists_state():
    state = GameState(session_id="test-intro")
    intro = prepare_session_intro(state, use_llm=False)
    assert intro["status"] == "ready"
    assert intro.get("text")
    session_snapshot = state.state.get("session", {})
    stored = session_snapshot.get("intro")
    assert stored
    assert stored["status"] == "ready"
