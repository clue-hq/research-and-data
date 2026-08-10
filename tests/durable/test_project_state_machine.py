"""Campaign-run state-machine behaviour (M7.3) — in-memory store + fake handlers, no DB.

Exercises the M7.3 acceptance criteria on :class:`FakeProjectRunStore` with recording phase
handlers: phases advance in order; a crash resumes at the last committed phase without re-running;
``pause``/``resume`` stop and continue without re-spending; the ``tier_checkpoint`` human gate
suspends durably and ``submit_checkpoint`` resumes ``deep``; ``adjust`` is journaled and the next
phase sees the change; ``pre_run_estimate`` delegates to the budget engine.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from clue_core import (
    BudgetEngine,
    DeepAccountExternalWait,
    DeepExternalWait,
    DeepExternalWakeReason,
    DeepFleetExternalWait,
    DiscoveryExternalWait,
    DiscoveryWakeReason,
    ExternalResearchPreparation,
    ExternalResearchPreparationOutcome,
    PhaseHandler,
    PhaseStatus,
    ProjectPhase,
    new_discovery_batch_id,
    new_discovery_operation_id,
    new_entity_id,
    new_project_run_id,
    new_run_id,
)
from clue_research.durable import (
    PHASE_SEQUENCE,
    REENTRANT_HOLD_KEY,
    BudgetEngineNotConfigured,
    CheckpointNotAwaiting,
    NoPhaseHandlerRegistered,
    PhaseCheckpointStatus,
    PhaseHandlerRegistry,
    ProjectRun,
    ProjectRunError,
    ProjectRunNotFound,
    ProjectRunStatus,
    ProjectRunStore,
)
from tests.db.conftest import run_async
from tests.durable.conftest import (
    FakeBudgetEngine,
    FakeProjectRunStore,
    RecordingPhaseHandler,
)


def _registry(
    events: list[str], overrides: dict[ProjectPhase, RecordingPhaseHandler] | None = None
) -> tuple[PhaseHandlerRegistry, dict[ProjectPhase, RecordingPhaseHandler]]:
    """A registry with one recording handler per phase (all ``COMPLETED`` by default), sharing one
    ``events`` list so phase ordering is observable. ``overrides`` swaps specific phases (a gate /
    a failure)."""
    overrides = overrides or {}
    registry = PhaseHandlerRegistry()
    handlers: dict[ProjectPhase, RecordingPhaseHandler] = {}
    for phase in PHASE_SEQUENCE:
        handler = overrides.get(phase) or RecordingPhaseHandler(phase, events=events)
        registry.register(handler)
        handlers[phase] = handler
    return registry, handlers


def test_advances_through_all_phases_in_order() -> None:
    store = FakeProjectRunStore()
    events: list[str] = []
    registry, handlers = _registry(events)
    machine = ProjectRun(store=store, registry=registry)

    async def _run() -> None:
        run_id = await machine.start(
            project_id="prj-test", workspace_id="c1", icp_key="default", icp_version=1
        )
        run = await machine.run_to_completion(run_id)
        assert run.status is ProjectRunStatus.COMPLETED
        assert run.phase is ProjectPhase.HANDOFF
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
    store = FakeProjectRunStore()
    events: list[str] = []
    review = {
        "proposed_cutoffs": {"top": 0.8},
        "tier_distribution": {"top": 10, "high": 25},
        "cost_estimate_cents": "5000",
    }
    gate = RecordingPhaseHandler(
        ProjectPhase.TIER_CHECKPOINT,
        result_status=PhaseStatus.PAUSED,
        payload=review,
        events=events,
    )
    registry, handlers = _registry(events, overrides={ProjectPhase.TIER_CHECKPOINT: gate})
    machine = ProjectRun(store=store, registry=registry)

    async def _run() -> None:
        run_id = await machine.start(
            project_id="prj-test", workspace_id="c1", icp_key="default", icp_version=1
        )
        run = await machine.run_to_completion(run_id)
        # suspended durably at the human gate; deep has NOT run
        assert run.status is ProjectRunStatus.PAUSED
        assert run.phase is ProjectPhase.TIER_CHECKPOINT
        assert handlers[ProjectPhase.DEEP].calls == 0

        # read-back: the M6.4 review payload is durable (the M6↔M7 hand-off surface)
        checkpoint = await machine.await_checkpoint(run_id)
        assert checkpoint is not None
        assert checkpoint.status is PhaseCheckpointStatus.AWAITING_INPUT
        assert checkpoint.payload["proposed_cutoffs"] == {"top": 0.8}

        # submit the human decision → advances into deep
        run = await machine.submit_checkpoint(run_id, decision={"action": "approve"})
        assert run.phase is ProjectPhase.DEEP
        assert run.status is ProjectRunStatus.ACTIVE
        committed = await store.get_checkpoint(run_id, ProjectPhase.TIER_CHECKPOINT)
        assert committed is not None
        assert committed.status is PhaseCheckpointStatus.COMMITTED
        assert committed.payload["decision"] == {"action": "approve"}

        # a re-submit is rejected (idempotent — no double-advance)
        with pytest.raises(CheckpointNotAwaiting):
            await machine.submit_checkpoint(run_id, decision={"action": "approve"})

        run = await machine.run_to_completion(run_id)
        assert run.status is ProjectRunStatus.COMPLETED
        assert handlers[ProjectPhase.DEEP].calls == 1
        # secure-input approval re-enters the gate once so it can persist the approved decision
        assert gate.calls == 2

    run_async(_run())


def test_suspended_run_survives_restart() -> None:
    # "survives a restart while suspended": a fresh ProjectRun over the SAME store reads the
    # suspended checkpoint back and can resume it (state lives in the durable store, not in memory).
    store = FakeProjectRunStore()
    events: list[str] = []
    gate = RecordingPhaseHandler(
        ProjectPhase.TIER_CHECKPOINT,
        result_status=PhaseStatus.PAUSED,
        payload={"proposed_cutoffs": {"top": 0.8}},
        events=events,
    )
    registry, handlers = _registry(events, overrides={ProjectPhase.TIER_CHECKPOINT: gate})

    async def _run() -> None:
        run_id = await ProjectRun(store=store, registry=registry).start(
            project_id="prj-test", workspace_id="c1", icp_key="default", icp_version=1
        )
        await ProjectRun(store=store, registry=registry).run_to_completion(run_id)
        # a brand-new state-machine instance (simulating a process restart) over the same store
        restarted = ProjectRun(store=store, registry=registry)
        checkpoint = await restarted.await_checkpoint(run_id)
        assert checkpoint is not None
        assert checkpoint.status is PhaseCheckpointStatus.AWAITING_INPUT
        run = await restarted.submit_checkpoint(run_id, decision={"action": "approve"})
        assert run.phase is ProjectPhase.DEEP
        run = await restarted.run_to_completion(run_id)
        assert run.status is ProjectRunStatus.COMPLETED
        assert handlers[ProjectPhase.DEEP].calls == 1

    run_async(_run())


def test_discovery_waits_externally_and_reenters_after_scheduler_wake() -> None:
    """Provider-owned wait time is durable and active; it is never a human pause."""

    store = FakeProjectRunStore()
    events: list[str] = []
    wait = DiscoveryExternalWait(
        discovery_batch_id=new_discovery_batch_id(),
        pending_operation_ids=(new_discovery_operation_id(),),
        next_poll_at=datetime.now(UTC) + timedelta(minutes=2),
        wake_reason=DiscoveryWakeReason.SCHEDULED_POLL,
    )
    waiting_handler = RecordingPhaseHandler(
        ProjectPhase.DISCOVERY,
        result_status=PhaseStatus.WAITING_EXTERNAL,
        payload=wait.model_dump(mode="json"),
        events=events,
    )
    registry, handlers = _registry(events, overrides={ProjectPhase.DISCOVERY: waiting_handler})

    async def _run() -> None:
        machine = ProjectRun(store=store, registry=registry)
        run_id = await machine.start(
            project_id="prj-test", workspace_id="c1", icp_key="default", icp_version=1
        )
        await machine.advance(run_id)  # reverse_profiling -> icp_confirmed
        await machine.advance(run_id)  # icp_confirmed -> discovery
        waiting = await machine.advance(run_id)

        assert waiting.phase is ProjectPhase.DISCOVERY
        assert waiting.status is ProjectRunStatus.ACTIVE
        checkpoint = await store.get_checkpoint(run_id, ProjectPhase.DISCOVERY)
        assert checkpoint is not None
        assert checkpoint.status is PhaseCheckpointStatus.WAITING_EXTERNAL
        assert checkpoint.payload == wait.model_dump(mode="json")
        assert handlers[ProjectPhase.SCORING].calls == 0

        # A new process receives the durable scheduler/webhook wake, swaps in the now-terminal
        # handler result, and re-enters discovery without a user resume action.
        completed = RecordingPhaseHandler(ProjectPhase.DISCOVERY, events=events)
        registry.register(completed)
        restarted = ProjectRun(store=store, registry=registry)
        advanced = await restarted.advance(run_id)
        assert advanced.phase is ProjectPhase.SCORING
        assert advanced.status is ProjectRunStatus.ACTIVE
        assert completed.calls == 1
        committed = await store.get_checkpoint(run_id, ProjectPhase.DISCOVERY)
        assert committed is not None
        assert committed.status is PhaseCheckpointStatus.COMMITTED

    run_async(_run())


def test_deep_waits_externally_and_reenters_same_phase_after_wake() -> None:
    """DEEP provider waits are active checkpoints, not discovery-only or human pauses."""

    store = FakeProjectRunStore()
    events: list[str] = []
    retry_after = datetime.now(UTC) + timedelta(minutes=1)
    wait = DeepExternalWait(
        pending_accounts=(
            DeepAccountExternalWait(
                account_entity_id=new_entity_id(),
                account_run_id=new_run_id(),
                preparation=ExternalResearchPreparation(
                    outcome=ExternalResearchPreparationOutcome.WAITING_EXTERNAL,
                    operation_ref="committee-operation:op-1",
                    retry_after=retry_after,
                    reason_code="provider_pending",
                ),
            ),
        ),
        next_poll_at=retry_after,
    )
    waiting_handler = RecordingPhaseHandler(
        ProjectPhase.DEEP,
        result_status=PhaseStatus.WAITING_EXTERNAL,
        payload=wait.model_dump(mode="json"),
        events=events,
    )
    registry, handlers = _registry(events, overrides={ProjectPhase.DEEP: waiting_handler})

    async def _run() -> None:
        machine = ProjectRun(store=store, registry=registry)
        project_run_id = await machine.start(
            project_id="prj-test", workspace_id="c1", icp_key="default", icp_version=1
        )
        for _ in range(5):
            await machine.advance(project_run_id)
        waiting = await machine.advance(project_run_id)
        assert waiting.phase is ProjectPhase.DEEP
        assert waiting.status is ProjectRunStatus.ACTIVE
        checkpoint = await store.get_checkpoint(project_run_id, ProjectPhase.DEEP)
        assert checkpoint is not None
        assert checkpoint.status is PhaseCheckpointStatus.WAITING_EXTERNAL
        assert checkpoint.payload == wait.model_dump(mode="json")
        assert handlers[ProjectPhase.VERIFICATION].calls == 0

        completed = RecordingPhaseHandler(ProjectPhase.DEEP, events=events)
        registry.register(completed)
        restarted = ProjectRun(store=store, registry=registry)
        advanced = await restarted.advance(project_run_id)
        assert advanced.phase is ProjectPhase.VERIFICATION
        assert advanced.status is ProjectRunStatus.ACTIVE
        assert completed.calls == 1

    run_async(_run())


# --- R11.4: the DEEP waiting_external arm accepts two disjoint reference-only shapes ------------


def _fleet_wait() -> DeepFleetExternalWait:
    return DeepFleetExternalWait(
        research_run_id=uuid4(),
        job_state_counts={"queued": 2, "running": 1, "terminal": 0},
        next_poll_at=datetime.now(UTC) + timedelta(seconds=60),
    )


def test_deep_fleet_external_wait_requires_a_live_job_census() -> None:
    """R11.4 payload validation: a census must exist, be non-negative, and describe live work."""

    wait = _fleet_wait()
    assert wait.wake_reason is DeepExternalWakeReason.SCHEDULED_POLL
    assert DeepFleetExternalWait.model_validate(wait.model_dump(mode="json")) == wait

    for counts in ({}, {"queued": -1}, {"terminal": 0}):
        with pytest.raises(ValidationError):
            DeepFleetExternalWait(
                research_run_id=uuid4(),
                job_state_counts=counts,
                next_poll_at=datetime.now(UTC) + timedelta(seconds=60),
            )


def test_deep_waiting_external_accepts_the_fleet_shape_and_still_accepts_the_legacy_shape() -> None:
    """The M8D bridge's payload lands a durable checkpoint; historical payloads are unchanged."""

    retry_after = datetime.now(UTC) + timedelta(minutes=1)
    legacy = DeepExternalWait(
        pending_accounts=(
            DeepAccountExternalWait(
                account_entity_id=new_entity_id(),
                account_run_id=new_run_id(),
                preparation=ExternalResearchPreparation(
                    outcome=ExternalResearchPreparationOutcome.WAITING_EXTERNAL,
                    operation_ref="committee-operation:op-1",
                    retry_after=retry_after,
                    reason_code="provider_pending",
                ),
            ),
        ),
        next_poll_at=retry_after,
    )

    async def _wait_at_deep(payload: dict[str, object]) -> PhaseCheckpointStatus:
        store = FakeProjectRunStore()
        events: list[str] = []
        registry, _ = _registry(
            events,
            overrides={
                ProjectPhase.DEEP: RecordingPhaseHandler(
                    ProjectPhase.DEEP,
                    result_status=PhaseStatus.WAITING_EXTERNAL,
                    payload=payload,
                    events=events,
                )
            },
        )
        machine = ProjectRun(store=store, registry=registry)
        project_run_id = await machine.start(
            project_id="prj-test", workspace_id="c1", icp_key="default", icp_version=1
        )
        for _ in range(5):
            await machine.advance(project_run_id)
        run = await machine.advance(project_run_id)
        assert run.phase is ProjectPhase.DEEP
        assert run.status is ProjectRunStatus.ACTIVE
        checkpoint = await store.get_checkpoint(project_run_id, ProjectPhase.DEEP)
        assert checkpoint is not None
        assert checkpoint.payload == payload
        return checkpoint.status

    for payload in (_fleet_wait().model_dump(mode="json"), legacy.model_dump(mode="json")):
        assert run_async(_wait_at_deep(payload)) is PhaseCheckpointStatus.WAITING_EXTERNAL


