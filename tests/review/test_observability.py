"""M13.4 acceptance — the ObservabilitySurface panels, on in-memory reader fakes (no DB).

Covers the spec §M13.4 acceptance criteria that are pure surface logic: phase progress matches the
state machine; cost burn-down derives the graceful-stop / near-cap status; the pre-run estimate
recomputes as cutoffs change; verification health raises the configured alert on a fixture drop and
honours the at-rest strong-binding surface; coverage confidence returns a band + a non-empty
unsearched-channel list and never a "100%/complete" claim; the per-client exposure flag toggles
visibility without a code change. The DB-backed criteria (per-source-yield equality, the at-rest
claim scan, the cost_estimate snapshot, no-domain-mutation) live in ``test_observability_db.py``.
"""

from __future__ import annotations

from decimal import Decimal

from clue_config import (
    ConfigOverlay,
    OverlayStore,
    VerificationHealthThresholds,
    get_config,
)
from clue_core import (
    BurnDown,
    CampaignPhase,
    CoverageReport,
    Estimate,
    UnsearchedChannel,
    new_campaign_run_id,
    new_run_id,
)
from clue_research.review import (
    COST_STATUS_GRACEFUL_STOP,
    COST_STATUS_NEAR_CAP,
    COST_STATUS_OK,
    InMemoryCampaignStateReader,
    InMemoryCostBurnDownReader,
    InMemoryCoverageReportReader,
    InMemoryPreRunEstimator,
    InMemoryVerificationHealthReader,
    ObservabilitySurface,
    PhaseProgress,
    RunPhaseState,
    VerificationHealthCounts,
    observability_is_client_facing,
)
from clue_research.review.observability import _estimate_summary

from .conftest import run_async

_CLIENT = "acme"
_OTHER = "globex"


def _surface(
    *,
    campaign_reader: InMemoryCampaignStateReader | None = None,
    burndown_reader: InMemoryCostBurnDownReader | None = None,
    estimator: InMemoryPreRunEstimator | None = None,
    health_reader: InMemoryVerificationHealthReader | None = None,
    coverage_reader: InMemoryCoverageReportReader | None = None,
    thresholds: VerificationHealthThresholds | None = None,
) -> ObservabilitySurface:
    """An ObservabilitySurface wired entirely on fakes — no DB, no config store."""
    floors = thresholds or VerificationHealthThresholds()
    return ObservabilitySurface(
        campaign_reader=campaign_reader or InMemoryCampaignStateReader(),
        burndown_reader=burndown_reader or InMemoryCostBurnDownReader(),
        estimator=estimator or InMemoryPreRunEstimator(lambda *_: _ESTIMATE),
        health_reader=health_reader or InMemoryVerificationHealthReader(),
        coverage_reader=coverage_reader or InMemoryCoverageReportReader(),
        thresholds_for=lambda _client: floors,
    )


_ESTIMATE = Estimate(
    discovered_count=100,
    projected_deep_count=20,
    estimated_cost_cents=Decimal("50000"),
    cost_per_account_cents=Decimal("2500"),
)


# --- campaign_progress (AC: matches state-machine ground truth) ---------------


def test_campaign_progress_orders_phases_and_marks_current_complete_awaiting() -> None:
    run = new_campaign_run_id()
    reader = InMemoryCampaignStateReader()
    reader.set(
        RunPhaseState(
            campaign_run_id=run,
            client_id=_CLIENT,
            current_phase=CampaignPhase.REVIEW,
            run_status="paused",
            is_terminal=False,
            checkpoints=(
                PhaseProgress(phase=CampaignPhase.DISCOVERY, status="committed"),
                PhaseProgress(phase=CampaignPhase.SCORING, status="committed"),
                PhaseProgress(phase=CampaignPhase.REVIEW, status="awaiting_input"),
            ),
        )
    )
    surface = _surface(campaign_reader=reader)

    progress = run_async(surface.campaign_progress(campaign_run_id=run, client_id=_CLIENT))
    assert progress is not None
    # phases come back in the canonical CampaignPhase order, no manual refresh.
    assert tuple(p.phase for p in progress.phases) == tuple(CampaignPhase)
    by_phase = {p.phase: p for p in progress.phases}
    assert by_phase[CampaignPhase.DISCOVERY].is_complete is True
    assert by_phase[CampaignPhase.REVIEW].is_current is True
    assert by_phase[CampaignPhase.REVIEW].is_complete is False
    # a phase with no checkpoint row reads "pending".
    assert by_phase[CampaignPhase.HANDOFF].status == "pending"
    assert by_phase[CampaignPhase.HANDOFF].is_complete is False
    # REVIEW gate: paused + current-phase AWAITING_INPUT == a human gate.
    assert progress.is_paused is True
    assert progress.awaiting_input is True
    assert progress.current_phase is CampaignPhase.REVIEW


