from fastapi.testclient import TestClient

from app.main import app
from app.services.session_store import get_session_state

AUTH_HEADERS = {"Authorization": "Bearer changeme-super-secret"}
client = TestClient(app)


def _bootstrap_players(session_id: str) -> None:
    state = get_session_state(session_id)
    state.players = {
        "p1": {"player_id": "p1", "display_name": "Alice"},
        "p2": {"player_id": "p2", "display_name": "Bob"},
        "p3": {"player_id": "p3", "display_name": "Charlie"},
        "p4": {"player_id": "p4", "display_name": "Dana"},
    }
    state.save()


def test_session_round_flow_endpoints():
    # Création session
    response = client.post("/session", json={}, headers=AUTH_HEADERS)
    assert response.status_code == 200
    payload = response.json()
    session_id = payload["session_id"]

    # Snapshot brut
    state_resp = client.get(f"/session/{session_id}/state", headers=AUTH_HEADERS)
    assert state_resp.status_code == 200
    snapshot = state_resp.json()
    assert snapshot["session_id"] == session_id
    assert snapshot["events_count"] >= 0

    # Prépare des joueurs pour les tests d'équipes et de rounds
    _bootstrap_players(session_id)

    # Tirage équipes
    teams_resp = client.post(
        f"/session/{session_id}/teams/draw",
        json={"team_prefix": "E"},
        headers=AUTH_HEADERS,
    )
    assert teams_resp.status_code == 200
    teams_payload = teams_resp.json()
    assert set(teams_payload["teams"].keys()) == {"E1", "E2"}

    # Préparer round 1 (LLM désactivé pour rapidité)
    prep_resp = client.post(
        f"/session/{session_id}/round/1/prepare",
        params={"use_llm": False},
        headers=AUTH_HEADERS,
    )
    assert prep_resp.status_code == 200
    assert prep_resp.json()["round_index"] == 1

    # Lancer l'intro du round 1
    start_intro = client.post(
        f"/session/{session_id}/round/1/start",
        json={"action": "intro", "auto_prepare_round": False},
        headers=AUTH_HEADERS,
    )
    assert start_intro.status_code == 200
    assert start_intro.json()["phase"] == "INTRO"

    # Confirmer le démarrage physique
    start_confirm = client.post(
        f"/session/{session_id}/round/1/start",
        json={"action": "confirm"},
        headers=AUTH_HEADERS,
    )
    assert start_confirm.status_code == 200
    assert start_confirm.json()["phase"] == "ACTIVE"

    # Clôturer la manche
    end_resp = client.post(
        f"/session/{session_id}/round/1/end",
        json={"winners": ["p1"], "meta": {"score": 10}},
        headers=AUTH_HEADERS,
    )
    assert end_resp.status_code == 200
    end_payload = end_resp.json()
    assert end_payload["result"]["ok"] is True

    # Soumission finale
    submit_resp = client.post(
        f"/session/{session_id}/submit",
        json={"scores": {"p1": 10, "p2": 5}, "finalize": True},
        headers=AUTH_HEADERS,
    )
    assert submit_resp.status_code == 200
    assert submit_resp.json()["finalize"] is True


def test_session_websocket_stream():
    response = client.post("/session", json={}, headers=AUTH_HEADERS)
    session_id = response.json()["session_id"]

    with client.websocket_connect(f"/ws/session/{session_id}") as ws:
        first = ws.receive_json()
        assert first["type"] == "session_state"
        phase_tick = ws.receive_json()
        assert phase_tick["type"] in {"phase", "timer_tick"}
