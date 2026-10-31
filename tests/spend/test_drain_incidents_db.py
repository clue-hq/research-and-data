"""The shared ledger drain records provider incidents itself (design 2026-10-31 §6.4).

Before this, only the platform's wrapper (``clue_api.arv2.provider_ledger``) recorded incidents, so
a design request scope or an ingestion-pool coordinator — which drain through the bare library —
ledgered PDL's 402 and told nobody.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from clue_spend import incidents
from clue_spend.incidents import open_incidents
from clue_spend.ledger import (
    BufferedLedger,
    BufferedRawSink,
    LedgerStamp,
    drain_provider_calls,
)
from clue_spend.sinks import LedgerRow
from tests.api.test_provider_incidents_db import StubTransport
from tests.claimstore.conftest import rollback_conn
from tests.db.conftest import run_async

NOW = datetime(2026, 10, 31, 9, 0, tzinfo=UTC)
STAMP = LedgerStamp(workspace_id="ws_drain_incidents")


def _refusal(provider: str, at: datetime) -> LedgerRow:
    return LedgerRow(
        row_id=str(uuid4()),
        call_id=str(uuid4()),
        phase="result",
        provider=provider,
        operation="design.ad_library.identity",
        label="ad_library:company identity",
        recorded_at=at,
        http_status=402,
        attempts=1,
        outcome="client_error",
        credits=Decimal(1),
        extras={
            "provider_failure": {
                "kind": "refusal",
                "reason": "credits_exhausted",
                "message": "Payment Required",
            },
            "cost_source": "free",
        },
    )


def _drain_rows(rows: list[LedgerRow]):
    ledger = BufferedLedger()
    for row in rows:
        ledger.record(row)

    async def scenario():
        async with rollback_conn(seed_pack=False) as conn:
            report = await drain_provider_calls(
                conn, raw=BufferedRawSink(), ledger=ledger, artifacts=None, stamp=STAMP
            )
            return report, await open_incidents(conn, providers=[rows[0].provider])

    return run_async(scenario())


def test_the_bare_library_drain_opens_an_incident(require_claimstore_db: None) -> None:
    _, live = _drain_rows([_refusal("pdl", NOW)])
    assert [(i.provider, i.reason) for i in live] == [("pdl", "credits_exhausted")]


def test_two_hundred_refusals_in_one_drain_open_one_incident(
    require_claimstore_db: None, sentry: StubTransport
) -> None:
    rows = [_refusal("exa", NOW + timedelta(milliseconds=i)) for i in range(200)]
    report, live = _drain_rows(rows)
    assert report.rows == 200
    assert len(live) == 1 and live[0].failure_count == 200
    assert [event["level"] for event in sentry.events] == ["error"]


def test_a_drain_whose_recorder_fails_still_writes_its_rows(
    require_claimstore_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(*_args, **_kwargs):
        raise RuntimeError("database went away")

    monkeypatch.setattr(incidents, "record_failure", boom)
    monkeypatch.setattr(incidents, "record_success", boom)
    report, _ = _drain_rows([_refusal("pdl", NOW)])
    assert report.rows == 1


def test_a_recorder_sql_error_never_rolls_back_the_drains_own_rows(
    require_claimstore_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Final review #1: the recorder writes on the drain's connection. A database error inside it
    must not abort that transaction — the ledger rows are the money trail."""
    from sqlalchemy import text

    monkeypatch.setattr(
        incidents, "_INCREMENT", text("SELECT no_such_column FROM provider_incident")
    )
    ledger = BufferedLedger()
    row = _refusal("pdl", NOW)
    ledger.record(row)

    async def scenario() -> int:
        async with rollback_conn(seed_pack=False) as conn:
            await drain_provider_calls(
                conn, raw=BufferedRawSink(), ledger=ledger, artifacts=None, stamp=STAMP
            )
            # The transaction must still be usable: the drain's row is there to read back.
            return (
                await conn.execute(
                    text("SELECT count(*) FROM provider_call_ledger WHERE call_id = :c"),
                    {"c": row.call_id},
                )
            ).scalar_one()

    assert run_async(scenario()) == 1
