"""The provider-incident recorder in its shared home (``clue_spend.incidents``, design 2026-10-31).

What this file adds on top of ``tests/api/test_provider_incidents_db.py`` (which keeps proving the
original open/count/close rules through the platform's re-export): the alert tag the Sentry email
rule matches on, the late send of an open event no process could send, the design-provider
override on a stamped ledger row, and how a missing-key incident names itself.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import text

from clue_core.provider_failures import ProviderFailure
from clue_spend.incidents import provider_display, record_failure, record_success
from clue_spend.ledger import _stamped_failure
from clue_spend.sinks import LedgerRow
from tests.api.test_provider_incidents_db import StubTransport
from tests.claimstore.conftest import rollback_conn
from tests.db.conftest import run_async

NOW = datetime(2026, 10, 31, 9, 0, tzinfo=UTC)
NO_CREDIT = ProviderFailure("pdl", "refusal", "credits_exhausted", "Payment Required")


def _tags(event: dict) -> dict:
    tags = event.get("tags") or {}
    return dict(tags)


def test_open_event_carries_the_alert_tag_and_close_event_does_not(
    require_claimstore_db: None, sentry: StubTransport
) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            await record_failure(
                conn, NO_CREDIT, surface="onboarding", workspace_id="ws_a", now=NOW
            )
            await record_success(conn, "pdl", now=NOW + timedelta(minutes=3))

    run_async(scenario())
    opened, closed = sentry.events
    assert opened["level"] == "error" and _tags(opened)["alert"] == "provider"
    assert closed["level"] == "info" and "alert" not in _tags(closed)


def test_an_unsent_open_event_is_sent_by_the_next_recorder(
    require_claimstore_db: None, sentry: StubTransport
) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            # An incident opened by a process with no Sentry: the row exists, nobody was told.
            await conn.execute(
                text(
                    "INSERT INTO provider_incident (incident_id, provider, kind, reason, "
                    "opened_at, last_failure_at, failure_count, sample_message) "
                    "VALUES (:id, 'pdl', "
                    "'refusal', 'credits_exhausted', :now, :now, 1, 'Payment Required')"
                ),
                {"id": uuid4(), "now": NOW},
            )
            later = NOW + timedelta(minutes=1)
            first = await record_failure(
                conn, NO_CREDIT, surface="onboarding", workspace_id=None, now=later
            )
            assert first is not None and first.notified
            await record_failure(
                conn, NO_CREDIT, surface="onboarding", workspace_id=None, now=later
            )

    run_async(scenario())
    assert [event["level"] for event in sentry.events] == ["error"]


def test_stamped_failure_prefers_the_override_provider() -> None:
    row = LedgerRow(
        row_id="r",
        call_id="c",
        phase="result",
        provider="openrouter",
        operation="design.image",
        label="image",
        recorded_at=NOW,
        http_status=402,
        attempts=1,
        outcome="client_error",
        extras={
            "provider_failure": {
                "kind": "refusal",
                "reason": "credits_exhausted",
                "message": "m",
                "provider": "openrouter_design",
            }
        },
    )
    failure = _stamped_failure(row)
    assert failure is not None and failure.provider == "openrouter_design"


def test_a_missing_key_incident_names_its_env_and_role() -> None:
    shown = provider_display("worker:ADYNTEL_API_KEY")
    assert "ADYNTEL_API_KEY" in shown and "(worker)" in shown


def test_design_side_throttling_reaches_its_own_threshold(
    require_claimstore_db: None,
) -> None:
    """Final-review minor: design rows stay provider='openrouter' in the ledger, so the 3-in-5
    count must read the incident provider they name, or design throttling never opens."""
    from clue_api.arv2.provider_ledger import _INSERT_LEDGER, LedgerStamp, _ledger_params

    throttled = ProviderFailure("openrouter_design", "failure", "rate_limited", "slow down")

    async def scenario():
        async with rollback_conn(seed_pack=False) as conn:
            for i in range(3):
                row = LedgerRow(
                    row_id=str(uuid4()),
                    call_id=str(uuid4()),
                    phase="result",
                    provider="openrouter",
                    operation="design.ingestion.describe",
                    label="describe",
                    recorded_at=NOW + timedelta(seconds=i),
                    http_status=429,
                    attempts=4,
                    outcome="retry_exhausted",
                    extras={
                        "incident_provider": "openrouter_design",
                        "provider_failure": {
                            "kind": "failure",
                            "reason": "rate_limited",
                            "message": "slow down",
                            "provider": "openrouter_design",
                        },
                    },
                )
                await conn.execute(
                    _INSERT_LEDGER,
                    _ledger_params(row, stamp=LedgerStamp(workspace_id="ws_d"), keys={}),
                )
            return await record_failure(
                conn,
                throttled,
                surface="design",
                workspace_id="ws_d",
                now=NOW + timedelta(seconds=5),
            )

    opened = run_async(scenario())
    assert opened is not None and opened.provider == "openrouter_design"


def test_two_processes_recording_at_once_open_one_incident_and_one_event(
    require_claimstore_db: None, sentry: StubTransport
) -> None:
    """Two writers on two connections (two worker processes) record the same refusal at the same
    moment: the partial unique index lets exactly one insert win, the other counts onto it, and
    exactly one Sentry event goes out."""
    import asyncio

    from sqlalchemy import text as sql

    from clue_db import create_engine

    provider = f"race_{uuid4().hex[:8]}"
    failure = ProviderFailure(provider, "refusal", "credits_exhausted", "Payment Required")

    async def scenario() -> tuple[int, int]:
        engine = create_engine()
        try:
            gate = asyncio.Barrier(2)

            async def writer() -> None:
                async with engine.begin() as conn:
                    await gate.wait()
                    await record_failure(
                        conn, failure, surface="research_job", workspace_id=None, now=NOW
                    )

            await asyncio.gather(writer(), writer())
            async with engine.begin() as conn:
                rows = (
                    await conn.execute(
                        sql(
                            "SELECT failure_count FROM provider_incident "
                            "WHERE provider = :p AND closed_at IS NULL"
                        ),
                        {"p": provider},
                    )
                ).all()
                await conn.execute(
                    sql("DELETE FROM provider_incident WHERE provider = :p"), {"p": provider}
                )
            return len(rows), rows[0].failure_count if rows else 0
        finally:
            await engine.dispose()

    assert run_async(scenario()) == (1, 2)
    assert [e["level"] for e in sentry.events if provider in json.dumps(e)] == ["error"]


def test_one_exa_outage_sends_one_email_for_search_and_websets(
    require_claimstore_db: None, sentry: StubTransport
) -> None:
    """Exa search and Exa Websets bill one Exa account: when the account runs dry both refuse.
    The second incident shares the first one's Sentry event instead of sending its own."""

    async def scenario():
        async with rollback_conn(seed_pack=False) as conn:
            first = await record_failure(
                conn,
                ProviderFailure("exa", "refusal", "credits_exhausted", "NO_MORE_CREDITS"),
                surface="research_job",
                workspace_id=None,
                now=NOW,
            )
            second = await record_failure(
                conn,
                ProviderFailure("exa_websets", "refusal", "credits_exhausted", "payment_required"),
                surface="discovery",
                workspace_id=None,
                now=NOW + timedelta(seconds=30),
            )
            return first, second

    first, second = run_async(scenario())
    assert first is not None and second is not None
    assert first.notified and second.notified  # the card still says "Clue has been notified."
    assert [e["level"] for e in sentry.events] == ["error"]


