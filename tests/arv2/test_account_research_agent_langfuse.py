"""Lane 3 slice 3b, Task 4: an ARV2 research job is one named Langfuse trace; each model round
row carries its generation's ids; the ending is an event and a cap is a guardrail.

Lane 3 slice 4, Task 2: the same trace is tagged with the entities the job carried — its subject
before any work, and everything it wrote a claim about at the ending."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage

from clue_api.arv2.claim_writer import ClaimDraft, WriteReceipt
from clue_core import ClaimId, EntityType, ExtractionMethod, ResearchMode, RunId
from clue_gateway.metadata import ANSWERING_MODEL_KEY, COST_CENTS_KEY, COST_SOURCE_KEY
from clue_obs.langfuse import ENTITIES_METADATA_KEY
from tests._langfuse import finished_spans, langfuse_installed
from tests.arv2.test_account_research_agent import (
    SCOPE,
    StructuredTool,
    _call,
    _counting_tool,
    _drive,
    _finalizing_tool,
    _NoArgs,
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


def _tagged_sets(spans: Any) -> list[str]:
    return [
        _attrs(s)[f"langfuse.trace.metadata.{ENTITIES_METADATA_KEY}"]
        for s in spans
        if s.name == "entities.tagged"
    ]


def test_the_job_tags_its_subject_and_every_entity_it_wrote() -> None:
    runtime = _runtime()
    written = StructuredTool.from_function(
        coroutine=_writing(runtime, "con-77"),
        name="write_claims",
        description="records an entity the job wrote about",
        args_schema=_NoArgs,
    )

    def respond(messages: Any) -> AIMessage:
        if any(getattr(m, "name", None) == "finalize_research" for m in messages):
            return _priced(AIMessage(content="done"))
        if any(getattr(m, "name", None) == "write_claims" for m in messages):
            return _priced(AIMessage(content="", tool_calls=[_call("finalize_research", 2)]))
        return _priced(AIMessage(content="", tool_calls=[_call("write_claims", 1)]))

    with langfuse_installed() as (exporter, _provider):
        outcome = _run(
            _drive(_ScriptedModel(respond), [written, _finalizing_tool(runtime)], runtime)
        )
        spans = finished_spans(exporter)
    assert outcome.reason == "finalized"
    sets = _tagged_sets(spans)
    assert sets[0] == str(SCOPE.account_id)  # the subject, first thing in the trace
    assert sets[-1] == ",".join(sorted({str(SCOPE.account_id), "con-77"}))  # the ending
    job = next(s for s in spans if s.name == "arv2.account_research")
    last = next(
        s
        for s in spans
        if s.name == "entities.tagged"
        and _attrs(s)[f"langfuse.trace.metadata.{ENTITIES_METADATA_KEY}"] == sets[-1]
    )
    assert format(last.context.trace_id, "032x") == format(job.context.trace_id, "032x")
    assert f"entity:{SCOPE.account_id}" in _attrs(last)["langfuse.trace.tags"]


def _writing(runtime: Any, entity: str) -> Any:
    async def call() -> str:
        runtime.tool_calls += 1
        runtime.entities_touched.add(entity)  # what write_each records for every draft it writes
        return json.dumps({"ok": True})

    return call


def _draft(runtime: Any, field_key: str, entity_id: str) -> ClaimDraft:
    """One draft shaped like the ones the model's write tool hands the runtime."""
    return ClaimDraft(
        entity_id=entity_id,  # type: ignore[arg-type]
        entity_type=EntityType.ACCOUNT,
        field_key=field_key,
        value_json="robotics",
        extraction_method=ExtractionMethod.LLM_SYNTHESIS,
        run_id=RunId(runtime.scope.run_id),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        workspace_id=runtime.scope.workspace_id,
        source_url="https://probook.ai/about",
    )


def test_write_each_records_every_drafts_entity_before_writing() -> None:
    runtime = _runtime()

    class _Writer:
        async def write(self, conn: Any, draft: Any) -> Any:
            if draft.field_key.endswith("bad"):
                raise RuntimeError("store refused")
            return WriteReceipt(
                claim_id=ClaimId(uuid4()),
                field_key=draft.field_key,
                markers={},
                registered_field=False,
            )

    runtime._writer = _Writer()  # type: ignore[attr-defined]
    drafts = [_draft(runtime, "core.industry", "acc-1"), _draft(runtime, "core.bad", "con-2")]
    results = _run(runtime.write_each(drafts))
    assert len(results) == 2
    assert runtime.entities_touched == {"acc-1", "con-2"}


def test_write_records_every_drafts_entity_too() -> None:
    """The code-built batch (an ATS board, a provider record) names its entities just as loudly."""
    runtime = _runtime()

    class _Writer:
        async def write(self, conn: Any, draft: Any) -> Any:
            return WriteReceipt(
                claim_id=ClaimId(uuid4()),
                field_key=draft.field_key,
                markers={},
                registered_field=False,
            )

    runtime._writer = _Writer()  # type: ignore[attr-defined]
    drafts = [_draft(runtime, "core.industry", "acc-1"), _draft(runtime, "core.headcount", "con-2")]
    receipts = _run(runtime.write(drafts))
    assert len(receipts) == 2
    assert runtime.entities_touched == {"acc-1", "con-2"}
