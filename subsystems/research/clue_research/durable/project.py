"""The outer project-run state machine (M7.3) — the durable scheduler over the phase sequence.

The substrate nails *per-account* durable execution (M7.1) but not the **project run** — the
long-lived job spanning ``reverse_profiling → icp_confirmed → discovery → scoring → tier_checkpoint
→ deep → verification → handoff`` (Doc C §4). :class:`ProjectRun` owns that lifecycle: explicit
phase ordering, per-phase checkpointing so a crash resumes at the last committed phase, the durable
human gate at ``tier_checkpoint`` (an ``interrupt()``-style suspend/resume), and client-driven
**pause / resume / adjust** with safe re-entry.

It owns *transitions, persistence, and re-entry* — never phase content: phase bodies are supplied by
M5/M6/M8/M9/M12 as :class:`~clue_core.PhaseHandler`\\s registered into a
:class:`~clue_research.durable.phases.PhaseHandlerRegistry` (the same registration seam as the
aspect-worker registry). Persistence sits behind the :class:`ProjectRunStore` seam, so the state
machine is testable on an in-memory store and the durable backend is swappable (Postgres now,
Temporal later — the design is Temporal-shaped: phases ↦ activities, checkpoints ↦ timers/signals).

Crash-resume is the property the whole thing turns on. Each phase is run in two durable steps:
``upsert_checkpoint(COMMITTED)`` then ``transition`` to the next phase. A re-entered phase whose
checkpoint is already ``COMMITTED`` short-circuits (the handler is **not** re-run) and just replays
the transition — so a crash *between* the two steps is recovered without double-running a phase, and
a re-entered already-done phase costs nothing. A phase that returns ``PAUSED`` lands an
``AWAITING_INPUT`` checkpoint and suspends the run durably until :meth:`submit_checkpoint`.
"""

from __future__ import annotations

import math
from datetime import timedelta
from decimal import Decimal
from typing import Protocol, runtime_checkable

from pydantic import JsonValue

from clue_core import (
    BudgetEngine,
    BudgetScope,
    BudgetVerdict,
    BurnDown,
    CostCents,
    Estimate,
    IdempotencyScope,
    PhaseContext,
    PhaseStatus,
    ProjectPhase,
    ProjectRunId,
    new_project_run_id,
    parse_cost_cents,
)
from clue_core.idempotency import phase_key
from clue_db import ConnFactory, transaction
from clue_obs.otel import (
    ATTR_PROJECT_RUN_ID,
    apply_attributes,
    phase_span,
    traced_step,
)
from clue_research.durable.enums import PhaseCheckpointStatus, ProjectRunStatus
from clue_research.durable.idempotency import (
    IdempotencyStore,
    idempotent,
)
from clue_research.durable.phases import PhaseHandlerRegistry, default_phase_handler_registry
from clue_research.durable.project_run import (
    ProjectPhaseCheckpointRow,
    ProjectRunRow,
    TierCutoffs,
    ensure_project_run,
    get_checkpoint,
    get_project_run,
    insert_adjustment,
    set_budget_cap,
    set_icp_version,
    set_phase,
    set_run_status,
    set_tier_cutoffs,
    upsert_checkpoint,
)
from clue_research.durable.spans import ATTR_PHASE, ATTR_PHASE_STATUS

# The canonical phase sequence (Doc C §4 / conventions §3) — derived from the single source of truth
# ``core.ProjectPhase`` (enum definition order), so the state-machine order, the obs span tokens,
# and the DB enum cannot drift. ``test_project_phase_sequence`` asserts it equals the spec list.
PHASE_SEQUENCE: tuple[ProjectPhase, ...] = tuple(ProjectPhase)


def next_phase(phase: ProjectPhase) -> ProjectPhase | None:
    """The phase after ``phase`` in the canonical sequence, or ``None`` if ``phase`` is terminal
    (``HANDOFF``)."""
    idx = PHASE_SEQUENCE.index(phase)
    return PHASE_SEQUENCE[idx + 1] if idx + 1 < len(PHASE_SEQUENCE) else None


# A project run has a *single driver* (M7.3 owns its phase progression), so a ledger row found
# ``in_progress`` on re-entry is always *this* run's own crashed/partial attempt resuming — never a
# live concurrent holder. Phase idempotency therefore claims with a zero staleness window: any
# ``in_progress`` is immediately re-ownable (the re-entry executes), so re-entry can never raise a
# spurious :class:`~clue_research.durable.idempotency.IdempotencyConflict`. The ledger's job at the
# phase level is the exactly-once *finalize* (a re-finalize replays) + the per-phase charge record.
DEFAULT_PHASE_STALE_AFTER = timedelta(0)


