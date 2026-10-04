"""The Images-API call is priced from OpenRouter's own metering, never a stand-in zero.

Live 2026-10-04 (`openai/gpt-image-2.5-flare`, a BYOK key): the response body has no `id` — the
generation id is the `x-generation-id` header — and it carries a `usage` block whose `cost` is 0
while `cost_details.upstream_inference_cost` holds what OpenAI charged. The old reader looked for a
body `id`, found none, and the row was written as an estimate of $0.
"""

from __future__ import annotations

import json
from decimal import Decimal

from clue_spend import HttpResponse

from lumen_api import spend

LIVE_SHAPE = {
    "created": 1791126201,
    "data": [{"b64_json": "iVBORw0KGgo=", "media_type": "image/png"}],
    "usage": {
        "prompt_tokens": 15,
        "completion_tokens": 1756,
        "total_tokens": 1771,
        "cost": 0,
        "is_byok": True,
        "prompt_tokens_details": {"cached_tokens": 0},
        "cost_details": {
            "upstream_inference_cost": 0.052755,
            "upstream_inference_prompt_cost": 7.5e-05,
            "upstream_inference_completions_cost": 0.05268,
        },
        "completion_tokens_details": {"reasoning_tokens": 0, "image_tokens": 1756},
    },
}


def response(payload: dict, headers: dict | None = None) -> HttpResponse:
    return HttpResponse(200, headers or {}, json.dumps(payload).encode("utf-8"))


def test_the_usage_block_prices_the_call_and_the_header_names_it(monkeypatch) -> None:
    monkeypatch.setattr(spend, "_generation_lookup", lambda: (_ for _ in ()).throw(AssertionError))
    reading = spend.image_generation_cost_reader(
        response(LIVE_SHAPE, {"x-generation-id": "gen-img-1791126188-KP7h"})
    )
    assert reading.cost_usd == Decimal("0.052755")
    assert reading.provider_request_id == "gen-img-1791126188-KP7h"
    assert reading.extras["generation_id"] == "gen-img-1791126188-KP7h"
    assert reading.extras["completion_tokens"] == 1756


def test_without_usage_the_generation_lookup_uses_the_header_id(monkeypatch) -> None:
    asked: list[str] = []

    class Lookup:
        def cost_cents(self, generation_id: str):
            asked.append(generation_id)
            return Decimal("5.2755")

    monkeypatch.setattr(spend, "_generation_lookup", lambda: Lookup())
    payload = {k: v for k, v in LIVE_SHAPE.items() if k != "usage"}
    reading = spend.image_generation_cost_reader(response(payload, {"x-generation-id": "gen-img-2"}))
    assert asked == ["gen-img-2"]
    assert reading.cost_usd == Decimal("0.052755")
    assert reading.provider_request_id == "gen-img-2"


def test_no_usage_and_no_id_is_an_honest_unknown(monkeypatch) -> None:
    monkeypatch.setattr(spend, "_generation_lookup", lambda: (_ for _ in ()).throw(AssertionError))
    payload = {k: v for k, v in LIVE_SHAPE.items() if k != "usage"}
    reading = spend.image_generation_cost_reader(response(payload))
    assert reading.cost_usd is None


# --- drain_safely: a transient database fault must not drop a turn's spend --------------------


def _scope_with_rows(n: int):
    from datetime import UTC, datetime

    from clue_spend import LedgerRow, LedgerStamp

    with spend.spend_scope(LedgerStamp(workspace_id="ws_drain")) as scope:
        for i in range(n):
            scope.ledger.record(
                LedgerRow(
                    row_id=f"r{i}", call_id=f"c{i}", phase="result", provider="openrouter",
                    operation="design.image.generate", label="image:x",
                    recorded_at=datetime.now(UTC), cost_usd=Decimal("0.05"), outcome="ok",
                )
            )
    return scope


def test_drain_safely_retries_and_lands_every_row(monkeypatch) -> None:
    scope = _scope_with_rows(3)
    landed: list[str] = []
    failures = iter([True, True, False])

    def flaky_drain(staged):
        rows = staged.ledger.drain()  # the library drain empties its buffer BEFORE inserting
        if next(failures):
            raise ConnectionError("sorry, too many clients already")
        landed.extend(row.row_id for row in rows)

    monkeypatch.setattr(spend, "drain_sync", flaky_drain)
    spend.drain_safely(scope, sleep=lambda _s: None)
    assert landed == ["r0", "r1", "r2"]
    assert scope.ledger.rows == ()


def test_drain_safely_reports_what_it_lost_when_every_attempt_fails(monkeypatch, caplog) -> None:
    scope = _scope_with_rows(2)

    def dead_drain(staged):
        staged.ledger.drain()
        raise ConnectionError("sorry, too many clients already")

    monkeypatch.setattr(spend, "drain_sync", dead_drain)
    with caplog.at_level("ERROR"):
        spend.drain_safely(scope, sleep=lambda _s: None)
    message = " ".join(record.getMessage() for record in caplog.records if record.levelname == "ERROR")
    assert "rows_lost=2" in message and "usd_lost=0.10" in message
    assert len(scope.ledger.rows) == 2  # still held, never silently discarded
