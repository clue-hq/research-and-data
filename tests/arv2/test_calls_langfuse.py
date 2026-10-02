"""Lane 3 slice 3b, Task 2: every provider call is one typed Langfuse observation carrying the
settled money and the ledger row id; the row carries the Langfuse ids back; a halt and a ceiling
are guardrails. Off: the rows are byte-for-byte what they were."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest

from clue_api.arv2.calls import Ceilings, CostReading, SpendEstimate
from clue_api.arv2.errors import ProviderHalted, ProviderTransportError
from clue_api.arv2.transport import HttpRequest, HttpResponse, TransportFailure
from tests._langfuse import finished_spans, langfuse_installed
from tests.arv2.test_calls import _caller, _spec

_OK = HttpResponse(200, {"Content-Type": "application/json"}, b'{"ok":true}')


def _attrs(span: Any) -> dict[str, Any]:
    return dict(span.attributes or {})


def _reader(_response: HttpResponse) -> CostReading:
    return CostReading(
        cost_usd=Decimal("0.02"),
        provider_request_id="req-1",
        extras={"model": "x-ai/grok-4.6", "prompt_tokens": 10, "completion_tokens": 2},
    )


def test_off_the_result_row_extras_carry_no_langfuse_keys() -> None:
    caller, _t, _r, ledger, _c = _caller([_OK])
    caller.call(_spec(cost_reader=_reader))
    result = [row for row in ledger.rows if row.phase == "result"][0]
    assert "langfuse_trace_id" not in result.extras


def test_a_chat_completion_is_a_generation_with_cost_usage_and_the_row_id() -> None:
    with langfuse_installed() as (exporter, _provider):
        caller, _t, _r, ledger, _c = _caller([_OK])
        outcome = caller.call(
            _spec(provider="openrouter", operation="chat/completions", cost_reader=_reader)
        )
        spans = finished_spans(exporter)
    span = next(s for s in spans if s.name == "openrouter.chat/completions")
    attrs = _attrs(span)
    assert attrs["langfuse.observation.type"] == "generation"
    assert attrs["langfuse.observation.model.name"] == "x-ai/grok-4.6"
    assert json.loads(attrs["langfuse.observation.cost_details"]) == {"total": 0.02}
    assert json.loads(attrs["langfuse.observation.usage_details"]) == {"input": 10, "output": 2}
    assert attrs["langfuse.observation.metadata.ledger_row_id"] == outcome.ledger_row_id
    assert attrs["langfuse.observation.metadata.cost_source"] == "metered"
    payload = json.loads(attrs["langfuse.observation.input"])
    assert payload["host"] == "provider.test" and payload["path"] == "/v1/thing"
    assert "body" not in payload and "query" not in payload
    output = json.loads(attrs["langfuse.observation.output"])
    assert output["status"] == 200 and output["outcome"] == "ok" and output["attempts"] == 1
    result = [row for row in ledger.rows if row.phase == "result"][0]
    assert result.extras["langfuse_trace_id"] == format(span.context.trace_id, "032x")
    assert result.extras["langfuse_observation_id"] == format(span.context.span_id, "016x")
    estimate = [row for row in ledger.rows if row.phase == "estimate"][0]
    assert "langfuse_trace_id" not in estimate.extras


def test_the_input_names_the_host_without_any_credentials_in_the_url() -> None:
    with langfuse_installed() as (exporter, _provider):
        caller, _t, _r, _l, _c = _caller([_OK])
        caller.call(
            _spec(
                request=HttpRequest(
                    method="POST", url="https://user:pw@provider.test/v1/thing", body=b"{}"
                )
            )
        )
        spans = finished_spans(exporter)
    raw = _attrs(next(s for s in spans if s.name == "prov.v1/thing"))["langfuse.observation.input"]
    assert json.loads(raw)["host"] == "provider.test"
    assert "user" not in raw and "pw" not in raw


def test_a_free_public_fetch_is_a_tool_observation() -> None:
    with langfuse_installed() as (exporter, _provider):
        caller, _t, _r, _l, _c = _caller([_OK])
        caller.call(_spec(provider="youtube", operation="watch", estimate=SpendEstimate()))
        spans = finished_spans(exporter)
    attrs = _attrs(next(s for s in spans if s.name == "youtube.watch"))
    assert attrs["langfuse.observation.type"] == "tool"
    assert attrs["langfuse.observation.metadata.cost_source"] == "free"
    # The SDK keeps ``cost_details`` on generation-like observations only, so a span-like one
    # carries its settled money in metadata instead — a free call still settles (at zero).
    assert attrs["langfuse.observation.metadata.cost_usd"] == "0"


@pytest.mark.parametrize("malformed_metering", [False, True])
def test_native_generation_preserves_unpriced_usd_even_if_metering_is_malformed(
    malformed_metering: bool,
) -> None:
    def read(_response: HttpResponse) -> CostReading:
        if malformed_metering:
            raise ValueError("unreadable metering")
        return CostReading(media_seconds=60, extras={"model": "native-video", "prompt_tokens": 42})

    with langfuse_installed() as (exporter, _provider):
        caller, _t, _r, ledger, _c = _caller([_OK])
        result = caller.call(
            _spec(
                provider="gemini",
                operation="models/native-video:generateContent",
                estimate=SpendEstimate(media_seconds=60),
                extras={"usd_unpriced": True},
                cost_reader=read,
            )
        )
        spans = finished_spans(exporter)
    assert result.call_cost.cost_usd is None
    assert result.call_cost.cost_source == "unpriced"
    assert result.call_cost.media_seconds == 60
    row = next(r for r in ledger.rows if r.phase == "result")
    assert row.cost_usd is None and row.extras["cost_source"] == "unpriced"
    generation = next(s for s in spans if s.name == "gemini.models/native-video:generateContent")
    attrs = _attrs(generation)
    assert attrs["langfuse.observation.type"] == "generation"
    assert "langfuse.observation.cost_details" not in attrs
    assert "langfuse.observation.model.name" not in attrs  # no automatic vendor pricing
    assert attrs["langfuse.observation.metadata.cost_source"] == "unpriced"
    assert row.extras["langfuse_observation_id"] == format(generation.context.span_id, "016x")
    assert caller.totals().usd == 0 and caller.totals().media_seconds == 60


def test_reported_usd_overrides_an_unpriced_reservation() -> None:
    caller, _t, _r, _ledger, _c = _caller([_OK])
    result = caller.call(_spec(extras={"usd_unpriced": True}, cost_reader=_reader))
    assert result.call_cost.cost_usd == Decimal("0.02")
    assert result.call_cost.cost_source == "metered"


def test_a_halt_is_an_error_and_the_next_call_is_a_latch_guardrail() -> None:
    refused = HttpResponse(402, {}, b'{"error":"out of credit"}')
    with langfuse_installed() as (exporter, _provider):
        caller, _t, _r, _l, _c = _caller([refused])
        spec = _spec(halt_rule=lambda response: "out_of_credit" if response.status == 402 else None)
        with pytest.raises(ProviderHalted):
            caller.call(spec)
        with pytest.raises(ProviderHalted):
            caller.call(spec)
        spans = finished_spans(exporter)
    by_name = {s.name: _attrs(s) for s in spans}
    assert by_name["prov.v1/thing"]["langfuse.observation.level"] == "ERROR"
    assert by_name["prov.v1/thing"]["langfuse.observation.status_message"] == "out_of_credit"
    latch = by_name["provider.halt_latch"]
    assert latch["langfuse.observation.type"] == "guardrail"
    assert "latched:out_of_credit" in latch["langfuse.observation.status_message"]


def test_transport_exhaustion_is_an_error_observation() -> None:
    with langfuse_installed() as (exporter, _provider):
        caller, _t, _r, ledger, _c = _caller([TransportFailure("boom")] * 4)
        with pytest.raises(ProviderTransportError):
            caller.call(_spec(max_attempts=2))
        spans = finished_spans(exporter)
    span = next(s for s in spans if s.name == "prov.v1/thing")
    attrs = _attrs(span)
    assert attrs["langfuse.observation.level"] == "ERROR"
    assert attrs["langfuse.observation.status_message"] == "transport_error"
    result = [row for row in ledger.rows if row.phase == "result"][0]
    assert result.extras["langfuse_trace_id"] == format(span.context.trace_id, "032x")


def test_an_over_ceiling_estimate_records_a_ceiling_guardrail() -> None:
    with langfuse_installed() as (exporter, _provider):
        caller, _t, _r, _l, _c = _caller([_OK], ceilings=Ceilings(usd=Decimal("0.005")))
        caller.call(_spec())  # the estimate is 0.01 > 0.005: flagged, never stopped
        spans = finished_spans(exporter)
    ceiling = next(s for s in spans if s.name == "provider.ceiling")
    assert _attrs(ceiling)["langfuse.observation.type"] == "guardrail"
