"""fleet worker tables (PB-B1)

Revision ID: 10642c862e43
Revises: 98422adaaa38
Create Date: 2026-07-21

The fleet plane's two tables (harness build step 0 — ``docs/specs/PB-B1-fleet-worker.md``):

* ``run_lease`` — the per-run **driver lease**: at most one worker drives a campaign run at a
  time. One row per driven run; acquire atomically re-owns an expired row (``ON CONFLICT … WHERE
  expires_at <= now()``); renew/release are holder-guarded. Enforces the single-driver-per-run
  precondition M7.3 documents ("left to the scheduler/ops layer") — this is that layer.
* ``fleet_task`` — the durable **task queue** the detached ``ProjectRunWorker`` drains:
  ``drive_run`` jobs (drive one campaign run until it rests) and ``account_job`` rows (the
  REQ-10 tier-priority deep queue — ``priority`` = tier rank, claimed best-first under the
  concurrency window). ``UNIQUE (kind, project_run_id, dedup_key)`` makes enqueue idempotent;
  claim-next is ``FOR UPDATE SKIP LOCKED`` over the partial claim index. The deep drain narrows the
  claim by ``project_run_id`` and orders by ``(priority, enqueue_seq)``, so ``fleet_task_run``
  carries the claim order after the run key (``(project_run_id, kind, priority, enqueue_seq)``) —
  otherwise a run's per-claim cost would scale with other runs' backlog.

Soft FK to campaign_run (renames to project_run at the stage-2 rename — see
docs/specs/PB-rename-campaign-run-to-project-run.md), no ``REFERENCES`` (mirroring
``claim``/``account_run``): ``project_run_id`` rides as an opaque uuid so the fleet plane stays
subsystem-agnostic and this migration is order-independent of the research tables. Both tables
are *mutable* execution state (a lease renews; a task's status advances) — like ``account_run``,
deliberately not append-only: the claim store keeps immutable history; these are resumable
cursors over work.

Enums: ``fleet_task_kind`` / ``fleet_task_status`` mirror the **package-local**
:mod:`clue_fleet.enums` (the ``durable/enums.py`` precedent — no other package references them,
so they stay out of ``core.enums`` per the Phase B treaty §3.3). Parity tests in
``tests/fleet/`` assert Python members and DB labels stay in lock-step.

Conventions every migration must honour (docs/specs/M00-foundations-and-shared-contracts.md §M0.3):
- UTC ``timestamptz`` for time columns; JSONB payloads carry references only, never blobs.
- Named constraints/indexes; forward + reverse: ``downgrade()`` cleanly reverses ``upgrade()``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "10642c862e43"
down_revision: str | None = "98422adaaa38"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirror clue_fleet.enums (package-local lifecycle enums; parity-tested in tests/fleet/).
_FLEET_TASK_KIND = ("drive_run", "account_job")
_FLEET_TASK_STATUS = ("queued", "claimed", "done", "failed")


def _enum_values_sql(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute(f"CREATE TYPE fleet_task_kind AS ENUM ({_enum_values_sql(_FLEET_TASK_KIND)})")
    op.execute(f"CREATE TYPE fleet_task_status AS ENUM ({_enum_values_sql(_FLEET_TASK_STATUS)})")

    # --- run_lease: the per-run driver lease -------------------------------------------------
    op.execute(
        """
        CREATE TABLE run_lease (
            project_run_id  uuid NOT NULL,
            worker_id       text NOT NULL,
            acquired_at     timestamptz NOT NULL DEFAULT now(),
            renewed_at      timestamptz NOT NULL DEFAULT now(),
            expires_at      timestamptz NOT NULL,

            CONSTRAINT run_lease_pkey PRIMARY KEY (project_run_id)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE run_lease IS 'Per-run driver lease (PB-B1): at most one worker drives "
        "a campaign run at a time; held while expires_at > now(). Acquire re-owns only an "
        "expired row; renew/release are holder-guarded (worker_id). Enforces M7.3''s "
        "single-driver precondition.'"
    )

    # --- fleet_task: the durable task queue --------------------------------------------------
    op.execute(
        """
        CREATE TABLE fleet_task (
            task_id         uuid NOT NULL,
            kind            fleet_task_kind NOT NULL,
            project_run_id  uuid NOT NULL,
            dedup_key       text NOT NULL,
            priority        integer NOT NULL DEFAULT 0,
            status          fleet_task_status NOT NULL DEFAULT 'queued',
            attempts        integer NOT NULL DEFAULT 0,
            payload_json    jsonb NOT NULL DEFAULT '{}'::jsonb,
            result_ref_json jsonb NOT NULL DEFAULT '{}'::jsonb,
            claimed_by      text,
            claimed_at      timestamptz,
            enqueued_at     timestamptz NOT NULL DEFAULT now(),
            -- The total FIFO order key. now() is transaction-stable, so same-priority rows
            -- enqueued in one transaction share an enqueued_at and tie with no final key; a
            -- monotonic insertion sequence breaks the tie deterministically. GENERATED ALWAYS
            -- AS IDENTITY does not re-mint on UPDATE, so a reopen_terminal re-drive keeps its
            -- original place ahead of newer work (intended).
            enqueue_seq     bigint GENERATED ALWAYS AS IDENTITY,
            updated_at      timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT fleet_task_pkey PRIMARY KEY (task_id),
            -- Idempotent enqueue: one logical task per (kind, run, unit-of-work).
            CONSTRAINT fleet_task_dedup UNIQUE (kind, project_run_id, dedup_key),
            CONSTRAINT fleet_task_attempts_nonneg CHECK (attempts >= 0),
            CONSTRAINT fleet_task_payload_is_object CHECK (jsonb_typeof(payload_json) = 'object'),
            CONSTRAINT fleet_task_result_is_object
                CHECK (jsonb_typeof(result_ref_json) = 'object'),
            -- A claimed task always records who/when; queued rows carry neither.
            CONSTRAINT fleet_task_claim_stamped
                CHECK (status <> 'claimed' OR (claimed_by IS NOT NULL AND claimed_at IS NOT NULL)),
            CONSTRAINT fleet_task_queued_unstamped
                CHECK (status <> 'queued' OR (claimed_by IS NULL AND claimed_at IS NULL))
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE fleet_task IS 'Durable fleet task queue (PB-B1): drive_run jobs the "
        "detached ProjectRunWorker drains and account_job rows forming the REQ-10 tier-priority "
        "deep queue. Claim-next = FOR UPDATE SKIP LOCKED in (priority, enqueue_seq) order; a "
        "stale claim (killed holder) is re-owned; payload/result carry references only.'"
    )
    # The claim-next hot path: runnable rows of one kind in claim order. Ordered by the monotonic
    # enqueue_seq (not enqueued_at) so same-priority rows have a total FIFO order — timestamps
    # alone cannot: now() is transaction-stable. Partial — done/failed rows leave the index as
    # they leave the drain.
    op.execute(
        """
        CREATE INDEX fleet_task_claim_next
            ON fleet_task (kind, priority, enqueue_seq)
            WHERE status IN ('queued', 'claimed')
        """
    )
    # The per-run observability/drain read. The deep drain claims with
    # ``project_run_id = :x ... ORDER BY priority, enqueue_seq LIMIT 1``, so the run key must be
    # followed by the claim order — otherwise per-claim cost scales with *other* runs' backlog (the
    # only ordered index, ``fleet_task_claim_next``, has no run key). The ``(project_run_id, kind)``
    # prefix still serves the projection read that only filters on run+kind.
    op.execute(
        "CREATE INDEX fleet_task_run ON fleet_task (project_run_id, kind, priority, enqueue_seq)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX fleet_task_run")
    op.execute("DROP INDEX fleet_task_claim_next")
    op.execute("DROP TABLE fleet_task")
    op.execute("DROP TABLE run_lease")
    op.execute("DROP TYPE fleet_task_status")
    op.execute("DROP TYPE fleet_task_kind")
