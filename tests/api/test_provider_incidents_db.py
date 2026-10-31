"""The incident recorder on the lane database: open once, count, close once, tell Sentry twice."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import sentry_sdk
from sentry_sdk.transport import Transport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.provider_ledger import _INSERT_LEDGER as INSERT_LEDGER
from clue_api.arv2.provider_ledger import LedgerStamp
from clue_api.arv2.provider_ledger import _ledger_params as ledger_params
from clue_api.arv2.sinks import LedgerRow
from clue_api.provider_incidents import _INSERT as INSERT_STATEMENT
from clue_api.provider_incidents import (
    FAILURE_THRESHOLD,
    OpenIncident,
    incident_sentence,
    open_incidents,
    record_failure,
    record_success,
)
from clue_core.provider_failures import ProviderFailure
from clue_obs import sentry as sentry_state
from clue_obs.sentry import install_sentry

# The claim-store harness lives in a sibling test package; a fixture is only visible to a module
# that imports it, so re-export all three (``require_claimstore_db`` depends on ``migrated_db``).
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
)
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

NOW = datetime(2026, 9, 16, 10, 31, 23, tzinfo=UTC)
KEY_LIMIT = ProviderFailure(
    "openrouter", "refusal", "key_limit", "Key limit exceeded (weekly limit)"
)
FIVE_OH_THREE = ProviderFailure("exa", "failure", "server_error", "upstream unavailable")


async def seed_failed_call(conn: AsyncConnection, *, provider: str, at: datetime) -> None:
    """Write what a writer writes before it tells the recorder: one classified-failure ``result``
    row in ``provider_call_ledger``.

    The row goes in through the drain's own statement and parameter builder rather than through
    :func:`drain_provider_calls` itself, because from Task 3 on the drain *is* a writer: it calls
    the recorder for every stamped failure it lands. Seeding through it here would tell the
    recorder twice per call and the threshold arithmetic below would be measuring the double.
    That the drain records is Task 3's own test (``tests/arv2/test_provider_ledger_db.py``).
    """
    row = LedgerRow(
        row_id=str(uuid4()),
        call_id=str(uuid4()),
        phase="result",
        provider=provider,
        operation="answer",
        label="discovery:x",
        recorded_at=at,
        http_status=503,
        attempts=1,
        outcome="client_error",
        extras={
            "provider_failure": {
                "kind": "failure",
                "reason": "server_error",
                "message": "503",
            },
            "cost_source": "estimate",
        },
    )
    await conn.execute(
        INSERT_LEDGER,
        ledger_params(row, stamp=LedgerStamp(workspace_id="ws_incidents"), keys={}),
    )


class StubTransport(Transport):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[dict[str, Any]] = []

    def capture_envelope(self, envelope: Any) -> None:
        event = envelope.get_event()
        if event is not None:
            self.events.append(event)


@pytest.fixture
def sentry(monkeypatch: pytest.MonkeyPatch) -> Iterator[StubTransport]:
    # Installation changes process-global state. Restore both the SDK client and the wrapper's
    # flag so later read-surface tests do not inherit a fake "Clue has been notified" result.
    scope = sentry_sdk.get_global_scope()
    previous_client = scope.client
    monkeypatch.setattr(sentry_state, "_installed", sentry_state.sentry_is_installed())
    transport = StubTransport()
    assert install_sentry(
        dsn="https://k@o1.ingest.sentry.io/1",
        environment="test",
        release=None,
        process_name="t",
        transport=transport,
    )
    installed_client = scope.client
    try:
        yield transport
    finally:
        try:
            installed_client.close()
        finally:
            scope.set_client(previous_client)


def test_a_refusal_opens_once_counts_afterwards_and_closes_on_success(
    sentry: StubTransport,
) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            opened = await record_failure(
                conn, KEY_LIMIT, surface="research_job", workspace_id="ws_a", now=NOW
            )
            assert opened is not None and opened.failure_count == 1 and opened.notified
            again = await record_failure(
                conn,
                KEY_LIMIT,
                surface="display_section",
                workspace_id="ws_b",
                now=NOW + timedelta(seconds=12),
            )
            assert again is not None and again.incident_id == opened.incident_id
            assert again.failure_count == 2
            assert again.surfaces == {"research_job": 1, "display_section": 1}
            (live,) = await open_incidents(conn, providers=["openrouter"])
            assert live.incident_id == opened.incident_id
            closed = await record_success(
                conn, "openrouter", now=NOW + timedelta(hours=2, minutes=14)
            )
            assert [c.incident_id for c in closed] == [opened.incident_id]
            assert await open_incidents(conn) == ()
            row = (
                await conn.execute(
                    text(
                        "SELECT closed_at, sentry_open_event_id, sentry_close_event_id "
                        "FROM provider_incident WHERE incident_id = :id"
                    ),
                    {"id": opened.incident_id},
                )
            ).one()
            assert row.closed_at is not None
            assert row.sentry_open_event_id and row.sentry_close_event_id

    run_async(scenario())
    titles = [e.get("message") or e.get("logentry", {}).get("message") for e in sentry.events]
    assert titles == [
        "Model provider refused: key limit exceeded",
        "Model provider recovered after 2h 14m — 2 calls failed "
        "(1 research job, 1 overview section)",
    ]
    assert [e["level"] for e in sentry.events] == ["error", "info"]
    assert sentry.events[0]["tags"]["provider"] == "openrouter"
    assert sentry.events[0]["tags"]["reason"] == "key_limit"
    assert sentry.events[0]["fingerprint"] == sentry.events[1]["fingerprint"]


def test_failures_open_only_at_the_threshold_inside_the_window(sentry: StubTransport) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            for n in range(FAILURE_THRESHOLD - 1):
                at = NOW + timedelta(seconds=n)
                await seed_failed_call(conn, provider="exa", at=at)
                assert (
                    await record_failure(
                        conn, FIVE_OH_THREE, surface="discovery", workspace_id=None, now=at
                    )
                    is None
                )
            assert await open_incidents(conn) == ()
            at = NOW + timedelta(seconds=5)
            await seed_failed_call(conn, provider="exa", at=at)
            opened = await record_failure(
                conn, FIVE_OH_THREE, surface="discovery", workspace_id=None, now=at
            )
            assert opened is not None
            assert opened.kind == "failure" and opened.failure_count == FAILURE_THRESHOLD
            # An old failure outside the window does not count toward a new incident: half an hour
            # later only that one call is inside the five-minute window.
            await record_success(conn, "exa", now=NOW + timedelta(minutes=1))
            later = NOW + timedelta(minutes=30)
            await seed_failed_call(conn, provider="exa", at=later)
            assert (
                await record_failure(
                    conn, FIVE_OH_THREE, surface="discovery", workspace_id=None, now=later
                )
                is None
            )

    run_async(scenario())
    assert [e["level"] for e in sentry.events] == ["error", "info"]
    first = sentry.events[0].get("message") or sentry.events[0]["logentry"]["message"]
    assert first == "Discovery provider failing: server errors"


def test_a_second_open_on_the_same_provider_and_reason_does_not_insert(
    sentry: StubTransport,
) -> None:
    """The partial unique index is the open-once rule: a second insert for the same
    ``(provider, reason)`` conflicts and returns nothing, so only the first one tells Sentry."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            first = await record_failure(
                conn, KEY_LIMIT, surface="chat_turn", workspace_id="ws_a", now=NOW
            )
            second = await record_failure(
                conn,
                KEY_LIMIT,
                surface="research_job",
                workspace_id="ws_a",
                now=NOW + timedelta(seconds=3),
            )
            assert first is not None and second is not None
            assert second.incident_id == first.incident_id and second.failure_count == 2
            conflicted = (
                await conn.execute(
                    INSERT_STATEMENT,
                    {
                        "id": uuid.uuid4(),
                        "provider": KEY_LIMIT.provider,
                        "kind": KEY_LIMIT.kind,
                        "reason": KEY_LIMIT.reason,
                        "now": NOW + timedelta(seconds=4),
                        "count": 1,
                        "message": KEY_LIMIT.message,
                        "surfaces": "{}",
                        "workspaces": "[]",
                    },
                )
            ).first()
            assert conflicted is None

    run_async(scenario())
    assert len([e for e in sentry.events if e["level"] == "error"]) == 1