# The phases that incur resolver spend, and so are gated by the per-run budget cap (M7.5). Before
# running one of these, the state machine asks the budget engine whether the per-run hard cap is
# already reached and, if so, graceful-stops (Doc C §5; substrate §5c). The setup / human-gate /
# output phases (``reverse_profiling`` / ``icp_confirmed`` / ``tier_checkpoint`` / ``handoff``) are
# *not* gated: they spend nothing meaningful and gating them would block a run from even starting or
# from reaching the client's raise-the-cap decision at the checkpoint.
_BUDGET_GATED_PHASES: frozenset[ProjectPhase] = frozenset(
    {
        ProjectPhase.DISCOVERY,
        ProjectPhase.SCORING,
        ProjectPhase.DEEP,
        ProjectPhase.VERIFICATION,
    }
)


# --- errors ----------------------------------------------------------------------------------


class ProjectRunError(Exception):
    """Base error for the project-run state machine (M7.3)."""


class ProjectRunNotFound(ProjectRunError):
    """No ``project_run`` row exists for the given id."""


class NoPhaseHandlerRegistered(ProjectRunError):
    """No :class:`~clue_core.PhaseHandler` is registered for the run's current phase — the
    api composition root must bind one (M5/M6/M8/M9/M12)."""


class CheckpointNotAwaiting(ProjectRunError):
    """:meth:`ProjectRun.submit_checkpoint` was called but the current phase is not suspended at an
    ``AWAITING_INPUT`` checkpoint (nothing to submit)."""


class BudgetEngineNotConfigured(ProjectRunError):
    """:meth:`ProjectRun.pre_run_estimate` needs a :class:`~clue_core.BudgetEngine` (M7.5
    supplies the cost math); none was injected."""


# --- the persistence seam --------------------------------------------------------------------


@runtime_checkable
class ProjectRunStore(Protocol):
    """The persistence seam the state machine reads/writes campaign state through (M7.3).

    Abstracting persistence keeps the transition/pause/resume/idempotency logic testable on an
    in-memory store without Postgres, and keeps the durable backend swappable (conventions §2). The
    production implementation is :class:`DbProjectRunStore`."""

    async def create(
        self,
        *,
        project_run_id: ProjectRunId,
        workspace_id: str,
        icp_key: str,
        icp_version: int,
        budget_cap_cents: CostCents | None,
        tier_cutoffs: TierCutoffs,
    ) -> None: ...

    async def get(self, project_run_id: ProjectRunId) -> ProjectRunRow | None: ...

    async def transition(
        self, project_run_id: ProjectRunId, *, phase: ProjectPhase, status: ProjectRunStatus
    ) -> None: ...

    async def mark_status(
        self,
        project_run_id: ProjectRunId,
        *,
        status: ProjectRunStatus,
        stamp_paused: bool = False,
        stamp_resumed: bool = False,
    ) -> None: ...

    async def put_checkpoint(
        self,
        *,
        project_run_id: ProjectRunId,
        phase: ProjectPhase,
        idempotency_key: str,
        status: PhaseCheckpointStatus,
        payload: dict[str, JsonValue],
    ) -> None: ...

    async def get_checkpoint(
        self, project_run_id: ProjectRunId, phase: ProjectPhase
    ) -> ProjectPhaseCheckpointRow | None: ...

    async def adjust(
        self,
        project_run_id: ProjectRunId,
        *,
        icp_version: int | None = None,
        budget_cap_cents: CostCents | None = None,
        tier_cutoffs: TierCutoffs | None = None,
    ) -> None: ...


