"""M6.3 (ENG-138) — the integrated SCORING PhaseHandler, against a live Postgres.

End to end: the handler loads the pinned ICP spec + rubric, enumerates the accounts admitted in the
campaign's discovery run (via their discovery-provenance), scores each over the Pass-A waterfall,
persists the decomposed fit/intent score, records per-source yield, and is M7-replay-idempotent (a
re-run writes no new score claim). Also: a spec with no rubric fails cleanly (never fabricates one).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    EntityType,
    ExtractionMethod,
    ICPCreatedFrom,
    PhaseContext,
    PhaseStatus,
    ProjectPhase,
    ResearchMode,
    account_claim,
    discovery_claim,
    new_project_run_id,
    new_run_id,
)
from clue_research.claimstore import WorkspaceScope, claims_for, insert_claim, load_core_pack
from clue_research.discovery_scoring import ScoringPhaseHandler
from clue_research.discovery_scoring.phases import _discovery_run_id
from clue_research.discovery_scoring.scoring import FIT_FIELD, INTENT_FIELD
from clue_research.icp import (
    RubricEntry,
    ScoringRubric,
    ScoringTransform,
    SubRubric,
    create_icp_spec,
    rubric_to_slot,
)
from clue_research.identity import insert_account_entity

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_discovery_db")

CLIENT = "acme"
ICP = "default"
_EMP = "core.employee_count"
_FUND = "account.recent_funding"


def _session_factory(
    conn: AsyncConnection,
) -> Callable[[], AbstractAsyncContextManager[AsyncConnection]]:
    """Hand the handler the test's rollback connection (no commit)."""

    @asynccontextmanager
    async def _session() -> AsyncIterator[AsyncConnection]:
        yield conn

    return _session


def _rubric() -> ScoringRubric:
    return ScoringRubric(
        fit=SubRubric(
            entries=(
                RubricEntry(
                    field_key=_EMP,
                    transform=ScoringTransform.LINEAR,
                    params={"lo": 0, "hi": 1000},
                ),
            )
        ),
        intent=SubRubric(
            entries=(RubricEntry(field_key=_FUND, transform=ScoringTransform.BOOLEAN),)
        ),
    )


def _ctx(*, icp_version: int = 1) -> PhaseContext:
    return PhaseContext(
        project_run_id=new_project_run_id(),
        phase=ProjectPhase.SCORING,
        workspace_id=CLIENT,
        icp_key=ICP,
        icp_version=icp_version,
    )


async def _seed_active_icp(conn: AsyncConnection, *, with_rubric: bool = True) -> None:
    await create_icp_spec(
        conn,
        workspace_id=CLIENT,
        icp_key=ICP,
        created_from=ICPCreatedFrom.SYNTHESIS,
        field_keys=(_EMP, _FUND),
        scoring_rubric=rubric_to_slot(_rubric()) if with_rubric else None,
        activate=True,
    )


async def _seed_admitted(conn: AsyncConnection, ctx: PhaseContext, *, name: str, domain: str):
    """An admitted account: an entity + its discovery-provenance for the run + the input proxies."""
    eid = await insert_account_entity(conn, canonical_name=name, primary_domain=domain)
    await insert_claim(
        conn,
        discovery_claim(
            entity_id=eid,
            entity_type=EntityType.ACCOUNT,
            field_key="core.discovery_provenance",
            value_json={
                "matched_channel": "exa",
                "matched_signal": "saas",
                "discovery_confidence": 0.8,
            },
            source_tier=2,
            extraction_method=ExtractionMethod.SCRAPE,
            confidence=0.8,
            run_id=_discovery_run_id(ctx),
            research_mode=ResearchMode.ACCOUNT_DISCOVERY,
            found_via="exa",
            matched_signal="saas",
            discovery_confidence=0.8,
            source_url=f"https://exa/{domain}",
        ),
    )
    for field_key, value in ((_EMP, 500), (_FUND, {"amount_usd": 5_000_000, "round": "B"})):
        await insert_claim(
            conn,
            account_claim(
                entity_id=eid,
                field_key=field_key,
                value_json=value,
                source_tier=1,
                extraction_method=ExtractionMethod.API,
                confidence=0.9,
                run_id=new_run_id(),
                research_mode=ResearchMode.ACCOUNT_PROFILING,
                source_url=f"https://src/{field_key}",
            ),
        )
    return eid


def test_scoring_phase_scores_admitted_and_records_yield() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await load_core_pack(conn)
            await _seed_active_icp(conn)
            ctx = _ctx()
            e1 = await _seed_admitted(conn, ctx, name="Alpha", domain="alpha.example")
            e2 = await _seed_admitted(conn, ctx, name="Beta", domain="beta.example")

            handler = ScoringPhaseHandler(session_factory=_session_factory(conn))
            result = await handler.run(ctx)

            assert result.status is PhaseStatus.COMPLETED
            assert result.accounts_processed == 2
            assert result.payload["written"] == 2
            assert result.payload["rubric_version"] == 1
            for eid in (e1, e2):
                scope = WorkspaceScope.for_workspace(CLIENT)
                assert len(await claims_for(conn, eid, FIT_FIELD, scope=scope)) == 1
                assert len(await claims_for(conn, eid, INTENT_FIELD, scope=scope)) == 1
            # per-source scoring yield landed in the shared telemetry (disposition tags the kind)
            raw = (
                await conn.execute(
                    text(
                        "SELECT disposition FROM source_yield "
                        "WHERE disposition->>'kind' = 'scoring' LIMIT 1"
                    )
                )
            ).scalar_one_or_none()
            assert raw is not None
            dispo = json.loads(raw) if isinstance(raw, str) else raw
            assert dispo["kind"] == "scoring"

    run_async(_run())


def test_scoring_phase_replay_is_idempotent() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await load_core_pack(conn)
            await _seed_active_icp(conn)
            ctx = _ctx()
            eid = await _seed_admitted(conn, ctx, name="Alpha", domain="alpha.example")

            handler = ScoringPhaseHandler(session_factory=_session_factory(conn))
            first = await handler.run(ctx)
            second = await handler.run(ctx)  # same ctx → same scoring run_id

            assert first.payload["written"] == 1
            assert second.accounts_processed == 1
            assert second.payload["written"] == 0  # nothing re-written
            assert second.payload["replayed"] == 1
            # no duplicate score claims
            scope = WorkspaceScope.for_workspace(CLIENT)
            assert len(await claims_for(conn, eid, FIT_FIELD, scope=scope)) == 1
            assert len(await claims_for(conn, eid, INTENT_FIELD, scope=scope)) == 1

    run_async(_run())


def test_scoring_phase_fails_without_a_rubric() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await load_core_pack(conn)
            await _seed_active_icp(conn, with_rubric=False)
            handler = ScoringPhaseHandler(session_factory=_session_factory(conn))
            result = await handler.run(_ctx())
            assert result.status is PhaseStatus.FAILED
            assert "no scoring rubric" in str(result.payload["error"])

    run_async(_run())