def test_the_recorder_never_raises_into_the_call_it_observes() -> None:
    class BrokenConn:
        async def execute(self, *a: Any, **k: Any) -> Any:
            raise RuntimeError("db down")

    async def scenario() -> None:
        assert (
            await record_failure(BrokenConn(), KEY_LIMIT, surface="x", workspace_id=None, now=NOW)  # type: ignore[arg-type]
            is None
        )
        assert await record_success(BrokenConn(), "openrouter", now=NOW) == ()  # type: ignore[arg-type]
        assert await open_incidents(BrokenConn()) == ()  # type: ignore[arg-type]

    run_async(scenario())


def test_the_inline_sentence_reads_as_the_founder_approved() -> None:
    since = datetime(2026, 9, 16, 16, 1, tzinfo=UTC)
    assert incident_sentence(
        provider="openrouter",
        kind="refusal",
        reason="key_limit",
        since=since,
        affected=45,
        unit="jobs",
        notified=True,
    ) == (
        "Model provider refused: key limit exceeded. "
        "Since 16:01, 45 jobs affected. Clue has been notified."
    )
    assert incident_sentence(
        provider="exa_websets",
        kind="refusal",
        reason="credits_exhausted",
        since=since,
        affected=None,
        unit="calls",
        notified=False,
    ) == ("Discovery provider refused: credits exhausted. Since 16:01.")
    assert incident_sentence(
        provider="openrouter",
        kind="failure",
        reason="server_error",
        since=since,
        affected=7,
        unit="calls",
        notified=True,
    ) == (
        "Model provider failing: server errors. "
        "Since 16:01, 7 calls affected. Clue has been notified."
    )


def test_customer_readers_ignore_key_missing_and_design_incidents() -> None:
    """Design 2026-10-31: alert-only incidents never reach a customer surface. The overview and
    research-card readers ask for the research provider's incidents by id (``openrouter``, or the
    job's own provider), and neither a design refusal nor a missing key is filed under one."""

    async def scenario() -> tuple[OpenIncident, ...]:
        async with rollback_conn(seed_pack=False) as conn:
            await record_failure(
                conn,
                ProviderFailure("openrouter_design", "refusal", "credits_exhausted", "no credit"),
                surface="design",
                workspace_id="ws_a",
                now=NOW,
            )
            await record_failure(
                conn,
                ProviderFailure(
                    "platform-api:CLUE_OPENROUTER_API_KEY",
                    "refusal",
                    "key_missing",
                    "CLUE_OPENROUTER_API_KEY is not set",
                ),
                surface="startup",
                workspace_id=None,
                now=NOW,
            )
            return await open_incidents(conn, providers=["openrouter"])

    assert run_async(scenario()) == ()
