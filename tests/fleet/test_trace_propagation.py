"""Lane 3 slice 2, Task 4 (offline): the worker runs every handler inside the task's trace and
run context. Uses the fakes the worker's own tests use."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

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
)
from clue_fleet.work_worker import PAYLOAD_CONTEXT_KEYS
from clue_obs.otel import (
    CARRIER_KEYS,
    carrier_from_current_span,
    collect_spans,
    traced_step,
)


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


def test_the_handler_runs_inside_the_payloads_trace_and_the_bound_context() -> None:
    handler = _Seeing()
    with collect_spans() as exporter:
        with traced_step("api.request") as api_span:
            carrier = carrier_from_current_span()
        row = _row({**carrier, "turn_id": "turn-1", "workspace_id": "ws-1", "thread_id": "thr-1"})
        _drain(handler, row)
    (seen,) = handler.seen
    assert seen["trace_id"] == api_span.get_span_context().trace_id
    bound = seen["bound"]
    assert bound["fleet_kind"] == "agent_turn" and bound["task_attempt"] == 2
    assert bound["turn_id"] == "turn-1" and bound["workspace_id"] == "ws-1"
    assert bound["thread_id"] == "thr-1"
    assert bound["task_id"] == str(row.task_id) and bound["worker_id"] == "w1"
    fleet_span = next(s for s in exporter.get_finished_spans() if s.name == "fleet.task")
    assert fleet_span.parent is not None
    assert fleet_span.parent.span_id == api_span.get_span_context().span_id
    assert fleet_span.attributes is not None
    assert fleet_span.attributes["fleet_kind"] == "agent_turn"
    assert structlog.contextvars.get_contextvars().get("turn_id") is None  # cleared after


def test_a_payload_without_a_carrier_starts_a_fresh_trace() -> None:
    handler = _Seeing()
    with collect_spans() as exporter:
        _drain(handler, _row({"turn_id": "turn-2", "workspace_id": "ws-1"}))
    (seen,) = handler.seen
    fleet_span = next(s for s in exporter.get_finished_spans() if s.name == "fleet.task")
    assert fleet_span.parent is None
    assert seen["trace_id"] == fleet_span.get_span_context().trace_id
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


def test_the_handler_sees_no_carrier_keys_while_the_span_still_parents_on_them() -> None:
    handler = _Strict()
    with collect_spans() as exporter:
        with traced_step("api.request") as api_span:
            carrier = carrier_from_current_span()
        assert set(carrier) & set(CARRIER_KEYS)  # the enqueue really did stamp one
        _drain(handler, _row({**carrier, "workspace_id": "ws-1", "run_id": "run-1"}))
    (payload,) = handler.payloads
    assert payload == {"workspace_id": "ws-1", "run_id": "run-1"}
    fleet_span = next(s for s in exporter.get_finished_spans() if s.name == "fleet.task")
    assert fleet_span.parent is not None
    assert fleet_span.parent.span_id == api_span.get_span_context().span_id
    assert handler.trace_ids == [api_span.get_span_context().trace_id]
