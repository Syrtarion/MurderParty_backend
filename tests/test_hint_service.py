from __future__ import annotations

import pytest

from app.services.session_store import create_session_state, drop_session_state
from app.services.hint_service import deliver_hint, destroy_hint


SESSION_ID = "test_hint_policy"


def setup_session():
    state = create_session_state(SESSION_ID)
    state.players = {
        "p1": {"player_id": "p1"},
        "p2": {"player_id": "p2"},
    }
    state.state.setdefault("session", {}).setdefault("prepared_rounds", {})["1"] = {
        "llm_assets": {
            "hints": {
                "hints": {
                    "major": "Indice majeur",
                    "minor": "Indice secondaire",
                    "vague": "Indice vague",
                    "misleading": "Indice trompeur",
                }
            }
        }
    }
    state.save()
    return state


def teardown_session():
    drop_session_state(SESSION_ID)


@pytest.fixture
def session_state():
    state = setup_session()
    try:
        yield state
    finally:
        teardown_session()


def test_deliver_hint_shared(session_state):
    entry = deliver_hint(session_state, round_index=1, discoverer_id="p1", tier="major", share=True)

    assert entry["shared"] is True
    tiers = {d["player_id"]: d["tier"] for d in entry["deliveries"]}
    assert tiers == {"p1": "major", "p2": "major"}
    assert session_state.state["hints_history"]


def test_deliver_hint_not_shared_degrades(session_state):
    entry = deliver_hint(session_state, round_index=1, discoverer_id="p1", tier="major", share=False)

    assert entry["shared"] is False
    tiers = {d["player_id"]: d["tier"] for d in entry["deliveries"]}
    # sharing rules in story_seed.json map major -> vague for others
    assert tiers["p1"] == "major"
    assert tiers["p2"] == "vague"


def test_destroy_hint_updates_quota(session_state):
    entry = deliver_hint(session_state, round_index=1, discoverer_id="p1", tier="major", share=True)
    session_state.state.setdefault("canon", {})["culprit_player_id"] = "p1"

    destroyed = destroy_hint(session_state, entry["hint_id"], killer_id="p1")
    assert destroyed["destroyed"] is True
    assert session_state.state["killer_actions"]["destroy_used"] == 1


def test_destroy_hint_rejects_non_killer(session_state):
    entry = deliver_hint(session_state, round_index=1, discoverer_id="p1", tier="major", share=True)
    session_state.state.setdefault("canon", {})["culprit_player_id"] = "p1"

    with pytest.raises(ValueError):
        destroy_hint(session_state, entry["hint_id"], killer_id="p2")