def test_deep_waiting_external_rejects_a_payload_matching_neither_shape() -> None:
    """Garbage (and a body-bearing hybrid) is refused with a message naming both admissible
    shapes — the checkpoint stays reference-only."""

    async def _run(payload: dict[str, object]) -> None:
        store = FakeProjectRunStore()
        events: list[str] = []
        registry, _ = _registry(
            events,
            overrides={
                ProjectPhase.DEEP: RecordingPhaseHandler(
                    ProjectPhase.DEEP,
                    result_status=PhaseStatus.WAITING_EXTERNAL,
                    payload=payload,
                    events=events,
                )
            },
        )
        machine = ProjectRun(store=store, registry=registry)
        project_run_id = await machine.start(
            project_id="prj-test", workspace_id="c1", icp_key="default", icp_version=1
        )
        for _ in range(5):
            await machine.advance(project_run_id)
        with pytest.raises(ProjectRunError) as excinfo:
            await machine.advance(project_run_id)
        assert "DeepFleetExternalWait" in str(excinfo.value)
        assert "DeepExternalWait" in str(excinfo.value)

    hybrid = _fleet_wait().model_dump(mode="json") | {"pending_accounts": []}
    for payload in ({"research_note": "everything is fine"}, {}, hybrid):
        run_async(_run(payload))


