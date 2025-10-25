from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services import llm_engine
from app.services.llm_engine import LLMClient, LLMServiceError


@pytest.fixture(autouse=True)
def fake_canon_context(monkeypatch):
    """Évite d'accéder aux fichiers de données pendant les tests."""
    monkeypatch.setattr(
        llm_engine,
        "get_canon_summary",
        lambda: {
            "culprit": "Victor",
            "weapon": "Corde",
            "location": "Bibliothèque",
            "motive": "Jalousie",
            "last_clues": {},
        },
    )
    monkeypatch.setattr(llm_engine, "get_sensitive_terms", lambda: [])


@pytest.fixture
def client_stub(monkeypatch):
    stub = SimpleNamespace(chat=Mock(), generate=Mock())
    monkeypatch.setattr(llm_engine, "CLIENT", stub)
    return stub


def test_generate_indice_success(client_stub):
    client_stub.chat.return_value = {"message": {"content": "Indice: Les rideaux sont froissés."}}

    result = llm_engine.generate_indice("Fais court.", kind="ambiguous")

    assert result["text"] == "Les rideaux sont froissés."
    assert result["kind"] == "ambiguous"
    assert result["attempts"] == 1
    client_stub.chat.assert_called_once()


def test_generate_indice_retry_on_spoiler(client_stub, monkeypatch):
    monkeypatch.setattr(llm_engine, "get_sensitive_terms", lambda: ["secret"])
    client_stub.chat.side_effect = [
        {"message": {"content": "secret dévoilé."}},
        {"message": {"content": "Indice: Voix étouffée derrière la porte."}},
    ]

    result = llm_engine.generate_indice("Évite les spoilers.", kind="crucial", max_attempts=3)

    assert result["text"] == "Voix étouffée derrière la porte."
    assert result["attempts"] == 2
    assert client_stub.chat.call_count == 2


def test_generate_indice_raises_on_failure(client_stub):
    client_stub.chat.side_effect = LLMServiceError("timeout")

    with pytest.raises(LLMServiceError):
        llm_engine.generate_indice("Fais court.", kind="decor", max_attempts=1)
    assert client_stub.chat.call_count == 2  # tentative initiale + ultime


def test_run_llm_success(client_stub):
    client_stub.generate.return_value = "Un texte narratif."

    result = llm_engine.run_llm("Raconte une scène.")

    assert result == {"text": "Un texte narratif."}
    client_stub.generate.assert_called_once()


def test_run_llm_raises_on_error(client_stub):
    client_stub.generate.side_effect = LLMServiceError("service down")

    with pytest.raises(LLMServiceError):
        llm_engine.run_llm("Raconte une scène.")


@pytest.mark.parametrize(
    "endpoint,expected",
    [
        ("http://localhost:11434/api/chat", "http://localhost:11434/api/generate"),
        ("http://localhost:11434/api/chat/", "http://localhost:11434/api/generate"),
        ("http://example.com/custom/chat", "http://example.com/custom/generate"),
    ],
)
def test_resolve_generate_endpoint(endpoint, expected):
    assert LLMClient._resolve_generate_endpoint(endpoint) == expected