def test_different_reasons_on_one_account_still_alert_separately(
    require_claimstore_db: None, sentry: StubTransport
) -> None:
    async def scenario():
        async with rollback_conn(seed_pack=False) as conn:
            await record_failure(
                conn,
                ProviderFailure("exa", "refusal", "credits_exhausted", "NO_MORE_CREDITS"),
                surface="research_job",
                workspace_id=None,
                now=NOW,
            )
            await record_failure(
                conn,
                ProviderFailure("exa_websets", "refusal", "auth_invalid", "bad key"),
                surface="discovery",
                workspace_id=None,
                now=NOW,
            )

    run_async(scenario())
    assert [e["level"] for e in sentry.events] == ["error", "error"]



def test_a_keyless_provider_is_tagged_for_the_email_like_any_other(
    require_claimstore_db: None, sentry: StubTransport
) -> None:
    """Founder ruling 2026-10-31: keyless downloads (public media, the website fetch) stay in scope.
    Their refusals open an incident and email the founders like every other provider's."""

    async def scenario():
        async with rollback_conn(seed_pack=False) as conn:
            await record_failure(
                conn,
                ProviderFailure("public_media", "refusal", "auth_invalid", "403 Forbidden"),
                surface="research_job",
                workspace_id=None,
                now=NOW,
            )

    run_async(scenario())
    (event,) = sentry.events
    assert _tags(event)["alert"] == "provider"
