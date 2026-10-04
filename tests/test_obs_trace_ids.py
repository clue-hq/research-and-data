"""Every log line carries the trace it was written under (2026-10-03 agent-scoped tracing spec,
R4): ``trace_id``/``span_id`` as 32/16 lowercase hex — the ids Langfuse shows — and an error
logged after its span closed carries the trace the exception was raised under."""

from __future__ import annotations

import sys
from typing import Any

from clue_obs.config_types import LogMode
from clue_obs.otel import collect_spans, traced_step
from clue_obs.otel.trace_ids import add_trace_ids, remember_trace, remembered_trace
from clue_obs.processors import build_shared_processors


def _hex(span: Any) -> tuple[str, str]:
    context = span.get_span_context()
    return format(context.trace_id, "032x"), format(context.span_id, "016x")


def test_a_line_inside_a_span_carries_its_trace_and_span_ids() -> None:
    with collect_spans(), traced_step("work") as span:
        event = add_trace_ids(None, "info", {"event": "x"})
    trace_id, span_id = _hex(span)
    assert event == {"event": "x", "trace_id": trace_id, "span_id": span_id}


def test_a_line_outside_any_span_carries_no_ids() -> None:
    assert add_trace_ids(None, "info", {"event": "x"}) == {"event": "x"}


def test_an_error_logged_after_its_span_closed_carries_the_trace_it_was_raised_under() -> None:
    with collect_spans():
        try:
            with traced_step("fleet.task") as span:
                try:
                    raise RuntimeError("boom")
                except RuntimeError as exc:
                    remember_trace(exc)
                    raise
        except RuntimeError:
            event = add_trace_ids(None, "error", {"event": "worker.work_error", "exc_info": True})
            caught = sys.exc_info()[1]
    trace_id, span_id = _hex(span)
    assert event["trace_id"] == trace_id and event["span_id"] == span_id
    assert caught is not None and remembered_trace(caught) == (trace_id, span_id)


def test_the_first_remembered_trace_wins_as_the_exception_climbs() -> None:
    with collect_spans(), traced_step("inner") as inner:
        exc = RuntimeError("boom")
        remember_trace(exc)
    with collect_spans(), traced_step("outer"):
        remember_trace(exc)
    assert remembered_trace(exc) == _hex(inner)


def test_the_shared_chain_stamps_trace_ids_for_native_and_stdlib_lines() -> None:
    assert add_trace_ids in build_shared_processors(LogMode.coerce(None))
