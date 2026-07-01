"""M13.4 — the api-root wiring for the client-facing cost & progress surface.

The composition root is the only place that may import both ``review`` and the sibling worker
packages it reads (the import-linter independence contract). This module builds the concrete
:mod:`clue_research.review.observability` reader Protocols over those siblings and injects them into
the :class:`~clue_research.review.ObservabilitySurface`:

* :class:`DurableCampaignStateReader` — phase progress over the M7.3 ``campaign_run`` /
  ``campaign_phase_checkpoint`` tables (``durable``).
* :class:`BudgetEngineBurnDownReader` — the live burn-down over the **same**
  :class:`~clue_research.core.BudgetEngine` the deep run uses (one materialization, never
  re-derived).
* :class:`BudgetCapsPreRunEstimator` — the pure ``project_spend`` projection over the client's
  ``config.BudgetCaps`` (side-effect-free — it never persists onto ``campaign_run``, unlike the
  durable ``BudgetEngine.estimate``, so a "read"/estimate never mutates the domain).
* :class:`ClaimScanVerificationHealthReader` — the at-rest verification-health scan over the
  campaign's claims (``claimstore.claims_for_runs``) + the ``obs`` at-rest counter (strong identity-
  binding via the immutable ``claim.identity_binding`` column — **never** the M9.4 live
  per-classification view, ``[M9.4×M13.4]``).
* :class:`CheckpointCoverageReportReader` — the M6.5 coverage estimate, read from the serialized
  ``discovery_scoring.CoverageReport`` the M6.4 ``tier_checkpoint`` payload persists, mapped onto
  the
  additive ``core.CoverageReport`` projection.

Each reader is tenant-scoped (a run whose ``client_id`` is not the caller's resolves to ``None``,
substrate §2) and manages its own short read transaction via an injected ``conn_factory`` (mirroring
:class:`~clue_research.api.handoff_wiring.DurableHandoffReadinessReader`). Nothing imports ``api``
(Rule 5); this module is a leaf wired only at an app/test composition root — and it does **not**
edit
``api/composition.py`` (the shared join), per the M13.4 brief.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from clue_research.claimstore import TenantScope, claims_for_runs
from clue_research.config import BudgetCaps, get_config
from clue_research.core import (
    BudgetEngine,
    BurnDown,
    CampaignPhase,
    CampaignRunId,
    CoverageReport,
    Estimate,
    UnsearchedChannel,
    VerificationStatus,
)
from clue_research.db import ConnFactory, connection
from clue_research.discovery_scoring import CoverageReport as _DiscoveryCoverageReport
from clue_research.durable import (
    BudgetStateNotFound,
    CampaignRunStatus,
    get_campaign_run,
    get_checkpoint,
    list_account_runs,
    project_spend,
)
from clue_research.obs import (
    METRIC_CONTACT_CLAIMS_TOTAL,
    METRIC_CONTACT_STRONG_BINDING,
    METRIC_TIER4_PASSED,
    METRIC_TIER4_TOTAL,
    InMemorySink,
    record_verification_health,
)
from clue_research.review import (
    CampaignStateReader,
    CostBurnDownReader,
    CoverageReportReader,
    ObservabilitySurface,
    PhaseProgress,
    PreRunEstimator,
    RunPhaseState,
    VerificationHealthCounts,
    VerificationHealthReader,
)

# A run past these statuses produces no further work (mirrors api/handoff_wiring).
_TERMINAL_RUN_STATUSES = frozenset({CampaignRunStatus.COMPLETED, CampaignRunStatus.FAILED})


class DurableCampaignStateReader:
    """The production :class:`CampaignStateReader` over the M7.3 ``campaign_run`` /
    ``campaign_phase_checkpoint`` tables. Reads the run row + a checkpoint per
    :class:`~clue_research.core.CampaignPhase` (the per-phase ``campaign_phase_checkpoint_run``
    index
    supports the per-phase look-ups). Tenant-scoped; projects the durable enums to plain strings so
    ``review`` never learns the durable enum tokens."""

    def __init__(self, *, conn_factory: ConnFactory = connection) -> None:
        self._conn_factory = conn_factory

    async def run_phase_state(
        self, *, campaign_run_id: CampaignRunId, client_id: str
    ) -> RunPhaseState | None:
        async with self._conn_factory() as conn:
            run = await get_campaign_run(conn, campaign_run_id)
            if run is None or run.client_id != client_id:
                return None
            checkpoints: list[PhaseProgress] = []
            for phase in CampaignPhase:
                cp = await get_checkpoint(conn, campaign_run_id, phase)
                if cp is not None:
                    checkpoints.append(PhaseProgress(phase=phase, status=cp.status.value))
        return RunPhaseState(
            campaign_run_id=campaign_run_id,
            client_id=client_id,
            current_phase=run.phase,
            run_status=run.status.value,
            is_terminal=run.status in _TERMINAL_RUN_STATUSES,
            checkpoints=tuple(checkpoints),
        )


class BudgetEngineBurnDownReader:
    """The production :class:`CostBurnDownReader` — the live ``core.BudgetEngine.burn_down`` (the
    authoritative ``campaign_run.spent_cents`` counter). Reuse the SAME engine instance the deep run
    uses so M13.3/M13.4 and the engine never diverge on the number. Tenant-scoped via a
    ``get_campaign_run`` check before reading the burn-down."""

    def __init__(self, *, budget: BudgetEngine, conn_factory: ConnFactory = connection) -> None:
        self._budget = budget
        self._conn_factory = conn_factory

    async def burn_down(self, *, campaign_run_id: CampaignRunId, client_id: str) -> BurnDown | None:
        async with self._conn_factory() as conn:
            run = await get_campaign_run(conn, campaign_run_id)
        if run is None or run.client_id != client_id:
            return None
        try:
            return await self._budget.burn_down(campaign_run_id)
        except BudgetStateNotFound:
            return None


class BudgetCapsPreRunEstimator:
    """The production :class:`PreRunEstimator` — the **pure** ``project_spend`` projection over the
    client's ``config.BudgetCaps``. Side-effect-free (it does not persist onto ``campaign_run`` the
    way the durable ``BudgetEngine.estimate`` does), so the observability surface's pre-run estimate
    is a true read. ``caps_for`` is injectable so a test pins fixture caps without the config
    store."""

    def __init__(self, *, caps_for: Callable[[str], BudgetCaps] | None = None) -> None:
        self._caps_for = caps_for or (lambda client_id: get_config(client_id).budget_caps)

    async def estimate(
        self,
        *,
        client_id: str,
        discovered_count: int,
        tier_cutoffs: Mapping[str, float] | None = None,
    ) -> Estimate:
        caps = self._caps_for(client_id)
        return project_spend(
            caps,
            discovered_count=discovered_count,
            tier_cutoffs=dict(tier_cutoffs) if tier_cutoffs else None,
        )


class ClaimScanVerificationHealthReader:
    """The production :class:`VerificationHealthReader` — the at-rest verification-health scan over
    one campaign run's claims.

    Enumerates the campaign's account runs (``durable.list_account_runs``), reads their claims in
    one
    pass (``claimstore.claims_for_runs`` — every worker stamps its account ``run_id`` on each
    claim),
    and computes:

    * tier-4 faithfulness pass share + **strong identity-binding share** via
      ``obs.record_verification_health`` over a fresh sink — the AT-REST column scan of the
      immutable
      ``claim.identity_binding`` column (``[M9.4×M13.4]`` — the authoritative surface, **never**
      summed with the live per-classification view);
    * the M9.2 corroboration pass rate from ``claim.verification_status`` (``VERIFIED`` over the
      claims the verification/merge layer evaluated, i.e. ``VERIFIED`` + ``FLAGGED``) — the in-claim
      corroboration signal (the authoritative mode-aware ``conflict_flag`` table is a future
      refinement).

    Tenant-scoped; ``None`` for a missing / cross-tenant run. ``[]`` account runs → all-zero counts
    (a run with no deep claims is not unhealthy, it is empty)."""

    def __init__(self, *, conn_factory: ConnFactory = connection) -> None:
        self._conn_factory = conn_factory

    async def health_counts(
        self, *, campaign_run_id: CampaignRunId, client_id: str
    ) -> VerificationHealthCounts | None:
        async with self._conn_factory() as conn:
            run = await get_campaign_run(conn, campaign_run_id)
            if run is None or run.client_id != client_id:
                return None
            account_runs = await list_account_runs(conn, campaign_run_id)
            run_ids = [ar.id for ar in account_runs]
            claims = (
                await claims_for_runs(conn, run_ids, scope=TenantScope.for_tenant(client_id))
                if run_ids
                else []
            )
        sink = InMemorySink()  # fresh sink → point-in-time counts, never the accumulating global
        record_verification_health(claims, sink=sink)
        corroboration_total = 0
        corroboration_passed = 0
        for claim in claims:
            if claim.verification_status in (
                VerificationStatus.VERIFIED,
                VerificationStatus.FLAGGED,
            ):
                corroboration_total += 1
                if claim.verification_status is VerificationStatus.VERIFIED:
                    corroboration_passed += 1
        return VerificationHealthCounts(
            faithfulness_passed=int(sink.counter(METRIC_TIER4_PASSED)),
            faithfulness_total=int(sink.counter(METRIC_TIER4_TOTAL)),
            strong_binding=int(sink.counter(METRIC_CONTACT_STRONG_BINDING)),
            contact_total=int(sink.counter(METRIC_CONTACT_CLAIMS_TOTAL)),
            corroboration_passed=corroboration_passed,
            corroboration_total=corroboration_total,
        )


class CheckpointCoverageReportReader:
    """The production :class:`CoverageReportReader` — the M6.5 coverage estimate read from the M6.4
    ``tier_checkpoint`` checkpoint payload (where the tiering phase persists the serialized
    ``discovery_scoring.CoverageReport`` under ``payload['coverage']``), mapped onto the additive
    ``core.CoverageReport`` projection. ``None`` when the run has no tier checkpoint or no coverage
    telemetry (e.g. an import-only campaign) — surfaced honestly, never fabricated.
    Tenant-scoped."""

    def __init__(self, *, conn_factory: ConnFactory = connection) -> None:
        self._conn_factory = conn_factory

    async def coverage_for_run(
        self, *, campaign_run_id: CampaignRunId, client_id: str
    ) -> CoverageReport | None:
        async with self._conn_factory() as conn:
            run = await get_campaign_run(conn, campaign_run_id)
            if run is None or run.client_id != client_id:
                return None
            checkpoint = await get_checkpoint(conn, campaign_run_id, CampaignPhase.TIER_CHECKPOINT)
        if checkpoint is None:
            return None
        coverage_json = checkpoint.payload.get("coverage")
        if not isinstance(coverage_json, Mapping):
            return None  # no discovery telemetry / coverage not populated
        report = _DiscoveryCoverageReport.model_validate(coverage_json)
        return _map_coverage(report)


def _map_coverage(report: _DiscoveryCoverageReport) -> CoverageReport:
    """Map the ``discovery_scoring`` M6.5 report onto the additive ``core.CoverageReport``
    projection,
    preserving the honesty guarantee — the percent is the band's pre-rendered ``~X–Y%`` (bounded by
    the M6.5 ceiling, so never ``100%``) and the framing is the completeness-free statement."""
    band = report.coverage_estimate_band
    return CoverageReport(
        run_id=report.run_id,
        coverage_low=band.low,
        coverage_high=band.high,
        coverage_point=band.point,
        confidence=band.confidence.value,
        estimate_percent=band.as_percent(),
        channels_searched=report.channels_searched,
        channels_not_searched=tuple(
            UnsearchedChannel(source_key=ch.source_key, tier=ch.tier, geo_coverage=ch.geo_coverage)
            for ch in report.channels_not_searched
        ),
        stopping_reason=report.stopping_reason.value,
        framing=report.framing,
        recommendation=report.recommendation,
    )


def build_campaign_state_reader(*, conn_factory: ConnFactory = connection) -> CampaignStateReader:
    """The api-root durable-backed :class:`CampaignStateReader`."""
    return DurableCampaignStateReader(conn_factory=conn_factory)


def build_cost_burndown_reader(
    *, budget: BudgetEngine, conn_factory: ConnFactory = connection
) -> CostBurnDownReader:
    """The api-root :class:`CostBurnDownReader` over the shared :class:`BudgetEngine`."""
    return BudgetEngineBurnDownReader(budget=budget, conn_factory=conn_factory)


def build_pre_run_estimator(
    *, caps_for: Callable[[str], BudgetCaps] | None = None
) -> PreRunEstimator:
    """The api-root pure :class:`PreRunEstimator` over ``config.BudgetCaps``."""
    return BudgetCapsPreRunEstimator(caps_for=caps_for)


def build_verification_health_reader(
    *, conn_factory: ConnFactory = connection
) -> VerificationHealthReader:
    """The api-root at-rest :class:`VerificationHealthReader`."""
    return ClaimScanVerificationHealthReader(conn_factory=conn_factory)


def build_coverage_report_reader(*, conn_factory: ConnFactory = connection) -> CoverageReportReader:
    """The api-root :class:`CoverageReportReader` over the M6.4 tier-checkpoint coverage payload."""
    return CheckpointCoverageReportReader(conn_factory=conn_factory)


def build_observability_surface(
    *,
    budget: BudgetEngine,
    conn_factory: ConnFactory = connection,
    caps_for: Callable[[str], BudgetCaps] | None = None,
) -> ObservabilitySurface:
    """Construct the wired M13.4 :class:`ObservabilitySurface` — the durable-backed readers over the
    M7/M9/M6 substrate, with the live burn-down bound to the SAME ``budget`` engine the deep run
    uses. The per-source-yield + cost-estimate-snapshot reads/writes use the connection a caller
    passes to the surface methods; everything else is served through these injected readers."""
    return ObservabilitySurface(
        campaign_reader=build_campaign_state_reader(conn_factory=conn_factory),
        burndown_reader=build_cost_burndown_reader(budget=budget, conn_factory=conn_factory),
        estimator=build_pre_run_estimator(caps_for=caps_for),
        health_reader=build_verification_health_reader(conn_factory=conn_factory),
        coverage_reader=build_coverage_report_reader(conn_factory=conn_factory),
    )


# Static conformance asserts — mypy proves each api-root concrete satisfies the review-defined seam
# (the api/handoff_retention.py idiom). A drift between a concrete and its Protocol fails the build.
_CAMPAIGN_READER_IS: type[CampaignStateReader] = DurableCampaignStateReader
_BURNDOWN_READER_IS: type[CostBurnDownReader] = BudgetEngineBurnDownReader
_ESTIMATOR_IS: type[PreRunEstimator] = BudgetCapsPreRunEstimator
_HEALTH_READER_IS: type[VerificationHealthReader] = ClaimScanVerificationHealthReader
_COVERAGE_READER_IS: type[CoverageReportReader] = CheckpointCoverageReportReader
