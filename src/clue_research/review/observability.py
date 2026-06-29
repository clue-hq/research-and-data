"""M13.4 — the client-facing cost & progress surface (the read-only ``ObservabilitySurface``).

Doc C §6 requires a long campaign run never leave the client staring at a spinner: this surface
exposes **phase progress**, live **cost burn-down vs estimate vs cap**, a **pre-run estimate**,
**per-source yield**, **verification health**, and **coverage confidence** — every panel a *read
projection* over the Postgres provenance the rest of the subsystem already writes (substrate §9).
The
surface writes **nothing** into the domain write path; the only write it ever makes is its own
``cost_estimate`` snapshot materialization (an M13.4-owned side table), exactly as the interface
allows ("the surface writes nothing to the domain … it may write/refresh materialized views only").

**Where it sits in the import graph.** ``review`` is a milestone worker package: it may import the
shared base (``core``/``config``/``obs``) and the M1–M4 services
(``claimstore``/``identity``/``icp``/
``sources``) freely, but **not** a sibling worker
(``durable``/``verification``/``discovery_scoring``/
``narrative``/…). So the panels that need cross-package data — phase state (M7 ``durable``), the
live
burn-down + pre-run estimate (M7.5 ``core.BudgetEngine``, concrete in ``durable``), verification
health (M9 ``verification`` side tables), and coverage (M6.5 ``discovery_scoring``) — arrive through
the **injected reader Protocols** defined here, whose concrete impls are built and injected at the
``api`` composition root (``api/observability_wiring.py``). This mirrors the M13.1
``core.review.VerificationAnnotationReader`` / M12.3 ``narrative.readiness.HandoffReadinessReader``
seam discipline. The in-boundary panels — per-source yield (``sources.get_source_yield``) and the
``cost_estimate`` snapshot — are read/written directly through the connection a caller passes.

**The two divergent-surface traps, resolved (decisions locked 2026-06-26).**

* *Verification health — strong identity-binding share* uses the **at-rest column scan** over the
  immutable ``claim.identity_binding`` column (the surface
  ``obs.metrics.record_verification_health``
  computes), as the authoritative, born-correct, policy-stable truth — **never** summed with the
  M9.4
  *live per-classification* counters (a different numerator/denominator over a different timeline).
  The scan itself runs inside the injected :class:`VerificationHealthReader` at the ``api`` root
  (which can reach ``claimstore`` + ``durable``); this surface only divides the counts and raises
  the
  configured alert. See backlog item ``[M9.4×M13.4]``.
* *Cost burn-down* uses the **live ``core.BudgetEngine.burn_down``** number (the authoritative
  ``campaign_run.spent_cents`` counter), **never** re-derived from ``Σ claim.cost_cents`` or the
  in-memory ``obs`` gauges — one materialization, so M13.3/M13.4 and the engine never diverge.

Architecture sources: Doc C §5 (cost dial & governance — pre-run estimate, client-set hard cap,
graceful stop), §6 (observability & progress surface), §7 (coverage confidence — estimate +
unsearched
channels, not exhaustiveness); substrate §5c (budget caps the burn-down reads), §6 (verification
mechanisms whose health this panel reports), §9 (provenance-backed, the same data the dashboard
reads); Doc D (strong identity-binding share); docs/specs/M13-review-feedback-observability.md
§M13.4.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.config import VerificationHealthThresholds, get_config
from clue_research.core import (
    BurnDown,
    CampaignPhase,
    CampaignRunId,
    CostCents,
    CoverageReport,
    Estimate,
    UnitInterval,
    serialize_value_json,
)
from clue_research.sources import SourceYieldStat, get_source_yield

# Mirrors of the durable status tokens (``durable`` may not be imported by ``review``). The injected
# readers hand back these statuses as plain strings; the surface compares against these constants.
_CHECKPOINT_COMMITTED = "committed"  # PhaseCheckpointStatus.COMMITTED
_CHECKPOINT_AWAITING_INPUT = "awaiting_input"  # PhaseCheckpointStatus.AWAITING_INPUT
_PHASE_PENDING = "pending"  # a phase with no checkpoint row yet (not a durable status)
_RUN_PAUSED = "paused"  # CampaignRunStatus.PAUSED

# A run is "near cap" once remaining spend falls to this fraction of the cap (a surfacing threshold;
# the engine itself has no warning band — only the discrete graceful-stop at the cap).
_DEFAULT_NEAR_CAP_REMAINING_FRACTION = 0.1

# cost-burn-down status tokens this surface emits (derived from the live BurnDown; not durable
# enums).
COST_STATUS_OK = "ok"
COST_STATUS_NEAR_CAP = "near_cap"
COST_STATUS_GRACEFUL_STOP = "graceful_stop"


# --- panel projections (what the surface returns) ----------------------------


class PhaseProgress(BaseModel):
    """One phase's state within :class:`CampaignProgress` — the per-phase completion view over the
    M7.3 state machine. ``status`` is the durable checkpoint status (``in_progress`` /
    ``awaiting_input`` / ``committed`` / ``failed``) or ``"pending"`` for a phase that has not run
    yet; ``is_complete`` is the committed checkpoint; ``is_current`` marks the run's current
    phase."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    phase: CampaignPhase
    status: str
    is_current: bool = False
    is_complete: bool = False


