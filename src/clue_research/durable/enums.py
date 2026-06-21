"""Durable-execution lifecycle enums — table-column taxonomies internal to ``durable`` (M7).

These are deliberately **not** in ``core.enums`` (Beat-0 freeze): unlike the cross-milestone
``CampaignPhase`` / ``PhaseStatus`` / ``WorkerStatus`` (which every phase package exchanges and so
must live in ``core``), these are *internal lifecycle states* of the M7 tables that no other
milestone references. Keeping them here keeps ``core`` minimal and the durable layer self-contained.

Each enum is mirrored by a Postgres ``ENUM`` type created in the M7 migrations; a per-enum parity
test in ``tests/durable/`` asserts the Python members and the DB labels stay in lock-step (the same
``StrEnum`` discipline the rest of the subsystem uses — ``core.enums``).
"""

from __future__ import annotations

from enum import StrEnum


class AccountRunStatus(StrEnum):
    """Lifecycle of one per-account research run (``account_run.status``; M7.1).

    Full lifecycle: ``PENDING`` (row staged, not yet planned) → ``PLANNING`` (lead computing the
    plan) → ``RUNNING`` (aspect workers fanning out) → ``DONE``. M7.1's ``begin()`` creates *and*
    plans an account run in **one transaction**, so a run started by the graph is ``RUNNING`` from
    its first commit; ``PENDING``/``PLANNING`` are the resting states a *staged* lifecycle exposes
    (e.g. the M7.3 campaign scheduler pre-creating ``PENDING`` rows for every account it will deep
    research), which is why all seven values exist in the DB enum and mirror the §M7.1 schema.
    ``PAUSED`` is a durable suspension (the outer state machine paused the campaign); ``FAILED`` is
    an error; ``BUDGET_EXCEEDED`` is the *governed* cost-cap stop (M7.5) — a correct outcome, not a
    crash (mirrors ``WorkerStatus`` semantics).
    """

    PENDING = "pending"
    PLANNING = "planning"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    FAILED = "failed"
    BUDGET_EXCEEDED = "budget_exceeded"


class CampaignRunStatus(StrEnum):
    """Lifecycle of one campaign run (``campaign_run.status``; M7.3).

    The *outer* state machine's run-level status, distinct from the per-phase
    :class:`PhaseCheckpointStatus` and the inner :class:`AccountRunStatus`:

    * ``ACTIVE`` — the run is advancing through its phases (the normal driving state).
    * ``PAUSED`` — a durable suspension: either a client ``pause`` (a cooperative stop the driver
      honours at the next phase boundary) or a phase that returned ``PAUSED`` (the human
      ``TIER_CHECKPOINT`` gate, or a budget graceful-stop). Resumable without re-spending committed
      work.
    * ``COMPLETED`` — the terminal ``HANDOFF`` phase committed; the run is done.
    * ``FAILED`` — a phase handler returned ``FAILED``; the run stopped at that phase.
    """

    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class PhaseCheckpointStatus(StrEnum):
    """Lifecycle of one ``campaign_phase_checkpoint`` row (M7.3) — the durable record of a single
    phase of a single run.

    * ``IN_PROGRESS`` — the phase handler is running (the row is staged before the handler is
      invoked, so a crash *during* the phase leaves a resumable marker, not a silent gap).
    * ``AWAITING_INPUT`` — the phase returned ``PAUSED`` and the run is suspended at this checkpoint
      waiting for a client action (the M6.4 tier-checkpoint ``awaiting`` state, or a budget
      graceful-stop). ``payload_json`` holds the review payload the surface (M13) reads back.
    * ``COMMITTED`` — the phase completed; ``payload_json`` is its committed
      :class:`~clue_research.core.PhaseResult` payload and re-entry short-circuits (idempotency).
    * ``FAILED`` — the phase handler failed; the run is ``FAILED`` at this phase.
    """

    IN_PROGRESS = "in_progress"
    AWAITING_INPUT = "awaiting_input"
    COMMITTED = "committed"
    FAILED = "failed"
