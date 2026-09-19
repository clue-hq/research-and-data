"""Lane 3 slice 3a, Task 6: the turn runner appends the Langfuse handler to the callback tuple
(and only then), names the trace, and leaves the tuple untouched when Langfuse is off."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from langchain_core.callbacks import AsyncCallbackHandler

from clue_agents.contracts import AgentRole, ArtifactRef
from clue_agents.execution import AgentExecutionStatus, AgentTurnOutcome
from clue_api.agent_runtime_wiring import (
    DurableAgentModelCallHandler,
    DurableDeepAgentTurnRunner,
    TurnWorkGuard,
)
from clue_api.langfuse_callbacks import ClueLangfuseHandler
from clue_core import ExecutionId
from tests._langfuse import finished_spans, langfuse_installed
from tests.db.conftest import run_async


class _Runtime:
    def __init__(self) -> None:
        self.callbacks: tuple[Any, ...] = ()
        self.trace_attrs: dict[str, Any] = {}

    async def run(self, *, request: Any, callbacks: Any, **kwargs: Any) -> AgentTurnOutcome:
        del kwargs
        self.callbacks = tuple(callbacks)
        # Any span opened during the run carries the propagated trace attributes.
        from clue_obs.langfuse import observation

        with observation("probe", as_type="span"):
            pass
        return AgentTurnOutcome(
            turn_id=request.turn_id,
            execution_id=request.constitution.execution_id,
            status=AgentExecutionStatus.COMPLETED,
            # A completed outcome must carry its finalization (the contract's own validator), so
            # the fake runtime hands back a well-formed one; the runner's failure branch is
            # covered elsewhere.
            finalization_ref=ArtifactRef(
                workspace_id=request.constitution.workspace_id,
                artifact_key="ws-1/final",
                sha256="0" * 64,
                media_type="application/json",
                byte_count=2,
            ),
        )


class _Turns:
    async def mark_running(self, **kwargs: Any) -> None:
        del kwargs

    async def next_model_call_sequence(self, *, turn_id: Any) -> int:
        del turn_id
        return 1

    async def mark_unfinalized(self, **kwargs: Any) -> None:
        del kwargs


def _request() -> Any:
    return SimpleNamespace(
        turn_id=uuid4(),
        thread_id="thread-1",
        constitution=SimpleNamespace(
            workspace_id="ws-1",
            project_id="project-1",
            execution_id=ExecutionId(uuid4()),
            role=AgentRole.HEAD_OF_ABM,
            profile_ref=SimpleNamespace(name="head-of-abm", version="v1"),
            actor_id="user-1",
        ),
    )


def _run(runtime: _Runtime, *, before_work: Any = None) -> None:
    runner = DurableDeepAgentTurnRunner(
        runtime=runtime,  # type: ignore[arg-type]
        turns=_Turns(),  # type: ignore[arg-type]
        artifacts=SimpleNamespace(),  # type: ignore[arg-type]
        before_work=before_work,
    )
    run_async(
        runner.run(
            request=_request(),
            resolved_profile=SimpleNamespace(  # type: ignore[arg-type]
                profile=SimpleNamespace(model=SimpleNamespace(model_id="m"))
            ),
            context=SimpleNamespace(),  # type: ignore[arg-type]
            lease=SimpleNamespace(backend=None),  # type: ignore[arg-type]
            tools=(),
        )
    )


def test_langfuse_off_leaves_the_callback_tuple_as_it_was() -> None:
    runtime = _Runtime()

    async def guard() -> None:
        return None

    _run(runtime, before_work=guard)
    kinds = [type(cb) for cb in runtime.callbacks]
    assert kinds == [TurnWorkGuard, DurableAgentModelCallHandler]
    assert all(isinstance(cb, AsyncCallbackHandler) for cb in runtime.callbacks)


def test_langfuse_on_appends_the_handler_and_names_the_trace() -> None:
    with langfuse_installed() as (exporter, _provider):
        runtime = _Runtime()
        _run(runtime)
        spans = finished_spans(exporter)
    kinds = [type(cb) for cb in runtime.callbacks]
    assert kinds == [DurableAgentModelCallHandler, ClueLangfuseHandler]
    probe = next(s for s in spans if s.name == "probe")
    attrs = dict(probe.attributes or {})
    assert attrs["langfuse.trace.name"] == "head-of-abm.turn"
    assert attrs["session.id"] == "thread-1"
    assert attrs["user.id"] == "ws-1"
    assert attrs["langfuse.trace.metadata.project_id"] == "project-1"
    assert attrs["langfuse.trace.tags"] == ("head_of_abm",)


def test_a_stopped_turn_records_a_work_guard_guardrail() -> None:
    import asyncio

    async def stop() -> None:
        raise asyncio.CancelledError("chat turn stopped before admitting more work")

    with langfuse_installed() as (exporter, _provider):
        guard = TurnWorkGuard(stop)
        try:
            run_async(guard.on_chat_model_start())
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("the guard must re-raise")
        spans = finished_spans(exporter)
    attrs = dict(spans[0].attributes or {})
    assert spans[0].name == "turn.work_guard"
    assert attrs["langfuse.observation.type"] == "guardrail"
    assert "CancelledError" in attrs["langfuse.observation.status_message"]
