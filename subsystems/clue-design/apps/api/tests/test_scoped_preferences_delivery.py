"""Scene execution passes authorized advice as a capability, never a saved prompt."""

from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from lumen_api import main
from lumen_api.fleet_handler import DesignTurnHost

from clue_design.envelopes import DesignTurnEnvelope


def envelope(*, memory=True):
    config = {"request": {"prompt": "Make an ad", "scene": {}}}
    if memory:
        config["design_memory"] = {"version": 1}
    run_id = f"run_{uuid4().hex}"
    return DesignTurnEnvelope(
        kind="agent_turn",
        run_id=run_id,
        checkpoint_thread_id=run_id,
        work_id=uuid4(),
        workspace_id="ws_preference_delivery",
        config=config,
    )


def test_frozen_preference_context_requires_host_authority_before_runtime(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("runtime must not run without scoped preference authority")

    monkeypatch.setattr(main, "run_agent_turn_preview", forbidden)
    status, response, _, _ = main.execute_agent_turn_job(
        envelope(),
        store=SimpleNamespace(),
        host=DesignTurnHost(),
        event_sink=None,
    )
    assert status == "failed"
    assert "scoped_preferences" in str(response)


@pytest.mark.parametrize("selection_enabled", [True, False])
def test_host_capability_reaches_runtime_without_adding_preference_bodies_to_prompt(
    monkeypatch,
    selection_enabled,
):
    request = envelope()
    seen = []

    def preferences():
        pytest.fail("API must not resolve bodies outside the model boundary")

    def prepare(received):
        assert received == request
        return preferences if selection_enabled else None

    def preview(payload, root, **kwargs):
        assert payload.prompt == "Make an ad"
        assert payload.model_dump().get("scoped_preferences") is None
        assert kwargs.get("scoped_preferences") is (preferences if selection_enabled else None)
        seen.append(True)
        return {"status": "proposed", "operations": []}

    monkeypatch.setattr(main, "run_agent_turn_preview", preview)
    host = replace(DesignTurnHost(), preference_resolver_factory=prepare)
    status, _, _, _ = main.execute_agent_turn_job(
        request,
        store=SimpleNamespace(),
        host=host,
        event_sink=None,
    )
    assert status == "succeeded" and seen == [True]


def test_legacy_turn_does_not_invoke_preference_factory(monkeypatch):
    def forbidden(*args):
        pytest.fail("legacy turns have no memory step")

    def preview(payload, root, **kwargs):
        assert "scoped_preferences" not in kwargs
        return {"status": "proposed", "operations": []}

    monkeypatch.setattr(main, "run_agent_turn_preview", preview)
    host = replace(DesignTurnHost(), preference_resolver_factory=forbidden)
    assert (
        main.execute_agent_turn_job(
            envelope(memory=False),
            store=SimpleNamespace(),
            host=host,
            event_sink=None,
        )[0]
        == "succeeded"
    )


def test_rejected_host_scope_does_not_leak_failure_details_or_call_runtime(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("runtime must not run after failed authorization")

    def prepare(request):
        raise ValueError("PRIVATE_SENTINEL must not be saved in a failure response")

    monkeypatch.setattr(main, "run_agent_turn_preview", forbidden)
    host = replace(DesignTurnHost(), preference_resolver_factory=prepare)
    status, response, _, _ = main.execute_agent_turn_job(
        envelope(),
        store=SimpleNamespace(),
        host=host,
        event_sink=None,
    )
    assert status == "failed"
    assert "PRIVATE_SENTINEL" not in str(response)


def test_preference_enabled_override_is_refused_even_if_it_accepts_the_capability():
    calls = []

    def override(payload, root, **kwargs):
        calls.append("unguarded override entered")
        return {"status": "proposed", "operations": []}

    host = replace(
        DesignTurnHost(),
        agent_turn_runner=override,
        preference_resolver_factory=lambda _: lambda: None,
    )
    status, response, _, _ = main.execute_agent_turn_job(
        envelope(),
        store=SimpleNamespace(),
        host=host,
        event_sink=None,
    )
    assert calls == []
    assert status == "failed"
    assert "scoped_preferences.override_unsupported" in str(response)