class DbProjectRunStore:
    """The Postgres :class:`ProjectRunStore` — the production persistence path (M7.3).

    Each method runs in its own ``db.transaction()``. The phase commit and the phase transition are
    deliberately *separate* transactions (see the module docstring): the ``COMMITTED`` checkpoint is
    the durable "this phase is done" marker the transition replays off, so a crash between them is
    recovered idempotently. ``adjust`` updates the run field(s) **and** journals each change in one
    transaction (atomic + audited)."""

    def __init__(self, *, conn_factory: ConnFactory = transaction) -> None:
        # B4 slice-2 (S6): an injectable ``ConnFactory`` so a test/toolbelt composition can
        # bind a savepoint-scoped factory; defaults to the process ``transaction`` (the
        # production path, byte-identical behaviour).
        self._conn_factory = conn_factory

    async def create(
        self,
        *,
        project_run_id: ProjectRunId,
        workspace_id: str,
        icp_key: str,
        icp_version: int,
        budget_cap_cents: CostCents | None,
        tier_cutoffs: TierCutoffs,
    ) -> None:
        async with self._conn_factory() as conn:
            await ensure_project_run(
                conn,
                project_run_id=project_run_id,
                workspace_id=workspace_id,
                icp_key=icp_key,
                icp_version=icp_version,
                budget_cap_cents=budget_cap_cents,
                tier_cutoffs=tier_cutoffs,
            )

    async def get(self, project_run_id: ProjectRunId) -> ProjectRunRow | None:
        async with self._conn_factory() as conn:
            return await get_project_run(conn, project_run_id)

    async def transition(
        self, project_run_id: ProjectRunId, *, phase: ProjectPhase, status: ProjectRunStatus
    ) -> None:
        async with self._conn_factory() as conn:
            await set_phase(conn, project_run_id, phase=phase, status=status)

    async def mark_status(
        self,
        project_run_id: ProjectRunId,
        *,
        status: ProjectRunStatus,
        stamp_paused: bool = False,
        stamp_resumed: bool = False,
    ) -> None:
        async with self._conn_factory() as conn:
            await set_run_status(
                conn,
                project_run_id,
                status=status,
                stamp_paused=stamp_paused,
                stamp_resumed=stamp_resumed,
            )

    async def put_checkpoint(
        self,
        *,
        project_run_id: ProjectRunId,
        phase: ProjectPhase,
        idempotency_key: str,
        status: PhaseCheckpointStatus,
        payload: dict[str, JsonValue],
    ) -> None:
        async with self._conn_factory() as conn:
            await upsert_checkpoint(
                conn,
                project_run_id=project_run_id,
                phase=phase,
                idempotency_key=idempotency_key,
                status=status,
                payload=payload,
            )

    async def get_checkpoint(
        self, project_run_id: ProjectRunId, phase: ProjectPhase
    ) -> ProjectPhaseCheckpointRow | None:
        async with self._conn_factory() as conn:
            return await get_checkpoint(conn, project_run_id, phase)

    async def adjust(
        self,
        project_run_id: ProjectRunId,
        *,
        icp_version: int | None = None,
        budget_cap_cents: CostCents | None = None,
        tier_cutoffs: TierCutoffs | None = None,
    ) -> None:
        async with self._conn_factory() as conn:
            if icp_version is not None:
                await set_icp_version(conn, project_run_id, icp_version)
                await insert_adjustment(
                    conn,
                    project_run_id=project_run_id,
                    kind="icp_version",
                    detail={"icp_version": icp_version},
                )
            if budget_cap_cents is not None:
                await set_budget_cap(conn, project_run_id, budget_cap_cents)
                await insert_adjustment(
                    conn,
                    project_run_id=project_run_id,
                    kind="budget_cap",
                    detail={"budget_cap_cents": str(budget_cap_cents)},
                )
            if tier_cutoffs is not None:
                await set_tier_cutoffs(conn, project_run_id, tier_cutoffs)
                await insert_adjustment(
                    conn,
                    project_run_id=project_run_id,
                    kind="tier_cutoffs",
                    detail={"tier_cutoffs": tier_cutoffs},
                )


# --- the state machine -----------------------------------------------------------------------