def test_pause_resume_does_not_respend() -> None:
    store = FakeProjectRunStore()
    events: list[str] = []
    registry, handlers = _registry(events)
    machine = ProjectRun(store=store, registry=registry)

    async def _run() -> None:
        run_id = await machine.start(
            project_id="prj-test", workspace_id="c1", icp_key="default", icp_version=1
        )
        await machine.advance(run_id)  # reverse_profiling -> icp_confirmed
        run = await machine.advance(run_id)  # icp_confirmed -> discovery
        assert run.phase is ProjectPhase.DISCOVERY

        run = await machine.pause(run_id)
        assert run.status is ProjectRunStatus.PAUSED
        assert run.phase is ProjectPhase.DISCOVERY  # paused at a safe phase boundary
        assert run.paused_at is not None

        # run_to_completion is a no-op while paused (no work re-spent)
        run = await machine.run_to_completion(run_id)
        assert run.status is ProjectRunStatus.PAUSED
        assert run.phase is ProjectPhase.DISCOVERY

        run = await machine.resume(run_id)
        assert run.status is ProjectRunStatus.ACTIVE
        assert run.resumed_at is not None
        run = await machine.run_to_completion(run_id)
        assert run.status is ProjectRunStatus.COMPLETED
        # nothing re-ran across the pause: each phase handler fired exactly once
        assert all(h.calls == 1 for h in handlers.values())

    run_async(_run())


