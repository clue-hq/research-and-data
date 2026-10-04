"""Every design job drained by a worker is one named Langfuse trace (2026-10-03 agent-scoped
tracing spec, R7): a design turn, an ingestion job and an asset analysis each open their own trace,
so the design agent's model and tool steps (and ingestion's model calls) have somewhere to land.
The inline leg lane already runs inside ``design-leg.turn`` and opens none of its own."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

import pytest
from langfuse._client.resource_manager import LangfuseResourceManager
from lumen_api.fleet_handler import DesignJobWorkHandler
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from clue_fleet import WorkContext, WorkResult
from clue_obs.langfuse import (
    flush_langfuse,
    install_langfuse,
    observation,
    shutdown_langfuse,
)


@contextmanager
def _langfuse() -> Iterator[InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    assert install_langfuse(
        public_key="pk-lf-test",
        secret_key="sk-lf-test",
        host="http://127.0.0.1:9",
        environment="lane-test",
        release="test",
        tracer_provider=TracerProvider(),
        process_name="clue-test",
        span_exporter=exporter,
    )
    try:
        yield exporter
    finally:
        shutdown_langfuse()
        LangfuseResourceManager.reset()


def _context(payload: dict[str, Any]) -> WorkContext:
    return WorkContext(
        task_id=uuid4(),
        work_id=uuid4(),  # type: ignore[arg-type]
        worker_id="w1",
        lease_generation=1,  # type: ignore[arg-type]
        payload=payload,
        stop_requested=asyncio.Event(),
        lease_lost=asyncio.Event(),
    )


def _run(handler: DesignJobWorkHandler, payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    with _langfuse() as exporter:
        asyncio.run(handler.handle(_context(payload)))
        flush_langfuse()
        spans: list[ReadableSpan] = list(exporter.get_finished_spans())
    return {span.name: dict(span.attributes or {}) for span in spans}


@pytest.fixture
def inner_step(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real preamble needs a database; the trace is opened around it, so a stand-in body that
    opens one observation shows what the job's own steps nest under."""

    async def body(self: DesignJobWorkHandler, context: WorkContext) -> WorkResult:
        with observation("design.step"):
            pass
        return WorkResult(outcome="done", references={})

    monkeypatch.setattr(DesignJobWorkHandler, "_handle", body)


_TURN = {
    "kind": "web_turn",
    "workspace_id": "ws-1",
    "run_id": "run-1",
    "checkpoint_thread_id": "dsess-1",
    "document_id": "doc-1",
    "project_id": "prj-1",
}


def test_a_design_turn_is_its_own_named_agent_trace(inner_step: None) -> None:
    by_name = _run(DesignJobWorkHandler(), _TURN)
    job = by_name["design.turn"]
    assert job["langfuse.observation.type"] == "agent"
    step = by_name["design.step"]
    assert step["langfuse.trace.name"] == "design.turn"
    assert step["session.id"] == "dsess-1" and step["user.id"] == "ws-1"
    assert step["langfuse.trace.metadata.run_id"] == "run-1"
    assert step["langfuse.trace.metadata.document_id"] == "doc-1"
    assert step["langfuse.trace.metadata.project_id"] == "prj-1"
    assert set(step["langfuse.trace.tags"]) == {"design", "web_turn"}


def test_an_ingestion_job_is_its_own_named_trace(inner_step: None) -> None:
    payload = {
        "kind": "ingestion",
        "workspace_id": "ws-1",
        "job_id": "job-1",
        "ingestion_kind": "website",
    }
    by_name = _run(DesignJobWorkHandler(ingestion_only=True), payload)
    step = by_name["design.step"]
    assert step["langfuse.trace.name"] == "design.ingestion"
    assert step["langfuse.trace.metadata.job_id"] == "job-1"
    assert set(step["langfuse.trace.tags"]) == {"design", "ingestion", "website"}
    assert "design.ingestion" in by_name


def test_the_inline_leg_lane_opens_no_trace_of_its_own(inner_step: None) -> None:
    by_name = _run(DesignJobWorkHandler(named_trace=False), _TURN)
    assert set(by_name) == {"design.step"}
    assert "langfuse.trace.name" not in by_name["design.step"]


def test_a_turn_with_no_injected_callbacks_reports_through_the_platform_handler() -> None:
    """The drain on the fleet and the ingestion pool inject nothing; the design graph still gets
    the platform's LangChain handler when Langfuse is installed, and nothing when it is not."""
    handler = DesignJobWorkHandler()
    assert handler._turn_callbacks().handlers == ()
    with _langfuse():
        callbacks = handler._turn_callbacks()
    (only,) = callbacks.handlers
    assert type(only).__name__ == "ClueLangfuseHandler"
    assert callbacks.langfuse_ids is not None


def test_an_injected_factory_wins() -> None:
    sentinel: Any = object()
    handler = DesignJobWorkHandler(turn_callbacks_factory=lambda: sentinel)
    assert handler._turn_callbacks() is sentinel
