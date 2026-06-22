"""Campaign-run state-machine behaviour (M7.3) — in-memory store + fake handlers, no DB.

Exercises the M7.3 acceptance criteria on :class:`FakeCampaignRunStore` with recording phase
handlers: phases advance in order; a crash resumes at the last committed phase without re-running;
``pause``/``resume`` stop and continue without re-spending; the ``tier_checkpoint`` human gate
suspends durably and ``submit_checkpoint`` resumes ``deep``; ``adjust`` is journaled and the next
phase sees the change; ``pre_run_estimate`` delegates to the budget engine.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from clue_research.core import (
    BudgetEngine,
    CampaignPhase,
    PhaseHandler,
    PhaseStatus,
    new_campaign_run_id,
)
from clue_research.durable import (
    PHASE_SEQUENCE,
    BudgetEngineNotConfigured,
    CampaignRun,
    CampaignRunNotFound,
    CampaignRunStatus,
    CampaignRunStore,
    CheckpointNotAwaiting,
    NoPhaseHandlerRegistered,
    PhaseCheckpointStatus,
    PhaseHandlerRegistry,
)
from tests.db.conftest import run_async
from tests.durable.conftest import (
    FakeBudgetEngine,
    FakeCampaignRunStore,
    RecordingPhaseHandler,
)


def _registry(
    events: list[str], overrides: dict[CampaignPhase, RecordingPhaseHandler] | None = None
) -> tuple[PhaseHandlerRegistry, dict[CampaignPhase, RecordingPhaseHandler]]:
    """A registry with one recording handler per phase (all ``COMPLETED`` by default), sharing one
    ``events`` list so phase ordering is observable. ``overrides`` swaps specific phases (a gate /
    a failure)."""
    overrides = overrides or {}
    registry = PhaseHandlerRegistry()
    handlers: dict[CampaignPhase, RecordingPhaseHandler] = {}
    for phase in PHASE_SEQUENCE:
        handler = overrides.get(phase) or RecordingPhaseHandler(phase, events=events)
        registry.register(handler)
        handlers[phase] = handler
    return registry, handlers


def test_advances_through_all_phases_in_order() -> None:
    store = FakeCampaignRunStore()
    events: list[str] = []
    registry, handlers = _registry(events)
    machine = CampaignRun(store=store, registry=registry)

    async def _run() -> None:
        run_id = await machine.start(client_id="c1", icp_key="default", icp_version=1)
        run = await machine.run_to_completion(run_id)
        assert run.status is CampaignRunStatus.COMPLETED
        assert run.phase is CampaignPhase.HANDOFF
        # every phase ran exactly once, in the canonical order
        assert events == [p.value for p in PHASE_SEQUENCE]
        assert all(h.calls == 1 for h in handlers.values())
        # and every phase left a committed checkpoint with a commit timestamp
        for phase in PHASE_SEQUENCE:
            checkpoint = await store.get_checkpoint(run_id, phase)
            assert checkpoint is not None
            assert checkpoint.status is PhaseCheckpointStatus.COMMITTED
            assert checkpoint.committed_at is not None

    run_async(_run())


def test_tier_checkpoint_suspends_then_submit_resumes_deep() -> None:
    store = FakeCampaignRunStore()
    events: list[str] = []
    review = {
        "proposed_cutoffs": {"top": 0.8},
        "tier_distribution": {"top": 10, "high": 25},
        "cost_estimate_cents": "5000",
    }
    gate = RecordingPhaseHandler(
        CampaignPhase.TIER_CHECKPOINT,
        result_status=PhaseStatus.PAUSED,
        payload=review,
        events=events,
    )
    registry, handlers = _registry(events, overrides={CampaignPhase.TIER_CHECKPOINT: gate})
    machine = CampaignRun(store=store, registry=registry)

    async def _run() -> None:
        run_id = await machine.start(client_id="c1", icp_key="default", icp_version=1)
        run = await machine.run_to_completion(run_id)
        # suspended durably at the human gate; deep has NOT run
        assert run.status is CampaignRunStatus.PAUSED
        assert run.phase is CampaignPhase.TIER_CHECKPOINT
        assert handlers[CampaignPhase.DEEP].calls == 0

        # read-back: the M6.4 review payload is durable (the M6↔M7 hand-off surface)
        checkpoint = await machine.await_checkpoint(run_id)
        assert checkpoint is not None
        assert checkpoint.status is PhaseCheckpointStatus.AWAITING_INPUT
        assert checkpoint.payload["proposed_cutoffs"] == {"top": 0.8}

        # submit the human decision → advances into deep
        run = await machine.submit_checkpoint(run_id, decision={"action": "approve"})
        assert run.phase is CampaignPhase.DEEP
        assert run.status is CampaignRunStatus.ACTIVE
        committed = await store.get_checkpoint(run_id, CampaignPhase.TIER_CHECKPOINT)
        assert committed is not None
        assert committed.status is PhaseCheckpointStatus.COMMITTED
        assert committed.payload["decision"] == {"action": "approve"}

        # a re-submit is rejected (idempotent — no double-advance)
        with pytest.raises(CheckpointNotAwaiting):
            await machine.submit_checkpoint(run_id, decision={"action": "approve"})

        run = await machine.run_to_completion(run_id)
        assert run.status is CampaignRunStatus.COMPLETED
        assert handlers[CampaignPhase.DEEP].calls == 1
        # the gate handler ran exactly once — suspension never re-ran it
        assert gate.calls == 1

    run_async(_run())


def test_suspended_run_survives_restart() -> None:
    # "survives a restart while suspended": a fresh CampaignRun over the SAME store reads the
    # suspended checkpoint back and can resume it (state lives in the durable store, not in memory).
    store = FakeCampaignRunStore()
    events: list[str] = []
    gate = RecordingPhaseHandler(
        CampaignPhase.TIER_CHECKPOINT,
        result_status=PhaseStatus.PAUSED,
        payload={"proposed_cutoffs": {"top": 0.8}},
        events=events,
    )
    registry, handlers = _registry(events, overrides={CampaignPhase.TIER_CHECKPOINT: gate})

    async def _run() -> None:
        run_id = await CampaignRun(store=store, registry=registry).start(
            client_id="c1", icp_key="default", icp_version=1
        )
        await CampaignRun(store=store, registry=registry).run_to_completion(run_id)
        # a brand-new state-machine instance (simulating a process restart) over the same store
        restarted = CampaignRun(store=store, registry=registry)
        checkpoint = await restarted.await_checkpoint(run_id)
        assert checkpoint is not None
        assert checkpoint.status is PhaseCheckpointStatus.AWAITING_INPUT
        run = await restarted.submit_checkpoint(run_id, decision={"action": "approve"})
        assert run.phase is CampaignPhase.DEEP
        run = await restarted.run_to_completion(run_id)
        assert run.status is CampaignRunStatus.COMPLETED
        assert handlers[CampaignPhase.DEEP].calls == 1

    run_async(_run())


def test_pause_resume_does_not_respend() -> None:
    store = FakeCampaignRunStore()
    events: list[str] = []
    registry, handlers = _registry(events)
    machine = CampaignRun(store=store, registry=registry)

    async def _run() -> None:
        run_id = await machine.start(client_id="c1", icp_key="default", icp_version=1)
        await machine.advance(run_id)  # reverse_profiling -> icp_confirmed
        run = await machine.advance(run_id)  # icp_confirmed -> discovery
        assert run.phase is CampaignPhase.DISCOVERY

        run = await machine.pause(run_id)
        assert run.status is CampaignRunStatus.PAUSED
        assert run.phase is CampaignPhase.DISCOVERY  # paused at a safe phase boundary
        assert run.paused_at is not None

        # run_to_completion is a no-op while paused (no work re-spent)
        run = await machine.run_to_completion(run_id)
        assert run.status is CampaignRunStatus.PAUSED
        assert run.phase is CampaignPhase.DISCOVERY

        run = await machine.resume(run_id)
        assert run.status is CampaignRunStatus.ACTIVE
        assert run.resumed_at is not None
        run = await machine.run_to_completion(run_id)
        assert run.status is CampaignRunStatus.COMPLETED
        # nothing re-ran across the pause: each phase handler fired exactly once
        assert all(h.calls == 1 for h in handlers.values())

    run_async(_run())


def test_committed_checkpoint_short_circuits_reentry() -> None:
    store = FakeCampaignRunStore()
    events: list[str] = []
    registry, handlers = _registry(events)
    machine = CampaignRun(store=store, registry=registry)

    async def _run() -> None:
        run_id = await machine.start(client_id="c1", icp_key="default", icp_version=1)
        await machine.advance(run_id)  # reverse_profiling committed + transitioned
        assert (await machine.status(run_id)).phase is CampaignPhase.ICP_CONFIRMED
        assert handlers[CampaignPhase.REVERSE_PROFILING].calls == 1

        # simulate a crash BETWEEN commit and transition: checkpoint COMMITTED, pointer rolled back.
        await store.transition(
            run_id, phase=CampaignPhase.REVERSE_PROFILING, status=CampaignRunStatus.ACTIVE
        )
        run = await machine.advance(run_id)
        # the transition is replayed off the committed checkpoint — the handler is NOT re-run
        assert run.phase is CampaignPhase.ICP_CONFIRMED
        assert handlers[CampaignPhase.REVERSE_PROFILING].calls == 1

    run_async(_run())


def test_failed_phase_marks_run_failed() -> None:
    store = FakeCampaignRunStore()
    events: list[str] = []
    failing = RecordingPhaseHandler(
        CampaignPhase.DISCOVERY,
        result_status=PhaseStatus.FAILED,
        payload={"error": "boom"},
        events=events,
    )
    registry, handlers = _registry(events, overrides={CampaignPhase.DISCOVERY: failing})
    machine = CampaignRun(store=store, registry=registry)

    async def _run() -> None:
        run_id = await machine.start(client_id="c1", icp_key="default", icp_version=1)
        run = await machine.run_to_completion(run_id)
        assert run.status is CampaignRunStatus.FAILED
        assert run.phase is CampaignPhase.DISCOVERY
        checkpoint = await store.get_checkpoint(run_id, CampaignPhase.DISCOVERY)
        assert checkpoint is not None
        assert checkpoint.status is PhaseCheckpointStatus.FAILED
        # downstream phases never ran
        assert handlers[CampaignPhase.SCORING].calls == 0

    run_async(_run())


def test_adjust_updates_fields_and_journals() -> None:
    store = FakeCampaignRunStore()
    registry, _ = _registry([])
    budget = FakeBudgetEngine()
    machine = CampaignRun(store=store, registry=registry, budget_engine=budget)

    async def _run() -> None:
        run_id = await machine.start(client_id="c1", icp_key="default", icp_version=1)
        run = await machine.adjust(
            run_id,
            budget_cap_cents=Decimal("100000"),
            icp_version=2,
            tier_cutoffs={"top": 0.9},
        )
        assert run.icp_version == 2
        assert run.budget_cap_cents == Decimal("100000")
        assert run.tier_cutoffs == {"top": 0.9}
        # every change is journaled for audit
        assert [a.kind for a in store.adjustments] == ["icp_version", "budget_cap", "tier_cutoffs"]
        # the budget cap flowed through to the engine (M7.5)
        assert budget.caps_set == [(run_id, Decimal("100000"))]

    run_async(_run())


def test_adjusted_icp_version_seen_by_next_phase() -> None:
    store = FakeCampaignRunStore()
    events: list[str] = []
    registry, handlers = _registry(events)
    machine = CampaignRun(store=store, registry=registry)

    async def _run() -> None:
        run_id = await machine.start(client_id="c1", icp_key="default", icp_version=1)
        await machine.adjust(run_id, icp_version=7)
        await machine.advance(run_id)  # reverse_profiling compiles against the new version
        ctx = handlers[CampaignPhase.REVERSE_PROFILING].seen_contexts[0]
        assert ctx.icp_version == 7

    run_async(_run())


def test_pre_run_estimate_delegates_to_budget_engine() -> None:
    store = FakeCampaignRunStore()
    registry, _ = _registry([])
    budget = FakeBudgetEngine()
    machine = CampaignRun(store=store, registry=registry, budget_engine=budget)

    async def _run() -> None:
        run_id = await machine.start(
            client_id="c1", icp_key="default", icp_version=1, tier_cutoffs={"top": 0.8}
        )
        estimate = await machine.pre_run_estimate(run_id, discovered_count=500)
        assert estimate.discovered_count == 500
        assert budget.estimate_calls[0]["discovered_count"] == 500
        # the run's stored cutoffs are forwarded to the estimate
        assert budget.estimate_calls[0]["tier_cutoffs"] == {"top": 0.8}

    run_async(_run())


def test_pre_run_estimate_without_engine_raises() -> None:
    store = FakeCampaignRunStore()
    registry, _ = _registry([])
    machine = CampaignRun(store=store, registry=registry)

    async def _run() -> None:
        run_id = await machine.start(client_id="c1", icp_key="default", icp_version=1)
        with pytest.raises(BudgetEngineNotConfigured):
            await machine.pre_run_estimate(run_id, discovered_count=10)

    run_async(_run())


def test_submit_approve_applies_embedded_adjustments() -> None:
    store = FakeCampaignRunStore()
    events: list[str] = []
    gate = RecordingPhaseHandler(
        CampaignPhase.TIER_CHECKPOINT, result_status=PhaseStatus.PAUSED, events=events
    )
    registry, _ = _registry(events, overrides={CampaignPhase.TIER_CHECKPOINT: gate})
    budget = FakeBudgetEngine()
    machine = CampaignRun(store=store, registry=registry, budget_engine=budget)

    async def _run() -> None:
        run_id = await machine.start(client_id="c1", icp_key="default", icp_version=1)
        await machine.run_to_completion(run_id)
        run = await machine.submit_checkpoint(
            run_id,
            decision={
                "action": "approve",
                "tier_cutoffs": {"top": 0.7},
                "budget_cap_cents": "200000",
            },
        )
        # the embedded cutoff + cap edits applied, then the run advanced into deep
        assert run.phase is CampaignPhase.DEEP
        assert run.tier_cutoffs == {"top": 0.7}
        assert run.budget_cap_cents == Decimal("200000")
        assert budget.caps_set[-1] == (run_id, Decimal("200000"))

    run_async(_run())


def test_submit_pause_keeps_suspended() -> None:
    store = FakeCampaignRunStore()
    events: list[str] = []
    gate = RecordingPhaseHandler(
        CampaignPhase.TIER_CHECKPOINT,
        result_status=PhaseStatus.PAUSED,
        payload={"k": "v"},
        events=events,
    )
    registry, handlers = _registry(events, overrides={CampaignPhase.TIER_CHECKPOINT: gate})
    machine = CampaignRun(store=store, registry=registry)

    async def _run() -> None:
        run_id = await machine.start(client_id="c1", icp_key="default", icp_version=1)
        await machine.run_to_completion(run_id)
        run = await machine.submit_checkpoint(run_id, decision={"action": "pause"})
        assert run.phase is CampaignPhase.TIER_CHECKPOINT
        checkpoint = await store.get_checkpoint(run_id, CampaignPhase.TIER_CHECKPOINT)
        assert checkpoint is not None
        assert checkpoint.status is PhaseCheckpointStatus.AWAITING_INPUT
        assert checkpoint.payload["decision"] == {"action": "pause"}
        assert handlers[CampaignPhase.DEEP].calls == 0

    run_async(_run())


def test_advance_without_handler_raises() -> None:
    machine = CampaignRun(store=FakeCampaignRunStore(), registry=PhaseHandlerRegistry())

    async def _run() -> None:
        run_id = await machine.start(client_id="c1", icp_key="default", icp_version=1)
        with pytest.raises(NoPhaseHandlerRegistered):
            await machine.advance(run_id)

    run_async(_run())


def test_completed_run_advance_is_noop() -> None:
    store = FakeCampaignRunStore()
    events: list[str] = []
    registry, handlers = _registry(events)
    machine = CampaignRun(store=store, registry=registry)

    async def _run() -> None:
        run_id = await machine.start(client_id="c1", icp_key="default", icp_version=1)
        await machine.run_to_completion(run_id)
        run = await machine.advance(run_id)
        assert run.status is CampaignRunStatus.COMPLETED
        assert all(h.calls == 1 for h in handlers.values())

    run_async(_run())


def test_start_is_idempotent_on_supplied_id() -> None:
    store = FakeCampaignRunStore()
    events: list[str] = []
    registry, _ = _registry(events)
    machine = CampaignRun(store=store, registry=registry)

    async def _run() -> None:
        run_id = new_campaign_run_id()
        await machine.start(
            client_id="c1", icp_key="default", icp_version=1, campaign_run_id=run_id
        )
        await machine.advance(run_id)  # advance to icp_confirmed
        # a re-start with the same id must not reset an advanced run
        await machine.start(
            client_id="c1", icp_key="default", icp_version=1, campaign_run_id=run_id
        )
        assert (await machine.status(run_id)).phase is CampaignPhase.ICP_CONFIRMED

    run_async(_run())


def test_status_missing_run_raises() -> None:
    machine = CampaignRun(store=FakeCampaignRunStore(), registry=PhaseHandlerRegistry())

    async def _run() -> None:
        with pytest.raises(CampaignRunNotFound):
            await machine.status(new_campaign_run_id())

    run_async(_run())


# --- review-driven regression tests (M7.3 adversarial review) ----------------


def _gate_machine(
    store: FakeCampaignRunStore, *, budget: FakeBudgetEngine | None = None
) -> tuple[CampaignRun, dict[CampaignPhase, RecordingPhaseHandler]]:
    """A machine whose ``tier_checkpoint`` handler PAUSES (the human gate), all others complete."""
    events: list[str] = []
    gate = RecordingPhaseHandler(
        CampaignPhase.TIER_CHECKPOINT, result_status=PhaseStatus.PAUSED, events=events
    )
    registry, handlers = _registry(events, overrides={CampaignPhase.TIER_CHECKPOINT: gate})
    return CampaignRun(store=store, registry=registry, budget_engine=budget), handlers


def test_malformed_budget_cap_does_not_crash_or_persist() -> None:
    # HIGH (review): a NaN cap used to raise InvalidOperation out of submit_checkpoint (the run
    # stuck AWAITING_INPUT forever); an Infinity cap used to persist as an effectively-uncapped
    # budget. Both must now be ignored (coerced to None) — the approve path still advances.
    async def _check(bad_value: str) -> None:
        store = FakeCampaignRunStore()
        budget = FakeBudgetEngine()
        machine, _ = _gate_machine(store, budget=budget)
        run_id = await machine.start(client_id="c1", icp_key="default", icp_version=1)
        await machine.run_to_completion(run_id)
        run = await machine.submit_checkpoint(
            run_id, decision={"action": "approve", "budget_cap_cents": bad_value}
        )
        # no crash; the malformed cap was ignored, not persisted
        assert run.budget_cap_cents is None
        assert budget.caps_set == []
        # the approve still resumed into deep
        assert run.phase is CampaignPhase.DEEP
        assert run.status is CampaignRunStatus.ACTIVE

    for bad in ("NaN", "nan", "Infinity", "inf", "-5", "notanumber"):
        run_async(_check(bad))


def test_valid_budget_cap_still_applies() -> None:
    # Guard the fix did not break the happy path: a well-formed cap applies + flows to the engine.
    store = FakeCampaignRunStore()
    budget = FakeBudgetEngine()
    machine, _ = _gate_machine(store, budget=budget)

    async def _run() -> None:
        run_id = await machine.start(client_id="c1", icp_key="default", icp_version=1)
        await machine.run_to_completion(run_id)
        run = await machine.submit_checkpoint(
            run_id, decision={"action": "approve", "budget_cap_cents": "150000"}
        )
        assert run.budget_cap_cents == Decimal("150000")
        assert budget.caps_set == [(run_id, Decimal("150000"))]

    run_async(_run())


def test_pre_run_estimate_drops_non_numeric_cutoffs() -> None:
    # _to_float_cutoffs must drop bool / non-finite stored cutoffs before the BudgetEngine estimate.
    store = FakeCampaignRunStore()
    budget = FakeBudgetEngine()
    machine, _ = _gate_machine(store, budget=budget)

    async def _run() -> None:
        run_id = await machine.start(
            client_id="c1",
            icp_key="default",
            icp_version=1,
            tier_cutoffs={"top": 0.8, "flag": True, "broken": float("inf")},
        )
        await machine.pre_run_estimate(run_id, discovered_count=100)
        assert budget.estimate_calls[0]["tier_cutoffs"] == {"top": 0.8}

    run_async(_run())


def test_submit_checkpoint_self_heals_partial_approve() -> None:
    # MED (review): a crash between the COMMITTED write and the resume leaves the run PAUSED at a
    # COMMITTED phase. A retried submit_checkpoint must finish it (not raise CheckpointNotAwaiting).
    store = FakeCampaignRunStore()
    machine, handlers = _gate_machine(store)

    async def _run() -> None:
        run_id = await machine.start(client_id="c1", icp_key="default", icp_version=1)
        await machine.run_to_completion(run_id)  # PAUSED + AWAITING_INPUT at tier_checkpoint
        # simulate the partial crash: checkpoint COMMITTED, run still PAUSED (resume never ran)
        await store.put_checkpoint(
            campaign_run_id=run_id,
            phase=CampaignPhase.TIER_CHECKPOINT,
            idempotency_key="k",
            status=PhaseCheckpointStatus.COMMITTED,
            payload={"decision": {"action": "approve"}},
        )
        run = await machine.submit_checkpoint(run_id, decision={"action": "approve"})
        assert run.phase is CampaignPhase.DEEP
        assert run.status is CampaignRunStatus.ACTIVE

    run_async(_run())


def test_resubmit_same_decision_does_not_duplicate_journal() -> None:
    # MED (review): re-submitting the same embedded adjustment must not append a duplicate audit
    # row (the diff-guard skips a no-op edit).
    store = FakeCampaignRunStore()
    budget = FakeBudgetEngine()
    machine, _ = _gate_machine(store, budget=budget)

    async def _run() -> None:
        run_id = await machine.start(client_id="c1", icp_key="default", icp_version=1)
        await machine.run_to_completion(run_id)
        # first pause-with-edit journals once
        await machine.submit_checkpoint(
            run_id, decision={"action": "pause", "budget_cap_cents": "100000"}
        )
        # re-submitting the SAME cap is a no-op (value unchanged) — no second journal row
        await machine.submit_checkpoint(
            run_id, decision={"action": "pause", "budget_cap_cents": "100000"}
        )
        assert [a.kind for a in store.adjustments] == ["budget_cap"]
        assert budget.caps_set == [(run_id, Decimal("100000"))]
        # approving with the same cap still does not re-journal, and advances
        run = await machine.submit_checkpoint(
            run_id, decision={"action": "approve", "budget_cap_cents": "100000"}
        )
        assert run.phase is CampaignPhase.DEEP
        assert [a.kind for a in store.adjustments] == ["budget_cap"]

    run_async(_run())


def test_unknown_action_stays_suspended_but_applies_edits() -> None:
    # MED (review): a non-approve/garbage action must fail safe (stay suspended, never auto-advance
    # into deep) while the embedded edit still applies+journals (per M6.4 resume-with-cutoffs).
    store = FakeCampaignRunStore()
    machine, handlers = _gate_machine(store)

    async def _run() -> None:
        run_id = await machine.start(client_id="c1", icp_key="default", icp_version=1)
        await machine.run_to_completion(run_id)
        run = await machine.submit_checkpoint(
            run_id, decision={"action": "reject", "tier_cutoffs": {"top": 0.7}}
        )
        assert run.phase is CampaignPhase.TIER_CHECKPOINT
        assert run.status is CampaignRunStatus.PAUSED
        assert handlers[CampaignPhase.DEEP].calls == 0
        checkpoint = await store.get_checkpoint(run_id, CampaignPhase.TIER_CHECKPOINT)
        assert checkpoint is not None
        assert checkpoint.status is PhaseCheckpointStatus.AWAITING_INPUT
        assert checkpoint.payload["decision"]["action"] == "reject"
        # the cutoff edit applied regardless of the (non-approve) action
        assert run.tier_cutoffs == {"top": 0.7}
        assert [a.kind for a in store.adjustments] == ["tier_cutoffs"]

    run_async(_run())


def test_run_to_completion_respects_max_steps() -> None:
    # LOW (review): the max_steps safety-stop bound.
    store = FakeCampaignRunStore()
    registry, _ = _registry([])
    machine = CampaignRun(store=store, registry=registry)

    async def _run() -> None:
        run_id = await machine.start(client_id="c1", icp_key="default", icp_version=1)
        run = await machine.run_to_completion(run_id, max_steps=2)
        # exactly two advances: reverse_profiling -> icp_confirmed -> discovery, then stop
        assert run.phase is CampaignPhase.DISCOVERY
        assert run.status is CampaignRunStatus.ACTIVE

    run_async(_run())


def test_run_to_completion_no_progress_guard_does_not_spin() -> None:
    # LOW (review): resuming a run still behind its AWAITING_INPUT gate (without submitting) must
    # not spin — the no-progress guard returns at the unchanged boundary.
    store = FakeCampaignRunStore()
    machine, handlers = _gate_machine(store)

    async def _run() -> None:
        run_id = await machine.start(client_id="c1", icp_key="default", icp_version=1)
        await machine.run_to_completion(run_id)  # PAUSED at the gate
        await machine.resume(run_id)  # ACTIVE, but checkpoint still AWAITING_INPUT (no submit)
        run = await machine.run_to_completion(run_id)
        # returned without spinning; still parked at the gate, deep never ran
        assert run.phase is CampaignPhase.TIER_CHECKPOINT
        assert run.status is CampaignRunStatus.ACTIVE
        assert handlers[CampaignPhase.DEEP].calls == 0

    run_async(_run())


def test_fakes_conform_to_their_runtime_protocols() -> None:
    # LOW (review): the in-memory fakes must structurally satisfy the seams they stand in for, so a
    # future protocol change that the fake misses is caught here rather than at one call site.
    assert isinstance(FakeCampaignRunStore(), CampaignRunStore)
    assert isinstance(FakeBudgetEngine(), BudgetEngine)
    assert isinstance(RecordingPhaseHandler(CampaignPhase.DISCOVERY), PhaseHandler)