def test_committed_checkpoint_short_circuits_reentry() -> None:
    store = FakeProjectRunStore()
    events: list[str] = []
    registry, handlers = _registry(events)
    machine = ProjectRun(store=store, registry=registry)

    async def _run() -> None:
        run_id = await machine.start(
            project_id="prj-test", workspace_id="c1", icp_key="default", icp_version=1
        )
        await machine.advance(run_id)  # reverse_profiling committed + transitioned
        assert (await machine.status(run_id)).phase is ProjectPhase.ICP_CONFIRMED
        assert handlers[ProjectPhase.REVERSE_PROFILING].calls == 1

        # simulate a crash BETWEEN commit and transition: checkpoint COMMITTED, pointer rolled back.
        await store.transition(
            run_id, phase=ProjectPhase.REVERSE_PROFILING, status=ProjectRunStatus.ACTIVE
        )
        run = await machine.advance(run_id)
        # the transition is replayed off the committed checkpoint — the handler is NOT re-run
        assert run.phase is ProjectPhase.ICP_CONFIRMED
        assert handlers[ProjectPhase.REVERSE_PROFILING].calls == 1

    run_async(_run())


def test_failed_phase_marks_run_failed() -> None:
    store = FakeProjectRunStore()
    events: list[str] = []
    failing = RecordingPhaseHandler(
        ProjectPhase.DISCOVERY,
        result_status=PhaseStatus.FAILED,
        payload={"error": "boom"},
        events=events,
    )
    registry, handlers = _registry(events, overrides={ProjectPhase.DISCOVERY: failing})
    machine = ProjectRun(store=store, registry=registry)

    async def _run() -> None:
        run_id = await machine.start(
            project_id="prj-test", workspace_id="c1", icp_key="default", icp_version=1
        )
        run = await machine.run_to_completion(run_id)
        assert run.status is ProjectRunStatus.FAILED
        assert run.phase is ProjectPhase.DISCOVERY
        checkpoint = await store.get_checkpoint(run_id, ProjectPhase.DISCOVERY)
        assert checkpoint is not None
        assert checkpoint.status is PhaseCheckpointStatus.FAILED
        # downstream phases never ran
        assert handlers[ProjectPhase.SCORING].calls == 0

    run_async(_run())


