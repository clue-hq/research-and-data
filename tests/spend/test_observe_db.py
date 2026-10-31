"""``clue_spend.record_observed_call``: a client that keeps its own HTTP stack reports each answer
to the spend layer, which ledgers it and opens a provider incident on a refusal.

Design 2026-10-31.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import uuid4

from sqlalchemy import text

from clue_spend import record_observed_call
from clue_spend.incidents import open_incidents
from tests.claimstore.conftest import rollback_conn
from tests.db.conftest import run_async


def _observe(conn, provider: str, workspace_id: str | None, status: int, body: bytes):
    @asynccontextmanager
    async def same():
        yield conn

    return record_observed_call(
        provider=provider,
        conn_factory=same,
        workspace_id=workspace_id,
        operation=f"test.{provider}",
        label=f"{provider}:test",
        status=status,
        body=body,
        latency_ms=12,
    )


def test_an_answered_call_is_one_ok_result_row(require_claimstore_db: None) -> None:
    workspace = f"ws_observe_{uuid4().hex[:8]}"

    async def scenario():
        async with rollback_conn(seed_pack=False) as conn:
            await _observe(conn, "composio", workspace, 200, b"{}")
            return (
                await conn.execute(
                    text(
                        "SELECT provider, outcome, http_status, attempts FROM provider_call_ledger "
                        "WHERE workspace_id = :ws"
                    ),
                    {"ws": workspace},
                )
            ).all()

    rows = run_async(scenario())
    assert [tuple(r) for r in rows] == [("composio", "ok", 200, 1)]


def test_a_402_opens_an_incident_even_with_no_workspace(require_claimstore_db: None) -> None:
    async def scenario():
        async with rollback_conn(seed_pack=False) as conn:
            await _observe(
                conn, "cloudflare", None, 402, b'{"errors":[{"message":"payment required"}]}'
            )
            return await open_incidents(conn, providers=["cloudflare"])

    live = run_async(scenario())
    assert [(i.kind, i.reason) for i in live] == [("refusal", "credits_exhausted")]


def test_recording_never_raises() -> None:
    @asynccontextmanager
    async def broken():
        raise RuntimeError("database went away")
        yield  # pragma: no cover

    run_async(
        record_observed_call(
            provider="clerk",
            conn_factory=broken,
            workspace_id=None,
            operation="o",
            label="l",
            status=200,
            body=b"{}",
            latency_ms=1,
        )
    )


def test_an_unclassified_answer_is_ledgered_but_opens_no_incident(
    require_claimstore_db: None,
) -> None:
    async def scenario():
        async with rollback_conn(seed_pack=False) as conn:

            @asynccontextmanager
            async def same():
                yield conn

            await record_observed_call(
                provider="composio",
                conn_factory=same,
                workspace_id=None,
                operation="o",
                label="l",
                status=401,
                body=b"token expired",
                latency_ms=1,
                classify=False,
            )
            return await open_incidents(conn, providers=["composio"])

    assert run_async(scenario()) == ()


def test_a_server_error_is_retry_exhausted_and_a_billed_provider_is_an_estimate(
    require_claimstore_db: None,
) -> None:
    workspace = f"ws_observe_{uuid4().hex[:8]}"

    async def scenario():
        async with rollback_conn(seed_pack=False) as conn:

            @asynccontextmanager
            async def same():
                yield conn

            await record_observed_call(
                provider="exa_websets",
                conn_factory=same,
                workspace_id=workspace,
                operation="o",
                label="l",
                status=503,
                body=b"busy",
                latency_ms=1,
                cost_source="estimate",
            )
            return (
                await conn.execute(
                    text(
                        "SELECT outcome, extras_json ->> 'cost_source' AS source "
                        "FROM provider_call_ledger WHERE workspace_id = :ws"
                    ),
                    {"ws": workspace},
                )
            ).one()

    row = run_async(scenario())
    assert (row.outcome, row.source) == ("retry_exhausted", "estimate")
