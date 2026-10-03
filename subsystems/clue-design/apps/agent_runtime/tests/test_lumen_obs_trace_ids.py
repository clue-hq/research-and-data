"""The design log chain stamps the trace a line was written under, exactly as the platform's does
(2026-10-03 agent-scoped tracing spec, R4): design jobs run in the fleet worker, and whichever obs
package configured the console last formats every line in that process."""

from __future__ import annotations

import sys

from opentelemetry.sdk.trace import TracerProvider
from py_lumen_obs import LogMode
from py_lumen_obs.processors import add_trace_ids, build_shared_processors

_PLATFORM_EXCEPTION_ATTR = "__clue_trace_ids__"  # clue_obs.otel.trace_ids.EXCEPTION_TRACE_ATTR


def test_a_line_inside_a_span_carries_its_trace_and_span_ids() -> None:
    tracer = TracerProvider().get_tracer("test")
    with tracer.start_as_current_span("work") as span:
        event = add_trace_ids(None, "info", {"event": "x"})
    context = span.get_span_context()
    assert event["trace_id"] == format(context.trace_id, "032x")
    assert event["span_id"] == format(context.span_id, "016x")


def test_a_line_outside_any_span_carries_no_ids() -> None:
    assert add_trace_ids(None, "info", {"event": "x"}) == {"event": "x"}


def test_an_error_logged_after_its_span_closed_reads_the_platform_stamp() -> None:
    try:
        error = RuntimeError("boom")
        setattr(error, _PLATFORM_EXCEPTION_ATTR, ("a" * 32, "b" * 16))
        raise error
    except RuntimeError:
        event = add_trace_ids(None, "error", {"event": "x", "exc_info": True})
        assert sys.exc_info()[1] is error
    assert event["trace_id"] == "a" * 32 and event["span_id"] == "b" * 16


def test_the_shared_chain_includes_it() -> None:
    assert add_trace_ids in build_shared_processors(LogMode.coerce(None))
