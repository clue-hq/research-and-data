"""M7.4 phase-level idempotency wired into the M7.3 state machine — in-memory store + fake ledger.

These assert that, with an :class:`IdempotencyStore` injected, ``CampaignRun`` finalizes each phase
**exactly once** on the ``(campaign_run, phase)`` key: a full run records one ``succeeded`` ledger
row per phase with the phase's charge; re-driving a completed run re-charges nothing;
``submit_checkpoint`` approves through the ledger; and a simulated crash between the commit and the
resume (run left PAUSED at a COMMITTED phase with the ledger still ``in_progress``) self-heals
through the same ledger-bracketed finalize. Phase progression stays identical to the no-ledger path.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from clue_research.core import CampaignPhase, IdempotencyScope, PhaseStatus
from clue_research.core.idempotency import phase_key
from clue_research.durable import (
    PHASE_SEQUENCE,
    CampaignRun,
    CampaignRunStatus,
    IdempotencyStatus,
    PhaseCheckpointStatus,
    PhaseHandlerRegistry,
)
from tests.db.conftest import run_async
from tests.durable.conftest import (
    FakeCampaignRunStore,
    FakeIdempotencyStore,
    RecordingPhaseHandler,
)


def _registry(
    events: list[str], overrides: dict[CampaignPhase, RecordingPhaseHandler] | None = None
) -> tuple[PhaseHandlerRegistry, dict[CampaignPhase, RecordingPhaseHandler]]:
    overrides = overrides or {}
    registry = PhaseHandlerRegistry()
    handlers: dict[CampaignPhase, RecordingPhaseHandler] = {}
    for phase in PHASE_SEQUENCE:
        handler = overrides.get(phase) or RecordingPhaseHandler(phase, events=events)
        registry.register(handler)
        handlers[phase] = handler
    return registry, handlers


def test_full_run_records_one_succeeded_ledger_row_per_phase() -> None:
    store = FakeCampaignRunStore()
    ledger = FakeIdempotencyStore()
    events: list[str] = []
    # each phase charges a distinct cost so we can assert the per-phase charge lands in the ledger
    overrides = {
        phase: RecordingPhaseHandler(phase, events=events, cost_cents=Decimal(i + 1))
        for i, phase in enumerate(PHASE_SEQUENCE)
    }
    registry, handlers = _registry(events, overrides=overrides)
    machine = CampaignRun(store=store, registry=registry, ledger=ledger)

    async def _run() -> None:
        run_id = await machine.start(client_id="c1", icp_key="default", icp_version=1)
        run = await machine.run_to_completion(run_id)
        # phase progression identical to the no-ledger path
        assert run.status is CampaignRunStatus.COMPLETED
        assert events == [p.value for p in PHASE_SEQUENCE]
        assert all(h.calls == 1 for h in handlers.values())
        # exactly one succeeded ledger row per phase, each with that phase's charge
        for i, phase in enumerate(PHASE_SEQUENCE):
            row = await ledger.get(phase_key(run_id, phase))
            assert row is not None, phase
            assert row.scope is IdempotencyScope.CAMPAIGN_PHASE
            assert row.status is IdempotencyStatus.SUCCEEDED
            assert row.result_ref == {"phase": phase.value}
            assert row.cost_cents_charged == Decimal(i + 1)

    run_async(_run())


def test_re_driving_a_completed_run_recharges_nothing() -> None:
    store = FakeCampaignRunStore()
    ledger = FakeIdempotencyStore()
    events: list[str] = []
    registry, handlers = _registry(events)
    machine = CampaignRun(store=store, registry=registry, ledger=ledger)

    async def _run() -> None:
        run_id = await machine.start(client_id="c1", icp_key="default", icp_version=1)
        await machine.run_to_completion(run_id)
        # a second drive over the finished run is a no-op: no handler re-runs, no ledger row flips
        again = await machine.run_to_completion(run_id)
        assert again.status is CampaignRunStatus.COMPLETED
        assert all(h.calls == 1 for h in handlers.values())
        for phase in PHASE_SEQUENCE:
            row = await ledger.get(phase_key(run_id, phase))
            assert row is not None and row.status is IdempotencyStatus.SUCCEEDED

    run_async(_run())


def test_submit_checkpoint_approve_finalizes_through_the_ledger() -> None:
    store = FakeCampaignRunStore()
    ledger = FakeIdempotencyStore()
    events: list[str] = []
    gate = RecordingPhaseHandler(
        CampaignPhase.TIER_CHECKPOINT,
        result_status=PhaseStatus.PAUSED,
        payload={"proposed_cutoffs": {"top": 0.8}},
        events=events,
    )
    registry, handlers = _registry(events, overrides={CampaignPhase.TIER_CHECKPOINT: gate})
    machine = CampaignRun(store=store, registry=registry, ledger=ledger)

    async def _run() -> None:
        run_id = await machine.start(client_id="c1", icp_key="default", icp_version=1)
        run = await machine.run_to_completion(run_id)
        assert run.status is CampaignRunStatus.PAUSED
        assert run.phase is CampaignPhase.TIER_CHECKPOINT
        # before approval the gate has not committed in the ledger
        gate_key = phase_key(run_id, CampaignPhase.TIER_CHECKPOINT)
        assert await ledger.get(gate_key) is None

        resumed = await machine.submit_checkpoint(run_id, decision={"action": "approve"})
        assert resumed.phase is CampaignPhase.DEEP
        assert resumed.status is CampaignRunStatus.ACTIVE
        # the gate is now finalized in the ledger exactly once
        gate_row = await ledger.get(gate_key)
        assert gate_row is not None and gate_row.status is IdempotencyStatus.SUCCEEDED

        final = await machine.run_to_completion(run_id)
        assert final.status is CampaignRunStatus.COMPLETED
        assert handlers[CampaignPhase.DEEP].calls == 1

    run_async(_run())


def test_self_heal_finalizes_through_ledger_after_crash_between_commit_and_resume() -> None:
    """A crash after the checkpoint commit but before the resume leaves the run PAUSED at a
    COMMITTED phase with the ledger still in_progress; a retried submit re-owns (the stale window
    is zero for the single-driver phase) and finalizes — advancing the gate, marking the ledger
    done."""
    store = FakeCampaignRunStore()
    ledger = FakeIdempotencyStore()
    events: list[str] = []
    gate = RecordingPhaseHandler(
        CampaignPhase.TIER_CHECKPOINT, result_status=PhaseStatus.PAUSED, events=events
    )
    registry, _ = _registry(events, overrides={CampaignPhase.TIER_CHECKPOINT: gate})
    machine = CampaignRun(store=store, registry=registry, ledger=ledger)

    async def _run() -> None:
        run_id = await machine.start(client_id="c1", icp_key="default", icp_version=1)
        await machine.run_to_completion(run_id)  # suspended at the gate
        gate_key = phase_key(run_id, CampaignPhase.TIER_CHECKPOINT)

        # Simulate the partial-approve crash: checkpoint COMMITTED, run still PAUSED, ledger claimed
        # in_progress but never finished.
        await store.put_checkpoint(
            campaign_run_id=run_id,
            phase=CampaignPhase.TIER_CHECKPOINT,
            idempotency_key=gate_key,
            status=PhaseCheckpointStatus.COMMITTED,
            payload={"decision": {"action": "approve"}},
        )
        await ledger.claim(
            key=gate_key, scope=IdempotencyScope.CAMPAIGN_PHASE, stale_after=timedelta(0)
        )
        assert (await ledger.get(gate_key)).status is IdempotencyStatus.IN_PROGRESS  # type: ignore[union-attr]

        # the retried submit self-heals to the next phase and finalizes the ledger
        healed = await machine.submit_checkpoint(run_id, decision={"action": "approve"})
        assert healed.phase is CampaignPhase.DEEP
        assert healed.status is CampaignRunStatus.ACTIVE
        assert (await ledger.get(gate_key)).status is IdempotencyStatus.SUCCEEDED  # type: ignore[union-attr]

    run_async(_run())


def test_self_heal_finalizes_after_crash_between_resume_and_transition() -> None:
    """Crash *after* the resume mark (run already ACTIVE) but before the transition: the checkpoint
    is COMMITTED, the run is ACTIVE at the gate phase, the ledger is still in_progress. A retried
    submit must self-heal (the COMMITTED+ACTIVE branch) — not raise CheckpointNotAwaiting — and
    finalize to the next phase."""
    store = FakeCampaignRunStore()
    ledger = FakeIdempotencyStore()
    events: list[str] = []
    gate = RecordingPhaseHandler(
        CampaignPhase.TIER_CHECKPOINT, result_status=PhaseStatus.PAUSED, events=events
    )
    registry, _ = _registry(events, overrides={CampaignPhase.TIER_CHECKPOINT: gate})
    machine = CampaignRun(store=store, registry=registry, ledger=ledger)

    async def _run() -> None:
        run_id = await machine.start(client_id="c1", icp_key="default", icp_version=1)
        await machine.run_to_completion(run_id)  # suspended at the gate (PAUSED, AWAITING_INPUT)
        gate_key = phase_key(run_id, CampaignPhase.TIER_CHECKPOINT)

        # Crash state: checkpoint COMMITTED, run already marked ACTIVE (the resume happened), ledger
        # still in_progress (succeed never ran), and not yet transitioned.
        await store.put_checkpoint(
            campaign_run_id=run_id,
            phase=CampaignPhase.TIER_CHECKPOINT,
            idempotency_key=gate_key,
            status=PhaseCheckpointStatus.COMMITTED,
            payload={"decision": {"action": "approve"}},
        )
        await store.mark_status(run_id, status=CampaignRunStatus.ACTIVE, stamp_resumed=True)
        await ledger.claim(
            key=gate_key, scope=IdempotencyScope.CAMPAIGN_PHASE, stale_after=timedelta(0)
        )

        healed = await machine.submit_checkpoint(run_id, decision={"action": "approve"})
        assert healed.phase is CampaignPhase.DEEP
        assert healed.status is CampaignRunStatus.ACTIVE
        assert (await ledger.get(gate_key)).status is IdempotencyStatus.SUCCEEDED  # type: ignore[union-attr]

    run_async(_run())


def test_self_heal_replay_still_transitions_when_ledger_already_succeeded() -> None:
    """Crash *after* the ledger succeed but before the transition: checkpoint COMMITTED, run ACTIVE,
    ledger already SUCCEEDED. A retried submit hits the finalize REPLAY path, which must STILL
    transition (not return a stuck, non-transitioned run)."""
    store = FakeCampaignRunStore()
    ledger = FakeIdempotencyStore()
    events: list[str] = []
    gate = RecordingPhaseHandler(
        CampaignPhase.TIER_CHECKPOINT, result_status=PhaseStatus.PAUSED, events=events
    )
    registry, _ = _registry(events, overrides={CampaignPhase.TIER_CHECKPOINT: gate})
    machine = CampaignRun(store=store, registry=registry, ledger=ledger)

    async def _run() -> None:
        run_id = await machine.start(client_id="c1", icp_key="default", icp_version=1)
        await machine.run_to_completion(run_id)
        gate_key = phase_key(run_id, CampaignPhase.TIER_CHECKPOINT)

        await store.put_checkpoint(
            campaign_run_id=run_id,
            phase=CampaignPhase.TIER_CHECKPOINT,
            idempotency_key=gate_key,
            status=PhaseCheckpointStatus.COMMITTED,
            payload={"decision": {"action": "approve"}},
        )
        await store.mark_status(run_id, status=CampaignRunStatus.ACTIVE, stamp_resumed=True)
        await ledger.claim(
            key=gate_key, scope=IdempotencyScope.CAMPAIGN_PHASE, stale_after=timedelta(0)
        )
        await ledger.succeed(
            key=gate_key, result_ref={"phase": "tier_checkpoint"}, cost_cents=Decimal(0)
        )

        healed = await machine.submit_checkpoint(run_id, decision={"action": "approve"})
        assert healed.phase is CampaignPhase.DEEP  # replay still transitioned
        assert healed.status is CampaignRunStatus.ACTIVE

    run_async(_run())


def test_phase_progression_is_identical_with_and_without_a_ledger() -> None:
    """Wiring a ledger must not change *what* happens, only add the exactly-once charge record."""

    async def _drive(ledger: FakeIdempotencyStore | None) -> list[str]:
        store = FakeCampaignRunStore()
        events: list[str] = []
        registry, _ = _registry(events)
        machine = CampaignRun(store=store, registry=registry, ledger=ledger)
        run_id = await machine.start(client_id="c1", icp_key="default", icp_version=1)
        await machine.run_to_completion(run_id)
        return events

    with_ledger = run_async(_drive(FakeIdempotencyStore()))
    without_ledger = run_async(_drive(None))
    assert with_ledger == without_ledger == [p.value for p in PHASE_SEQUENCE]