class CampaignProgress(BaseModel):
    """Phase-progress panel (Doc C §6): the run's current phase + per-phase completion over the
    ``reverse_profiling → … → review → handoff`` sequence (conventions §3), read straight from the
    M7.3 state machine so it tracks ground truth with no manual refresh.

    ``awaiting_input`` is the run suspended at a *human gate* (the current-phase checkpoint is
    ``AWAITING_INPUT`` — the ``tier_checkpoint`` or the M13.1 ``review`` gate), distinct from a
    budget graceful-stop / client pause (``is_paused`` with no awaiting checkpoint)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    campaign_run_id: CampaignRunId
    client_id: str
    current_phase: CampaignPhase
    run_status: str
    is_paused: bool = False
    is_terminal: bool = False
    awaiting_input: bool = False
    phases: tuple[PhaseProgress, ...] = ()


class CostBurnDown(BaseModel):
    """Cost burn-down panel (Doc C §5/§6): live spent vs. estimate vs. cap vs. remaining, plus a
    derived ``status``. ``status`` is ``graceful_stop`` once spend reaches the cap (the run stops at
    a checkpoint — never a hard crash / silent overspend), ``near_cap`` as it approaches, else
    ``ok``. All money is :class:`~decimal.Decimal` (``CostCents``) — exact, never float."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    campaign_run_id: CampaignRunId
    spent_cents: CostCents
    estimated_cents: CostCents
    cap_cents: CostCents
    remaining_cents: CostCents
    status: str = COST_STATUS_OK
    over_cap: bool = False
    has_cap: bool = False


class PreRunEstimate(BaseModel):
    """Pre-run estimate panel (Doc C §5): the "~N discovered → ~M go deep → ~\\$X" projection before
    any spend, recomputed as tier cutoffs are adjusted. ``confidence`` carries the uniform-score
    modelling assumption (0.5) honestly — it is a projection, not a committed figure."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    campaign_run_id: CampaignRunId
    discovered_count: int
    projected_deep_count: int
    estimated_cents: CostCents
    cost_per_account_cents: CostCents
    confidence: UnitInterval
    summary: str


class VerificationHealthCounts(BaseModel):
    """The raw counts the injected :class:`VerificationHealthReader` returns — numerators and
    denominators for the three Doc C §6 health rates, so the surface can compute shares *and* show
    the denominators for explainability. The reader computes these at the ``api`` root over the
    campaign's claims + M9 side tables; this surface only divides and thresholds them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # tier-4 faithfulness (M9.3): claims passing the judge / tier-4 claims.
    faithfulness_passed: int = 0
    faithfulness_total: int = 0
    # strong identity-binding (M9.4 / Doc D): the AT-REST column scan over claim.identity_binding —
    # strong-bound contact claims / all contact claims. NEVER summed with the live per-class view.
    strong_binding: int = 0
    contact_total: int = 0
    # corroboration (M9.2): claims that passed corroboration / claims evaluated for it.
    corroboration_passed: int = 0
    corroboration_total: int = 0


