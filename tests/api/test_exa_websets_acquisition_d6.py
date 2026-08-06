"""D6 confirmed-ICP acquisition composition and durable paid-call replay."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.discovery_seal import DurableDiscoveryPhaseHandler
from clue_api.exa_websets_acquisition import (
    ExaDiscoveryAcquisitionError,
    ExaDiscoveryAcquisitionPolicy,
    ExaWebsetsDiscoveryStarter,
    compile_exa_discovery_preflight,
)
from clue_core import (
    DiscoveryEnrichmentFormat,
    DiscoveryEntityKind,
    ExtractionMethod,
    ICPCreatedFrom,
    ICPSpec,
    ICPStatus,
    PhaseContext,
    PhaseResult,
    PhaseStatus,
    ProjectPhase,
    ProjectRunId,
    ResearchMode,
    account_claim,
    new_project_run_id,
    revalidate_with,
)
from clue_research.claimstore import insert_claim
from clue_research.durable import (
    ProjectRunStatus,
    ensure_project_run,
    get_current_discovery_batch,
    get_discovery_item,
    get_project_run,
)
from clue_research.icp import create_icp_spec
from clue_storage import FsStorage
from tests._workspace import seed_project
from tests.api.test_exa_websets_submit_d2 import _RecordingTransport
from tests.db.conftest import run_async
from tests.durable.conftest import rollback_conn
from tests.durable.test_discovery_batch_d1 import _complete_batch, _start_batch

pytestmark = pytest.mark.usefixtures("require_profiling_db")


def _strategy(*, count: int = 2, entity: str = "company") -> dict[str, object]:
    return {
        "channels": ["exa_websets"],
        "requested_count": count,
        "entity_type": entity,
        "query": "Independent U.S. neurosurgery practices with multiple providers",
        "must_have_criteria": [
            "U.S.-based independent neurosurgery or spine specialty practice",
            "Not a general hospital or health-system department",
            "Multiple providers and public referral workflow evidence",
        ],
        "scoring_mode": "disabled",
        "selection_mode": "discovery_criteria",
        "approved_tier": "high",
    }


def _context(
    *, run_id: ProjectRunId | None = None, workspace_id: str = "ws-d6-unit"
) -> PhaseContext:
    return PhaseContext(
        project_run_id=run_id or new_project_run_id(),
        project_id="project-d6",
        brand_id="brand-d6",
        phase=ProjectPhase.DISCOVERY,
        workspace_id=workspace_id,
        icp_key="neurosurgery",
        icp_version=1,
        budget_cap_cents=Decimal("1000"),
    )


def _spec(ctx: PhaseContext, *, strategy: dict[str, object] | None = None) -> ICPSpec:
    return ICPSpec(
        workspace_id=ctx.workspace_id,
        icp_key=ctx.icp_key,
        version=ctx.icp_version,
        status=ICPStatus.ACTIVE,
        created_from=ICPCreatedFrom.SYNTHESIS,
        discovery_strategy=strategy or _strategy(),  # type: ignore[arg-type]
    )


def test_preflight_is_exact_bounded_scoring_bypass_workload() -> None:
    ctx = _context()
    preflight = compile_exa_discovery_preflight(ctx=ctx, spec=_spec(ctx))
    search = preflight.plan.searches[0]

    assert search.requested_count == 2
    assert search.entity_type is DiscoveryEntityKind.COMPANY
    assert tuple(item.description for item in search.criteria) == tuple(
        _strategy()["must_have_criteria"]  # type: ignore[arg-type]
    )
    assert tuple(str(item.field_key) for item in search.enrichments) == (
        "core.company_linkedin_url",
        "core.revenue_band",
    )
    assert tuple(item.format for item in search.enrichments) == (
        DiscoveryEnrichmentFormat.URL,
        DiscoveryEnrichmentFormat.OPTIONS,
    )
    assert preflight.maximum_provider_credits == Decimal("28")
    assert preflight.maximum_cost_cents == Decimal("12.572")
    assert preflight.contact_enrichments_enabled is False
    assert preflight.plan.provider_credit_cap == 28
    assert preflight.plan.money_budget_cap_cents == Decimal("12.572")
    assert preflight.plan.stopping_policy["closed_batch"] is True

    replay = compile_exa_discovery_preflight(ctx=ctx, spec=_spec(ctx))
    assert replay == preflight


def test_contact_opt_in_is_explicit_and_reserves_full_maximum() -> None:
    ctx = _context()
    policy = ExaDiscoveryAcquisitionPolicy(include_contact_enrichments=True)
    preflight = compile_exa_discovery_preflight(ctx=ctx, spec=_spec(ctx), policy=policy)

    assert tuple(str(item.field_key) for item in preflight.plan.searches[0].enrichments) == (
        "core.company_linkedin_url",
        "core.revenue_band",
        "core.company_email",
        "core.company_phone",
    )
    assert preflight.maximum_provider_credits == Decimal("48")
    assert preflight.maximum_cost_cents == Decimal("21.552")
    assert preflight.contact_enrichments_enabled is True


@pytest.mark.parametrize(
    ("strategy", "match"),
    [
        (_strategy(count=3), "exceeds policy maximum"),
        (_strategy(entity="person"), "company rows only"),
        ({**_strategy(), "channels": ["other"]}, "does not enable Exa"),
    ],
)
def test_preflight_fails_closed_outside_policy(strategy: dict[str, object], match: str) -> None:
    ctx = _context()
    with pytest.raises(ExaDiscoveryAcquisitionError, match=match):
        compile_exa_discovery_preflight(ctx=ctx, spec=_spec(ctx, strategy=strategy))


class _FallbackMustNotRun:
    phase = ProjectPhase.DISCOVERY

    async def run(self, ctx: PhaseContext) -> PhaseResult:
        raise AssertionError(f"durable D6 run {ctx.project_run_id} used legacy discovery")


def test_real_db_phase_originates_once_waits_and_restart_replays_without_http(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        workspace_id = "ws-d6-acquisition-replay"
        storage = FsStorage(tmp_path / "artifacts")
        transport = _RecordingTransport()

        async with rollback_conn(seed_pack=True) as conn:
            project = await seed_project(conn, workspace_id, name="D6 acquisition")
            icp = await create_icp_spec(
                conn,
                workspace_id=workspace_id,
                icp_key="neurosurgery",
                created_from=ICPCreatedFrom.SYNTHESIS,
                field_keys=("core.primary_domain", "core.employee_count"),
                discovery_strategy=_strategy(),  # type: ignore[arg-type]
                activate=True,
            )
            run_id = new_project_run_id()
            await ensure_project_run(
                conn,
                project_run_id=run_id,
                project_id=project.project_id,
                workspace_id=workspace_id,
                icp_key=icp.icp_key,
                icp_version=icp.version,
                phase=ProjectPhase.DISCOVERY,
                status=ProjectRunStatus.ACTIVE,
                budget_cap_cents=Decimal("1000"),
            )
            ctx = PhaseContext(
                project_run_id=run_id,
                project_id=project.project_id,
                brand_id=project.brand_id,
                phase=ProjectPhase.DISCOVERY,
                workspace_id=workspace_id,
                icp_key=icp.icp_key,
                icp_version=icp.version,
                budget_cap_cents=Decimal("1000"),
            )

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            @asynccontextmanager
            async def transport_context() -> AsyncIterator[_RecordingTransport]:
                yield transport

            starter = ExaWebsetsDiscoveryStarter(
                transport_factory=transport_context,
                storage=storage,
                conn_factory=same_connection,
            )
            handler = DurableDiscoveryPhaseHandler(
                storage=storage,
                fallback=_FallbackMustNotRun(),
                starter=starter,
                conn_factory=same_connection,
            )

            first = await handler.run(ctx)
            assert first.status is PhaseStatus.WAITING_EXTERNAL
            assert transport.create_calls == 1
            assert transport.lookup_calls == 0

            # A new starter instance represents a process restart. PostgreSQL alone must suppress
            # both create and lookup, while returning the same plan/batch/operation.
            restarted = ExaWebsetsDiscoveryStarter(
                transport_factory=transport_context,
                storage=storage,
                conn_factory=same_connection,
            )
            replay = await restarted.start(ctx)
            assert replay.submissions[0].create_calls == 0
            assert replay.submissions[0].lookup_calls == 0
            assert replay.submissions[0].outcome.value == "replayed"
            assert transport.create_calls == 1
            assert transport.lookup_calls == 0

            paused_savepoint = await conn.begin_nested()
            await conn.execute(
                text("UPDATE project_run SET status='paused' WHERE id=:run"),
                {"run": run_id},
            )
            with pytest.raises(ExaDiscoveryAcquisitionError, match="currently in discovery"):
                await restarted.preflight(ctx)
            await paused_savepoint.rollback()
            assert transport.create_calls == 1

            batch = await get_current_discovery_batch(
                conn, workspace_id=workspace_id, project_run_id=run_id
            )
            assert batch is not None and batch.id == replay.preflight.batch_id
            counts = (
                await conn.execute(
                    text(
                        "SELECT (SELECT count(*) FROM discovery_plan WHERE project_run_id=:run), "
                        "(SELECT count(*) FROM discovery_batch WHERE project_run_id=:run), "
                        "(SELECT count(*) FROM discovery_operation WHERE batch_id=:batch)"
                    ),
                    {"run": run_id, "batch": batch.id},
                )
            ).one()
            assert tuple(int(value) for value in counts) == (1, 1, 1)

    run_async(scenario())


def test_real_d4_claim_manifest_is_sealable_by_d5(tmp_path: Path) -> None:
    """D5 freezes item-linked provenance claims outside field-resolution edges."""

    async def scenario() -> None:
        workspace_id = "ws-d6-d4-d5-manifest"
        storage = FsStorage(tmp_path / "manifest-artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            started = await _start_batch(conn, storage, workspace_id=workspace_id)
            ready = await _complete_batch(conn, storage, started=started, persist_manifest=False)
            item = await get_discovery_item(
                conn, workspace_id=workspace_id, item_snapshot_id=ready.item_id
            )
            assert item is not None
            provenance = revalidate_with(
                account_claim(
                    entity_id=ready.account_id,
                    field_key="core.company_about",
                    value_json="Provider-backed discovery provenance outside field resolutions",
                    source_tier=1,
                    extraction_method=ExtractionMethod.API,
                    confidence=0.95,
                    run_id=started.project_run_id,
                    research_mode=ResearchMode.ACCOUNT_DISCOVERY,
                    source_url="https://www.insighthealth.ai/",
                    evidence_span="Provider-backed discovery provenance",
                ),
                source_key="exa_websets",
                artifact_key=item.raw_artifact_key,
            )
            await insert_claim(conn, provenance, validate_field=False)

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            # Resolve the owning run from the batch itself; no test-crafted manifest is involved.
            run_row = await conn.execute(
                text(
                    "SELECT project_run_id FROM discovery_batch "
                    "WHERE workspace_id=:workspace_id AND id=:batch_id"
                ),
                {"workspace_id": workspace_id, "batch_id": started.batch_id},
            )
            run_id = run_row.scalar_one()
            run = await get_project_run(conn, run_id)
            assert run is not None
            handler = DurableDiscoveryPhaseHandler(
                storage=storage,
                fallback=_FallbackMustNotRun(),
                conn_factory=same_connection,
            )
            sealed = await handler.run(
                PhaseContext(
                    project_run_id=run.id,
                    project_id=run.project_id,
                    brand_id=run.brand_id,
                    phase=ProjectPhase.DISCOVERY,
                    workspace_id=run.workspace_id,
                    icp_key=run.icp_key,
                    icp_version=run.icp_version,
                )
            )
            assert sealed.status is PhaseStatus.COMPLETED
            assert sealed.accounts_processed == 1

    run_async(scenario())
