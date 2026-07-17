"""M6 (ENG-128 + ENG-133) — the integrated DISCOVERY PhaseHandler, against a live Postgres.

End to end: the handler loads the ICP spec, runs discovery, admits each grounded candidate through
the gate, persists per-channel yield, and is M7-replay-idempotent (a re-run admits to the same
entities and writes no duplicate provenance).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    CampaignPhase,
    ICPCreatedFrom,
    PhaseContext,
    PhaseStatus,
    new_campaign_run_id,
)
from clue_research.discovery_scoring import ChannelRegistry, DiscoveryPhaseHandler
from clue_research.icp import create_icp_spec

from .conftest import const_channel, record, rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_discovery_db")


def _session_factory(
    conn: AsyncConnection,
) -> Callable[[], AbstractAsyncContextManager[AsyncConnection]]:
    """A session factory that hands the handler the test's rollback connection (no commit)."""

    @asynccontextmanager
    async def _session() -> AsyncIterator[AsyncConnection]:
        yield conn

    return _session


async def _seed_active_icp(conn: AsyncConnection) -> None:
    await create_icp_spec(
        conn,
        workspace_id="acme",
        icp_key="default",
        created_from=ICPCreatedFrom.SYNTHESIS,
        discovery_strategy={"channels": ["exa"], "static_queries": {"exa": ["q"]}},
        activate=True,
    )


def _ctx(*, icp_version: int = 1) -> PhaseContext:
    return PhaseContext(
        campaign_run_id=new_campaign_run_id(),
        phase=CampaignPhase.DISCOVERY,
        workspace_id="acme",
        icp_key="default",
        icp_version=icp_version,
    )


async def _count_accounts(conn: AsyncConnection) -> int:
    return int((await conn.execute(text("SELECT count(*) FROM account_entity"))).scalar_one())


async def _count_provenance(conn: AsyncConnection) -> int:
    return int(
        (
            await conn.execute(
                text("SELECT count(*) FROM claim WHERE field_key = 'core.discovery_provenance'")
            )
        ).scalar_one()
    )


def test_discovery_phase_discovers_admits_and_records_yield() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _seed_active_icp(conn)
            channel = const_channel(
                "exa",
                [
                    record("exa:1", domain="alpha.example", name="Alpha"),
                    record("exa:2", domain="beta.example", name="Beta"),
                ],
            )
            handler = DiscoveryPhaseHandler(
                channels=ChannelRegistry((channel,)), session_factory=_session_factory(conn)
            )
            result = await handler.run(_ctx())

            assert result.status is PhaseStatus.COMPLETED
            assert result.accounts_processed == 2
            assert result.payload["admitted"] == 2
            assert result.payload["rejected"] == 0
            assert await _count_accounts(conn) == 2
            assert await _count_provenance(conn) == 2
            # per-channel discovery yield landed in the shared telemetry (counts in the jsonb hook)
            raw = (
                await conn.execute(
                    text(
                        "SELECT disposition FROM source_yield "
                        "WHERE source_key = 'exa' ORDER BY recorded_at DESC LIMIT 1"
                    )
                )
            ).scalar_one_or_none()
            assert raw is not None
            dispo = json.loads(raw) if isinstance(raw, str) else raw
            assert dispo["kind"] == "discovery" and dispo["new_candidates"] == 2

    run_async(_run())


def test_discovery_phase_replay_is_idempotent() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _seed_active_icp(conn)
            channel = const_channel("exa", [record("exa:1", domain="alpha.example", name="Alpha")])
            handler = DiscoveryPhaseHandler(
                channels=ChannelRegistry((channel,)), session_factory=_session_factory(conn)
            )
            ctx = _ctx()  # same ctx → same deterministic discovery run_id on replay

            first = await handler.run(ctx)
            second = await handler.run(ctx)

            assert first.payload["admitted"] == 1
            assert second.payload["admitted"] == 1  # re-admits to the same entity
            assert await _count_accounts(conn) == 1  # no duplicate entity
            assert await _count_provenance(conn) == 1  # no duplicate provenance claim

    run_async(_run())


def test_discovery_phase_fails_without_an_icp_spec() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            channel = const_channel("exa", [record("exa:1", domain="alpha.example")])
            handler = DiscoveryPhaseHandler(
                channels=ChannelRegistry((channel,)), session_factory=_session_factory(conn)
            )
            result = await handler.run(_ctx(icp_version=99))  # no such spec
            assert result.status is PhaseStatus.FAILED
            assert "no ICP spec" in str(result.payload["error"])

    run_async(_run())