class VerificationHealth(BaseModel):
    """Verification-health panel (Doc C §6 — the early-warning surface): the three rates plus, per
    rate, a ``*_alert`` flag set when the rate drops below its configured floor
    (:class:`~clue_research.config.VerificationHealthThresholds`) — the signal of a possible
    model/resolver regression. A rate is ``None`` (and never alerts) when it has no observations
    yet. ``alert`` is the OR of the three (any panel unhealthy)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    campaign_run_id: CampaignRunId
    faithfulness_pass_share: float | None = None
    strong_binding_share: float | None = None
    corroboration_pass_rate: float | None = None
    faithfulness_total: int = 0
    contact_total: int = 0
    corroboration_total: int = 0
    faithfulness_alert: bool = False
    strong_binding_alert: bool = False
    corroboration_alert: bool = False
    alert: bool = False


# --- injected reader Protocols (concrete impls wired at the api composition root) ----------------


class RunPhaseState(BaseModel):
    """What :class:`CampaignStateReader` returns — the durable phase snapshot for one campaign run,
    projected off ``durable`` enums into ``core``/``str`` (so ``review`` never learns the durable
    enum tokens). ``checkpoints`` lists only the phases that have a checkpoint row; the surface
    fills
    in ``"pending"`` for the rest from ``core.CampaignPhase``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    campaign_run_id: CampaignRunId
    client_id: str
    current_phase: CampaignPhase
    run_status: str
    is_terminal: bool = False
    checkpoints: tuple[PhaseProgress, ...] = ()


@runtime_checkable
class CampaignStateReader(Protocol):
    """Reads the M7.3 campaign-run phase state for the progress panel (the M13.4 ↔ M7 seam).

    ``review`` cannot import ``durable``, so the production impl (over ``durable.get_campaign_run``
    +
    ``durable.get_checkpoint``) is injected at the ``api`` root, like
    ``narrative.readiness.HandoffReadinessReader``. Tenant-scoped on ``client_id`` (returns ``None``
    for a missing run / a run that is not this tenant's)."""

    async def run_phase_state(
        self, *, campaign_run_id: CampaignRunId, client_id: str
    ) -> RunPhaseState | None: ...


@runtime_checkable
class CostBurnDownReader(Protocol):
    """Reads the live ``core.BudgetEngine.burn_down`` for the cost panel (the M13.4 ↔ M7.5 seam).

    Returns the authoritative :class:`~clue_research.core.BurnDown` (the
    ``campaign_run.spent_cents``
    counter, clamped remaining) — the single cost materialization, never re-derived. Tenant-scoped;
    ``None`` for a missing / cross-tenant run. Injected at the ``api`` root over the same
    ``BudgetEngine`` the deep run uses."""

    async def burn_down(
        self, *, campaign_run_id: CampaignRunId, client_id: str
    ) -> BurnDown | None: ...


@runtime_checkable
class PreRunEstimator(Protocol):
    """Computes the pre-run spend projection (the pure ``project_spend`` math, Doc C §5).

    Side-effect free — it must NOT persist onto ``campaign_run`` (the durable
    ``BudgetEngine.estimate``
    does; this read surface uses the pure projection so a "read" never mutates the domain). Injected
    at the ``api`` root, reading the client's ``config.BudgetCaps``."""

    async def estimate(
        self,
        *,
        client_id: str,
        discovered_count: int,
        tier_cutoffs: Mapping[str, float] | None = None,
    ) -> Estimate: ...


@runtime_checkable
class VerificationHealthReader(Protocol):
    """Reads the verification-health counts for one campaign run (the M13.4 ↔ M9 seam).

    ``review`` cannot import ``verification``; the production impl is injected at the ``api`` root,
    where it scans the campaign's claims (``claimstore``) — strong identity-binding via the at-rest
    ``claim.identity_binding`` column scan (``obs.metrics.record_verification_health``), tier-4
    faithfulness via the M9.3 verdicts, corroboration via the M9.2 signal — and returns the raw
    counts. Tenant-scoped; ``None`` for a missing / cross-tenant run."""

    async def health_counts(
        self, *, campaign_run_id: CampaignRunId, client_id: str
    ) -> VerificationHealthCounts | None: ...


