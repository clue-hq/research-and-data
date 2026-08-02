"""M6A D0 — executable, sanitized Exa Websets v0 payload fixtures."""

from __future__ import annotations

import hashlib
import json
import socket
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from clue_core import (
    DiscoveryItemSnapshot,
    DiscoveryNormalizationState,
    new_discovery_item_snapshot_id,
    new_discovery_operation_id,
)

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/discovery/exa_websets"


def _load(name: str) -> dict[str, Any]:
    value = json.loads((_FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_company_item_pages_cover_evaluations_nulls_and_cursor_exhaustion() -> None:
    first = _load("items-page-1.json")
    second = _load("items-page-2.json")

    assert first["hasMore"] is True
    assert first["nextCursor"] == "cursor_fixture_page_2"
    assert second["hasMore"] is False
    assert second["nextCursor"] is None

    items = [*first["data"], *second["data"]]
    assert all(item["properties"]["type"] == "company" for item in items)
    assert all(item["properties"]["company"]["name"] for item in items)
    assert {evaluation["satisfied"] for item in items for evaluation in item["evaluations"]} == {
        "yes",
        "no",
        "unclear",
    }
    assert any(enrichment["result"] is None for item in items for enrichment in item["enrichments"])


def test_event_fixture_is_both_duplicate_and_out_of_order() -> None:
    payload = _load("events-duplicate-out-of-order.json")
    events = payload["data"]
    ids = Counter(event["id"] for event in events)
    created = [event["createdAt"] for event in events]

    assert ids["evt_fixture_item_created"] == 2
    assert created != sorted(created)
    assert any(event["type"] == "webset.idle" for event in events)


def test_cancellation_fixture_keeps_canceled_operations_distinct_from_success() -> None:
    payload = _load("webset-cancelled.json")

    assert payload["searches"][0]["status"] == "canceled"
    assert payload["searches"][0]["canceledAt"] is not None
    assert payload["enrichments"][0]["status"] == "canceled"


def test_additive_schema_drift_is_preserved_in_the_raw_item_artifact() -> None:
    path = _FIXTURES / "schema-drift-additive.json"
    raw = path.read_bytes()
    payload = json.loads(raw)
    snapshot = DiscoveryItemSnapshot(
        item_snapshot_id=new_discovery_item_snapshot_id(),
        operation_id=new_discovery_operation_id(),
        provider_item_id=payload["id"],
        source_kind=payload["source"],
        source_id=payload["sourceId"],
        raw_artifact_key="fixture/schema-drift-additive.json",
        item_sha256=hashlib.sha256(raw).hexdigest(),
        observed_at=payload["updatedAt"],
        normalization_state=DiscoveryNormalizationState.RAW,
    )

    assert payload["futureTopLevelField"] == ["must", "remain", "in", "raw", "artifact"]
    assert payload["properties"]["company"]["futureHeadcountConfidence"] == 0.93
    assert snapshot.item_sha256 == hashlib.sha256(raw).hexdigest()


def test_all_exa_fixtures_are_secret_free_and_require_no_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _forbid_network(*_args: object, **_kwargs: object) -> socket.socket:
        raise AssertionError("D0 fixture validation must not open a network socket")

    # This is intentionally a local-file contract test. If a future fixture helper silently starts
    # fetching Exa, this monkeypatch turns it into an immediate D0 gate failure.
    monkeypatch.setattr(socket, "socket", _forbid_network)

    forbidden = ("authorization", "api_key", "x-api-key", "whsec_", "bearer ")
    for path in _FIXTURES.glob("*.json"):
        body = path.read_text(encoding="utf-8").lower()
        assert not any(secret_marker in body for secret_marker in forbidden), path.name
        json.loads(body)
