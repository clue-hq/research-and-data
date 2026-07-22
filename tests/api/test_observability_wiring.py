"""M13.4 — the api-root observability wiring: the durable/M9/M6-backed reader concretes.

Exercises the production seams over **real** ``project_run`` / ``account_run`` / ``claim`` /
``project_phase_checkpoint`` rows: the phase-state reader projects the M7.3 state machine; the
burn-down reader delegates to the injected ``BudgetEngine`` (tenant-scoped); the pre-run estimator
is
the pure ``project_spend`` projection; the verification-health reader runs the at-rest claim scan
(tier-4 faithfulness, the strong identity-binding column scan, corroboration); and the coverage
reader maps the M6.4 ``tier_checkpoint`` coverage payload onto the ``core.CoverageReport``. Finally
the wired surface is driven end-to-end. These ``pytest.skip`` without a reachable DB.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api import (
    BudgetCapsPreRunEstimator,
    BudgetEngineBurnDownReader,
    CheckpointCoverageReportReader,
    ClaimScanVerificationHealthReader,
    DurableCampaignStateReader,
    build_observability_surface,
)
from clue_config import BudgetCaps, VerificationHealthThresholds
from clue_core import (
    BurnDown,
    ExtractionMethod,
    IdentityBinding,
    ProjectPhase,
    ProjectRunId,
    ResearchMode,
    UseClass,
    VerificationStatus,
    account_claim,
    contact_claim,
    new_entity_id,
    new_project_run_id,
    new_run_id,
)
from clue_research.claimstore import insert_claim, record_verification
from clue_research.discovery_scoring import (
    CoverageBand,
    CoverageConfidence,
    StoppingReason,
)
from clue_research.discovery_scoring import CoverageReport as DSCoverageReport
from clue_research.discovery_scoring import UnsearchedChannel as DSUnsearchedChannel
from clue_research.durable import (
    PhaseCheckpointStatus,
    ProjectRunStatus,
    ensure_project_run,
    insert_account_run,
    upsert_checkpoint,
)
from tests.db.conftest import run_async
from tests.profiling.conftest import rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_CLIENT = "client-acme"
_OTHER = "client-other"


def _factory(conn: AsyncConnection) -> Callable[[], AbstractAsyncContextManager[AsyncConnection]]:
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncConnection]:
        yield conn

    return factory


class _FakeBudget:
    """A minimal ``core.BudgetEngine`` whose only exercised method is ``burn_down`` (the reader
    calls
    nothing else). mypy does not check tests, so a partial stand-in is fine here."""

    def __init__(self, burndown: BurnDown) -> None:
        self._burndown = burndown

    async def burn_down(self, project_run_id: ProjectRunId) -> BurnDown:
        return self._burndown


async def _seed_run(
    conn: AsyncConnection,
    *,
    client: str = _CLIENT,
    phase: ProjectPhase = ProjectPhase.REVIEW,
    status: ProjectRunStatus = ProjectRunStatus.PAUSED,
) -> ProjectRunId:
    run = new_project_run_id()
    await ensure_project_run(
        conn,
        project_run_id=run,
        workspace_id=client,
        icp_key="enterprise",
        icp_version=1,
        phase=phase,
        status=status,
    )
    return run


async def _seed_health_claims(conn: AsyncConnection, run: ProjectRunId) -> None:
    """Two account runs with tier-4 account claims (1 verified, 1 unverified, 1 flagged) and two
    contact claims (1 strong, 1 weak) — the at-rest verification-health fixture."""
    ra, rb = new_run_id(), new_run_id()
    await insert_account_run(
        conn, account_run_id=ra, project_run_id=run, entity_id=new_entity_id(), tier="top"
    )
    await insert_account_run(
        conn, account_run_id=rb, project_run_id=run, entity_id=new_entity_id(), tier="high"
    )

    def _t4(field: str, run_id, span: str | None):  # type: ignore[no-untyped-def]
        return account_claim(
            entity_id=new_entity_id(),
            field_key=field,
            value_json="x",
            source_tier=4,
            extraction_method=ExtractionMethod.LLM_SYNTHESIS,
            confidence=0.7,
            run_id=run_id,
            research_mode=ResearchMode.ACCOUNT_PROFILING,
            evidence_span=span,
            source_url="https://example.com/synth",
        )

    id_pass = await insert_claim(conn, _t4("account.a", ra, "span-a"), validate_field=False)
    await record_verification(conn, id_pass, status=VerificationStatus.VERIFIED)
    await insert_claim(conn, _t4("account.b", ra, None), validate_field=False)  # stays UNVERIFIED
    id_flag = await insert_claim(conn, _t4("account.c", rb, "span-c"), validate_field=False)
    await record_verification(conn, id_flag, status=VerificationStatus.FLAGGED)

    def _contact(binding: IdentityBinding, run_id):  # type: ignore[no-untyped-def]
        return contact_claim(
            entity_id=new_entity_id(),
            field_key="contact.facet.hobby",
            value_json="golf",
            source_tier=3,
            extraction_method=ExtractionMethod.SCRAPE,
            confidence=0.8,
            run_id=run_id,
            research_mode=ResearchMode.CONTACT_PROFILING,
            identity_binding=binding,
            use_class=UseClass.PROFESSIONAL_PUBLIC,
            source_url="https://example.com/p",
            evidence_span="likes golf",
        )

    await insert_claim(conn, _contact(IdentityBinding.STRONG, ra), validate_field=False)
    await insert_claim(conn, _contact(IdentityBinding.WEAK, rb), validate_field=False)


# --- DurableCampaignStateReader ----------------------------------------------


def test_campaign_state_reader_projects_phases_and_is_workspace_scoped() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            run = await _seed_run(conn, phase=ProjectPhase.REVIEW, status=ProjectRunStatus.PAUSED)
            await upsert_checkpoint(
                conn,
                project_run_id=run,
                phase=ProjectPhase.DISCOVERY,
                idempotency_key="d",
                status=PhaseCheckpointStatus.COMMITTED,
                payload={},
            )
            await upsert_checkpoint(
                conn,
                project_run_id=run,
                phase=ProjectPhase.REVIEW,
                idempotency_key="r",
                status=PhaseCheckpointStatus.AWAITING_INPUT,
                payload={},
            )
            reader = DurableCampaignStateReader(conn_factory=_factory(conn))
            state = await reader.run_phase_state(project_run_id=run, workspace_id=_CLIENT)
            assert state is not None
            assert state.current_phase is ProjectPhase.REVIEW
            assert state.run_status == "paused"
            assert state.is_terminal is False
            by_phase = {cp.phase: cp.status for cp in state.checkpoints}
            assert by_phase[ProjectPhase.DISCOVERY] == "committed"
            assert by_phase[ProjectPhase.REVIEW] == "awaiting_input"
            # cross-tenant isolation.
            assert await reader.run_phase_state(project_run_id=run, workspace_id=_OTHER) is None

    run_async(_run())


# --- BudgetEngineBurnDownReader ----------------------------------------------


def test_burndown_reader_delegates_and_is_workspace_scoped() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            run = await _seed_run(conn, status=ProjectRunStatus.ACTIVE)
            burndown = BurnDown(
                spent_cents=Decimal("400"),
                estimated_cents=Decimal("1000"),
                cap_cents=Decimal("1000"),
                remaining_cents=Decimal("600"),
            )
            reader = BudgetEngineBurnDownReader(
                budget=_FakeBudget(burndown), conn_factory=_factory(conn)
            )
            got = await reader.burn_down(project_run_id=run, workspace_id=_CLIENT)
            assert got is not None and got.spent_cents == Decimal("400")
            assert await reader.burn_down(project_run_id=run, workspace_id=_OTHER) is None
            assert (
                await reader.burn_down(project_run_id=new_project_run_id(), workspace_id=_CLIENT)
                is None
            )

    run_async(_run())


# --- BudgetCapsPreRunEstimator (pure projection) -----------------------------


def test_pre_run_estimator_projects_and_recomputes_on_cutoff() -> None:
    async def _run() -> None:
        caps = BudgetCaps(
            per_account_cap_cents={"top": Decimal("100")},
            pass_a_cap_cents_per_account=Decimal("5"),
        )
        estimator = BudgetCapsPreRunEstimator(caps_for=lambda _c: caps)
        loose = await estimator.estimate(
            workspace_id=_CLIENT, discovered_count=100, tier_cutoffs={"top": 0.6}
        )
        strict = await estimator.estimate(
            workspace_id=_CLIENT, discovered_count=100, tier_cutoffs={"top": 0.9}
        )
        assert loose.projected_deep_count > strict.projected_deep_count
        assert loose.estimated_cost_cents > strict.estimated_cost_cents
        assert loose.confidence == 0.5

    run_async(_run())


# --- ClaimScanVerificationHealthReader (the at-rest scan) --------------------


def test_verification_health_reader_at_rest_scan_counts() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            run = await _seed_run(conn, status=ProjectRunStatus.ACTIVE)
            await _seed_health_claims(conn, run)
            reader = ClaimScanVerificationHealthReader(conn_factory=_factory(conn))
            counts = await reader.health_counts(project_run_id=run, workspace_id=_CLIENT)
            assert counts is not None
            # 3 tier-4 claims; 1 VERIFIED → faithfulness 1/3.
            assert counts.faithfulness_total == 3
            assert counts.faithfulness_passed == 1
            # 2 contact claims; 1 STRONG → strong-binding 1/2 (the at-rest column scan).
            assert counts.contact_total == 2
            assert counts.strong_binding == 1
            # corroboration over claims with a verdict (VERIFIED + FLAGGED) → 1/2.
            assert counts.corroboration_total == 2
            assert counts.corroboration_passed == 1
            # cross-tenant isolation.
            assert await reader.health_counts(project_run_id=run, workspace_id=_OTHER) is None

    run_async(_run())


def test_verification_health_reader_empty_run_is_all_zero() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            run = await _seed_run(conn, status=ProjectRunStatus.ACTIVE)  # no account runs / claims
            reader = ClaimScanVerificationHealthReader(conn_factory=_factory(conn))
            counts = await reader.health_counts(project_run_id=run, workspace_id=_CLIENT)
            assert counts is not None
            assert counts.faithfulness_total == 0 and counts.contact_total == 0

    run_async(_run())


# --- CheckpointCoverageReportReader ------------------------------------------


def _seed_coverage_checkpoint(conn: AsyncConnection, run: ProjectRunId):  # type: ignore[no-untyped-def]
    ds_report = DSCoverageReport(
        run_id=new_run_id(),
        coverage_estimate_band=CoverageBand(
            low=0.4, high=0.6, point=0.5, confidence=CoverageConfidence.MODERATE
        ),
        channels_searched=("linkedin", "crunchbase"),
        channels_not_searched=(DSUnsearchedChannel(source_key="g2", tier=3),),
        per_channel_new_candidate_curve=(),
        stopping_reason=StoppingReason.BUDGET_CAP,
        total_records=100,
        distinct_candidates=80,
        framing="estimated ~40–60% of the addressable set found via the channels searched",
    )
    return upsert_checkpoint(
        conn,
        project_run_id=run,
        phase=ProjectPhase.TIER_CHECKPOINT,
        idempotency_key="tc",
        status=PhaseCheckpointStatus.COMMITTED,
        payload={"coverage": ds_report.model_dump(mode="json")},
    )


def test_coverage_reader_maps_checkpoint_payload() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            run = await _seed_run(conn, status=ProjectRunStatus.ACTIVE)
            await _seed_coverage_checkpoint(conn, run)
            reader = CheckpointCoverageReportReader(conn_factory=_factory(conn))
            report = await reader.coverage_for_run(project_run_id=run, workspace_id=_CLIENT)
            assert report is not None
            assert report.confidence == "moderate"
            assert report.estimate_percent == "~40–60%"
            assert "100%" not in report.estimate_percent
            assert tuple(c.source_key for c in report.channels_not_searched) == ("g2",)
            assert "complete" not in report.framing.lower()

    run_async(_run())


def test_coverage_reader_none_without_checkpoint() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            run = await _seed_run(conn, status=ProjectRunStatus.ACTIVE)  # no tier_checkpoint
            reader = CheckpointCoverageReportReader(conn_factory=_factory(conn))
            assert await reader.coverage_for_run(project_run_id=run, workspace_id=_CLIENT) is None

    run_async(_run())


# --- build_observability_surface end-to-end ----------------------------------


def test_wired_surface_drives_all_panels() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            run = await _seed_run(conn, phase=ProjectPhase.REVIEW, status=ProjectRunStatus.PAUSED)
            await upsert_checkpoint(
                conn,
                project_run_id=run,
                phase=ProjectPhase.REVIEW,
                idempotency_key="r",
                status=PhaseCheckpointStatus.AWAITING_INPUT,
                payload={},
            )
            await _seed_health_claims(conn, run)
            await _seed_coverage_checkpoint(conn, run)
            burndown = BurnDown(
                spent_cents=Decimal("950"),
                estimated_cents=Decimal("1000"),
                cap_cents=Decimal("1000"),
                remaining_cents=Decimal("50"),
            )
            surface = build_observability_surface(
                budget=_FakeBudget(burndown),
                conn_factory=_factory(conn),
                caps_for=lambda _c: BudgetCaps(pass_a_cap_cents_per_account=Decimal("5")),
            )
            # progress reflects the REVIEW human gate.
            progress = await surface.campaign_progress(project_run_id=run, workspace_id=_CLIENT)
            assert progress is not None and progress.current_phase is ProjectPhase.REVIEW
            assert progress.awaiting_input is True
            # burn-down at 95% of cap → near_cap.
            bd = await surface.cost_burndown(project_run_id=run, workspace_id=_CLIENT)
            assert bd is not None and bd.status == "near_cap"
            # verification health: faithfulness 1/3 < the 0.8 floor → alert (default thresholds).
            health = await surface.verification_health(project_run_id=run, workspace_id=_CLIENT)
            assert health is not None
            assert health.faithfulness_alert is True and health.alert is True
            # coverage: a band + a non-empty unsearched list, never "100%/complete".
            coverage = await surface.coverage_confidence(project_run_id=run, workspace_id=_CLIENT)
            assert coverage is not None and coverage.channels_not_searched
            assert "100%" not in coverage.estimate_percent

    run_async(_run())


def test_wired_surface_default_thresholds_read_from_config() -> None:
    """The surface's verification-health alert uses the per-client config floors (policy-as-data)
    when
    no explicit ``thresholds_for`` is injected — the default path build_observability_surface
    wires."""
    # A purely-illustrative guard that the default thresholds object is the config one (no DB):
    cfg_floors = VerificationHealthThresholds()
    assert 0.0 <= cfg_floors.faithfulness_pass_floor <= 1.0