@runtime_checkable
class CoverageReportReader(Protocol):
    """Reads the M6.5 coverage estimate for one campaign run (the M13.4 ↔ M6 seam).

    ``review`` cannot import ``discovery_scoring``; the production impl is injected at the ``api``
    root, mapping the ``discovery_scoring`` coverage report (or its serialized copy on the M6.4
    ``tier_checkpoint`` payload) onto the additive ``core.CoverageReport`` projection. Returns
    ``None`` when a run has no discovery telemetry (e.g. an import-only campaign). Tenant-scoped."""

    async def coverage_for_run(
        self, *, campaign_run_id: CampaignRunId, client_id: str
    ) -> CoverageReport | None: ...


# --- in-memory fakes (for M13.4 unit tests / local runs before the api root is wired) ------------


class InMemoryCampaignStateReader:
    """A fixture :class:`CampaignStateReader` — backed by a map keyed on ``campaign_run_id``."""

    def __init__(self, states: Mapping[CampaignRunId, RunPhaseState] | None = None) -> None:
        self._states = dict(states or {})

    def set(self, state: RunPhaseState) -> None:
        self._states[state.campaign_run_id] = state

    async def run_phase_state(
        self, *, campaign_run_id: CampaignRunId, client_id: str
    ) -> RunPhaseState | None:
        state = self._states.get(campaign_run_id)
        if state is None or state.client_id != client_id:
            return None
        return state


class InMemoryCostBurnDownReader:
    """A fixture :class:`CostBurnDownReader` — backed by a map keyed on ``campaign_run_id``. The
    second map records which client each run belongs to (tenant isolation in tests)."""

    def __init__(
        self,
        burndowns: Mapping[CampaignRunId, BurnDown] | None = None,
        *,
        owners: Mapping[CampaignRunId, str] | None = None,
    ) -> None:
        self._burndowns = dict(burndowns or {})
        self._owners = dict(owners or {})

    def set(self, campaign_run_id: CampaignRunId, burndown: BurnDown, *, client_id: str) -> None:
        self._burndowns[campaign_run_id] = burndown
        self._owners[campaign_run_id] = client_id

    async def burn_down(self, *, campaign_run_id: CampaignRunId, client_id: str) -> BurnDown | None:
        owner = self._owners.get(campaign_run_id)
        if owner is not None and owner != client_id:
            return None
        return self._burndowns.get(campaign_run_id)


class InMemoryPreRunEstimator:
    """A fixture :class:`PreRunEstimator` — wraps a pure function so a test can make the estimate
    vary with the cutoffs (to prove "recomputes when cutoffs are adjusted")."""

    def __init__(self, fn: Callable[[str, int, Mapping[str, float] | None], Estimate]) -> None:
        self._fn = fn

    async def estimate(
        self,
        *,
        client_id: str,
        discovered_count: int,
        tier_cutoffs: Mapping[str, float] | None = None,
    ) -> Estimate:
        return self._fn(client_id, discovered_count, tier_cutoffs)


class InMemoryVerificationHealthReader:
    """A fixture :class:`VerificationHealthReader` — backed by a map keyed on
    ``campaign_run_id``."""

    def __init__(
        self,
        counts: Mapping[CampaignRunId, VerificationHealthCounts] | None = None,
        *,
        owners: Mapping[CampaignRunId, str] | None = None,
    ) -> None:
        self._counts = dict(counts or {})
        self._owners = dict(owners or {})

    def set(
        self, campaign_run_id: CampaignRunId, counts: VerificationHealthCounts, *, client_id: str
    ) -> None:
        self._counts[campaign_run_id] = counts
        self._owners[campaign_run_id] = client_id

    async def health_counts(
        self, *, campaign_run_id: CampaignRunId, client_id: str
    ) -> VerificationHealthCounts | None:
        owner = self._owners.get(campaign_run_id)
        if owner is not None and owner != client_id:
            return None
        return self._counts.get(campaign_run_id)


