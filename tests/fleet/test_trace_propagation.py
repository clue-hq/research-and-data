"""Lane 3 slice 2, Task 4 (offline): the worker runs every handler inside the task's trace and
run context. Uses the fakes the worker's own tests use.

Since 2026-10-03 (agent-scoped tracing spec, R3) a task is its OWN trace: the ``fleet.task`` span
is a new root that links to the span that enqueued it, and the enqueuer's trace id is bound as
``launched_by_trace_id``. One chat turn that launches research is one turn trace plus one trace
per job, not one tree holding every agent."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import structlog
from opentelemetry import trace
from pydantic import JsonValue
from tests.fleet.test_work_worker import _Leases, _Queue

from clue_fleet import (
    FleetTaskKind,
    FleetTaskStatus,
    LeasedWorkWorker,
    WorkContext,
    WorkId,
    WorkResult,
    WorkTaskRow,
    work_worker,
)
from clue_fleet.work_worker import PAYLOAD_CONTEXT_KEYS
from clue_obs.otel import (
    CARRIER_KEYS,
    carrier_from_current_span,
    collect_spans,
    traced_step,
)
from clue_obs.otel.trace_ids import remembered_trace


class _Seeing:
    kind = FleetTaskKind.AGENT_TURN

    def __init__(self) -> None:
        self.seen: list[dict[str, Any]] = []

    async def handle(self, context: WorkContext) -> WorkResult:
        del context
        self.seen.append(
            {
                "trace_id": trace.get_current_span().get_span_context().trace_id,
                "bound": dict(structlog.contextvars.get_contextvars()),
            }
        )
        return WorkResult(outcome="done", references={})


def _row(payload: dict[str, JsonValue]) -> WorkTaskRow:
    now = datetime.now(UTC)
    return WorkTaskRow(
        task_id=uuid4(),
        kind=FleetTaskKind.AGENT_TURN,
        work_id=WorkId(uuid4()),
        dedup_key="d",
        priority=0,
        status=FleetTaskStatus.QUEUED,
        attempts=2,
        payload=payload,
        result_ref={},
        claimed_by=None,
        claimed_at=None,
        available_at=now,
        enqueued_at=now,
        enqueue_seq=1,
        updated_at=now,
    )


def _drain(handler: _Seeing, row: WorkTaskRow) -> None:
    worker = LeasedWorkWorker(
        handlers=(handler,),
        queue=_Queue([row]),
        leases=_Leases(),
        worker_id="w1",
        poll_interval=0.0,
        lease_ttl=timedelta(seconds=30),
        heartbeat_interval=10,
    )
    asyncio.run(worker.drain_once())


def test_the_handler_runs_in_its_own_trace_linked_to_the_enqueuer_with_the_bound_context() -> None:
    handler = _Seeing()
    with collect_spans() as exporter:
        with traced_step("api.request") as api_span:
            carrier = carrier_from_current_span()
        row = _row({**carrier, "turn_id": "turn-1", "workspace_id": "ws-1", "thread_id": "thr-1"})
        _drain(handler, row)
    (seen,) = handler.seen
    launcher = api_span.get_span_context()
    fleet_span = next(s for s in exporter.get_finished_spans() if s.name == "fleet.task")
    assert fleet_span.parent is None
    assert seen["trace_id"] == fleet_span.get_span_context().trace_id != launcher.trace_id
    assert [link.context.span_id for link in fleet_span.links] == [launcher.span_id]
    assert [link.context.trace_id for link in fleet_span.links] == [launcher.trace_id]
    bound = seen["bound"]
    assert bound["launched_by_trace_id"] == format(launcher.trace_id, "032x")
    assert fleet_span.attributes is not None
    assert fleet_span.attributes["launched_by_trace_id"] == format(launcher.trace_id, "032x")
    assert bound["fleet_kind"] == "agent_turn" and bound["task_attempt"] == 2
    assert bound["turn_id"] == "turn-1" and bound["workspace_id"] == "ws-1"
    assert bound["thread_id"] == "thr-1"
    assert bound["task_id"] == str(row.task_id) and bound["worker_id"] == "w1"
    assert fleet_span.attributes["fleet_kind"] == "agent_turn"
    assert structlog.contextvars.get_contextvars().get("turn_id") is None  # cleared after


def test_a_payload_without_a_carrier_starts_a_fresh_trace() -> None:
    handler = _Seeing()
    with collect_spans() as exporter:
        _drain(handler, _row({"turn_id": "turn-2", "workspace_id": "ws-1"}))
    (seen,) = handler.seen
    fleet_span = next(s for s in exporter.get_finished_spans() if s.name == "fleet.task")
    assert fleet_span.parent is None and not fleet_span.links
    assert seen["trace_id"] == fleet_span.get_span_context().trace_id
    assert "launched_by_trace_id" not in seen["bound"]
    assert set(PAYLOAD_CONTEXT_KEYS) >= {"workspace_id", "turn_id", "job_id", "run_id"}


class _Strict:
    """A handler whose payload model forbids extra keys — the design job envelope's shape.

    ``DesignTurnEnvelope`` is ``extra="forbid"``, so the carrier the enqueue stamps into the
    payload made every QUEUED design job unparseable (47 ``design_job.preamble_error`` failures
    in the lane's logs on 2026-09-17). The carrier belongs to the queue, not to the work.
    """

    kind = FleetTaskKind.AGENT_TURN

    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []
        self.trace_ids: list[int] = []

    async def handle(self, context: WorkContext) -> WorkResult:
        self.payloads.append(dict(context.payload))
        self.trace_ids.append(trace.get_current_span().get_span_context().trace_id)
        if set(context.payload) & set(CARRIER_KEYS):
            raise AssertionError(f"payload carries queue transport keys: {sorted(context.payload)}")
        return WorkResult(outcome="done", references={})


def test_the_handler_sees_no_carrier_keys_while_the_span_still_links_to_them() -> None:
    handler = _Strict()
    with collect_spans() as exporter:
        with traced_step("api.request") as api_span:
            carrier = carrier_from_current_span()
        assert set(carrier) & set(CARRIER_KEYS)  # the enqueue really did stamp one
        _drain(handler, _row({**carrier, "workspace_id": "ws-1", "run_id": "run-1"}))
    (payload,) = handler.payloads
    assert payload == {"workspace_id": "ws-1", "run_id": "run-1"}
    fleet_span = next(s for s in exporter.get_finished_spans() if s.name == "fleet.task")
    assert [link.context.span_id for link in fleet_span.links] == [
        api_span.get_span_context().span_id
    ]
    assert handler.trace_ids == [fleet_span.get_span_context().trace_id]


class _Failing:
    kind = FleetTaskKind.AGENT_TURN

    async def handle(self, context: WorkContext) -> WorkResult:
        del context
        raise RuntimeError("handler blew up")


def test_an_error_escaping_a_task_remembers_the_tasks_trace_for_the_late_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R4/R5 (2026-10-03 spec): ``worker.work_error`` is logged and reported after the
    ``fleet.task`` span closed, so the exception carries the task's trace with it."""
    reported: list[BaseException] = []
    monkeypatch.setattr(work_worker, "capture", reported.append)
    with collect_spans() as exporter:
        _drain(_Failing(), _row({"workspace_id": "ws-1"}))  # type: ignore[arg-type]
    fleet_span = next(s for s in exporter.get_finished_spans() if s.name == "fleet.task")
    (error,) = reported
    assert remembered_trace(error) is not None
    assert remembered_trace(error)[0] == format(fleet_span.context.trace_id, "032x")
