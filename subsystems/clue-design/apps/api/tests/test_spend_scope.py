"""Every raw HTTP spend path on the design side goes through one ProviderCaller per unit of work."""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from uuid import uuid4

import pytest
from clue_spend import DrainReport, HttpRequest, HttpResponse, LedgerStamp, ProviderHalted
from lumen_api import spend


class _Transport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.sent: list[HttpRequest] = []

    def send(self, request: HttpRequest) -> HttpResponse:
        self.sent.append(request)
        return self.responses.pop(0)


def _openrouter_ok(cost: float = 0.0123) -> HttpResponse:
    body = {
        "choices": [{"message": {"content": "{}"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "cost": cost},
        "model": "x-ai/grok-4.5",
    }
    return HttpResponse(status=200, body=json.dumps(body).encode())


def test_openrouter_call_lands_a_priced_result_row_with_usage_include() -> None:
    transport = _Transport([_openrouter_ok()])
    with spend.spend_scope(
        LedgerStamp(workspace_id="ws_t", job_id=uuid4()), transport=transport
    ) as scope:
        response = spend.openrouter_call(
            operation="design.ingestion.describe",
            body={"model": "x-ai/grok-4.5", "messages": []},
            label="describe:3 assets",
            timeout_s=30.0,
            api_key="k",
            base_url="https://or.example/api/v1",
        )
    assert response.status == 200
    sent = json.loads(transport.sent[0].body)
    assert sent["usage"] == {"include": True}
    rows = [row for row in scope.ledger.rows if row.phase == "result"]
    assert len(rows) == 1
    assert rows[0].provider == "openrouter" and rows[0].operation == "design.ingestion.describe"
    assert rows[0].cost_usd == Decimal("0.0123")
    assert rows[0].extras["cost_source"] == "metered" and rows[0].extras["model"] == "x-ai/grok-4.5"


def test_a_402_halts_the_provider_and_raises() -> None:
    transport = _Transport([HttpResponse(status=402, body=b'{"error":"insufficient credits"}')])
    with spend.spend_scope(LedgerStamp(workspace_id="ws_t"), transport=transport) as scope:
        with pytest.raises(ProviderHalted):
            spend.openrouter_call(
                operation="design.ingestion.assist",
                body={"model": "m", "messages": []},
                label="assist",
                timeout_s=5.0,
                api_key="k",
                base_url="https://or.example/api/v1",
            )
        assert scope.caller.halted("openrouter") == "payment_required"


def test_unscoped_calls_record_to_memory_and_warn_once(caplog) -> None:
    transport = _Transport([_openrouter_ok(), _openrouter_ok()])
    spend.reset_unscoped_for_tests(transport=transport)
    for _ in range(2):
        spend.openrouter_call(
            operation="design.ad.style_group",
            body={"model": "m", "messages": []},
            label="style",
            timeout_s=5.0,
            api_key="k",
            base_url="https://or.example/api/v1",
        )
    assert sum(1 for record in caplog.records if "spend.unscoped_call" in record.getMessage()) == 1


def test_max_attempts_is_forwarded_to_the_call_spec() -> None:
    """The five ingestion/ad clients pass their historical retry count instead of hand-looping.

    Asserted with ``max_attempts=1`` so the proof costs no wall-clock: the transport holds exactly
    one retryable response, and the default of four attempts would exhaust it on the second try.
    """
    transport = _Transport([HttpResponse(status=503, body=b"upstream is down")])
    with spend.spend_scope(LedgerStamp(workspace_id="ws_t"), transport=transport) as scope:
        response = spend.openrouter_call(
            operation="design.ingestion.describe",
            body={"model": "m", "messages": []},
            label="describe",
            timeout_s=5.0,
            api_key="k",
            base_url="https://or.example/api/v1",
            max_attempts=1,
        )
    assert response.status == 503
    assert len(transport.sent) == 1
    rows = [row for row in scope.ledger.rows if row.phase == "result"]
    assert rows[0].attempts == 1


def test_the_style_group_tie_break_makes_exactly_one_attempt(monkeypatch) -> None:
    """A design turn never waits on a retry backoff (ruling T3-2).

    503 is a RETRYABLE status, so the default four attempts — or even two — would put law 2's
    twelve-second backoff in the middle of a marketer's turn to re-ask a tie-break the turn is
    happy to do without. One request on the wire, then the deterministic recency fallback.
    """
    from lumen_api import ad_runtime
    from py_lumen_config import settings

    monkeypatch.setattr(settings, "openrouter_api_key", "a-key", raising=False)
    monkeypatch.setattr(settings, "openrouter_base_url", "https://or.example/api/v1", raising=False)
    transport = _Transport([HttpResponse(status=503, body=b"upstream is down")])
    with spend.spend_scope(LedgerStamp(workspace_id="ws_t"), transport=transport) as scope:
        chosen = ad_runtime.choose_style_group("a calm clinic", ["Photo Poster", "Bold Type"])
    assert chosen is None
    assert len(transport.sent) == 1
    rows = [row for row in scope.ledger.rows if row.phase == "result"]
    assert len(rows) == 1 and rows[0].attempts == 1
    assert rows[0].operation == "design.ad.style_group"


def test_drain_awaits_the_scopes_own_drain_fn() -> None:
    """PRE-1b: the platform injects a whole drain function, so its bookkeeping is written once."""
    seen: dict[str, object] = {}
    report = DrainReport(
        rows=3, artifacts=0, cost_usd=Decimal("1.5"), credits=Decimal(0), media_seconds=0
    )

    async def injected(conn, raw, ledger, stamp) -> DrainReport:
        seen["args"] = (conn, raw, ledger, stamp)
        return report

    stamp = LedgerStamp(workspace_id="ws_t")
    with spend.spend_scope(stamp, transport=_Transport([]), drain_fn=injected) as scope:
        got = asyncio.run(spend.drain(scope, "conn-sentinel"))
    assert got is report
    assert seen["args"] == ("conn-sentinel", scope.raw, scope.ledger, stamp)


def test_a_scope_with_no_drain_fn_defaults_to_drain_provider_calls() -> None:
    with spend.spend_scope(LedgerStamp(workspace_id="ws_t"), transport=_Transport([])) as scope:
        assert scope.drain_fn is not None


def _collected_call(**overrides):
    """One receipt as `lumen_agent.usage_collector` builds it from the gateway's stamps."""
    from datetime import UTC, datetime

    from lumen_agent.usage_collector import CollectedModelCall

    fields = {
        "run_id": uuid4(),
        "sequence": 1,
        "requested_model": "x-ai/grok-4.6",
        "answering_model": "x-ai/grok-4.6",
        "status": "completed",
        "role": "ingestion-brief",
        "input_tokens": 1200,
        "output_tokens": 340,
        "cache_read_input_tokens": 900,
        "cost_cents": Decimal("2.50"),
        "cost_source": "metered",
        "langfuse_trace_id": "trace-1",
        "langfuse_observation_id": "obs-1",
        "latency_ms": 1234.5,
        "error_code": None,
        "started_at": datetime.now(UTC),
        "completed_at": datetime.now(UTC),
    }
    fields.update(overrides)
    return CollectedModelCall(**fields)


def test_a_collected_model_call_lands_one_result_row_in_usd() -> None:
    call = _collected_call()
    with spend.spend_scope(LedgerStamp(workspace_id="ws_t"), transport=_Transport([])) as scope:
        spend.record_collected_model_call(
            scope, call, operation="design.ingestion.brief", label="brief"
        )
    (row,) = scope.ledger.rows
    assert row.phase == "result" and row.outcome == "ok" and row.attempts == 1
    assert row.provider == "openrouter" and row.operation == "design.ingestion.brief"
    assert row.label == "brief" and row.call_id == str(call.run_id)
    # The gateway settles CENTS; the ledger holds USD.
    assert row.cost_usd == Decimal("0.025")
    assert row.latency_ms == 1234 and row.http_status is None
    assert row.recorded_at == call.completed_at
    assert row.extras == {
        "model": "x-ai/grok-4.6",
        "prompt_tokens": 1200,
        "completion_tokens": 340,
        "cached_prompt_tokens": 900,
        "cost_source": "metered",
        "langfuse_trace_id": "trace-1",
        "langfuse_observation_id": "obs-1",
    }


def test_an_unpriced_call_is_an_estimate_row_with_no_measured_cost() -> None:
    """The gateway's `unpriced` is NOT the ledger's `free` — the model is on no price sheet, so
    the row says `estimate`, keeps its estimate columns at zero, and leaves `cost_usd` NULL."""
    call = _collected_call(cost_cents=None, cost_source="unpriced")
    with spend.spend_scope(LedgerStamp(workspace_id="ws_t"), transport=_Transport([])) as scope:
        spend.record_collected_model_call(
            scope, call, operation="design.ingestion.brief", label="brief"
        )
    (row,) = scope.ledger.rows
    assert row.extras["cost_source"] == "estimate"
    assert row.cost_usd is None
    assert row.estimate_usd == Decimal(0) and row.estimate_credits == Decimal(0)
    assert row.estimate_media_seconds == 0


def test_a_failed_call_lands_a_client_error_row_with_its_code() -> None:
    call = _collected_call(
        status="failed",
        answering_model=None,
        cost_cents=None,
        cost_source=None,
        error_code="timeout_error",
    )
    with spend.spend_scope(LedgerStamp(workspace_id="ws_t"), transport=_Transport([])) as scope:
        spend.record_collected_model_call(
            scope, call, operation="design.ingestion.brief", label="brief"
        )
    (row,) = scope.ledger.rows
    assert row.outcome == "client_error" and row.error_code == "timeout_error"
    assert row.cost_usd is None and row.extras["cost_source"] == "estimate"