class InMemoryCoverageReportReader:
    """A fixture :class:`CoverageReportReader` — backed by a map keyed on ``campaign_run_id``."""

    def __init__(
        self,
        reports: Mapping[CampaignRunId, CoverageReport] | None = None,
        *,
        owners: Mapping[CampaignRunId, str] | None = None,
    ) -> None:
        self._reports = dict(reports or {})
        self._owners = dict(owners or {})

    def set(
        self, campaign_run_id: CampaignRunId, report: CoverageReport, *, client_id: str
    ) -> None:
        self._reports[campaign_run_id] = report
        self._owners[campaign_run_id] = client_id

    async def coverage_for_run(
        self, *, campaign_run_id: CampaignRunId, client_id: str
    ) -> CoverageReport | None:
        owner = self._owners.get(campaign_run_id)
        if owner is not None and owner != client_id:
            return None
        return self._reports.get(campaign_run_id)


# --- the cost_estimate snapshot write (M13.4-owned materialization) ------------------------------

_INSERT_COST_ESTIMATE = text(
    """
    INSERT INTO cost_estimate (
        campaign_run_id, icp_spec_version, discovered_count, projected_deep_count,
        cutoffs_json, estimated_cents
    ) VALUES (
        :campaign_run_id, :icp_spec_version, :discovered_count, :projected_deep_count,
        CAST(:cutoffs AS jsonb), :estimated_cents
    )
    """
)


def _default_thresholds_for(client_id: str) -> VerificationHealthThresholds:
    """The per-client verification-health alert floors, read from the merged config
    (policy-as-data).
    Injectable so unit tests pin fixture floors without touching the process config store."""
    return get_config(client_id).verification_health_thresholds


def _estimate_summary(estimate: Estimate) -> str:
    """The Doc C §5 "~N discovered → ~M go deep → ~\\$X" one-liner for the pre-run panel."""
    dollars = estimate.estimated_cost_cents / 100
    return (
        f"~{estimate.discovered_count} discovered → ~{estimate.projected_deep_count} go deep "
        f"→ est ~${dollars:,.2f}"
    )


def _share(passed: int, total: int) -> float | None:
    """A rate in ``[0, 1]`` — ``None`` when there are no observations (nothing to be unhealthy
    yet)."""
    return passed / total if total else None


def _alerts(share: float | None, floor: float) -> bool:
    """Alert iff a rate exists *and* is below its floor (a missing rate never alerts)."""
    return share is not None and share < floor


