"""Lane 3 slice 3a, Task 2: the Langfuse client at the roots, its redaction, and the no-op
posture when it is not installed."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from opentelemetry.sdk.trace import ReadableSpan

from clue_obs.langfuse import (
    DEFAULT_MASK_LIMIT,
    LangfuseIds,
    LangfuseRunRegistry,
    current_ids,
    event,
    guardrail,
    langfuse_is_installed,
    make_mask,
    observation,
    propagate_trace,
    tag_entities,
)
from tests._langfuse import finished_spans, langfuse_installed


def _attrs(span: ReadableSpan) -> dict[str, Any]:
    return dict(span.attributes or {})


def test_not_installed_every_helper_is_a_no_op() -> None:
    assert not langfuse_is_installed()
    assert current_ids() is None
    with observation("x", as_type="tool", input={"a": 1}) as obs:
        assert obs.id is None and obs.trace_id is None
        assert obs.update(output={"b": 2}) is obs
    event("e", metadata={"k": "v"})
    guardrail("g", reason="halted")
    with propagate_trace(trace_name="t", session_id="s"):
        pass


def test_an_observation_exports_its_type_ids_and_payload_under_the_trace_attributes() -> None:
    with langfuse_installed() as (exporter, _provider):
        assert langfuse_is_installed()
        with (
            propagate_trace(
                trace_name="head-of-abm.turn",
                session_id="thread-1",
                user_id="ws-1",
                metadata={"turn_id": "turn-1", "skipped": None},
                tags=("head_of_abm",),
            ),
            observation("gateway.completion", as_type="generation", input={"q": "hi"}) as obs,
        ):
            ids = current_ids()
            assert ids == LangfuseIds(trace_id=obs.trace_id, observation_id=obs.id)
            obs.update(
                output={"a": "ok"},
                usage_details={"input": 3, "output": 1},
                cost_details={"total": 0.01},
            )
            guardrail("provider.ceiling", reason="usd over ceiling")
            event("note", metadata={"k": "v"})
        spans = finished_spans(exporter)
    by_name = {span.name: _attrs(span) for span in spans}
    generation = by_name["gateway.completion"]
    assert generation["langfuse.observation.type"] == "generation"
    assert generation["langfuse.observation.cost_details"] == '{"total": 0.01}'
    assert generation["langfuse.trace.name"] == "head-of-abm.turn"
    assert generation["session.id"] == "thread-1"
    assert generation["user.id"] == "ws-1"
    assert generation["langfuse.trace.metadata.turn_id"] == "turn-1"
    assert "langfuse.trace.metadata.skipped" not in generation
    assert generation["langfuse.environment"] == "lane-test"
    assert by_name["provider.ceiling"]["langfuse.observation.type"] == "guardrail"
    assert by_name["provider.ceiling"]["langfuse.observation.level"] == "WARNING"
    assert by_name["provider.ceiling"]["langfuse.observation.status_message"] == "usd over ceiling"
    assert by_name["note"]["langfuse.observation.type"] == "event"
    assert by_name["note"]["langfuse.observation.metadata.k"] == "v"


def test_the_mask_applies_the_secret_and_blob_rules_and_truncates_but_keeps_claim_values() -> None:
    mask = make_mask(limit=20)
    blob = "QUJD" * 200  # base64-looking, 800 chars
    masked = mask(
        data={
            "api_key": "sk-live-abc",
            "nested": {"authorization": "Bearer x", "value": "Acme uses Snowflake"},
            "attachment": blob,
            "long": "x" * 50,
            "n": 3,
            "claim": {
                "value_json": "Acme uses Snowflake",
                "evidence_span": "quoted span",
                "api_key": "sk-nested",
            },
        }
    )
    assert masked["api_key"] != "sk-live-abc"
    assert masked["nested"]["authorization"] != "Bearer x"
    assert masked["nested"]["value"] == "Acme uses Snowflake"  # the claim-value rule is NOT applied
    # The log chain's ids-only rule must NOT run here: Langfuse is where these are debugged.
    assert masked["claim"]["value_json"] == "Acme uses Snowflake"
    assert masked["claim"]["evidence_span"] == "quoted span"
    assert masked["claim"]["api_key"] == "***"  # ... but the secret-key rule still runs nested
    assert blob not in masked["attachment"]
    assert masked["long"].startswith("x" * 20) and "+30 chars" in masked["long"]
    assert masked["n"] == 3
    assert DEFAULT_MASK_LIMIT == 8_000


def test_the_installed_client_masks_payloads_before_export() -> None:
    with langfuse_installed() as (exporter, _provider):
        with observation("tool", as_type="tool", input={"api_key": "sk-live-abc", "q": "hi"}):
            pass
        spans = finished_spans(exporter)
    payload = _attrs(spans[0])["langfuse.observation.input"]
    assert "sk-live-abc" not in payload
    assert '"q": "hi"' in payload


def test_health_check_server_spans_are_not_exported() -> None:
    with langfuse_installed() as (exporter, provider):
        tracer = provider.get_tracer("test")
        with tracer.start_as_current_span("GET /healthz", attributes={"http.route": "/healthz"}):
            pass
        with tracer.start_as_current_span("GET /accounts", attributes={"http.route": "/accounts"}):
            pass
        names = [span.name for span in finished_spans(exporter)]
    assert names == ["GET /accounts"]


def test_the_run_registry_remembers_and_pops_by_run_id() -> None:
    registry = LangfuseRunRegistry()
    run_id = uuid4()
    assert registry.get(run_id) is None
    registry.remember(run_id, LangfuseIds(trace_id="t", observation_id="o"))
    assert registry.get(run_id) == LangfuseIds(trace_id="t", observation_id="o")
    assert registry.latest() == LangfuseIds(trace_id="t", observation_id="o")
    assert registry.pop(run_id) == LangfuseIds(trace_id="t", observation_id="o")
    assert registry.get(run_id) is None
    assert registry.latest() is None


def test_tag_entities_is_a_no_op_when_not_installed() -> None:
    tag_entities(["acc-1"])  # must not raise, must open nothing


def test_tag_entities_accumulates_per_trace_and_re_emits_the_whole_set() -> None:
    with langfuse_installed() as (exporter, _provider):
        with (
            propagate_trace(trace_name="head-of-abm.turn", session_id="t-1", tags=("head_of_abm",)),
            observation("turn", as_type="agent"),
        ):
            tag_entities(["acc-1", "", None])
            tag_entities(["con-9", "acc-1"])
        with observation("another-trace", as_type="agent"):
            tag_entities(["con-2"])
        spans = finished_spans(exporter)
    tagged = [s for s in spans if s.name == "entities.tagged"]
    assert len(tagged) == 3
    first, second, third = (_attrs(s) for s in tagged)
    assert first["langfuse.trace.tags"] == ("head_of_abm", "entity:acc-1")
    assert first["langfuse.trace.metadata.entities"] == "acc-1"
    assert second["langfuse.trace.tags"] == ("head_of_abm", "entity:acc-1", "entity:con-9")
    assert second["langfuse.trace.metadata.entities"] == "acc-1,con-9"
    assert second["langfuse.trace.name"] == "head-of-abm.turn"
    assert second["session.id"] == "t-1"
    assert json.loads(second["langfuse.observation.output"]) == {"entities": ["acc-1", "con-9"]}
    # A different trace starts a fresh set.
    assert third["langfuse.trace.metadata.entities"] == "con-2"
    assert third["langfuse.trace.tags"] == ("entity:con-2",)
    turn = next(s for s in tagged if _attrs(s)["langfuse.trace.metadata.entities"] == "acc-1")
    assert format(turn.context.trace_id, "032x") != format(tagged[2].context.trace_id, "032x")


def test_tag_entities_with_no_current_trace_opens_nothing() -> None:
    with langfuse_installed() as (exporter, _provider):
        tag_entities(["acc-1"])  # no span is current: nowhere to tag
        spans = finished_spans(exporter)
    assert [s.name for s in spans] == []


def test_tag_entities_from_child_tasks_shares_one_accumulator() -> None:
    import asyncio

    async def scenario() -> None:
        with observation("root", as_type="agent"), propagate_trace(trace_name="t"):
            await asyncio.create_task(asyncio.to_thread(tag_entities, ["acc-1"]))
            await asyncio.create_task(asyncio.to_thread(tag_entities, ["con-2"]))

    with langfuse_installed() as (exporter, _provider):
        asyncio.run(scenario())
        spans = finished_spans(exporter)
    sets = [
        _attrs(s)["langfuse.trace.metadata.entities"] for s in spans if s.name == "entities.tagged"
    ]
    assert sets == ["acc-1", "acc-1,con-2"]