def test_adjust_updates_fields_and_journals() -> None:
    store = FakeProjectRunStore()
    registry, _ = _registry([])
    budget = FakeBudgetEngine()
    machine = ProjectRun(store=store, registry=registry, budget_engine=budget)

    async def _run() -> None:
        run_id = await machine.start(
            project_id="prj-test", workspace_id="c1", icp_key="default", icp_version=1
        )
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
    store = FakeProjectRunStore()
    events: list[str] = []
    registry, handlers = _registry(events)
    machine = ProjectRun(store=store, registry=registry)

    async def _run() -> None:
        run_id = await machine.start(
            project_id="prj-test", workspace_id="c1", icp_key="default", icp_version=1
        )
        await machine.adjust(run_id, icp_version=7)
        await machine.advance(run_id)  # reverse_profiling compiles against the new version
        ctx = handlers[ProjectPhase.REVERSE_PROFILING].seen_contexts[0]
        assert ctx.icp_version == 7
        assert ctx.project_id == "prj-test"
        assert ctx.brand_id == "brand-for-prj-test"

    run_async(_run())


def test_pre_run_estimate_delegates_to_budget_engine() -> None:
    store = FakeProjectRunStore()
    registry, _ = _registry([])
    budget = FakeBudgetEngine()
    machine = ProjectRun(store=store, registry=registry, budget_engine=budget)

    async def _run() -> None:
        run_id = await machine.start(
            project_id="prj-test",
            workspace_id="c1",
            icp_key="default",
            icp_version=1,
            tier_cutoffs={"top": 0.8},
        )
        estimate = await machine.pre_run_estimate(run_id, discovered_count=500)
        assert estimate.discovered_count == 500
        assert budget.estimate_calls[0]["discovered_count"] == 500
        # the run's stored cutoffs are forwarded to the estimate
        assert budget.estimate_calls[0]["tier_cutoffs"] == {"top": 0.8}

    run_async(_run())


def test_pre_run_estimate_without_engine_raises() -> None:
    store = FakeProjectRunStore()
    registry, _ = _registry([])
    machine = ProjectRun(store=store, registry=registry)

    async def _run() -> None:
        run_id = await machine.start(
            project_id="prj-test", workspace_id="c1", icp_key="default", icp_version=1
        )
        with pytest.raises(BudgetEngineNotConfigured):
            await machine.pre_run_estimate(run_id, discovered_count=10)

    run_async(_run())


def test_submit_approve_applies_embedded_adjustments() -> None:
    store = FakeProjectRunStore()
    events: list[str] = []
    gate = RecordingPhaseHandler(
        ProjectPhase.TIER_CHECKPOINT, result_status=PhaseStatus.PAUSED, events=events
    )
    registry, _ = _registry(events, overrides={ProjectPhase.TIER_CHECKPOINT: gate})
    budget = FakeBudgetEngine()
    machine = ProjectRun(store=store, registry=registry, budget_engine=budget)

    async def _run() -> None:
        run_id = await machine.start(
            project_id="prj-test", workspace_id="c1", icp_key="default", icp_version=1
        )
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
        assert run.phase is ProjectPhase.DEEP
        assert run.tier_cutoffs == {"top": 0.7}
        assert run.budget_cap_cents == Decimal("200000")
        assert budget.caps_set[-1] == (run_id, Decimal("200000"))

    run_async(_run())


