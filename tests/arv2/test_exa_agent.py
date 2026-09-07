"""The Exa Agent surface's pure parts and its poll sequence (ARV2-COMPANY-OVERVIEW-CONTRACT.md §1).

Provider behaviour stays live (test_exa_agent_live.py). What is unit-tested is what a live call
cannot show on demand: the body shape, the cost reader over the documented response, and the
client's own create → poll → terminal sequencing on the lane's one allowed double.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from pydantic import SecretStr

from clue_api.arv2.calls import ProviderCaller
from clue_api.arv2.exa_client import (
    AGENT_EFFORT_ESTIMATE_USD,
    AGENT_TERMINAL_STATUSES,
    EXA_AGENT_EFFORTS,
    ExaAgentRun,
    ExaClient,
    agent_run_body,
    exa_agent_cost_reader,
)
from clue_api.arv2.sinks import MemoryLedger, MemoryRawSink
from clue_api.arv2.transport import HttpResponse, ScriptedTransport

SCHEMA = {"type": "object", "required": ["facts"], "properties": {"facts": {"type": "object"}}}


def test_the_body_carries_exactly_what_the_agent_api_documents() -> None:
    body = agent_run_body(query="Research Insight Health", output_schema=SCHEMA, effort="high")
    assert body == {"query": "Research Insight Health", "effort": "high", "outputSchema": SCHEMA}
    with_prompt = agent_run_body(
        query="q", output_schema=SCHEMA, effort="low", system_prompt="Prefer the company's domain."
    )
    assert with_prompt["systemPrompt"] == "Prefer the company's domain."
    assert "stream" not in body and "previousRunId" not in body


def test_an_unknown_effort_is_refused_before_the_wire() -> None:
    with pytest.raises(ValueError):
        agent_run_body(query="q", output_schema=SCHEMA, effort="ultra")
    assert set(EXA_AGENT_EFFORTS) == {"minimal", "low", "medium", "high", "xhigh", "auto", "max"}
    assert AGENT_EFFORT_ESTIMATE_USD["high"] == Decimal("0.50")
    assert AGENT_EFFORT_ESTIMATE_USD["auto"] == Decimal("5")


def test_the_cost_reader_reads_the_completed_run_and_stays_silent_before_it() -> None:
    completed = HttpResponse(
        status=200,
        body=json.dumps(
            {
                "id": "agent_run_abc",
                "status": "completed",
                "costDollars": {"total": 0.5, "agentCompute": 0.2, "search": 0.3},
                "usage": {"agentComputeUnits": 2, "searches": 60},
            }
        ).encode(),
    )
    reading = exa_agent_cost_reader(completed)
    assert reading.cost_usd == Decimal("0.5")
    assert reading.provider_request_id == "agent_run_abc"
    assert reading.extras["cost_breakdown"]["search"] == 0.3
    assert reading.extras["usage"] == {"agentComputeUnits": 2, "searches": 60}

    queued = HttpResponse(status=200, body=b'{"id": "agent_run_abc", "status": "queued"}')
    silent = exa_agent_cost_reader(queued)
    assert silent.cost_usd is None and silent.provider_request_id == "agent_run_abc"
    assert exa_agent_cost_reader(HttpResponse(status=500, body=b"nope")).cost_usd is None


def test_terminal_statuses_are_the_three_the_api_documents() -> None:
    assert frozenset({"completed", "failed", "cancelled"}) == AGENT_TERMINAL_STATUSES


def _caller(transport: ScriptedTransport, sleeps: list[float]) -> ProviderCaller:
    from datetime import UTC, datetime

    return ProviderCaller(
        transport=transport,
        raw_sink=MemoryRawSink(),
        ledger=MemoryLedger(),
        sleep=sleeps.append,
        now=lambda: datetime(2026, 9, 7, 12, 0, tzinfo=UTC),
    )


def _run_json(**overrides: object) -> bytes:
    base: dict[str, object] = {"id": "agent_run_abc", "object": "agent_run", "status": "queued"}
    base.update(overrides)
    return json.dumps(base).encode()


def test_agent_run_creates_then_polls_until_terminal_and_settles_on_the_completed_body() -> None:
    transport = ScriptedTransport(
        [
            HttpResponse(status=200, body=_run_json(status="queued")),
            HttpResponse(status=200, body=_run_json(status="running")),
            HttpResponse(
                status=200,
                body=_run_json(
                    status="completed",
                    stopReason="schema_satisfied",
                    output={
                        "text": "done",
                        "structured": {"facts": {"legal_name": "Insight Health AI, Inc."}},
                        "grounding": [
                            {"field": "structured.facts", "citations": [], "confidence": "high"}
                        ],
                    },
                    usage={"agentComputeUnits": 1, "searches": 12},
                    costDollars={"total": 0.025},
                ),
            ),
        ]
    )
    wrapper_sleeps: list[float] = []
    client_sleeps: list[float] = []
    client = ExaClient(
        _caller(transport, wrapper_sleeps),
        SecretStr("key"),
        sleep=client_sleeps.append,
        monotonic=iter(range(0, 100, 1)).__next__,
    )
    run = client.agent_run(
        query="Research Insight Health", output_schema=SCHEMA, effort="low", poll_interval_s=4.0
    )
    assert isinstance(run, ExaAgentRun)
    assert run.status == "completed" and run.stop_reason == "schema_satisfied"
    assert run.run_id == "agent_run_abc"
    assert run.structured == {"facts": {"legal_name": "Insight Health AI, Inc."}}
    assert run.output_text == "done"
    assert run.grounding[0]["field"] == "structured.facts"
    assert run.usage == {"agentComputeUnits": 1, "searches": 12}
    assert run.cost_usd == Decimal("0.025")
    assert run.polls == 2
    assert client_sleeps == [4.0, 4.0]
    assert len(run.costs) == 3 and run.cost is run.costs[-1]
    assert run.cost.cost_source == "metered"
    assert run.costs[0].cost_source == "estimate"  # the create reserved the effort price
    assert run.costs[0].cost_usd == Decimal("0.025")

    create_request = transport.requests[0]
    assert create_request.method == "POST" and create_request.url.endswith("/agent/runs")
    assert create_request.headers["Authorization"] == "Bearer key"  # HttpRequest keeps case
    assert transport.requests[1].method == "GET"
    assert transport.requests[1].url.endswith("/agent/runs/agent_run_abc")


def test_a_failed_run_is_returned_with_its_error_never_raised() -> None:
    transport = ScriptedTransport(
        [
            HttpResponse(status=200, body=_run_json(status="running")),
            HttpResponse(
                status=200,
                body=_run_json(
                    status="failed",
                    error={"code": "schema_unsatisfiable", "message": "could not satisfy schema"},
                ),
            ),
        ]
    )
    client = ExaClient(_caller(transport, []), SecretStr("key"), sleep=lambda _: None)
    run = client.agent_run(query="q", output_schema=SCHEMA, effort="low")
    assert run.status == "failed"
    assert run.error_code == "schema_unsatisfiable"
    assert run.structured is None and run.output_text is None


def test_a_run_that_outlives_the_timeout_is_returned_as_timed_out() -> None:
    transport = ScriptedTransport(
        [HttpResponse(status=200, body=_run_json(status="running")) for _ in range(4)]
    )
    clock = iter([0.0, 0.0, 100.0, 200.0, 301.0, 400.0, 500.0]).__next__
    client = ExaClient(
        _caller(transport, []), SecretStr("key"), sleep=lambda _: None, monotonic=clock
    )
    run = client.agent_run(query="q", output_schema=SCHEMA, effort="low", timeout_s=300.0)
    assert run.status == "timed_out"
    assert run.run_id == "agent_run_abc"
    assert run.error_code == "timeout"


def test_a_create_that_already_returns_a_terminal_run_never_polls() -> None:
    transport = ScriptedTransport(
        [
            HttpResponse(
                status=200,
                body=_run_json(
                    status="completed",
                    output={"text": "quick", "structured": {"facts": {}}, "grounding": []},
                    costDollars={"total": 0.012},
                ),
            )
        ]
    )
    client = ExaClient(_caller(transport, []), SecretStr("key"), sleep=lambda _: None)
    run = client.agent_run(query="q", output_schema=SCHEMA, effort="minimal")
    assert run.status == "completed" and run.polls == 0 and len(transport.requests) == 1
