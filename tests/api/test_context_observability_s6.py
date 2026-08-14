"""S6-B/C privacy-safe metrics and body-free contract tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from clue_api.chat.context_refs import TurnContextRefsResponse
from clue_api.context_observability import (
    METRIC_CONTEXT_CARD_OMISSIONS,
    METRIC_CONTEXT_CARDS,
    METRIC_CONTEXT_RECEIPT_REFS,
    METRIC_CONTEXT_RECEIPTS,
    METRIC_CONTEXT_TOOL_OUTCOMES,
    record_context_card,
    record_context_receipt,
    record_context_tool_outcome,
)
from clue_obs.otel.metrics import InMemorySink


def _schema_field_names(schema: dict[str, Any]) -> set[str]:
    found: set[str] = set()
    stack: list[object] = [schema]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            properties = item.get("properties")
            if isinstance(properties, dict):
                found.update(str(key) for key in properties)
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return found


def test_context_metrics_use_only_bounded_operational_labels() -> None:
    sink = InMemorySink()
    record_context_card(
        card_kind="client_knowledge",
        schema_version="2",
        available=True,
        omitted_count=3,
        sink=sink,
    )
    record_context_card(
        card_kind="product_knowledge",
        schema_version="1",
        available=False,
        omitted_count=0,
        sink=sink,
    )
    record_context_receipt(
        schema_version="1",
        included_count=9,
        excluded_count=2,
        sink=sink,
    )
    record_context_tool_outcome(
        tool_address="inspect_client_claim@2",
        outcome="completed",
        replayed=False,
        sink=sink,
    )
    record_context_tool_outcome(
        tool_address="inspect_client_claim@2",
        outcome="completed",
        replayed=True,
        sink=sink,
    )

    assert (
        sink.counter(
            METRIC_CONTEXT_CARDS,
            card_kind="client_knowledge",
            schema_version="2",
            availability="available",
        )
        == 1
    )
    assert (
        sink.gauge_value(
            METRIC_CONTEXT_CARD_OMISSIONS,
            card_kind="client_knowledge",
            schema_version="2",
            availability="available",
        )
        == 3
    )
    assert sink.counter(METRIC_CONTEXT_RECEIPTS, schema_version="1") == 1
    assert (
        sink.gauge_value(
            METRIC_CONTEXT_RECEIPT_REFS,
            schema_version="1",
            disposition="included",
        )
        == 9
    )
    assert (
        sink.gauge_value(
            METRIC_CONTEXT_RECEIPT_REFS,
            schema_version="1",
            disposition="excluded",
        )
        == 2
    )
    assert (
        sink.counter(
            METRIC_CONTEXT_TOOL_OUTCOMES,
            tool_address="inspect_client_claim@2",
            outcome="completed",
            replayed="false",
        )
        == 1
    )
    assert (
        sink.counter(
            METRIC_CONTEXT_TOOL_OUTCOMES,
            tool_address="inspect_client_claim@2",
            outcome="completed",
            replayed="true",
        )
        == 1
    )

    allowed_attribute_keys = {
        "card_kind",
        "schema_version",
        "availability",
        "disposition",
        "tool_address",
        "outcome",
        "replayed",
    }
    all_keys = {
        key for _name, attributes in (*sink.counters, *sink.gauges) for key, _value in attributes
    }
    assert all_keys <= allowed_attribute_keys
    assert not {
        "workspace_id",
        "project_id",
        "client_entity_id",
        "product_id",
        "turn_id",
        "claim_id",
        "artifact_key",
        "content_sha256",
        "email",
        "token",
    }.intersection(all_keys)


def test_context_metric_helpers_refuse_impossible_negative_counts() -> None:
    with pytest.raises(ValueError, match="omission"):
        record_context_card(
            card_kind="client_knowledge",
            schema_version="2",
            available=True,
            omitted_count=-1,
            sink=InMemorySink(),
        )
    with pytest.raises(ValueError, match="receipt"):
        record_context_receipt(
            schema_version="1",
            included_count=0,
            excluded_count=-1,
            sink=InMemorySink(),
        )


def test_production_context_ref_schema_has_no_body_or_fact_channel() -> None:
    fields = _schema_field_names(TurnContextRefsResponse.model_json_schema())
    assert not {
        "body",
        "text",
        "value",
        "claim_value",
        "brief_value",
        "description",
        "evidence",
        "evidence_span",
        "source_url",
        "email",
        "token",
        "credential",
    }.intersection(fields)
    assert {
        "artifact_key",
        "artifact_sha256",
        "object_type",
        "object_id",
        "object_version",
        "content_sha256",
        "exclusion_reason_code",
    } <= fields


def test_context_observation_events_are_body_free_by_construction() -> None:
    root = Path(__file__).resolve().parents[2]
    sources = {
        "cards": (root / "platform/api/clue_api/agent_turn_fleet_wiring.py").read_text(),
        "receipts": (root / "platform/api/clue_api/agent_turn_wiring.py").read_text(),
        "tools": (root / "platform/api/clue_api/agent_execution_wiring.py").read_text(),
    }

    def event(source: str, name: str, metric_call: str) -> str:
        start = source.index(f'"{name}"')
        return source[start : source.index(metric_call, start)]

    events = {
        "cards": event(sources["cards"], "agent_turn.context_card", "record_context_card("),
        "receipts": event(
            sources["receipts"],
            "agent_turn.context_receipt",
            "record_context_receipt(",
        ),
        "tools": event(
            sources["tools"],
            "agent_turn.context_tool_outcome",
            "record_context_tool_outcome(",
        ),
    }
    forbidden = {
        "claim_value",
        "brief_value",
        "description",
        "evidence_span",
        "source_url",
        "raw_body",
        "email",
        "password",
        "credential",
        "access_token",
        "refresh_token",
    }
    for event in events.values():
        assert not forbidden.intersection(event)
