"""Lane 3 slice 3b, Task 3: every governed invocation is a tool/retriever observation carrying
the platform's disposition — completed, replayed, blocked, failed."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any
from uuid import uuid4

import pytest

from clue_core import ExecutionAttemptId, ExecutionNodeId, new_execution_id, new_operation_id
from clue_toolbelt import (
    PreconditionFailed,
    PreconditionFailure,
    ToolContext,
    ToolRegistry,
    ToolResult,
)
from clue_toolbelt.invoker import (
    JournalDisposition,
    JournalStart,
    ParameterSnapshot,
    ToolInvoker,
)
from tests._langfuse import finished_spans, langfuse_installed
from tests.db.conftest import run_async
from tests.toolbelt.conftest import EchoTool, InMemoryStore


class _Snapshotter:
    async def snapshot(self, *, descriptor: Any, inputs: Any, context: Any) -> ParameterSnapshot:
        del descriptor, inputs, context
        return _snapshot()


def _snapshot() -> ParameterSnapshot:
    return ParameterSnapshot(
        artifact_key="ws-1/snapshot", content_sha256="0" * 64, display_params={}
    )


class _Journal:
    def __init__(self, *, replay: ToolResult | None = None, blocked: Sequence[str] = ()) -> None:
        self._replay = replay
        self._blocked = tuple(blocked)
        self.events: list[str] = []

    async def begin(self, *, descriptor: Any, context: Any, snapshot: Any) -> JournalStart:
        del descriptor, context, snapshot
        if self._replay is not None:
            return JournalStart(
                execution_id=new_execution_id(),
                node_id=ExecutionNodeId(uuid4()),
                attempt_id=None,
                disposition=JournalDisposition.COMPLETED,
                result=self._replay,
            )
        if self._blocked:
            return JournalStart(
                execution_id=new_execution_id(),
                node_id=ExecutionNodeId(uuid4()),
                attempt_id=None,
                disposition=JournalDisposition.BLOCKED,
                blocked_reason_codes=self._blocked,
            )
        return JournalStart(
            execution_id=new_execution_id(),
            node_id=ExecutionNodeId(uuid4()),
            attempt_id=ExecutionAttemptId(uuid4()),
            disposition=JournalDisposition.STARTED,
        )

    async def steering_snapshot(self, **kwargs: Any) -> None:
        del kwargs

    async def blocked(self, **kwargs: Any) -> None:
        self.events.append("blocked")

    async def awaiting_input(self, **kwargs: Any) -> None:
        self.events.append("awaiting_input")

    async def failed(self, **kwargs: Any) -> None:
        self.events.append("failed")

    async def completed(self, *, start: Any, context: Any, result: ToolResult) -> ToolResult:
        del start, context
        self.events.append("completed")
        return result


class _NullConnFactory:
    def __call__(self) -> Any:
        raise AssertionError("no connection is opened in these tests")


def _invoker(tool: EchoTool, journal: _Journal) -> ToolInvoker:
    registry = ToolRegistry()
    registry.register(tool, make_default=True)
    return ToolInvoker(
        registry=registry,
        snapshotter=_Snapshotter(),
        journal=journal,
        idempotency_store=InMemoryStore(),
        idempotency_ttl_s=60.0,
    )


def _ctx() -> ToolContext:
    return ToolContext(
        workspace_id="ws-1",
        actor="agent",
        conn_factory=_NullConnFactory(),  # type: ignore[arg-type]
        operation_id=new_operation_id(),
    )


def _attrs(span: Any) -> dict[str, Any]:
    return dict(span.attributes or {})


def _governed(spans: Any) -> dict[str, Any]:
    return _attrs(next(s for s in spans if s.name == "governed.echo@1"))


def test_off_the_invoker_behaves_as_before() -> None:
    journal = _Journal()
    result = run_async(_invoker(EchoTool(), journal).invoke("echo", {"value": 7}, _ctx()))
    assert result.references == {"echoed": 7} and journal.events == ["completed"]


def test_a_completed_invocation_is_a_tool_observation_with_its_references() -> None:
    with langfuse_installed() as (exporter, _provider):
        run_async(_invoker(EchoTool(), _Journal()).invoke("echo", {"value": 7}, _ctx()))
        attrs = _governed(finished_spans(exporter))
    assert attrs["langfuse.observation.type"] == "tool"  # EchoTool's effect class is not READ
    assert attrs["langfuse.observation.metadata.disposition"] == "completed"
    assert json.loads(attrs["langfuse.observation.input"])["inputs"] == {"value": 7, "note": None}
    assert json.loads(attrs["langfuse.observation.output"])["references"] == {"echoed": 7}
    assert attrs["langfuse.observation.metadata.effect_class"] == "write"


def test_a_replay_is_marked_replayed() -> None:
    replay = ToolResult(tool="echo", version="1", references={"echoed": 1})
    with langfuse_installed() as (exporter, _provider):
        result = run_async(
            _invoker(EchoTool(), _Journal(replay=replay)).invoke("echo", {"value": 1}, _ctx())
        )
        attrs = _governed(finished_spans(exporter))
    assert result.replayed is True
    assert attrs["langfuse.observation.metadata.disposition"] == "replayed"


def test_a_durable_block_is_a_warning_naming_the_reason_codes() -> None:
    with langfuse_installed() as (exporter, _provider):
        with pytest.raises(PreconditionFailed):
            run_async(
                _invoker(EchoTool(), _Journal(blocked=("approval_required",))).invoke(
                    "echo", {"value": 1}, _ctx()
                )
            )
        attrs = _governed(finished_spans(exporter))
    assert attrs["langfuse.observation.level"] == "WARNING"
    assert attrs["langfuse.observation.status_message"] == "approval_required"
    assert attrs["langfuse.observation.metadata.disposition"] == "blocked"


def test_a_precondition_refusal_inside_the_tool_is_a_warning() -> None:
    tool = EchoTool(fail=[PreconditionFailure(reason_code="no_active_icp", message="nope")])
    with langfuse_installed() as (exporter, _provider):
        with pytest.raises(PreconditionFailed):
            run_async(_invoker(tool, _Journal()).invoke("echo", {"value": 1}, _ctx()))
        attrs = _governed(finished_spans(exporter))
    assert attrs["langfuse.observation.level"] == "WARNING"
    assert attrs["langfuse.observation.status_message"] == "no_active_icp"


def test_a_failure_is_an_error_with_the_stable_code() -> None:
    with langfuse_installed() as (exporter, _provider):
        with pytest.raises(RuntimeError):
            run_async(
                _invoker(EchoTool(raise_on_invoke=True), _Journal()).invoke(
                    "echo", {"value": 1}, _ctx()
                )
            )
        attrs = _governed(finished_spans(exporter))
    assert attrs["langfuse.observation.level"] == "ERROR"
    assert attrs["langfuse.observation.status_message"] == "runtime_error"
    assert attrs["langfuse.observation.metadata.disposition"] == "failed"