def test_submit_pause_keeps_suspended() -> None:
    store = FakeProjectRunStore()
    events: list[str] = []
    gate = RecordingPhaseHandler(
        ProjectPhase.TIER_CHECKPOINT,
        result_status=PhaseStatus.PAUSED,
        payload={"k": "v"},
        events=events,
    )
    registry, handlers = _registry(events, overrides={ProjectPhase.TIER_CHECKPOINT: gate})
    machine = ProjectRun(store=store, registry=registry)

    async def _run() -> None:
        run_id = await machine.start(
            project_id="prj-test", workspace_id="c1", icp_key="default", icp_version=1
        )
        await machine.run_to_completion(run_id)
        run = await machine.submit_checkpoint(run_id, decision={"action": "pause"})
        assert run.phase is ProjectPhase.TIER_CHECKPOINT
        checkpoint = await store.get_checkpoint(run_id, ProjectPhase.TIER_CHECKPOINT)
        assert checkpoint is not None
        assert checkpoint.status is PhaseCheckpointStatus.AWAITING_INPUT
        assert checkpoint.payload["decision"] == {"action": "pause"}
        assert handlers[ProjectPhase.DEEP].calls == 0

    run_async(_run())


def test_advance_without_handler_raises() -> None:
    machine = ProjectRun(store=FakeProjectRunStore(), registry=PhaseHandlerRegistry())

    async def _run() -> None:
        run_id = await machine.start(
            project_id="prj-test", workspace_id="c1", icp_key="default", icp_version=1
        )
        with pytest.raises(NoPhaseHandlerRegistered):
            await machine.advance(run_id)

    run_async(_run())


def test_completed_run_advance_is_noop() -> None:
    store = FakeProjectRunStore()
    events: list[str] = []
    registry, handlers = _registry(events)
    machine = ProjectRun(store=store, registry=registry)

    async def _run() -> None:
        run_id = await machine.start(
            project_id="prj-test", workspace_id="c1", icp_key="default", icp_version=1
        )
        await machine.run_to_completion(run_id)
        run = await machine.advance(run_id)
        assert run.status is ProjectRunStatus.COMPLETED
        assert all(h.calls == 1 for h in handlers.values())

    run_async(_run())


def test_start_is_idempotent_on_supplied_id() -> None:
    store = FakeProjectRunStore()
    events: list[str] = []
    registry, _ = _registry(events)
    machine = ProjectRun(store=store, registry=registry)

    async def _run() -> None:
        run_id = new_project_run_id()
        await machine.start(
            project_id="prj-test",
            workspace_id="c1",
            icp_key="default",
            icp_version=1,
            project_run_id=run_id,
        )
        await machine.advance(run_id)  # advance to icp_confirmed
        # a re-start with the same id must not reset an advanced run
        await machine.start(
            project_id="prj-test",
            workspace_id="c1",
            icp_key="default",
            icp_version=1,
            project_run_id=run_id,
        )
        assert (await machine.status(run_id)).phase is ProjectPhase.ICP_CONFIRMED

    run_async(_run())


def test_status_missing_run_raises() -> None:
    machine = ProjectRun(store=FakeProjectRunStore(), registry=PhaseHandlerRegistry())

    async def _run() -> None:
        with pytest.raises(ProjectRunNotFound):
            await machine.status(new_project_run_id())

    run_async(_run())


# --- review-driven regression tests (M7.3 adversarial review) ----------------


def _gate_machine(
    store: FakeProjectRunStore, *, budget: FakeBudgetEngine | None = None
) -> tuple[ProjectRun, dict[ProjectPhase, RecordingPhaseHandler]]:
    """A machine whose ``tier_checkpoint`` handler PAUSES (the human gate), all others complete."""
    events: list[str] = []
    gate = RecordingPhaseHandler(
        ProjectPhase.TIER_CHECKPOINT, result_status=PhaseStatus.PAUSED, events=events
    )
    registry, handlers = _registry(events, overrides={ProjectPhase.TIER_CHECKPOINT: gate})
    return ProjectRun(store=store, registry=registry, budget_engine=budget), handlers