def test_campaign_progress_is_tenant_scoped() -> None:
    run = new_campaign_run_id()
    reader = InMemoryCampaignStateReader()
    reader.set(
        RunPhaseState(
            campaign_run_id=run,
            client_id=_CLIENT,
            current_phase=CampaignPhase.DISCOVERY,
            run_status="active",
        )
    )
    surface = _surface(campaign_reader=reader)
    assert run_async(surface.campaign_progress(campaign_run_id=run, client_id=_OTHER)) is None


# --- cost_burndown (AC: spent/estimate/cap reconcile; graceful-stop status) ----


def _burndown(spent: str, estimated: str, cap: str) -> BurnDown:
    spent_d, cap_d = Decimal(spent), Decimal(cap)
    return BurnDown(
        spent_cents=spent_d,
        estimated_cents=Decimal(estimated),
        cap_cents=cap_d,
        remaining_cents=max(Decimal(0), cap_d - spent_d),
    )


def test_cost_burndown_status_ok_near_cap_and_graceful_stop() -> None:
    run = new_campaign_run_id()
    reader = InMemoryCostBurnDownReader()
    reader.set(run, _burndown("400", "1000", "1000"), client_id=_CLIENT)
    surface = _surface(burndown_reader=reader)

    bd = run_async(surface.cost_burndown(campaign_run_id=run, client_id=_CLIENT))
    assert bd is not None
    # reconciles spent/estimate/cap/remaining straight off the authoritative BurnDown.
    assert bd.spent_cents == Decimal("400")
    assert bd.cap_cents == Decimal("1000")
    assert bd.remaining_cents == Decimal("600")
    assert bd.status == COST_STATUS_OK
    assert bd.over_cap is False
    assert bd.has_cap is True

    reader.set(run, _burndown("950", "1000", "1000"), client_id=_CLIENT)  # 50 of 1000 left → near
    near = run_async(surface.cost_burndown(campaign_run_id=run, client_id=_CLIENT))
    assert near is not None and near.status == COST_STATUS_NEAR_CAP and near.over_cap is False

    reader.set(run, _burndown("1000", "1000", "1000"), client_id=_CLIENT)  # spent == cap
    stopped = run_async(surface.cost_burndown(campaign_run_id=run, client_id=_CLIENT))
    assert stopped is not None
    assert stopped.status == COST_STATUS_GRACEFUL_STOP  # stops at the cap, never overspends
    assert stopped.over_cap is True
    assert stopped.remaining_cents == Decimal("0")


def test_cost_burndown_no_cap_is_ok() -> None:
    run = new_campaign_run_id()
    reader = InMemoryCostBurnDownReader()
    reader.set(run, _burndown("9999", "0", "0"), client_id=_CLIENT)  # cap 0 == none configured
    surface = _surface(burndown_reader=reader)
    bd = run_async(surface.cost_burndown(campaign_run_id=run, client_id=_CLIENT))
    assert bd is not None and bd.status == COST_STATUS_OK and bd.has_cap is False


# --- pre_run_estimate (AC: ~N → ~M → ~$X, recomputes when cutoffs change) ------


def test_pre_run_estimate_summary_and_recompute_on_cutoff_change() -> None:
    run = new_campaign_run_id()

    def fn(client_id: str, discovered: int, cutoffs) -> Estimate:  # type: ignore[no-untyped-def]
        # a stricter cutoff sends fewer accounts deep — the estimate must move with the cutoffs.
        cutoff = max((cutoffs or {}).values(), default=0.0)
        deep = round(discovered * (1 - cutoff))
        return Estimate(
            discovered_count=discovered,
            projected_deep_count=deep,
            estimated_cost_cents=Decimal(deep * 2500),
            cost_per_account_cents=Decimal("2500"),
        )

    surface = _surface(estimator=InMemoryPreRunEstimator(fn))

    loose = run_async(
        surface.pre_run_estimate(
            campaign_run_id=run, client_id=_CLIENT, discovered_count=100, tier_cutoffs={"top": 0.6}
        )
    )
    strict = run_async(
        surface.pre_run_estimate(
            campaign_run_id=run, client_id=_CLIENT, discovered_count=100, tier_cutoffs={"top": 0.9}
        )
    )
    assert loose.projected_deep_count == 40
    assert strict.projected_deep_count == 10  # recomputed lower for the stricter cutoff
    assert strict.estimated_cents < loose.estimated_cents
    assert loose.confidence == 0.5  # the uniform-score assumption, surfaced honestly
    assert "100 discovered" in loose.summary and "40 go deep" in loose.summary


def test_estimate_summary_renders_dollars() -> None:
    summary = _estimate_summary(_ESTIMATE)
    assert summary == "~100 discovered → ~20 go deep → est ~$500.00"


# --- verification_health (AC: three rates; fixture drop raises the alert) ------


