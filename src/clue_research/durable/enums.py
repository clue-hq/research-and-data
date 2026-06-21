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
