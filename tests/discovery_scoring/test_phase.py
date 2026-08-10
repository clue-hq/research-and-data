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
    EntityId,
    ICPCreatedFrom,
    PhaseContext,
    PhaseStatus,
    ProjectPhase,
    new_project_run_id,
)
from clue_research.discovery_scoring import ChannelRegistry, DiscoveryPhaseHandler
from clue_research.discovery_scoring.phases import discovery_run_id
from clue_research.icp import create_icp_spec
from clue_research.membership import accounts_for_project
from tests._run_lineage import assert_written_claims_are_attributable
from tests._workspace import seed_phase_run

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
        project_run_id=new_project_run_id(),
        project_id="prj-test",
        brand_id="brd-test",
        phase=ProjectPhase.DISCOVERY,
        workspace_id="acme",
        icp_key="default",
        icp_version=icp_version,
    )


async def _count_accounts(conn: AsyncConnection) -> int:
    return int((await conn.execute(text("SELECT count(*) FROM account_entity"))).scalar_one())


async def _admitted_account_ids(conn: AsyncConnection, workspace_id: str) -> set[EntityId]:
    """Every account the workspace holds — the ids the phase's admissions created."""
    rows = await conn.execute(
        text("SELECT id FROM account_entity WHERE workspace_id = :workspace"),
        {"workspace": workspace_id},
    )
    return {EntityId(value) for value in rows.scalars()}


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
            ctx = _ctx()
            await seed_phase_run(conn, ctx)
            result = await handler.run(ctx)

            assert result.status is PhaseStatus.COMPLETED
            assert result.accounts_processed == 2
            assert result.payload["admitted"] == 2
            assert result.payload["rejected"] == 0
            assert await _count_accounts(conn) == 2
            assert await _count_provenance(conn) == 2
            # FI-2 P1 (spec §2): both admitted accounts — those exact ids, not merely that many —
            # joined the phase's project as targets.
            admitted = await _admitted_account_ids(conn, ctx.workspace_id)
            assert len(admitted) == 2
            assert (
                set(
                    await accounts_for_project(
                        conn, workspace_id=ctx.workspace_id, project_id=ctx.project_id
                    )
                )
                == admitted
            )
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
            await seed_phase_run(conn, ctx)

            first = await handler.run(ctx)
            second = await handler.run(ctx)

            assert first.payload["admitted"] == 1
            assert second.payload["admitted"] == 1  # re-admits to the same entity
            assert await _count_accounts(conn) == 1  # no duplicate entity
            assert await _count_provenance(conn) == 1  # no duplicate provenance claim
            admitted = await _admitted_account_ids(conn, ctx.workspace_id)
            assert len(admitted) == 1
            # exactly the re-admitted entity, once — the replay adds no second membership
            assert tuple(
                await accounts_for_project(
                    conn, workspace_id=ctx.workspace_id, project_id=ctx.project_id
                )
            ) == tuple(admitted)

    run_async(_run())


def test_discovery_phase_registers_its_run_in_run_lineage() -> None:
    """FI-2 P2: the admitted candidates' provenance claims back-join to this run's project."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            await _seed_active_icp(conn)
            channel = const_channel("exa", [record("exa:1", domain="alpha.example", name="Alpha")])
            handler = DiscoveryPhaseHandler(
                channels=ChannelRegistry((channel,)), session_factory=_session_factory(conn)
            )
            ctx = _ctx()
            await seed_phase_run(conn, ctx)

            result = await handler.run(ctx)
            assert result.status is PhaseStatus.COMPLETED

            await assert_written_claims_are_attributable(
                conn,
                discovery_run_id(ctx),
                kind="discovery",
                workspace_id=ctx.workspace_id,
                project_id=ctx.project_id,
                project_run_id=ctx.project_run_id,
            )
            # Replay re-registers harmlessly (ON CONFLICT DO NOTHING) rather than failing.
            assert (await handler.run(ctx)).status is PhaseStatus.COMPLETED

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
