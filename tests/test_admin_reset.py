import pytest

pytest.importorskip("httpx", reason="httpx requis pour les tests client FastAPI")

from fastapi.testclient import TestClient

from app.main import app
from app.config.settings import settings
from app.services.game_state import SESSIONS_DIR
from app.services.session_plan import SESSION_PLAN


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.MJ_TOKEN}"}


def test_reset_specific_session_removes_directory(tmp_path, monkeypatch):
    client = TestClient(app)

    # Cree une nouvelle session MJ.
    response = client.post("/session", headers=_auth_headers())
    assert response.status_code == 200
    data = response.json()
    session_id = data["session_id"]
    assert session_id

    session_path = SESSIONS_DIR / session_id
    assert session_path.exists()

    # Reset cible.
    reset = client.post(f"/admin/reset_game?session_id={session_id}", headers=_auth_headers())
    assert reset.status_code == 200
    payload = reset.json()
    assert payload["ok"] is True
    assert payload["session_reset"] == session_id

    assert not session_path.exists()
    assert session_id not in SESSION_PLAN.plans
    assert session_id not in SESSION_PLAN.cursors
