"""The start-up key check (design 2026-10-31 §6.3): one ``key_missing`` incident per role and env
name, closed only by that role's own next start-up with the key in place."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from clue_spend import key_check
from clue_spend.incidents import open_incidents, record_success
from clue_spend.key_check import PROVIDER_KEYS, check_provider_keys, provider_for_env
from tests.api.test_provider_incidents_db import StubTransport
from tests.claimstore.conftest import rollback_conn
from tests.db.conftest import run_async

NOW = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)


def _run(steps):
    """Run ``steps(conn, factory)`` on one rolled-back connection shared by every check."""

    async def scenario():
        async with rollback_conn(seed_pack=False) as conn:

            @asynccontextmanager
            async def same():
                yield conn

            return await steps(conn, same)

    return run_async(scenario())


def test_a_missing_key_opens_one_incident_per_role_and_env(
    require_claimstore_db: None, sentry: StubTransport
) -> None:
    async def steps(conn, factory):
        await check_provider_keys(factory, role="worker", environ={}, now=NOW)
        await check_provider_keys(
            factory, role="worker", environ={}, now=NOW + timedelta(minutes=1)
        )
        return await open_incidents(conn, providers=["worker:PDL_API_KEY"])

    (incident,) = _run(steps)
    assert (incident.kind, incident.reason) == ("refusal", "key_missing")
    assert incident.sample_message == "PDL_API_KEY is not set"
    assert incident.failure_count == 2
    pdl_events = [
        e for e in sentry.events if "PDL_API_KEY" in str(e.get("message") or e.get("logentry"))
    ]
    assert len(pdl_events) == 1


def test_a_fallback_name_satisfies_the_requirement(require_claimstore_db: None) -> None:
    async def steps(conn, factory):
        await check_provider_keys(
            factory, role="worker", environ={"DEEPGRAM_API_KEY": "dg"}, now=NOW
        )
        return await open_incidents(conn, providers=["worker:CLUE_DEEPGRAM_API_KEY"])

    assert _run(steps) == ()


def test_present_in_one_role_does_not_close_another_roles_incident(
    require_claimstore_db: None,
) -> None:
    everything = {name: "set" for requirement in PROVIDER_KEYS for name in requirement.env_names}

    async def steps(conn, factory):
        await check_provider_keys(factory, role="worker", environ={}, now=NOW)
        await check_provider_keys(factory, role="platform-api", environ=everything, now=NOW)
        await record_success(conn, "pdl", now=NOW + timedelta(minutes=2))
        return await open_incidents(conn, providers=["worker:PDL_API_KEY"])

    assert len(_run(steps)) == 1


def test_the_same_role_with_the_key_closes_it(
    require_claimstore_db: None, sentry: StubTransport
) -> None:
    async def steps(conn, factory):
        await check_provider_keys(factory, role="worker", environ={}, now=NOW)
        await check_provider_keys(
            factory, role="worker", environ={"PDL_API_KEY": "k"}, now=NOW + timedelta(hours=1)
        )
        return await open_incidents(conn, providers=["worker:PDL_API_KEY"])

    assert _run(steps) == ()
    closes = [e for e in sentry.events if e["level"] == "info" and "PDL_API_KEY" in json.dumps(e)]
    assert len(closes) == 1


def test_a_key_value_never_reaches_sentry_or_the_incident(
    require_claimstore_db: None, sentry: StubTransport
) -> None:
    async def steps(conn, factory):
        await check_provider_keys(
            factory,
            role="worker",
            environ={"PDL_API_KEY": "   ", "ADYNTEL_API_KEY": "secret-value-123"},
            now=NOW,
        )
        return await open_incidents(conn)

    live = _run(steps)
    assert any(i.provider == "worker:PDL_API_KEY" for i in live)
    assert "secret-value-123" not in json.dumps([i.sample_message for i in live])
    assert "secret-value-123" not in json.dumps(sentry.events, default=str)


def test_the_check_never_raises() -> None:
    @asynccontextmanager
    async def broken():
        raise RuntimeError("database went away")
        yield  # pragma: no cover

    run_async(check_provider_keys(broken, role="worker", environ={}, now=NOW))


def test_left_out_providers_are_not_checked() -> None:
    names = {name for requirement in PROVIDER_KEYS for name in requirement.env_names}
    for left_out in (
        "CLUE_ZOOMINFO_API_KEY",
        "CLUE_CLAY_API_KEY",
        "CLUE_APOLLO_API_KEY",
        "CLUE_BUILTWITH_API_KEY",
        "CLUE_DUNS_API_KEY",
        "CLUE_FIRECRAWL_API_KEY",
        "CLUE_SUMBLE_API_KEY",
    ):
        assert left_out not in names


def test_every_requirement_names_a_known_role_and_a_provider() -> None:
    for requirement in PROVIDER_KEYS:
        assert requirement.roles <= key_check.ROLES and requirement.roles
        assert provider_for_env(requirement.env_names[0]) == requirement.provider


def test_a_failed_check_logs_no_traceback_that_could_carry_keys() -> None:
    """Final review: the check holds every secret in ``environ``; a traceback rendered with its
    locals (the dev console's renderer does that) would print them. The failure is logged by type
    only."""
    from structlog.testing import capture_logs

    @asynccontextmanager
    async def broken():
        raise RuntimeError("database went away")
        yield  # pragma: no cover

    with capture_logs() as logs:
        run_async(
            check_provider_keys(
                broken, role="worker", environ={"PDL_API_KEY": "secret-value-123"}, now=NOW
            )
        )
    (entry,) = [e for e in logs if e["event"] == "provider_keys.check_failed"]
    assert "exc_info" not in entry
    assert entry["error"] == "RuntimeError"
    assert "secret-value-123" not in json.dumps(entry, default=str)


def test_an_incident_for_a_key_no_longer_on_the_list_is_closed_by_its_role(
    require_claimstore_db: None,
) -> None:
    from clue_core.provider_failures import ProviderFailure
    from clue_spend.incidents import record_failure

    everything = {name: "set" for requirement in PROVIDER_KEYS for name in requirement.env_names}

    async def steps(conn, factory):
        for name in ("worker:RETIRED_API_KEY", "platform-api:RETIRED_API_KEY"):
            await record_failure(
                conn,
                ProviderFailure(name, "refusal", "key_missing", "RETIRED_API_KEY is not set"),
                surface="startup",
                workspace_id=None,
                now=NOW,
            )
        await check_provider_keys(factory, role="worker", environ=everything, now=NOW)
        return {i.provider for i in await open_incidents(conn)}

    still_open = _run(steps)
    assert "worker:RETIRED_API_KEY" not in still_open
    assert "platform-api:RETIRED_API_KEY" in still_open  # another role's row is that role's


def test_any_start_up_sends_an_alert_nobody_could_send(
    require_claimstore_db: None, sentry: StubTransport
) -> None:
    from uuid import uuid4

    from sqlalchemy import text

    everything = {name: "set" for requirement in PROVIDER_KEYS for name in requirement.env_names}

    async def steps(conn, factory):
        await conn.execute(
            text(
                "INSERT INTO provider_incident (incident_id, provider, kind, reason, opened_at, "
                "last_failure_at, failure_count, sample_message) VALUES "
                "(:id, 'pdl', 'refusal', 'credits_exhausted', :now, :now, 1, 'Payment Required')"
            ),
            {"id": uuid4(), "now": NOW},
        )
        await check_provider_keys(factory, role="design-api", environ=everything, now=NOW)
        (row,) = await open_incidents(conn, providers=["pdl"])
        return row

    row = _run(steps)
    assert row.notified
    assert [e["level"] for e in sentry.events] == ["error"]


def test_startup_environ_reads_every_env_file_and_the_process_wins(tmp_path, monkeypatch) -> None:
    from clue_spend.key_check import startup_environ

    first, second = tmp_path / ".env", tmp_path / ".env.local"
    first.write_text("PDL_API_KEY=from-env\nADYNTEL_API_KEY=from-env\n")
    second.write_text("ADYNTEL_API_KEY=from-local\nBRANDFETCH_API_KEY=from-local\n")
    for name in ("PDL_API_KEY", "ADYNTEL_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("BRANDFETCH_API_KEY", "from-process")
    values = startup_environ([str(first), str(second)])
    assert values["PDL_API_KEY"] == "from-env"
    assert values["ADYNTEL_API_KEY"] == "from-local"
    assert values["BRANDFETCH_API_KEY"] == "from-process"