class ObservabilitySurface:
    """The read-only cost & progress surface (M13.4) — the six Doc C §6 panels behind one contract.

    A pure read API: a client portal or an internal dashboard are interchangeable clients of it. The
    cross-package panels (progress, burn-down, pre-run estimate, verification health, coverage) are
    served through the injected readers; per-source yield reads ``sources.get_source_yield``
    directly
    (the one shared materialization with the M13.3 learning loop — same helper, so the numbers can
    never diverge). The surface mutates the domain on **no** call; the only write is the optional
    ``cost_estimate`` snapshot in :meth:`pre_run_estimate` (an M13.4-owned side table — the
    interface
    permits writing/refreshing materialized views).

    The per-client exposure flag (``config.observability_client_facing``) is a *visibility* toggle
    enforced at the api/portal boundary, not in this surface — there is one read-projection
    implementation, never two code paths (see :func:`observability_is_client_facing`)."""

    def __init__(
        self,
        *,
        campaign_reader: CampaignStateReader,
        burndown_reader: CostBurnDownReader,
        estimator: PreRunEstimator,
        health_reader: VerificationHealthReader,
        coverage_reader: CoverageReportReader,
        thresholds_for: Callable[[str], VerificationHealthThresholds] = _default_thresholds_for,
        near_cap_remaining_fraction: float = _DEFAULT_NEAR_CAP_REMAINING_FRACTION,
    ) -> None:
        self._campaign_reader = campaign_reader
        self._burndown_reader = burndown_reader
        self._estimator = estimator
        self._health_reader = health_reader
        self._coverage_reader = coverage_reader
        self._thresholds_for = thresholds_for
        # Decimal so the near-cap comparison stays exact against the Decimal cap (no float coerce).
        self._near_cap_fraction = Decimal(str(near_cap_remaining_fraction))

    async def campaign_progress(
        self, *, campaign_run_id: CampaignRunId, client_id: str
    ) -> CampaignProgress | None:
        """Phase progress over the M7.3 state machine — current phase + per-phase completion in the
        canonical ``core.CampaignPhase`` order (so the panel tracks ground truth with no refresh of
        the underlying state). ``None`` for a missing / cross-tenant run."""
        state = await self._campaign_reader.run_phase_state(
            campaign_run_id=campaign_run_id, client_id=client_id
        )
        if state is None:
            return None
        by_phase = {cp.phase: cp.status for cp in state.checkpoints}
        phases = tuple(
            PhaseProgress(
                phase=phase,
                status=by_phase.get(phase, _PHASE_PENDING),
                is_current=phase == state.current_phase,
                is_complete=by_phase.get(phase) == _CHECKPOINT_COMMITTED,
            )
            for phase in CampaignPhase
        )
        return CampaignProgress(
            campaign_run_id=campaign_run_id,
            client_id=client_id,
            current_phase=state.current_phase,
            run_status=state.run_status,
            is_paused=state.run_status == _RUN_PAUSED,
            is_terminal=state.is_terminal,
            awaiting_input=by_phase.get(state.current_phase) == _CHECKPOINT_AWAITING_INPUT,
            phases=phases,
        )

    async def cost_burndown(
        self, *, campaign_run_id: CampaignRunId, client_id: str
    ) -> CostBurnDown | None:
        """Live cost burn-down — spent vs. estimate vs. cap vs. remaining from the authoritative
        ``BudgetEngine.burn_down``, with a derived ``status`` (``graceful_stop`` at the cap,
        ``near_cap`` approaching it, else ``ok``). ``None`` for a missing / cross-tenant run."""
        burndown = await self._burndown_reader.burn_down(
            campaign_run_id=campaign_run_id, client_id=client_id
        )
        if burndown is None:
            return None
        has_cap = burndown.cap_cents > 0
        over_cap = has_cap and burndown.spent_cents >= burndown.cap_cents
        near_cap = (
            has_cap
            and not over_cap
            and burndown.remaining_cents <= burndown.cap_cents * self._near_cap_fraction
        )
        status = (
            COST_STATUS_GRACEFUL_STOP
            if over_cap
            else COST_STATUS_NEAR_CAP
            if near_cap
            else COST_STATUS_OK
        )
        return CostBurnDown(
            campaign_run_id=campaign_run_id,
            spent_cents=burndown.spent_cents,
            estimated_cents=burndown.estimated_cents,
            cap_cents=burndown.cap_cents,
            remaining_cents=burndown.remaining_cents,
            status=status,
            over_cap=over_cap,
            has_cap=has_cap,
        )

    async def pre_run_estimate(
        self,
        *,
        campaign_run_id: CampaignRunId,
        client_id: str,
        discovered_count: int,
        tier_cutoffs: Mapping[str, float] | None = None,
        icp_spec_version: int = 1,
        conn: AsyncConnection | None = None,
    ) -> PreRunEstimate:
        """Pre-run "~N → ~M deep → ~\\$X" projection (Doc C §5), recomputed as ``tier_cutoffs``
        change.

        Pure projection (the injected :class:`PreRunEstimator` never writes ``campaign_run``); when
        a
        ``conn`` is supplied it additionally appends a ``cost_estimate`` snapshot (the M13.4-owned
        materialization — the one sanctioned write, "snapshots as cutoffs change"). With no ``conn``
        it is a side-effect-free read."""
        estimate = await self._estimator.estimate(
            client_id=client_id,
            discovered_count=discovered_count,
            tier_cutoffs=tier_cutoffs,
        )
        if conn is not None:
            await conn.execute(
                _INSERT_COST_ESTIMATE,
                {
                    "campaign_run_id": campaign_run_id,
                    "icp_spec_version": icp_spec_version,
                    "discovered_count": estimate.discovered_count,
                    "projected_deep_count": estimate.projected_deep_count,
                    "cutoffs": serialize_value_json(dict(tier_cutoffs) if tier_cutoffs else {}),
                    "estimated_cents": estimate.estimated_cost_cents,
                },
            )
        return PreRunEstimate(
            campaign_run_id=campaign_run_id,
            discovered_count=estimate.discovered_count,
            projected_deep_count=estimate.projected_deep_count,
            estimated_cents=estimate.estimated_cost_cents,
            cost_per_account_cents=estimate.cost_per_account_cents,
            confidence=estimate.confidence,
            summary=_estimate_summary(estimate),
        )

    async def source_yield(
        self,
        conn: AsyncConnection,
        *,
        client_id: str,
        icp_key: str | None = None,
        icp_version: int | None = None,
    ) -> Sequence[SourceYieldStat]:
        """Per-source yield panel — surfaces ``sources.get_source_yield`` *as-is* (the single shared
        materialization the M13.3 learning loop reweights on, so the two never diverge; a test
        asserts equality). Read-only; the surface writes no yield rows."""
        return await get_source_yield(
            conn, client_id=client_id, icp_key=icp_key, icp_version=icp_version
        )

    async def verification_health(
        self, *, campaign_run_id: CampaignRunId, client_id: str
    ) -> VerificationHealth | None:
        """Verification-health panel (Doc C §6) — tier-4 faithfulness pass share (M9.3), strong
        identity-binding share (the at-rest ``claim.identity_binding`` scan, M9.4 — never the live
        per-class view), and the M9.2 corroboration pass rate, each flagged when below its
        configured
        floor (an early warning of a model/resolver regression). ``None`` for a missing run."""
        counts = await self._health_reader.health_counts(
            campaign_run_id=campaign_run_id, client_id=client_id
        )
        if counts is None:
            return None
        thresholds = self._thresholds_for(client_id)
        faithfulness = _share(counts.faithfulness_passed, counts.faithfulness_total)
        strong_binding = _share(counts.strong_binding, counts.contact_total)
        corroboration = _share(counts.corroboration_passed, counts.corroboration_total)
        faithfulness_alert = _alerts(faithfulness, thresholds.faithfulness_pass_floor)
        strong_binding_alert = _alerts(strong_binding, thresholds.strong_binding_floor)
        corroboration_alert = _alerts(corroboration, thresholds.corroboration_pass_floor)
        return VerificationHealth(
            campaign_run_id=campaign_run_id,
            faithfulness_pass_share=faithfulness,
            strong_binding_share=strong_binding,
            corroboration_pass_rate=corroboration,
            faithfulness_total=counts.faithfulness_total,
            contact_total=counts.contact_total,
            corroboration_total=counts.corroboration_total,
            faithfulness_alert=faithfulness_alert,
            strong_binding_alert=strong_binding_alert,
            corroboration_alert=corroboration_alert,
            alert=faithfulness_alert or strong_binding_alert or corroboration_alert,
        )

    async def coverage_confidence(
        self, *, campaign_run_id: CampaignRunId, client_id: str
    ) -> CoverageReport | None:
        """Coverage-confidence panel (Doc C §7) — the M6.5 estimate ``%`` band **plus** the named
        unsearched channels, framed as confidence not completeness (never a "100%/complete" claim).
        ``None`` when a run has no discovery telemetry (an import-only campaign — surfaced honestly,
        never fabricated)."""
        return await self._coverage_reader.coverage_for_run(
            campaign_run_id=campaign_run_id, client_id=client_id
        )


def observability_is_client_facing(
    client_id: str,
    icp_id: str | None = None,
    *,
    config_loader: Callable[[str, str | None], bool] | None = None,
) -> bool:
    """Whether the observability surface is exposed to ``client_id`` (the D7 per-client toggle).

    Reads ``config.observability_client_facing`` (defaults to the client-facing posture, Doc C §5).
    This is the *only* place the flag is consulted — a portal/api gates exposure on it; the surface
    itself stays flag-agnostic (one read-projection implementation, never two code paths). The
    ``config_loader`` seam keeps it unit-testable without the process config store."""
    if config_loader is not None:
        return config_loader(client_id, icp_id)
    return get_config(client_id, icp_id).observability_client_facing
