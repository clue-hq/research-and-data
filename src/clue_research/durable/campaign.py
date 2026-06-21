"""The outer campaign-run state machine (M7.3) — the durable scheduler over the phase sequence.

The substrate nails *per-account* durable execution (M7.1) but not the **campaign run** — the
long-lived job spanning ``reverse_profiling → icp_confirmed → discovery → scoring → tier_checkpoint
→ deep → verification → handoff`` (Doc C §4). :class:`CampaignRun` owns that lifecycle: explicit
phase ordering, per-phase checkpointing so a crash resumes at the last committed phase, the durable
human gate at ``tier_checkpoint`` (an ``interrupt()``-style suspend/resume), and client-driven
**pause / resume / adjust** with safe re-entry.

It owns *transitions, persistence, and re-entry* — never phase content: phase bodies are supplied by
M5/M6/M8/M9/M12 as :class:`~clue_research.core.PhaseHandler`\\s registered into a
:class:`~clue_research.durable.phases.PhaseHandlerRegistry` (the same registration seam as the
aspect-worker registry). Persistence sits behind the :class:`CampaignRunStore` seam, so the state
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
from decimal import Decimal
from typing import Protocol, runtime_checkable

from pydantic import JsonValue

from clue_research.core import (
    BudgetEngine,
    CampaignPhase,
    CampaignRunId,
    CostCents,
    Estimate,
    PhaseContext,
    PhaseStatus,
    new_campaign_run_id,
)
from clue_research.core.idempotency import phase_key
from clue_research.db import transaction
from clue_research.durable.campaign_run import (
    CampaignPhaseCheckpointRow,
    CampaignRunRow,
    TierCutoffs,
    ensure_campaign_run,
    get_campaign_run,
    get_checkpoint,
    insert_adjustment,
    set_budget_cap,
    set_icp_version,
    set_phase,
    set_run_status,
    set_tier_cutoffs,
    upsert_checkpoint,
)
from clue_research.durable.enums import CampaignRunStatus, PhaseCheckpointStatus
from clue_research.durable.phases import PhaseHandlerRegistry, default_phase_handler_registry
from clue_research.durable.spans import ATTR_PHASE, ATTR_PHASE_STATUS
from clue_research.obs import (
    ATTR_CAMPAIGN_RUN_ID,
    apply_attributes,
    phase_span,
    traced_step,
)

# The canonical phase sequence (Doc C §4 / conventions §3) — derived from the single source of truth
# ``core.CampaignPhase`` (enum definition order), so the state-machine order, the obs span tokens,
# and the DB enum cannot drift. ``test_campaign_phase_sequence`` asserts it equals the spec list.
PHASE_SEQUENCE: tuple[CampaignPhase, ...] = tuple(CampaignPhase)


def next_phase(phase: CampaignPhase) -> CampaignPhase | None:
    """The phase after ``phase`` in the canonical sequence, or ``None`` if ``phase`` is terminal
    (``HANDOFF``)."""
    idx = PHASE_SEQUENCE.index(phase)
    return PHASE_SEQUENCE[idx + 1] if idx + 1 < len(PHASE_SEQUENCE) else None


# --- errors ----------------------------------------------------------------------------------


class CampaignRunError(Exception):
    """Base error for the campaign-run state machine (M7.3)."""


class CampaignRunNotFound(CampaignRunError):
    """No ``campaign_run`` row exists for the given id."""


class NoPhaseHandlerRegistered(CampaignRunError):
    """No :class:`~clue_research.core.PhaseHandler` is registered for the run's current phase — the
    api composition root must bind one (M5/M6/M8/M9/M12)."""


class CheckpointNotAwaiting(CampaignRunError):
    """:meth:`CampaignRun.submit_checkpoint` was called but the current phase is not suspended at an
    ``AWAITING_INPUT`` checkpoint (nothing to submit)."""


class BudgetEngineNotConfigured(CampaignRunError):
    """:meth:`CampaignRun.pre_run_estimate` needs a :class:`~clue_research.core.BudgetEngine` (M7.5
    supplies the cost math); none was injected."""


# --- the persistence seam --------------------------------------------------------------------


@runtime_checkable
class CampaignRunStore(Protocol):
    """The persistence seam the state machine reads/writes campaign state through (M7.3).

    Abstracting persistence keeps the transition/pause/resume/idempotency logic testable on an
    in-memory store without Postgres, and keeps the durable backend swappable (conventions §2). The
    production implementation is :class:`DbCampaignRunStore`."""

    async def create(
        self,
        *,
        campaign_run_id: CampaignRunId,
        client_id: str,
        icp_key: str,
        icp_version: int,
        budget_cap_cents: CostCents | None,
        tier_cutoffs: TierCutoffs,
    ) -> None: ...

    async def get(self, campaign_run_id: CampaignRunId) -> CampaignRunRow | None: ...

    async def transition(
        self, campaign_run_id: CampaignRunId, *, phase: CampaignPhase, status: CampaignRunStatus
    ) -> None: ...

    async def mark_status(
        self,
        campaign_run_id: CampaignRunId,
        *,
        status: CampaignRunStatus,
        stamp_paused: bool = False,
        stamp_resumed: bool = False,
    ) -> None: ...

    async def put_checkpoint(
        self,
        *,
        campaign_run_id: CampaignRunId,
        phase: CampaignPhase,
        idempotency_key: str,
        status: PhaseCheckpointStatus,
        payload: dict[str, JsonValue],
    ) -> None: ...

    async def get_checkpoint(
        self, campaign_run_id: CampaignRunId, phase: CampaignPhase
    ) -> CampaignPhaseCheckpointRow | None: ...

    async def adjust(
        self,
        campaign_run_id: CampaignRunId,
        *,
        icp_version: int | None = None,
        budget_cap_cents: CostCents | None = None,
        tier_cutoffs: TierCutoffs | None = None,
    ) -> None: ...


class DbCampaignRunStore:
    """The Postgres :class:`CampaignRunStore` — the production persistence path (M7.3).

    Each method runs in its own ``db.transaction()``. The phase commit and the phase transition are
    deliberately *separate* transactions (see the module docstring): the ``COMMITTED`` checkpoint is
    the durable "this phase is done" marker the transition replays off, so a crash between them is
    recovered idempotently. ``adjust`` updates the run field(s) **and** journals each change in one
    transaction (atomic + audited)."""

    async def create(
        self,
        *,
        campaign_run_id: CampaignRunId,
        client_id: str,
        icp_key: str,
        icp_version: int,
        budget_cap_cents: CostCents | None,
        tier_cutoffs: TierCutoffs,
    ) -> None:
        async with transaction() as conn:
            await ensure_campaign_run(
                conn,
                campaign_run_id=campaign_run_id,
                client_id=client_id,
                icp_key=icp_key,
                icp_version=icp_version,
                budget_cap_cents=budget_cap_cents,
                tier_cutoffs=tier_cutoffs,
            )

    async def get(self, campaign_run_id: CampaignRunId) -> CampaignRunRow | None:
        async with transaction() as conn:
            return await get_campaign_run(conn, campaign_run_id)

    async def transition(
        self, campaign_run_id: CampaignRunId, *, phase: CampaignPhase, status: CampaignRunStatus
    ) -> None:
        async with transaction() as conn:
            await set_phase(conn, campaign_run_id, phase=phase, status=status)

    async def mark_status(
        self,
        campaign_run_id: CampaignRunId,
        *,
        status: CampaignRunStatus,
        stamp_paused: bool = False,
        stamp_resumed: bool = False,
    ) -> None:
        async with transaction() as conn:
            await set_run_status(
                conn,
                campaign_run_id,
                status=status,
                stamp_paused=stamp_paused,
                stamp_resumed=stamp_resumed,
            )

    async def put_checkpoint(
        self,
        *,
        campaign_run_id: CampaignRunId,
        phase: CampaignPhase,
        idempotency_key: str,
        status: PhaseCheckpointStatus,
        payload: dict[str, JsonValue],
    ) -> None:
        async with transaction() as conn:
            await upsert_checkpoint(
                conn,
                campaign_run_id=campaign_run_id,
                phase=phase,
                idempotency_key=idempotency_key,
                status=status,
                payload=payload,
            )

    async def get_checkpoint(
        self, campaign_run_id: CampaignRunId, phase: CampaignPhase
    ) -> CampaignPhaseCheckpointRow | None:
        async with transaction() as conn:
            return await get_checkpoint(conn, campaign_run_id, phase)

    async def adjust(
        self,
        campaign_run_id: CampaignRunId,
        *,
        icp_version: int | None = None,
        budget_cap_cents: CostCents | None = None,
        tier_cutoffs: TierCutoffs | None = None,
    ) -> None:
        async with transaction() as conn:
            if icp_version is not None:
                await set_icp_version(conn, campaign_run_id, icp_version)
                await insert_adjustment(
                    conn,
                    campaign_run_id=campaign_run_id,
                    kind="icp_version",
                    detail={"icp_version": icp_version},
                )
            if budget_cap_cents is not None:
                await set_budget_cap(conn, campaign_run_id, budget_cap_cents)
                await insert_adjustment(
                    conn,
                    campaign_run_id=campaign_run_id,
                    kind="budget_cap",
                    detail={"budget_cap_cents": str(budget_cap_cents)},
                )
            if tier_cutoffs is not None:
                await set_tier_cutoffs(conn, campaign_run_id, tier_cutoffs)
                await insert_adjustment(
                    conn,
                    campaign_run_id=campaign_run_id,
                    kind="tier_cutoffs",
                    detail={"tier_cutoffs": tier_cutoffs},
                )


# --- the state machine -----------------------------------------------------------------------


class CampaignRun:
    """The outer campaign-run state machine (M7.3). Construct once with a :class:`CampaignRunStore`,
    a :class:`PhaseHandlerRegistry`, and (optionally) a :class:`~clue_research.core.BudgetEngine`;
    drive a run with :meth:`start` then :meth:`run_to_completion` (or step it with :meth:`advance`).

    The phase handlers do the work; this class owns ordering, durable checkpointing, the human gate,
    and pause/resume/adjust. It never imports a phase package — handlers reach it only through the
    registry (bound at the api root)."""

    def __init__(
        self,
        *,
        store: CampaignRunStore | None = None,
        registry: PhaseHandlerRegistry | None = None,
        budget_engine: BudgetEngine | None = None,
    ) -> None:
        self._store: CampaignRunStore = store if store is not None else DbCampaignRunStore()
        self._registry = registry if registry is not None else default_phase_handler_registry()
        self._budget = budget_engine

    # -- lifecycle --

    async def start(
        self,
        *,
        client_id: str,
        icp_key: str,
        icp_version: int,
        budget_cap_cents: CostCents | None = None,
        tier_cutoffs: TierCutoffs | None = None,
        campaign_run_id: CampaignRunId | None = None,
    ) -> CampaignRunId:
        """Create a campaign run at the first phase (``reverse_profiling``, ``ACTIVE``) and return
        its id. Idempotent on a supplied ``campaign_run_id`` (a re-``start`` never resets a run that
        already advanced), so the caller can mint the id and retry safely."""
        run_id = campaign_run_id if campaign_run_id is not None else new_campaign_run_id()
        await self._store.create(
            campaign_run_id=run_id,
            client_id=client_id,
            icp_key=icp_key,
            icp_version=icp_version,
            budget_cap_cents=budget_cap_cents,
            tier_cutoffs=tier_cutoffs if tier_cutoffs is not None else {},
        )
        return run_id

    async def status(self, campaign_run_id: CampaignRunId) -> CampaignRunRow:
        """The current run row (raises :class:`CampaignRunNotFound` if the run does not exist)."""
        run = await self._store.get(campaign_run_id)
        if run is None:
            raise CampaignRunNotFound(str(campaign_run_id))
        return run

    async def advance(self, campaign_run_id: CampaignRunId) -> CampaignRunRow:
        """Run (or replay) exactly one phase and return the resulting run row.

        Terminal (``COMPLETED``/``FAILED``) and ``PAUSED`` runs are no-ops (a paused run must be
        :meth:`resume`\\d first). Otherwise: a ``COMMITTED`` checkpoint short-circuits to the
        transition (no re-run); an ``AWAITING_INPUT`` checkpoint returns unchanged (waiting on
        :meth:`submit_checkpoint`); else the registered handler runs and its
        :class:`~clue_research.core.PhaseResult` is applied."""
        run = await self.status(campaign_run_id)
        if run.status in (CampaignRunStatus.COMPLETED, CampaignRunStatus.FAILED):
            return run
        if run.status == CampaignRunStatus.PAUSED:
            return run

        phase = run.phase
        checkpoint = await self._store.get_checkpoint(campaign_run_id, phase)
        if checkpoint is not None and checkpoint.status == PhaseCheckpointStatus.COMMITTED:
            # The phase already committed (e.g. a crash between commit and transition) — replay the
            # transition without re-running the handler (idempotent re-entry).
            return await self._transition_after(run)
        if checkpoint is not None and checkpoint.status == PhaseCheckpointStatus.AWAITING_INPUT:
            # Suspended at a durable gate; the handler does not re-run until a decision arrives.
            return run

        handler = self._registry.get(phase)
        if handler is None:
            raise NoPhaseHandlerRegistered(phase.value)

        key = phase_key(campaign_run_id, phase)
        # Stage IN_PROGRESS before invoking, so a crash *during* the handler leaves a resumable
        # marker (status stays ACTIVE; re-entry re-runs the not-yet-committed phase).
        await self._store.put_checkpoint(
            campaign_run_id=campaign_run_id,
            phase=phase,
            idempotency_key=key,
            status=PhaseCheckpointStatus.IN_PROGRESS,
            payload={},
        )
        with traced_step(
            phase_span(phase.value),
            **{ATTR_CAMPAIGN_RUN_ID: str(campaign_run_id), ATTR_PHASE: phase.value},
        ) as span:
            result = await handler.run(self._phase_context(run))
            apply_attributes(span, {ATTR_PHASE_STATUS: result.status.value})

        if result.status == PhaseStatus.COMPLETED:
            await self._store.put_checkpoint(
                campaign_run_id=campaign_run_id,
                phase=phase,
                idempotency_key=key,
                status=PhaseCheckpointStatus.COMMITTED,
                payload=result.payload,
            )
            return await self._transition_after(run)
        if result.status == PhaseStatus.PAUSED:
            await self._store.put_checkpoint(
                campaign_run_id=campaign_run_id,
                phase=phase,
                idempotency_key=key,
                status=PhaseCheckpointStatus.AWAITING_INPUT,
                payload=result.payload,
            )
            await self._store.mark_status(
                campaign_run_id, status=CampaignRunStatus.PAUSED, stamp_paused=True
            )
            return await self.status(campaign_run_id)
        # FAILED
        await self._store.put_checkpoint(
            campaign_run_id=campaign_run_id,
            phase=phase,
            idempotency_key=key,
            status=PhaseCheckpointStatus.FAILED,
            payload=result.payload,
        )
        await self._store.mark_status(campaign_run_id, status=CampaignRunStatus.FAILED)
        return await self.status(campaign_run_id)

    async def run_to_completion(
        self, campaign_run_id: CampaignRunId, *, max_steps: int | None = None
    ) -> CampaignRunRow:
        """Drive the run forward until it reaches a terminal or suspended state — ``COMPLETED``,
        ``FAILED``, or ``PAUSED`` (the human gate / a budget graceful-stop / a client pause). Each
        phase commits before the next runs, so an interrupted drive is resumable by calling this
        again. ``max_steps`` bounds the loop (a safety stop)."""
        steps = 0
        while True:
            run = await self.status(campaign_run_id)
            if run.status in (
                CampaignRunStatus.COMPLETED,
                CampaignRunStatus.FAILED,
                CampaignRunStatus.PAUSED,
            ):
                return run
            before = (run.phase, run.status)
            run = await self.advance(campaign_run_id)
            steps += 1
            if run.status in (
                CampaignRunStatus.COMPLETED,
                CampaignRunStatus.FAILED,
                CampaignRunStatus.PAUSED,
            ):
                return run
            # No-progress guard: an ACTIVE run that did not move (e.g. resumed while still
            # awaiting a checkpoint submission) would otherwise spin — stop and let the caller act.
            if (run.phase, run.status) == before:
                return run
            if max_steps is not None and steps >= max_steps:
                return run

    # -- client controls --

    async def pause(self, campaign_run_id: CampaignRunId) -> CampaignRunRow:
        """Bring an ``ACTIVE`` run to a safe boundary and record ``PAUSED``. Phases are the atomic
        unit: the in-flight phase commits and :meth:`run_to_completion` stops at the next boundary
        (no work already done is re-spent on :meth:`resume`). A no-op on a non-active run."""
        run = await self.status(campaign_run_id)
        if run.status == CampaignRunStatus.ACTIVE:
            await self._store.mark_status(
                campaign_run_id, status=CampaignRunStatus.PAUSED, stamp_paused=True
            )
        return await self.status(campaign_run_id)

    async def resume(self, campaign_run_id: CampaignRunId) -> CampaignRunRow:
        """Flip a ``PAUSED`` run back to ``ACTIVE`` (and stamp ``resumed_at``); the caller then
        drives :meth:`run_to_completion`, which continues from the last committed checkpoint. A run
        suspended at an ``AWAITING_INPUT`` gate also needs :meth:`submit_checkpoint` to proceed."""
        run = await self.status(campaign_run_id)
        if run.status == CampaignRunStatus.PAUSED:
            await self._store.mark_status(
                campaign_run_id, status=CampaignRunStatus.ACTIVE, stamp_resumed=True
            )
        return await self.status(campaign_run_id)

    async def adjust(
        self,
        campaign_run_id: CampaignRunId,
        *,
        icp_version: int | None = None,
        budget_cap_cents: CostCents | None = None,
        tier_cutoffs: TierCutoffs | None = None,
    ) -> CampaignRunRow:
        """Apply a versioned mid-run change the next phase picks up, journaled for audit: re-point
        the ICP version (M3 re-versions the spec), raise/lower the per-campaign budget cap (flowed
        to the M7.5 :class:`~clue_research.core.BudgetEngine` when one is wired), or edit the tier
        cutoffs (re-tiering happens deterministically at the next ``scoring``/``tier_checkpoint``).
        Only the provided fields change."""
        await self._store.adjust(
            campaign_run_id,
            icp_version=icp_version,
            budget_cap_cents=budget_cap_cents,
            tier_cutoffs=tier_cutoffs,
        )
        if budget_cap_cents is not None and self._budget is not None:
            await self._budget.set_campaign_cap(campaign_run_id, budget_cap_cents)
        return await self.status(campaign_run_id)

    # -- the durable human / budget gate --

    async def await_checkpoint(
        self, campaign_run_id: CampaignRunId, *, phase: CampaignPhase | None = None
    ) -> CampaignPhaseCheckpointRow | None:
        """Read back the durable checkpoint for ``phase`` (default: the run's current phase) — the
        M6↔M7 read-back surface. At ``tier_checkpoint`` this returns M6.4's review payload (proposed
        cutoffs, tier distribution, cost estimate) the client UI (M13) renders; ``None`` if the
        phase has not produced a checkpoint."""
        run = await self.status(campaign_run_id)
        target = phase if phase is not None else run.phase
        return await self._store.get_checkpoint(campaign_run_id, target)

    async def submit_checkpoint(
        self, campaign_run_id: CampaignRunId, *, decision: dict[str, JsonValue]
    ) -> CampaignRunRow:
        """Apply the client's decision at a suspended (``AWAITING_INPUT``) checkpoint.

        ``decision`` mirrors M6.4's ``resume({cutoffs?, budget_cap?, action: approve|pause})``: any
        ``tier_cutoffs`` / ``budget_cap_cents`` it carries are applied via :meth:`adjust` first
        (journaled, re-estimable), then — on ``action == "approve"`` (the default) — the checkpoint
        is committed (with the decision merged into its payload) and the run advances to the next
        phase (``tier_checkpoint`` → ``deep``); on ``action == "pause"`` the run stays suspended.

        Idempotency: the *advance* is keyed on ``(campaign_run, phase)`` (the committed-checkpoint
        short-circuit), so a re-submit does not re-advance; and the embedded adjustments are applied
        only when they actually change the run, so a re-submit of the same decision does not append
        a duplicate audit-journal row. (Exactly-once bracketing of *every* effect across a crash
        mid-submit arrives with M7.4's idempotency ledger, which this section will wrap.) Raises
        :class:`CheckpointNotAwaiting` if nothing is awaiting input."""
        run = await self.status(campaign_run_id)
        phase = run.phase
        checkpoint = await self._store.get_checkpoint(campaign_run_id, phase)
        # Self-heal a partially-applied approve: the commit and the resume are separate transactions
        # (DbCampaignRunStore), so a crash between them leaves the run PAUSED at a COMMITTED phase.
        # A retried submit finishes it idempotently — replaying the transition, re-running nothing —
        # rather than raising CheckpointNotAwaiting (mirrors advance()'s committed short-circuit).
        if (
            checkpoint is not None
            and checkpoint.status == PhaseCheckpointStatus.COMMITTED
            and run.status == CampaignRunStatus.PAUSED
        ):
            await self._store.mark_status(
                campaign_run_id, status=CampaignRunStatus.ACTIVE, stamp_resumed=True
            )
            return await self._transition_after(await self.status(campaign_run_id))
        if checkpoint is None or checkpoint.status != PhaseCheckpointStatus.AWAITING_INPUT:
            raise CheckpointNotAwaiting(f"{campaign_run_id}:{phase.value}")

        # Apply only the edits that actually change the run, so re-submitting the same decision (a
        # UI retry, or a crash between this adjust and the commit below) does not append a duplicate
        # journal row. ``_to_cost`` defends against a malformed/NaN/Infinity client cap (ignored).
        cutoffs_in = decision.get("tier_cutoffs")
        cap_in = _to_cost(decision.get("budget_cap_cents"))
        new_cutoffs = (
            cutoffs_in
            if isinstance(cutoffs_in, dict) and cutoffs_in and cutoffs_in != run.tier_cutoffs
            else None
        )
        new_cap = cap_in if cap_in is not None and cap_in != run.budget_cap_cents else None
        if new_cutoffs is not None or new_cap is not None:
            await self.adjust(campaign_run_id, tier_cutoffs=new_cutoffs, budget_cap_cents=new_cap)

        merged_payload: dict[str, JsonValue] = {**checkpoint.payload, "decision": decision}
        key = phase_key(campaign_run_id, phase)
        action = decision.get("action", "approve")
        if action == "approve":
            await self._store.put_checkpoint(
                campaign_run_id=campaign_run_id,
                phase=phase,
                idempotency_key=key,
                status=PhaseCheckpointStatus.COMMITTED,
                payload=merged_payload,
            )
            # The run was PAUSED at the gate — make it ACTIVE before advancing past the checkpoint.
            await self._store.mark_status(
                campaign_run_id, status=CampaignRunStatus.ACTIVE, stamp_resumed=True
            )
            return await self._transition_after(await self.status(campaign_run_id))
        # Any non-approve action keeps the run suspended, but records the decision on the payload.
        await self._store.put_checkpoint(
            campaign_run_id=campaign_run_id,
            phase=phase,
            idempotency_key=key,
            status=PhaseCheckpointStatus.AWAITING_INPUT,
            payload=merged_payload,
        )
        return await self.status(campaign_run_id)

    # -- cost estimate (delegates to M7.5) --

    async def pre_run_estimate(
        self,
        campaign_run_id: CampaignRunId,
        *,
        discovered_count: int,
        tier_cutoffs: dict[str, float] | None = None,
    ) -> Estimate:
        """Project the run's spend before any deep spend (Doc C §5) by delegating to the injected
        :class:`~clue_research.core.BudgetEngine` (M7.5 owns the math; M7.3 exposes the call the
        ``tier_checkpoint`` surface uses). Uses the run's stored cutoffs when none are supplied.
        Raises :class:`BudgetEngineNotConfigured` if no engine is wired."""
        if self._budget is None:
            raise BudgetEngineNotConfigured(str(campaign_run_id))
        run = await self.status(campaign_run_id)
        cutoffs = tier_cutoffs if tier_cutoffs is not None else _to_float_cutoffs(run.tier_cutoffs)
        return await self._budget.estimate(
            campaign_run_id, discovered_count=discovered_count, tier_cutoffs=cutoffs
        )

    # -- internals --

    def _phase_context(self, run: CampaignRunRow) -> PhaseContext:
        """Build the frozen :class:`~clue_research.core.PhaseContext` for the run's current phase —
        identifies the run + active ICP version; tier cutoffs ride ``params`` (the phase-specific
        escape hatch) so adding one never forces a ``core`` change."""
        return PhaseContext(
            campaign_run_id=run.id,
            phase=run.phase,
            client_id=run.client_id,
            icp_key=run.icp_key,
            icp_version=run.icp_version,
            budget_cap_cents=run.budget_cap_cents,
            params={"tier_cutoffs": run.tier_cutoffs},
        )

    async def _transition_after(self, run: CampaignRunRow) -> CampaignRunRow:
        """Advance the run pointer to the phase after ``run.phase`` (``ACTIVE``), or mark the run
        ``COMPLETED`` when the terminal ``HANDOFF`` phase has committed."""
        nxt = next_phase(run.phase)
        if nxt is None:
            await self._store.transition(
                run.id, phase=run.phase, status=CampaignRunStatus.COMPLETED
            )
        else:
            await self._store.transition(run.id, phase=nxt, status=CampaignRunStatus.ACTIVE)
        return await self.status(run.id)


def _to_cost(value: object) -> CostCents | None:
    """Coerce a JSON-carried cap (str/number) from a decision dict to ``CostCents``; ``None`` if
    absent, unparseable, non-finite, or negative (the decision is client input, so it is parsed
    defensively — a ``NaN`` / ``Infinity`` / negative cap is ignored rather than crashing or
    persisting an effectively-uncapped budget). ``is_finite()`` rejects ``NaN`` / ±``Infinity`` and
    never raises, so the ``>= 0`` comparison can never signal ``InvalidOperation`` on a ``NaN``."""
    if value is None:
        return None
    try:
        cost = Decimal(str(value))
    except (ValueError, ArithmeticError):
        return None
    return cost if cost.is_finite() and cost >= 0 else None


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