def test_verification_health_raises_alert_on_faithfulness_drop() -> None:
    run = new_campaign_run_id()
    reader = InMemoryVerificationHealthReader()
    # 1 / 10 tier-4 claims pass the judge — well below the 0.8 floor → faithfulness alert.
    reader.set(
        run,
        VerificationHealthCounts(
            faithfulness_passed=1,
            faithfulness_total=10,
            strong_binding=9,
            contact_total=10,
            corroboration_passed=8,
            corroboration_total=10,
        ),
        client_id=_CLIENT,
    )
    surface = _surface(
        health_reader=reader,
        thresholds=VerificationHealthThresholds(
            faithfulness_pass_floor=0.8, strong_binding_floor=0.5, corroboration_pass_floor=0.5
        ),
    )
    health = run_async(surface.verification_health(campaign_run_id=run, client_id=_CLIENT))
    assert health is not None
    assert health.faithfulness_pass_share == 0.1
    assert health.strong_binding_share == 0.9
    assert health.corroboration_pass_rate == 0.8
    assert health.faithfulness_alert is True  # the configured drop fires
    assert health.strong_binding_alert is False
    assert health.corroboration_alert is False
    assert health.alert is True


def test_verification_health_healthy_run_raises_no_alert() -> None:
    run = new_campaign_run_id()
    reader = InMemoryVerificationHealthReader()
    reader.set(
        run,
        VerificationHealthCounts(
            faithfulness_passed=9,
            faithfulness_total=10,
            strong_binding=8,
            contact_total=10,
            corroboration_passed=9,
            corroboration_total=10,
        ),
        client_id=_CLIENT,
    )
    surface = _surface(health_reader=reader)
    health = run_async(surface.verification_health(campaign_run_id=run, client_id=_CLIENT))
    assert health is not None and health.alert is False


def test_verification_health_no_observations_never_alerts() -> None:
    run = new_campaign_run_id()
    reader = InMemoryVerificationHealthReader()
    reader.set(run, VerificationHealthCounts(), client_id=_CLIENT)  # all zero denominators
    surface = _surface(
        health_reader=reader,
        thresholds=VerificationHealthThresholds(faithfulness_pass_floor=0.99),
    )
    health = run_async(surface.verification_health(campaign_run_id=run, client_id=_CLIENT))
    assert health is not None
    assert health.faithfulness_pass_share is None  # nothing to be unhealthy about yet
    assert health.alert is False


# --- coverage_confidence (AC: % + non-empty unsearched, never 100%/complete) --


def test_coverage_confidence_returns_band_and_unsearched_never_complete() -> None:
    run = new_campaign_run_id()
    discovery_run = new_run_id()
    reader = InMemoryCoverageReportReader()
    reader.set(
        run,
        CoverageReport(
            run_id=discovery_run,
            coverage_low=0.4,
            coverage_high=0.6,
            coverage_point=0.5,
            confidence="moderate",
            estimate_percent="~40–60%",
            channels_searched=("linkedin", "crunchbase"),
            channels_not_searched=(UnsearchedChannel(source_key="g2", tier=3),),
            framing="estimated ~40–60% of the addressable set found via the channels searched",
        ),
        client_id=_CLIENT,
    )
    surface = _surface(coverage_reader=reader)
    report = run_async(surface.coverage_confidence(campaign_run_id=run, client_id=_CLIENT))
    assert report is not None
    assert report.channels_not_searched  # the honesty guarantee: a non-empty gap list
    assert "100%" not in report.estimate_percent
    assert "complete" not in report.framing.lower()
    assert report.is_complete_claim is False


def test_coverage_confidence_none_for_import_only_run() -> None:
    run = new_campaign_run_id()
    surface = _surface(coverage_reader=InMemoryCoverageReportReader())  # no coverage telemetry
    assert run_async(surface.coverage_confidence(campaign_run_id=run, client_id=_CLIENT)) is None


# --- exposure flag (AC: toggles visibility without a code change) --------------


def test_exposure_flag_defaults_client_facing_and_overlay_flips_it() -> None:
    store = OverlayStore()
    # default posture (no overlay) is client-facing (Doc C §5).
    assert get_config("default-client", store=store).observability_client_facing is True
    # a per-client overlay flips JUST this flag — no sub-tree re-supply needed.
    store.set_client_overlay("internal-client", ConfigOverlay(observability_client_facing=False))
    assert get_config("internal-client", store=store).observability_client_facing is False
    # the merged config still has every other surface at its default (single scalar override).
    assert get_config("internal-client", store=store).budget_caps is not None


def test_exposure_flag_overlay_default_true_when_absent() -> None:
    store = OverlayStore()
    # an overlay that sets other knobs but not the flag leaves it at the default True.
    store.set_client_overlay(
        "c", ConfigOverlay(verification_health_thresholds=VerificationHealthThresholds())
    )
    assert get_config("c", store=store).observability_client_facing is True


def test_verification_health_thresholds_overlay_overrides_defaults() -> None:
    store = OverlayStore()
    store.set_client_overlay(
        "strict",
        ConfigOverlay(
            verification_health_thresholds=VerificationHealthThresholds(
                faithfulness_pass_floor=0.95
            )
        ),
    )
    floors = get_config("strict", store=store).verification_health_thresholds
    assert floors.faithfulness_pass_floor == 0.95


def test_observability_is_client_facing_reads_the_flag() -> None:
    assert observability_is_client_facing("c", config_loader=lambda _c, _i: True) is True
    assert observability_is_client_facing("c", config_loader=lambda _c, _i: False) is False
