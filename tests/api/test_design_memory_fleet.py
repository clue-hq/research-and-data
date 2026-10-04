"""Both design fleet entrypoints receive the same process-local memory capability."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from clue_api.design_fleet import build_design_job_handler, build_design_leg_lane_driver
from clue_fleet import FleetTaskKind
from tests.db.conftest import run_async


def test_inline_and_drain_hosts_receive_same_resolver_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lumen_api import fleet_handler

    offers: list[dict[str, Any]] = []

    class Handler:
        kind = FleetTaskKind.DESIGN_JOB

    def build(**kwargs: Any) -> Handler:
        offers.append(kwargs)
        return Handler()

    monkeypatch.setattr(fleet_handler, "build_design_job_handler", build)

    def resolver_factory(envelope: Any) -> None:
        return None

    assert (
        build_design_job_handler(enabled=True, preference_resolver_factory=resolver_factory)
        is not None
    )
    assert (
        build_design_leg_lane_driver(enabled=True, preference_resolver_factory=resolver_factory)
        is not None
    )
    assert len(offers) == 2
    for offer in offers:
        assert offer["host_provider"]().preference_resolver_factory is resolver_factory
        # Lane 3 slice 5: both entrypoints also inject the platform's whole drain, so a design
        # 402 opens a provider incident under the ARV2 close rule wherever the work is drained.
        assert offer["spend_drain"] is not None
    # The LEG lane injects its own per-turn Langfuse handler and runs inside ``design-leg.turn``,
    # so it opens no trace of its own; the drain injects none (the design side defaults to the
    # platform handler) and opens one named trace per job (2026-10-03 spec, R7).
    assert offers[0]["turn_callbacks_factory"] is None
    assert offers[1]["turn_callbacks_factory"] is not None
    assert offers[0]["named_trace"] is True
    assert offers[1]["named_trace"] is False

    assert build_design_job_handler(enabled=True) is not None
    # Preserve the installed app's legacy/default host construction: no host_provider.
    assert "host_provider" not in offers[-1]
    assert set(offers[-1]) == {"spend_drain", "turn_callbacks_factory", "named_trace"}
    assert (
        build_design_job_handler(enabled=False, preference_resolver_factory=resolver_factory)
        is None
    )
    assert len(offers) == 3


def test_preference_context_setting_is_default_off_and_loads_explicit_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from clue_config import Settings

    monkeypatch.delenv("CLUE_DESIGN_PREFERENCE_CONTEXT_ENABLED", raising=False)
    assert Settings(_env_file=None).design_preference_context_enabled is False
    monkeypatch.setenv("CLUE_DESIGN_PREFERENCE_CONTEXT_ENABLED", "true")
    assert Settings(_env_file=None).design_preference_context_enabled is True


@pytest.mark.parametrize("enabled", [None, False, True])
def test_production_handler_gates_only_design_preference_producer(
    monkeypatch: pytest.MonkeyPatch, enabled: bool | None
) -> None:
    from clue_api import agent_turn_fleet_wiring as wiring

    captured: dict[str, Any] = {}
    memory = object()

    def engine(**kwargs: Any) -> object:
        captured["platform_memory"] = kwargs["memory"]
        return object()

    def design(**kwargs: Any) -> object:
        captured["design_memory"] = kwargs["memory"]
        return object()

    monkeypatch.setattr(wiring, "build_conversation_turn_engine", engine)
    monkeypatch.setattr(wiring, "DesignLegTurnRunner", design)
    wiring.build_agent_turn_work_handler(
        components=SimpleNamespace(profiles=None, artifacts=None, turns=None, history=None),
        tools=None,
        tool_invoker=None,
        executor=None,
        compatibility=None,
        recipes=None,
        starter=None,
        parameters=None,
        memory=memory,
        queue=None,
        **({"design_preference_context_enabled": enabled} if enabled is not None else {}),
    )
    assert captured["platform_memory"] is memory
    assert captured["design_memory"] is (memory if enabled else None)


@pytest.mark.parametrize(
    "runtime,preferences", [(False, False), (False, True), (True, False), (True, True)]
)
def test_configured_resolver_requires_both_runtime_and_preference_context_switches(
    monkeypatch: pytest.MonkeyPatch, runtime: bool, preferences: bool
) -> None:
    from clue_api import design_memory_runtime
    from clue_config import Settings

    composed: list[Any] = []
    memory = object()
    sentinel = object()

    def compose(**kwargs: Any) -> object:
        composed.append(kwargs["memory"])
        asyncio.get_running_loop()  # It still composes on the pool-owning platform loop.
        return sentinel

    monkeypatch.setattr(design_memory_runtime, "build_design_preference_resolver_factory", compose)

    async def scenario() -> None:
        factory = design_memory_runtime.build_configured_design_preference_resolver_factory(
            settings=Settings(
                _env_file=None,
                design_runtime_enabled=runtime,
                design_preference_context_enabled=preferences,
            ),
            memory=memory,
        )
        assert factory is (sentinel if runtime and preferences else None)
        assert composed == ([memory] if runtime and preferences else [])

    run_async(scenario())
