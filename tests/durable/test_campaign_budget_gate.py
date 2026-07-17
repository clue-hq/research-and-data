"""M7.5 × M7.3 coupling — the per-run budget cap graceful-stops the campaign state machine.

The acceptance criteria: a campaign run that has reached its per-run cap performs a *graceful stop
at the next checkpoint* (via M7.3) instead of overspending, and raising the cap then lets ``resume``
continue the same phase. These wire the real :class:`BudgetEngine` (on an in-memory store) into a
:class:`CampaignRun` (on the in-memory campaign store) — exactly the production seam, fakes for
persistence.
"""

from __future__ import annotations

from decimal import Decimal

from clue_config import BudgetCaps
from clue_core import CampaignPhase
from clue_research.durable import (
    CampaignRun,
    CampaignRunStatus,
    PhaseCheckpointStatus,
    PhaseHandlerRegistry,
)
from clue_research.durable.budget import BudgetEngine
from clue_research.durable.campaign import PHASE_SEQUENCE
from clue_research.durable.enums import BudgetEventKind
from tests.db.conftest import run_async
from tests.durable.conftest import FakeBudgetStore, FakeCampaignRunStore, RecordingPhaseHandler


def _registry(events: list[str]) -> tuple[PhaseHandlerRegistry, dict]:
    registry = PhaseHandlerRegistry()
    handlers = {}
    for phase in PHASE_SEQUENCE:
        handler = RecordingPhaseHandler(phase, events=events)
        registry.register(handler)
        handlers[phase] = handler
    return registry, handlers


def test_over_cap_run_graceful_stops_before_first_spend_phase() -> None:
    async def _run() -> None:
        campaign_store = FakeCampaignRunStore()
        budget_store = FakeBudgetStore()
        events: list[str] = []
        registry, handlers = _registry(events)
        engine = BudgetEngine(store=budget_store)
        machine = CampaignRun(store=campaign_store, registry=registry, budget_engine=engine)

        run_id = await machine.start(client_id="c1", icp_key="default", icp_version=1)
        # Simulate prior spend already at/over the cap (cap lowered below spend).
        budget_store.set_run(run_id, spent=Decimal("900"), cap=Decimal("500"))

        run = await machine.run_to_completion(run_id)
        # The ungated setup phases ran; the first *spend* phase (discovery) is graceful-stopped.
        assert run.status is CampaignRunStatus.PAUSED
        assert run.phase is CampaignPhase.DISCOVERY
        assert handlers[CampaignPhase.REVERSE_PROFILING].calls == 1
        assert handlers[CampaignPhase.ICP_CONFIRMED].calls == 1
        assert handlers[CampaignPhase.DISCOVERY].calls == 0  # never spent
        # No checkpoint was staged for the stopped phase (cooperative pause, not an AWAITING gate).
        assert await campaign_store.get_checkpoint(run_id, CampaignPhase.DISCOVERY) is None
        # The graceful stop is audited.
        assert BudgetEventKind.GRACEFUL_STOP in budget_store.kinds()

    run_async(_run())


def test_raising_cap_then_resume_continues_the_same_phase() -> None:
    async def _run() -> None:
        campaign_store = FakeCampaignRunStore()
        budget_store = FakeBudgetStore()
        events: list[str] = []
        registry, handlers = _registry(events)
        engine = BudgetEngine(store=budget_store)
        machine = CampaignRun(store=campaign_store, registry=registry, budget_engine=engine)

        run_id = await machine.start(client_id="c1", icp_key="default", icp_version=1)
        budget_store.set_run(run_id, spent=Decimal("900"), cap=Decimal("500"))
        run = await machine.run_to_completion(run_id)
        assert run.status is CampaignRunStatus.PAUSED
        assert run.phase is CampaignPhase.DISCOVERY

        # Client raises the cap (flows through adjust → engine.set_campaign_cap) and resumes.
        await machine.adjust(run_id, budget_cap_cents=Decimal("5000"))
        assert budget_store.run_state is not None
        state = await budget_store.run_state(run_id)
        assert state is not None and state.cap_cents == Decimal("5000")
        assert BudgetEventKind.CAP_RAISED in budget_store.kinds()

        await machine.resume(run_id)
        run = await machine.run_to_completion(run_id)
        # Now under cap → discovery (and the rest) runs to completion; no phase was skipped.
        assert run.status is CampaignRunStatus.COMPLETED
        assert run.phase is CampaignPhase.HANDOFF
        assert handlers[CampaignPhase.DISCOVERY].calls == 1
        discovery_ckpt = await campaign_store.get_checkpoint(run_id, CampaignPhase.DISCOVERY)
        assert discovery_ckpt is not None
        assert discovery_ckpt.status is PhaseCheckpointStatus.COMMITTED

    run_async(_run())


