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


class AccountRunSubPhase(StrEnum):
    """Last-completed deep-orchestration boundary of one ``account_run`` (``account_run.sub_phase``;
    M8A.0).

    Orthogonal to :class:`AccountRunStatus`: ``status`` is the run's *coarse* lifecycle (pending →
    running → done/failed), while ``sub_phase`` records *which of the three deep stages* of the
    per-account ``account → committee → contact`` sequence (M8A.1) is done, so a crashed run can
    resume at its last boundary instead of re-discovering the committee or re-profiling the
    account. ``NULL`` (no member) = not started; it then advances **monotonically**:

    * ``ACCOUNT_PROFILED`` — stage 1 done: ``profile_account`` (M8.1/M8.2) wrote the deep account
      picture; the committee has not been discovered yet.
    * ``COMMITTEE_DISCOVERED`` — stage 2 done: ``discover_committee`` (M8.3) admitted the buying
      committee; the per-contact fan-out has not started.
    * ``CONTACTS_COMPLETE`` — stage 3 done: every admitted member was profiled (M8.4) — the account
      is M12-ready.

    The marker is **advisory** (a resume optimization): the M7.4 idempotency ledger remains
    authoritative for spend, and the claim-store gap-recompute is the correctness backstop, so a
    stale marker can only cause an idempotent re-run, never double-spend (Doc C; substrate §5).

    Durable-internal lifecycle enum (Beat-0: M7 owns it; NOT in ``core.enums``, like
    :class:`AccountRunStatus`). Mirrored by the ``account_run_sub_phase`` Postgres ``ENUM``; the
    parity test in ``tests/durable/`` asserts the Python members and DB labels stay aligned.
    """

    ACCOUNT_PROFILED = "account_profiled"
    COMMITTEE_DISCOVERED = "committee_discovered"
    CONTACTS_COMPLETE = "contacts_complete"


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


class IdempotencyStatus(StrEnum):
    """Lifecycle of one ``idempotency_ledger`` row (M7.4) — the exactly-once state of a keyed unit
    of work (a per-account research step, or a campaign phase).

    * ``IN_PROGRESS`` — a holder has claimed the key and is executing (staged before the effectful
      body runs, so a crash mid-step leaves a resumable marker, not a silent gap). A claim found
      ``in_progress`` and *not* stale is a live duplicate (skip/join); one older than the staleness
      window is presumed crashed and is re-owned (the stale-recovery path).
    * ``SUCCEEDED`` — the step completed; ``result_ref`` is the recorded output (claim ids / phase
      payload ref) and ``cost_cents_charged`` is what it spent. A subsequent claim of the same key
      short-circuits and returns the recorded result without re-spending (the idempotency property).
    * ``FAILED`` — the step raised; the key is released so a retry (same key) re-executes. Distinct
      from a *governed* budget stop, which a caller records as ``SUCCEEDED`` with a zero-cost
      ``result_ref`` (a correct outcome, not a re-executable failure).
    """

    IN_PROGRESS = "in_progress"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class BudgetEventKind(StrEnum):
    """Kind of one ``budget_event`` row (M7.5) — the append-only governance audit of the
    cost-governance engine's spend decisions (Doc C §5; the ``budget_event`` table).

    A budget *event* records a governance action, never a charge (charges live on the M7.4 ledger's
    ``cost_cents_charged`` + the ``spent_cents`` counters, counted once):

    * ``CHECK_DENY`` — a pre-spend :meth:`check` denied a within-cap-depth resolver call / facet
      spawn because the per-account (or per-pass) cap would be exceeded (the M7.2 spawn-denial). A
      *governed* stop, not an error: the run continues with the aspect marked partial.
    * ``GRACEFUL_STOP`` — a per-run :meth:`check` found the campaign hard cap reached: the run is
      brought to a graceful stop at the next checkpoint (via M7.3), never hard-killed mid-step.
    * ``BREACH_PENDING`` — :meth:`set_campaign_cap` set a cap *below* current spend (the run is now
      over budget): the client must raise the cap or tighten cutoffs before it can resume.
    * ``CAP_RAISED`` — the per-campaign hard cap was (re)set (any direction; the single
      cap-change event kind). Paired with ``BREACH_PENDING`` when the new cap is below spend.
    """

    CHECK_DENY = "check_deny"
    GRACEFUL_STOP = "graceful_stop"
    BREACH_PENDING = "breach_pending"
    CAP_RAISED = "cap_raised"