def test_malformed_budget_cap_does_not_crash_or_persist() -> None:
    # HIGH (review): a NaN cap used to raise InvalidOperation out of submit_checkpoint (the run
    # stuck AWAITING_INPUT forever); an Infinity cap used to persist as an effectively-uncapped
    # budget. Both must now be ignored (coerced to None) — the approve path still advances.
    async def _check(bad_value: str) -> None:
        store = FakeProjectRunStore()
        budget = FakeBudgetEngine()
        machine, _ = _gate_machine(store, budget=budget)
        run_id = await machine.start(
            project_id="prj-test", workspace_id="c1", icp_key="default", icp_version=1
        )
        await machine.run_to_completion(run_id)
        run = await machine.submit_checkpoint(
            run_id, decision={"action": "approve", "budget_cap_cents": bad_value}
        )
        # no crash; the malformed cap was ignored, not persisted
        assert run.budget_cap_cents is None
        assert budget.caps_set == []
        # the approve still resumed into deep
        assert run.phase is ProjectPhase.DEEP
        assert run.status is ProjectRunStatus.ACTIVE

    for bad in ("NaN", "nan", "Infinity", "inf", "-5", "notanumber"):
        run_async(_check(bad))


def test_valid_budget_cap_still_applies() -> None:
    # Guard the fix did not break the happy path: a well-formed cap applies + flows to the engine.
    store = FakeProjectRunStore()
    budget = FakeBudgetEngine()
    machine, _ = _gate_machine(store, budget=budget)

    async def _run() -> None:
        run_id = await machine.start(
            project_id="prj-test", workspace_id="c1", icp_key="default", icp_version=1
        )
        await machine.run_to_completion(run_id)
        run = await machine.submit_checkpoint(
            run_id, decision={"action": "approve", "budget_cap_cents": "150000"}
        )
        assert run.budget_cap_cents == Decimal("150000")
        assert budget.caps_set == [(run_id, Decimal("150000"))]

    run_async(_run())


