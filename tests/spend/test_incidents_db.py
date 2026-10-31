"""The provider-incident recorder in its shared home (``clue_spend.incidents``, design 2026-10-31).

What this file adds on top of ``tests/api/test_provider_incidents_db.py`` (which keeps proving the
original open/count/close rules through the platform's re-export): the alert tag the Sentry email
rule matches on, the late send of an open event no process could send, the design-provider
override on a stamped ledger row, and how a missing-key incident names itself.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import text

from clue_core.provider_failures import ProviderFailure
from clue_spend.incidents import provider_display, record_failure, record_success
from clue_spend.ledger import _stamped_failure
from clue_spend.sinks import LedgerRow
from tests.api.test_provider_incidents_db import StubTransport, sentry  # noqa: F401
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
)
from tests.db.conftest import run_async

NOW = datetime(2026, 10, 31, 9, 0, tzinfo=UTC)
NO_CREDIT = ProviderFailure("pdl", "refusal", "credits_exhausted", "Payment Required")


def _tags(event: dict) -> dict:
    tags = event.get("tags") or {}
    return dict(tags) if isinstance(tags, dict) else {k: v for k, v in tags}


def test_open_event_carries_the_alert_tag_and_close_event_does_not(
    require_claimstore_db: None, sentry: StubTransport
) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            await record_failure(conn, NO_CREDIT, surface="onboarding", workspace_id="ws_a", now=NOW)
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
                    "INSERT INTO provider_incident (incident_id, provider, kind, reason, opened_at, "
                    "last_failure_at, failure_count, sample_message) VALUES (:id, 'pdl', "
                    "'refusal', 'credits_exhausted', :now, :now, 1, 'Payment Required')"
                ),
                {"id": uuid4(), "now": NOW},
            )
            later = NOW + timedelta(minutes=1)
            first = await record_failure(
                conn, NO_CREDIT, surface="onboarding", workspace_id=None, now=later
            )
            assert first is not None and first.notified
            await record_failure(conn, NO_CREDIT, surface="onboarding", workspace_id=None, now=later)

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
