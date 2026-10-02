"""Lane 3 slice 2, Task 2: the W3C carrier round trip the fleet payload rides on."""

from __future__ import annotations

from opentelemetry import trace

from clue_obs.otel import (
    carrier_from_current_span,
    collect_spans,
    context_from_carrier,
    get_tracer,
    traced_step,
)


def test_no_current_span_yields_an_empty_carrier() -> None:
    assert carrier_from_current_span() == {}
    assert context_from_carrier({}) is None
    assert context_from_carrier({"turn_id": "x"}) is None


def test_a_carrier_round_trips_the_trace_id() -> None:
    with collect_spans():
        with traced_step("api.request") as parent:
            carrier = carrier_from_current_span()
        assert carrier["traceparent"].startswith("00-")
        restored = context_from_carrier({**carrier, "other": 1})
        assert restored is not None
        with get_tracer().start_as_current_span("fleet.task", context=restored) as child:
            pass
    assert child.get_span_context().trace_id == parent.get_span_context().trace_id
    assert child.parent is not None and child.parent.span_id == parent.get_span_context().span_id
    assert trace.get_current_span().get_span_context().is_valid is False