def test_pre_run_estimate_drops_non_numeric_cutoffs() -> None:
    # _to_float_cutoffs must drop bool / non-finite stored cutoffs before the BudgetEngine estimate.
    store = FakeProjectRunStore()
    budget = FakeBudgetEngine()
    machine, _ = _gate_machine(store, budget=budget)

    async def _run() -> None:
        run_id = await machine.start(
            project_id="prj-test",
            workspace_id="c1",
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
    store = FakeProjectRunStore()
    machine, handlers = _gate_machine(store)

    async def _run() -> None:
        run_id = await machine.start(
            project_id="prj-test", workspace_id="c1", icp_key="default", icp_version=1
        )
        await machine.run_to_completion(run_id)  # PAUSED + AWAITING_INPUT at tier_checkpoint
        # simulate the partial crash: checkpoint COMMITTED, run still PAUSED (resume never ran)
        await store.put_checkpoint(
            project_run_id=run_id,
            phase=ProjectPhase.TIER_CHECKPOINT,
            idempotency_key="k",
            status=PhaseCheckpointStatus.COMMITTED,
            payload={"decision": {"action": "approve"}},
        )
        run = await machine.submit_checkpoint(run_id, decision={"action": "approve"})
        assert run.phase is ProjectPhase.DEEP
        assert run.status is ProjectRunStatus.ACTIVE

    run_async(_run())


def test_resubmit_same_decision_does_not_duplicate_journal() -> None:
    # MED (review): re-submitting the same embedded adjustment must not append a duplicate audit
    # row (the diff-guard skips a no-op edit).
    store = FakeProjectRunStore()
    budget = FakeBudgetEngine()
    machine, _ = _gate_machine(store, budget=budget)

    async def _run() -> None:
        run_id = await machine.start(
            project_id="prj-test", workspace_id="c1", icp_key="default", icp_version=1
        )
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
        assert run.phase is ProjectPhase.DEEP
        assert [a.kind for a in store.adjustments] == ["budget_cap"]

    run_async(_run())


def test_unknown_action_stays_suspended_but_applies_edits() -> None:
    # MED (review): a non-approve/garbage action must fail safe (stay suspended, never auto-advance
    # into deep) while the embedded edit still applies+journals (per M6.4 resume-with-cutoffs).
    store = FakeProjectRunStore()
    machine, handlers = _gate_machine(store)

    async def _run() -> None:
        run_id = await machine.start(
            project_id="prj-test", workspace_id="c1", icp_key="default", icp_version=1
        )
        await machine.run_to_completion(run_id)
        run = await machine.submit_checkpoint(
            run_id, decision={"action": "reject", "tier_cutoffs": {"top": 0.7}}
        )
        assert run.phase is ProjectPhase.TIER_CHECKPOINT
        assert run.status is ProjectRunStatus.PAUSED
        assert handlers[ProjectPhase.DEEP].calls == 0
        checkpoint = await store.get_checkpoint(run_id, ProjectPhase.TIER_CHECKPOINT)
        assert checkpoint is not None
        assert checkpoint.status is PhaseCheckpointStatus.AWAITING_INPUT
        assert checkpoint.payload["decision"]["action"] == "reject"
        # the cutoff edit applied regardless of the (non-approve) action
        assert run.tier_cutoffs == {"top": 0.7}
        assert [a.kind for a in store.adjustments] == ["tier_cutoffs"]

    run_async(_run())


def test_run_to_completion_respects_max_steps() -> None:
    # LOW (review): the max_steps safety-stop bound.
    store = FakeProjectRunStore()
    registry, _ = _registry([])
    machine = ProjectRun(store=store, registry=registry)

    async def _run() -> None:
        run_id = await machine.start(
            project_id="prj-test", workspace_id="c1", icp_key="default", icp_version=1
        )
        run = await machine.run_to_completion(run_id, max_steps=2)
        # exactly two advances: reverse_profiling -> icp_confirmed -> discovery, then stop
        assert run.phase is ProjectPhase.DISCOVERY
        assert run.status is ProjectRunStatus.ACTIVE

    run_async(_run())


def test_run_to_completion_no_progress_guard_does_not_spin() -> None:
    # LOW (review): resuming a run still behind its AWAITING_INPUT gate (without submitting) must
    # not spin — the no-progress guard returns at the unchanged boundary.
    store = FakeProjectRunStore()
    machine, handlers = _gate_machine(store)

    async def _run() -> None:
        run_id = await machine.start(
            project_id="prj-test", workspace_id="c1", icp_key="default", icp_version=1
        )
        await machine.run_to_completion(run_id)  # PAUSED at the gate
        await machine.resume(run_id)  # ACTIVE, but checkpoint still AWAITING_INPUT (no submit)
        run = await machine.run_to_completion(run_id)
        # returned without spinning; still parked at the gate, deep never ran
        assert run.phase is ProjectPhase.TIER_CHECKPOINT
        assert run.status is ProjectRunStatus.ACTIVE
        assert handlers[ProjectPhase.DEEP].calls == 0

    run_async(_run())


def test_a_reentrant_hold_reruns_its_handler_after_an_explicit_resume() -> None:
    """R11 §6b: a phase that pauses on durable state it re-reads (M8D's DEEP fleet bridge) marks
    its payload re-entrant, so ``resume`` re-runs it — where a decision gate stays parked until a
    decision is submitted, and approving DEEP would wrongly finalize a phase that researched
    nothing."""

    store = FakeProjectRunStore()
    events: list[str] = []
    holding = RecordingPhaseHandler(
        ProjectPhase.DEEP,
        result_status=PhaseStatus.PAUSED,
        payload={REENTRANT_HOLD_KEY: True, "reason_code": "entity_research_fleet_not_launched"},
        events=events,
    )
    registry, handlers = _registry(events, overrides={ProjectPhase.DEEP: holding})

    async def _run() -> None:
        machine = ProjectRun(store=store, registry=registry)
        run_id = await machine.start(
            project_id="prj-test", workspace_id="c1", icp_key="default", icp_version=1
        )
        run = await machine.run_to_completion(run_id)
        assert (run.phase, run.status) == (ProjectPhase.DEEP, ProjectRunStatus.PAUSED)
        checkpoint = await store.get_checkpoint(run_id, ProjectPhase.DEEP)
        assert checkpoint is not None
        assert checkpoint.status is PhaseCheckpointStatus.AWAITING_INPUT
        assert handlers[ProjectPhase.VERIFICATION].calls == 0

        # A resume alone re-enters the same phase (the hold's condition may not have cleared yet).
        await machine.resume(run_id)
        run = await machine.advance(run_id)
        assert (run.phase, run.status) == (ProjectPhase.DEEP, ProjectRunStatus.PAUSED)
        assert holding.calls == 2

        # Once the external condition clears, the resumed run advances normally.
        cleared = RecordingPhaseHandler(ProjectPhase.DEEP, events=events)
        registry.register(cleared)
        await machine.resume(run_id)
        run = await machine.advance(run_id)
        assert (run.phase, run.status) == (ProjectPhase.VERIFICATION, ProjectRunStatus.ACTIVE)
        assert cleared.calls == 1

    run_async(_run())


def test_fakes_conform_to_their_runtime_protocols() -> None:
    # LOW (review): the in-memory fakes must structurally satisfy the seams they stand in for, so a
    # future protocol change that the fake misses is caught here rather than at one call site.
    assert isinstance(FakeProjectRunStore(), ProjectRunStore)
    assert isinstance(FakeBudgetEngine(), BudgetEngine)
    assert isinstance(RecordingPhaseHandler(ProjectPhase.DISCOVERY), PhaseHandler)
