"""Lane 3 slice 3b, Task 4: an ARV2 research job is one named Langfuse trace; each model round
row carries its generation's ids; the ending is an event and a cap is a guardrail."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage

from clue_gateway.metadata import ANSWERING_MODEL_KEY, COST_CENTS_KEY, COST_SOURCE_KEY
from tests._langfuse import finished_spans, langfuse_installed
from tests.arv2.test_account_research_agent import (
    SCOPE,
    _call,
    _counting_tool,
    _drive,
    _finalizing_tool,
    _run,
    _runtime,
    _ScriptedModel,
)


def _attrs(span: Any) -> dict[str, Any]:
    return dict(span.attributes or {})


def _priced(message: AIMessage) -> AIMessage:
    message.response_metadata = {
        **message.response_metadata,
        "model_name": "x-ai/grok-4.6",
        ANSWERING_MODEL_KEY: "x-ai/grok-4.6",
        COST_CENTS_KEY: "2.5",
        COST_SOURCE_KEY: "metered",
    }
    return message


def test_a_finalized_job_is_a_named_trace_with_priced_rounds_and_an_ending_event() -> None:
    runtime = _runtime()

    def respond(messages: Any) -> AIMessage:
        if any(getattr(m, "name", None) == "finalize_research" for m in messages):
            return _priced(AIMessage(content="done"))
        return _priced(AIMessage(content="", tool_calls=[_call("finalize_research", 1)]))

    with langfuse_installed() as (exporter, _provider):
        outcome = _run(_drive(_ScriptedModel(respond), [_finalizing_tool(runtime)], runtime))
        spans = finished_spans(exporter)
    assert outcome.reason == "finalized"
    generations = [s for s in spans if _attrs(s).get("langfuse.observation.type") == "generation"]
    assert len(generations) == outcome.model_rounds
    first = _attrs(generations[0])
    assert first["langfuse.trace.name"] == "arv2.account_research"
    assert first["session.id"] == str(SCOPE.run_id)
    assert first["user.id"] == SCOPE.workspace_id
    assert first["langfuse.trace.metadata.job_id"] == str(SCOPE.job_id)
    assert json.loads(first["langfuse.observation.cost_details"]) == {"total": 0.025}
    rows = [row for row in runtime.model_ledger.drain() if row.phase == "result"]
    assert len(rows) == outcome.model_rounds
    exported = {format(s.context.span_id, "016x") for s in generations}
    for row in rows:
        assert row.extras["langfuse_trace_id"] == format(generations[0].context.trace_id, "032x")
        assert row.extras["langfuse_observation_id"] in exported
    ending_span = next(s for s in spans if s.name == "arv2.agent.ending")
    ending = _attrs(ending_span)
    assert ending["langfuse.observation.type"] == "event"
    assert json.loads(ending["langfuse.observation.output"])["reason"] == "finalized"
    # The ending belongs to the job's own trace — it is that trace's last observation, not a
    # stray root trace of its own.
    assert format(ending_span.context.trace_id, "032x") == format(
        generations[0].context.trace_id, "032x"
    )
    assert ending["langfuse.trace.name"] == "arv2.account_research"
    # The job itself is one agent observation, and everything above sits beneath it.
    job = next(
        s
        for s in spans
        if s.name == "arv2.account_research"
        and _attrs(s).get("langfuse.observation.type") == "agent"
    )
    assert format(job.context.trace_id, "032x") == format(generations[0].context.trace_id, "032x")


def test_a_round_cap_is_a_guardrail() -> None:
    runtime = _runtime()

    def respond(messages: Any) -> AIMessage:
        return _priced(AIMessage(content="", tool_calls=[_call("read_account_state", 1)]))

    with langfuse_installed() as (exporter, _provider):
        outcome = _run(
            _drive(_ScriptedModel(respond), [_counting_tool(runtime)], runtime, max_model_rounds=2)
        )
        spans = finished_spans(exporter)
    assert outcome.reason == "round_cap"
    cap = _attrs(next(s for s in spans if s.name == "arv2.round_cap"))
    assert cap["langfuse.observation.type"] == "guardrail"
    assert cap["langfuse.observation.level"] == "WARNING"
    assert cap["langfuse.trace.name"] == "arv2.account_research"


def test_off_the_rows_carry_no_langfuse_keys() -> None:
    runtime = _runtime()

    def respond(messages: Any) -> AIMessage:
        return _priced(AIMessage(content="", tool_calls=[_call("finalize_research", 1)]))

    _run(_drive(_ScriptedModel(respond), [_finalizing_tool(runtime)], runtime))
    rows = [row for row in runtime.model_ledger.drain() if row.phase == "result"]
    assert rows and all("langfuse_trace_id" not in row.extras for row in rows)