def test_within_cap_run_completes_normally() -> None:
    async def _run() -> None:
        campaign_store = FakeCampaignRunStore()
        budget_store = FakeBudgetStore()
        events: list[str] = []
        registry, handlers = _registry(events)
        engine = BudgetEngine(store=budget_store)
        machine = CampaignRun(store=campaign_store, registry=registry, budget_engine=engine)

        run_id = await machine.start(client_id="c1", icp_key="default", icp_version=1)
        budget_store.set_run(run_id, spent=Decimal("100"), cap=Decimal("100000"))  # plenty

        run = await machine.run_to_completion(run_id)
        assert run.status is CampaignRunStatus.COMPLETED
        assert all(h.calls == 1 for h in handlers.values())
        # A run comfortably under cap records no graceful-stop event.
        assert BudgetEventKind.GRACEFUL_STOP not in budget_store.kinds()

    run_async(_run())


def test_pre_run_estimate_reflects_a_cutoff_adjust() -> None:
    # The AC "re-estimating after a cutoff adjust reflects the new projection" — end-to-end through
    # CampaignRun.pre_run_estimate → BudgetEngine.estimate, using the run's stored tier cutoffs.
    async def _run() -> None:
        campaign_store = FakeCampaignRunStore()
        budget_store = FakeBudgetStore()
        registry, _ = _registry([])
        engine = BudgetEngine(
            policy=BudgetCaps(
                pass_a_cap_cents_per_account=Decimal("1"),
                per_account_cap_cents={"top": Decimal("500")},
            ),
            store=budget_store,
        )
        machine = CampaignRun(store=campaign_store, registry=registry, budget_engine=engine)

        run_id = await machine.start(
            client_id="c1",
            icp_key="default",
            icp_version=1,
            tier_cutoffs={"top": 0.6},  # loose cutoff → more go deep
        )
        loose = await machine.pre_run_estimate(run_id, discovered_count=1000)

        # Tighten the cutoff mid-run; the next estimate must drop (fewer accounts go deep).
        await machine.adjust(run_id, tier_cutoffs={"top": 0.9})
        tight = await machine.pre_run_estimate(run_id, discovered_count=1000)

        assert tight.projected_deep_count < loose.projected_deep_count
        assert tight.estimated_cost_cents < loose.estimated_cost_cents

    run_async(_run())


def test_uncapped_run_with_engine_is_never_gated() -> None:
    async def _run() -> None:
        campaign_store = FakeCampaignRunStore()
        budget_store = FakeBudgetStore()
        events: list[str] = []
        registry, handlers = _registry(events)
        engine = BudgetEngine(store=budget_store)
        machine = CampaignRun(store=campaign_store, registry=registry, budget_engine=engine)

        run_id = await machine.start(client_id="c1", icp_key="default", icp_version=1)
        budget_store.set_run(run_id, spent=Decimal("999999"), cap=None)  # no cap → never stops

        run = await machine.run_to_completion(run_id)
        assert run.status is CampaignRunStatus.COMPLETED
        assert all(h.calls == 1 for h in handlers.values())

    run_async(_run())