class ProjectRun:
    """The outer project-run state machine (M7.3). Construct once with a :class:`ProjectRunStore`,
    a :class:`PhaseHandlerRegistry`, and (optionally) a :class:`~clue_core.BudgetEngine`;
    drive a run with :meth:`start` then :meth:`run_to_completion` (or step it with :meth:`advance`).

    The phase handlers do the work; this class owns ordering, durable checkpointing, the human gate,
    and pause/resume/adjust. It never imports a phase package — handlers reach it only through the
    registry (bound at the api root).

    **Single-driver-per-run is a precondition.** A given ``project_run_id`` is advanced by exactly
    one driver at a time — :meth:`advance` / :meth:`run_to_completion` / :meth:`submit_checkpoint`
    for the same run are never called concurrently (the run is one durable job; concurrency lives
    *inside* the ``deep`` phase across distinct accounts, mediated by the M2.4 entity lock, not
    across a run's own phases). This is what lets phase idempotency use a zero ``stale_after`` (an
    ``in_progress`` ledger row on re-entry is always this run's own crashed attempt resuming, never
    a live peer), so a crash-resume re-enters without a spurious
    :class:`~clue_research.durable.idempotency.IdempotencyConflict`. A per-run driver lock that
    would *enforce* this (vs. the M7.4 ledger relying on it) is left to the scheduler/ops layer,
    as M7.3
    recorded. The generic :func:`~clue_research.durable.idempotency.idempotent` primitive used for
    the *account-step* scope keeps the concurrency-safe non-zero default for parallel callers."""

    def __init__(
        self,
        *,
        store: ProjectRunStore | None = None,
        registry: PhaseHandlerRegistry | None = None,
        budget_engine: BudgetEngine | None = None,
        ledger: IdempotencyStore | None = None,
        phase_stale_after: timedelta = DEFAULT_PHASE_STALE_AFTER,
    ) -> None:
        self._store: ProjectRunStore = store if store is not None else DbProjectRunStore()
        self._registry = registry if registry is not None else default_phase_handler_registry()
        self._budget = budget_engine
        # The M7.4 phase-idempotency ledger. An *injected collaborator* (like ``budget_engine``):
        # the api composition root wires a ``DbIdempotencyStore`` so a phase finalize commits its
        # checkpoint + records its charge exactly once on the ``(project_run, phase)`` key. When
        # ``None`` (e.g. an in-memory unit test that does not
        # exercise idempotency), the phase finalize falls back to the M7.3 checkpoint-only path —
        # which is itself crash-safe (the ``COMMITTED`` short-circuit), just without the ledger's
        # exactly-once charge record.
        self._ledger = ledger
        self._phase_stale_after = phase_stale_after

    # -- lifecycle --

    async def start(
        self,
        *,
        workspace_id: str,
        icp_key: str,
        icp_version: int,
        budget_cap_cents: CostCents | None = None,
        tier_cutoffs: TierCutoffs | None = None,
        project_run_id: ProjectRunId | None = None,
    ) -> ProjectRunId:
        """Create a project run at the first phase (``reverse_profiling``, ``ACTIVE``) and return
        its id. Idempotent on a supplied ``project_run_id`` (a re-``start`` never resets a run that
        already advanced), so the caller can mint the id and retry safely."""
        run_id = project_run_id if project_run_id is not None else new_project_run_id()
        await self._store.create(
            project_run_id=run_id,
            workspace_id=workspace_id,
            icp_key=icp_key,
            icp_version=icp_version,
            budget_cap_cents=budget_cap_cents,
            tier_cutoffs=tier_cutoffs if tier_cutoffs is not None else {},
        )
        return run_id

    async def status(self, project_run_id: ProjectRunId) -> ProjectRunRow:
        """The current run row (raises :class:`ProjectRunNotFound` if the run does not exist)."""
        run = await self._store.get(project_run_id)
        if run is None:
            raise ProjectRunNotFound(str(project_run_id))
        return run

    async def advance(self, project_run_id: ProjectRunId) -> ProjectRunRow:
        """Run (or replay) exactly one phase and return the resulting run row.

        Terminal (``COMPLETED``/``FAILED``) and ``PAUSED`` runs are no-ops (a paused run must be
        :meth:`resume`\\d first). Otherwise: a ``COMMITTED`` checkpoint short-circuits to the
        transition (no re-run); an ``AWAITING_INPUT`` checkpoint returns unchanged (waiting on
        :meth:`submit_checkpoint`); else the registered handler runs and its
        :class:`~clue_core.PhaseResult` is applied."""
        run = await self.status(project_run_id)
        if run.status in (ProjectRunStatus.COMPLETED, ProjectRunStatus.FAILED):
            return run
        if run.status == ProjectRunStatus.PAUSED:
            return run

        phase = run.phase
        checkpoint = await self._store.get_checkpoint(project_run_id, phase)
        if checkpoint is not None and checkpoint.status == PhaseCheckpointStatus.COMMITTED:
            # The phase already committed (e.g. a crash between commit and transition) — replay the
            # transition without re-running the handler (idempotent re-entry).
            return await self._transition_after(run)
        if checkpoint is not None and checkpoint.status == PhaseCheckpointStatus.AWAITING_INPUT:
            # Suspended at a durable gate; the handler does not re-run until a decision arrives.
            return run

        # Budget pre-gate (M7.5): before running a *fresh* spend phase, if a budget engine is wired
        # and the per-run hard cap is already reached, graceful-stop the run at this boundary rather
        # than spending past the cap (Doc C §5). Placed after the checkpoint short-circuits (an
        # already-committed phase just transitions) and before the IN_PROGRESS stage (so a later
        # resume re-enters this same phase fresh once the cap is raised).
        if await self._budget_graceful_stop(run):
            await self._store.mark_status(
                project_run_id, status=ProjectRunStatus.PAUSED, stamp_paused=True
            )
            return await self.status(project_run_id)

        handler = self._registry.get(phase)
        if handler is None:
            raise NoPhaseHandlerRegistered(phase.value)

        key = phase_key(project_run_id, phase)
        # Stage IN_PROGRESS before invoking, so a crash *during* the handler leaves a resumable
        # marker (status stays ACTIVE; re-entry re-runs the not-yet-committed phase).
        await self._store.put_checkpoint(
            project_run_id=project_run_id,
            phase=phase,
            idempotency_key=key,
            status=PhaseCheckpointStatus.IN_PROGRESS,
            payload={},
        )
        with traced_step(
            phase_span(phase.value),
            **{ATTR_PROJECT_RUN_ID: str(project_run_id), ATTR_PHASE: phase.value},
        ) as span:
            result = await handler.run(self._phase_context(run))
            apply_attributes(span, {ATTR_PHASE_STATUS: result.status.value})

        if result.status == PhaseStatus.COMPLETED:
            # Finalize through the M7.4 ledger (when wired): commit the checkpoint + record the
            # exactly-once phase charge on phase_key, then transition. A re-finalize replays.
            return await self._finalize_phase(
                run, phase, payload=result.payload, cost_cents=result.cost_cents, resume=False
            )
        if result.status == PhaseStatus.PAUSED:
            await self._store.put_checkpoint(
                project_run_id=project_run_id,
                phase=phase,
                idempotency_key=key,
                status=PhaseCheckpointStatus.AWAITING_INPUT,
                payload=result.payload,
            )
            await self._store.mark_status(
                project_run_id, status=ProjectRunStatus.PAUSED, stamp_paused=True
            )
            return await self.status(project_run_id)
        # FAILED
        await self._store.put_checkpoint(
            project_run_id=project_run_id,
            phase=phase,
            idempotency_key=key,
            status=PhaseCheckpointStatus.FAILED,
            payload=result.payload,
        )
        await self._store.mark_status(project_run_id, status=ProjectRunStatus.FAILED)
        return await self.status(project_run_id)

    async def run_to_completion(
        self, project_run_id: ProjectRunId, *, max_steps: int | None = None
    ) -> ProjectRunRow:
        """Drive the run forward until it reaches a terminal or suspended state — ``COMPLETED``,
        ``FAILED``, or ``PAUSED`` (the human gate / a budget graceful-stop / a client pause). Each
        phase commits before the next runs, so an interrupted drive is resumable by calling this
        again. ``max_steps`` bounds the loop (a safety stop)."""
        steps = 0
        while True:
            run = await self.status(project_run_id)
            if run.status in (
                ProjectRunStatus.COMPLETED,
                ProjectRunStatus.FAILED,
                ProjectRunStatus.PAUSED,
            ):
                return run
            before = (run.phase, run.status)
            run = await self.advance(project_run_id)
            steps += 1
            if run.status in (
                ProjectRunStatus.COMPLETED,
                ProjectRunStatus.FAILED,
                ProjectRunStatus.PAUSED,
            ):
                return run
            # No-progress guard: an ACTIVE run that did not move (e.g. resumed while still
            # awaiting a checkpoint submission) would otherwise spin — stop and let the caller act.
            if (run.phase, run.status) == before:
                return run
            if max_steps is not None and steps >= max_steps:
                return run

    # -- client controls --

    async def pause(self, project_run_id: ProjectRunId) -> ProjectRunRow:
        """Bring an ``ACTIVE`` run to a safe boundary and record ``PAUSED``. Phases are the atomic
        unit: the in-flight phase commits and :meth:`run_to_completion` stops at the next boundary
        (no work already done is re-spent on :meth:`resume`). A no-op on a non-active run."""
        run = await self.status(project_run_id)
        if run.status == ProjectRunStatus.ACTIVE:
            await self._store.mark_status(
                project_run_id, status=ProjectRunStatus.PAUSED, stamp_paused=True
            )
        return await self.status(project_run_id)

    async def resume(self, project_run_id: ProjectRunId) -> ProjectRunRow:
        """Flip a ``PAUSED`` run back to ``ACTIVE`` (and stamp ``resumed_at``); the caller then
        drives :meth:`run_to_completion`, which continues from the last committed checkpoint. A run
        suspended at an ``AWAITING_INPUT`` gate also needs :meth:`submit_checkpoint` to proceed."""
        run = await self.status(project_run_id)
        if run.status == ProjectRunStatus.PAUSED:
            await self._store.mark_status(
                project_run_id, status=ProjectRunStatus.ACTIVE, stamp_resumed=True
            )
        return await self.status(project_run_id)

    async def adjust(
        self,
        project_run_id: ProjectRunId,
        *,
        icp_version: int | None = None,
        budget_cap_cents: CostCents | None = None,
        tier_cutoffs: TierCutoffs | None = None,
    ) -> ProjectRunRow:
        """Apply a versioned mid-run change the next phase picks up, journaled for audit: re-point
        the ICP version (M3 re-versions the spec), raise/lower the per-campaign budget cap (flowed
        to the M7.5 :class:`~clue_core.BudgetEngine` when one is wired), or edit the tier
        cutoffs (re-tiering happens deterministically at the next ``scoring``/``tier_checkpoint``).
        Only the provided fields change."""
        await self._store.adjust(
            project_run_id,
            icp_version=icp_version,
            budget_cap_cents=budget_cap_cents,
            tier_cutoffs=tier_cutoffs,
        )
        if budget_cap_cents is not None and self._budget is not None:
            # The campaign store owns ``project_run.budget_cap_cents`` + its append-only
            # ``adjustment_journal`` row (M7.3, written atomically above). The engine's
            # ``set_campaign_cap`` re-asserts the *same* value (an idempotent no-op on the column)
            # and adds the M7.5 governance events (``cap_raised`` / ``breach_pending``). The
            # redundant same-value column write is benign (single-driver precondition; the value is
            # identical); collapsing the two writers into one when the engine is wired is a noted
            # follow-up (cf. the account_run.cost_cents single-writer follow-up for M8).
            await self._budget.set_campaign_cap(project_run_id, budget_cap_cents)
        return await self.status(project_run_id)

    # -- the durable human / budget gate --

    async def await_checkpoint(
        self, project_run_id: ProjectRunId, *, phase: ProjectPhase | None = None
    ) -> ProjectPhaseCheckpointRow | None:
        """Read back the durable checkpoint for ``phase`` (default: the run's current phase) — the
        M6↔M7 read-back surface. At ``tier_checkpoint`` this returns M6.4's review payload (proposed
        cutoffs, tier distribution, cost estimate) the client UI (M13) renders; ``None`` if the
        phase has not produced a checkpoint."""
        run = await self.status(project_run_id)
        target = phase if phase is not None else run.phase
        return await self._store.get_checkpoint(project_run_id, target)

    async def submit_checkpoint(
        self, project_run_id: ProjectRunId, *, decision: dict[str, JsonValue]
    ) -> ProjectRunRow:
        """Apply the client's decision at a suspended (``AWAITING_INPUT``) checkpoint.

        ``decision`` mirrors M6.4's ``resume({cutoffs?, budget_cap?, action: approve|pause})``: any
        ``tier_cutoffs`` / ``budget_cap_cents`` it carries are applied via :meth:`adjust` first
        (journaled, re-estimable), then — on ``action == "approve"`` (the default) — the checkpoint
        is committed (with the decision merged into its payload) and the run advances to the next
        phase (``tier_checkpoint`` → ``deep``); on ``action == "pause"`` the run stays suspended.

        Idempotency: the effectful finalize (commit + resume + transition) is bracketed by M7.4's
        idempotency ledger on ``(project_run, phase)`` (when a ledger is wired), so a re-submit
        replays at the ledger instead of re-committing or double-charging; the embedded adjustments
        are additionally diff-guarded — applied only when they actually change the run — so a
        re-submit of the same decision does not append a duplicate audit-journal row. Together they
        close the crash window between the adjust and the commit that the diff guard alone could
        only partially cover. Raises :class:`CheckpointNotAwaiting` if nothing is awaiting input."""
        run = await self.status(project_run_id)
        phase = run.phase
        checkpoint = await self._store.get_checkpoint(project_run_id, phase)
        # Self-heal a partially-applied approve. The approve finalize is several steps (commit
        # checkpoint → mark ACTIVE → ledger succeed → transition), each its own transaction, so a
        # crash mid-finalize can leave the run at a COMMITTED-but-not-transitioned phase in *either*
        # interim status: ``PAUSED`` (crash before the resume mark) or ``ACTIVE`` (crash after it,
        # before the transition). Both are recovered by re-running the same ledger-bracketed
        # finalize (idempotent: re-commit is an upsert, the charge records once, the transition
        # runs exactly once) — not by raising CheckpointNotAwaiting. (A run that already
        # transitioned is at a *different* phase, so this never fires there.)
        if (
            checkpoint is not None
            and checkpoint.status == PhaseCheckpointStatus.COMMITTED
            and (run.status in (ProjectRunStatus.PAUSED, ProjectRunStatus.ACTIVE))
        ):
            return await self._finalize_phase(
                run, phase, payload=checkpoint.payload, cost_cents=Decimal(0), resume=True
            )
        if checkpoint is None or checkpoint.status != PhaseCheckpointStatus.AWAITING_INPUT:
            raise CheckpointNotAwaiting(f"{project_run_id}:{phase.value}")

        # Apply only the edits that actually change the run, so re-submitting the same decision (a
        # UI retry, or a crash between this adjust and the commit below) does not append a duplicate
        # journal row. ``parse_cost_cents`` defends against a malformed/NaN/Infinity/negative client
        # cap (ignored).
        cutoffs_in = decision.get("tier_cutoffs")
        cap_in = parse_cost_cents(decision.get("budget_cap_cents"))
        new_cutoffs = (
            cutoffs_in
            if isinstance(cutoffs_in, dict) and cutoffs_in and cutoffs_in != run.tier_cutoffs
            else None
        )
        new_cap = cap_in if cap_in is not None and cap_in != run.budget_cap_cents else None
        if new_cutoffs is not None or new_cap is not None:
            await self.adjust(project_run_id, tier_cutoffs=new_cutoffs, budget_cap_cents=new_cap)

        merged_payload: dict[str, JsonValue] = {**checkpoint.payload, "decision": decision}
        action = decision.get("action", "approve")
        if action == "approve":
            # Finalize through the M7.4 ledger (when wired): commit the checkpoint, resume the run,
            # and record the exactly-once charge on phase_key, then advance past the gate. A
            # re-submit of the same decision replays at the ledger (and the diff-guarded adjust
            # above is itself a no-op), so the whole approve is exactly-once across the crash window
            # the M7.3 diff guard could only partially cover.
            return await self._finalize_phase(
                run, phase, payload=merged_payload, cost_cents=Decimal(0), resume=True
            )
        # Any non-approve action keeps the run suspended, but records the decision on the payload.
        await self._store.put_checkpoint(
            project_run_id=project_run_id,
            phase=phase,
            idempotency_key=phase_key(project_run_id, phase),
            status=PhaseCheckpointStatus.AWAITING_INPUT,
            payload=merged_payload,
        )
        return await self.status(project_run_id)

    # -- cost estimate (delegates to M7.5) --

    async def pre_run_estimate(
        self,
        project_run_id: ProjectRunId,
        *,
        discovered_count: int,
        tier_cutoffs: dict[str, float] | None = None,
    ) -> Estimate:
        """Project the run's spend before any deep spend (Doc C §5) by delegating to the injected
        :class:`~clue_core.BudgetEngine` (M7.5 owns the math; M7.3 exposes the call the
        ``tier_checkpoint`` surface uses). Uses the run's stored cutoffs when none are supplied.
        Raises :class:`BudgetEngineNotConfigured` if no engine is wired."""
        if self._budget is None:
            raise BudgetEngineNotConfigured(str(project_run_id))
        run = await self.status(project_run_id)
        cutoffs = tier_cutoffs if tier_cutoffs is not None else _to_float_cutoffs(run.tier_cutoffs)
        return await self._budget.estimate(
            project_run_id, discovered_count=discovered_count, tier_cutoffs=cutoffs
        )

    async def burn_down(self, project_run_id: ProjectRunId) -> BurnDown:
        """The live cost burn-down for the run (Doc C §5/§6) — spent vs estimate vs cap vs remaining
        — by delegating to the injected :class:`~clue_core.BudgetEngine` (M7.5 owns the
        accounting; M7.3 exposes the call the client surface / M13.4 uses). Raises
        :class:`BudgetEngineNotConfigured` if no engine is wired."""
        if self._budget is None:
            raise BudgetEngineNotConfigured(str(project_run_id))
        return await self._budget.burn_down(project_run_id)

    # -- internals --

    async def _budget_graceful_stop(self, run: ProjectRunRow) -> bool:
        """Whether the per-run budget cap requires a graceful stop *before* ``run``'s current phase
        (M7.5). Only the spend phases (:data:`_BUDGET_GATED_PHASES`) are gated, and only when a
        budget engine is wired. A ``GRACEFUL_STOP`` verdict (the per-run hard cap is reached) pauses
        the run cooperatively — status ``PAUSED``, **no** ``AWAITING_INPUT`` checkpoint — so a later
        :meth:`resume` re-enters the *same* phase once the cap is raised, distinct from the human
        ``tier_checkpoint`` gate (which commits-and-advances on approve). The engine records the
        ``graceful_stop`` ``budget_event`` as part of the check."""
        if self._budget is None or run.phase not in _BUDGET_GATED_PHASES:
            return False
        decision = await self._budget.check(
            scope=BudgetScope.RUN, projected_cents=Decimal(0), project_run_id=run.id
        )
        return decision.verdict is BudgetVerdict.GRACEFUL_STOP

    def _phase_context(self, run: ProjectRunRow) -> PhaseContext:
        """Build the frozen :class:`~clue_core.PhaseContext` for the run's current phase —
        identifies the run + active ICP version; tier cutoffs ride ``params`` (the phase-specific
        escape hatch) so adding one never forces a ``core`` change."""
        return PhaseContext(
            project_run_id=run.id,
            phase=run.phase,
            workspace_id=run.workspace_id,
            icp_key=run.icp_key,
            icp_version=run.icp_version,
            budget_cap_cents=run.budget_cap_cents,
            params={"tier_cutoffs": run.tier_cutoffs},
        )

    async def _transition_after(self, run: ProjectRunRow) -> ProjectRunRow:
        """Advance the run pointer to the phase after ``run.phase`` (``ACTIVE``), or mark the run
        ``COMPLETED`` when the terminal ``HANDOFF`` phase has committed."""
        nxt = next_phase(run.phase)
        if nxt is None:
            await self._store.transition(run.id, phase=run.phase, status=ProjectRunStatus.COMPLETED)
        else:
            await self._store.transition(run.id, phase=nxt, status=ProjectRunStatus.ACTIVE)
        return await self.status(run.id)

    async def _commit_phase(
        self,
        project_run_id: ProjectRunId,
        phase: ProjectPhase,
        *,
        payload: dict[str, JsonValue],
        resume: bool,
    ) -> None:
        """Commit the ``(project_run, phase)`` checkpoint (``COMMITTED``) and, when ``resume`` (the
        human-gate approve path), flip the PAUSED run back to ``ACTIVE`` — the durable "this phase
        is done" marker the transition replays off."""
        await self._store.put_checkpoint(
            project_run_id=project_run_id,
            phase=phase,
            idempotency_key=phase_key(project_run_id, phase),
            status=PhaseCheckpointStatus.COMMITTED,
            payload=payload,
        )
        if resume:
            await self._store.mark_status(
                project_run_id, status=ProjectRunStatus.ACTIVE, stamp_resumed=True
            )

    async def _finalize_phase(
        self,
        run: ProjectRunRow,
        phase: ProjectPhase,
        *,
        payload: dict[str, JsonValue],
        cost_cents: CostCents,
        resume: bool,
    ) -> ProjectRunRow:
        """Commit the phase and transition past it — bracketed by the M7.4 idempotency ledger when
        one is wired (``with idempotent(phase_key(...))``), so the commit + the per-phase charge
        record happen **exactly once** on the ``(project_run, phase)`` key.

        With a ledger, the outcome depends on the ledger row for this phase. If it is already
        ``succeeded`` (a re-finalize after a prior full success that crashed before transitioning)
        the finalize **replays** — nothing re-committed, nothing re-charged — but the idempotent
        transition still runs, so a single call completes the phase. If it is fresh /
        ``in_progress`` (the crash-between-commit-and-succeed window) it is re-owned
        (phase ``stale_after`` is zero — single-driver, see the class docstring) and the commit +
        charge-record run again *idempotently* (``put_checkpoint`` is an upsert; the charge is
        recorded once on success), so a retry can never double-commit or double-charge. The narrow
        residual is that a crash *between* the durable ``COMMITTED`` checkpoint and the ledger
        ``succeed`` can leave a phase's ledger row ``in_progress`` (the ``advance`` ``COMMITTED``
        short-circuit transitions without re-touching the ledger): the checkpoint stays the
        authoritative "phase done" record, and the (nominal) phase charge is best-effort — the
        airtight exactly-once charge is the *account-step* ledger (paid resolvers), whose caller
        finishes the ledger in the claim-write transaction (M8).

        Without a ledger (``ledger is None``): the M7.3 checkpoint-only path — itself crash-safe via
        the ``COMMITTED`` short-circuit, just without the ledger's charge record. ``resume`` flips a
        PAUSED gate back to ``ACTIVE`` (the ``submit_checkpoint`` approve path); ``cost_cents`` is
        the phase's charge recorded in the ledger (the single record M7.5 counts once)."""
        if self._ledger is None:
            await self._commit_phase(run.id, phase, payload=payload, resume=resume)
            return await self._transition_after(await self.status(run.id))
        key = phase_key(run.id, phase)
        async with idempotent(
            key,
            IdempotencyScope.PROJECT_PHASE,
            store=self._ledger,
            stale_after=self._phase_stale_after,
        ) as step:
            if step.is_replay:
                # This phase already committed + charged in a prior attempt that crashed before it
                # transitioned (the ledger row is ``succeeded``). Do NOT re-commit or re-charge, but
                # still replay the transition so the finalize is complete from a single call — it is
                # idempotent (``_transition_after`` is an UPDATE, and at this point the run is still
                # at ``phase``; a fully-finalized phase would be at the *next* phase and not
                # re-enter here). Both finalize outcomes (execute / replay) thus end transitioned.
                return await self._transition_after(await self.status(run.id))
            await self._commit_phase(run.id, phase, payload=payload, resume=resume)
            step.record(result_ref={"phase": phase.value}, cost_cents=cost_cents)
        return await self._transition_after(await self.status(run.id))


def _to_float_cutoffs(cutoffs: TierCutoffs) -> dict[str, float] | None:
    """Project the run's stored tier cutoffs to the ``dict[str, float]`` the BudgetEngine estimate
    expects, dropping any non-numeric, boolean, or non-finite (``NaN``/``inf``) value; ``None`` when
    empty."""
    numeric = {
        key: float(value)
        for key, value in cutoffs.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    }
    return numeric or None
