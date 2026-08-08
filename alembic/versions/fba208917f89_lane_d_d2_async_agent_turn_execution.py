"""lane D D2 async agent turn execution

Revision ID: fba208917f89
Revises: c4ccc7b11810
Create Date: 2026-08-08 13:12:50.188754+00:00

FI Lane D slice **D2** (`docs/specs/FI-lane-D-D2-implementation-brief.md`; charter §3-P3, ratified
§6-D1 *async worker-executed turns*). Two things land here, and nothing else:

1. **``fleet_task_kind`` grows ``agent_turn``** — the queue kind for one human-submitted platform
   deepagent turn. The queue table itself is untouched: ``work_id`` carries the *thread* (so the
   existing driver lease is a per-thread single-flight fence) and ``dedup_key`` carries
   ``agent-turn:<turn_id>``, both of which the PB-B1 schema already supports.

2. **``agent_turn_submission``** — the durable record of *"this human submitted this turn"*, written
   by the HTTP route **before** it enqueues anything, and read back by the worker as the authority
   for who is acting.

   Why a row rather than a task payload: Lane B's contract (§7) lets the queue carry internal ids,
   but the identity that ends up in ``constitution.actor_id`` and in
   ``agent_turn.submitted_by_user_id`` must come from a durable row, never from a message a worker
   was handed. Why a *new* row rather than ``agent_turn`` itself: an ``agent_turn`` row cannot exist
   before its execution does (``agent_turn.execution_id`` references ``execution``) and its
   constitution pins a resolved profile, a resource-manifest artifact, a project card and a budget
   envelope — i.e. the whole agent plane, including the model provider that the very same slice
   forbids the HTTP process from composing. So the submission is the pre-execution half of a turn's
   identity and the ``agent_turn`` row is the execution half; the worker joins them on ``turn_id``,
   which is derived deterministically from the submission's idempotency identity.

   The row is **immutable** (the shared agent-plane append-only trigger): a submission is a receipt,
   and "queued / executing / done" is *derived* from the fleet task and the finalization commit
   rather than stored as a mutable status — the same append-only doctrine the 13 C6 tables follow
   and the shape §3-P5(a) ratifies for gates.

Conventions every migration must honour (docs/specs/M00-foundations-and-shared-contracts.md §M0.3;
see src/clue_research/db/README.md "Migration conventions checklist"):
- Append-only: claim history supersedes via ``superseded_by``; never UPDATE a value column in place.
- UTC ``timestamptz`` for time columns (e.g. ``observed_at`` / ``collected_at``).
- JSONB ``value_json`` payloads, with real indexed columns on the hot query keys (``entity_id`` …).
- Everything keys on a resolved ``entity_id`` — never a free-text name.
- Forward + reverse: ``downgrade()`` must cleanly reverse ``upgrade()`` (CI runs up → down → up).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fba208917f89"
down_revision: str | None = "c4ccc7b11810"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ``ADD VALUE`` appends, which is what keeps the Python ``FleetTaskKind`` and the DB labels in
    # the *same order* for the parity test. Safe inside the migration transaction because nothing
    # here writes the new value (PG's only restriction).
    op.execute("ALTER TYPE fleet_task_kind ADD VALUE IF NOT EXISTS 'agent_turn'")

    op.execute(
        """
        CREATE TABLE agent_turn_submission (
            turn_id                     uuid PRIMARY KEY,
            workspace_id                text NOT NULL,
            project_id                  text NOT NULL,
            thread_id                   text NOT NULL,
            submitted_by_user_id        text NOT NULL,
            submitted_via_membership_id text NOT NULL,
            onboarding_input_id         uuid NOT NULL,
            message_artifact_key        text NOT NULL,
            message_sha256              text NOT NULL,
            idempotency_key             text,
            requested_at                timestamptz NOT NULL DEFAULT now(),

            -- The thread anchor pins the submission to a thread *in its own workspace*; the
            -- project anchor does the same for the project. Both are the composite-FK pattern
            -- agent_thread/agent_turn already use.
            CONSTRAINT agent_turn_submission_thread_fk
                FOREIGN KEY (thread_id, workspace_id)
                REFERENCES agent_thread (id, workspace_id),
            CONSTRAINT agent_turn_submission_project_fk
                FOREIGN KEY (project_id, workspace_id)
                REFERENCES project (project_id, workspace_id),
            -- Clue-owned internal identity only (contract §§1.2-1.3). NOT NULL here, unlike the
            -- nullable agent_turn columns: a *submission* is by definition a human act, and a
            -- machine-originated turn never passes through this table at all.
            CONSTRAINT agent_turn_submission_user_fk
                FOREIGN KEY (submitted_by_user_id)
                REFERENCES platform_user (user_id),
            CONSTRAINT agent_turn_submission_membership_fk
                FOREIGN KEY (submitted_via_membership_id, workspace_id)
                REFERENCES workspace_membership (membership_id, workspace_id),
            -- The captured human message: the turn cannot be enqueued unless its bytes were
            -- captured first (capture-before-spend), and D1's turn-action resolver re-derives this
            -- same join to prove the receipt.
            CONSTRAINT agent_turn_submission_capture_fk
                FOREIGN KEY (onboarding_input_id)
                REFERENCES onboarding_input (id),
            CONSTRAINT agent_turn_submission_identity_nonempty CHECK (
                length(btrim(workspace_id)) > 0
                AND length(btrim(project_id)) > 0
                AND length(btrim(thread_id)) > 0
                AND length(btrim(submitted_by_user_id)) > 0
                AND length(btrim(submitted_via_membership_id)) > 0
                AND length(btrim(message_artifact_key)) > 0
                AND length(btrim(message_sha256)) > 0
            ),
            CONSTRAINT agent_turn_submission_idempotency_nonempty CHECK (
                idempotency_key IS NULL OR length(btrim(idempotency_key)) > 0
            )
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE agent_turn_submission IS 'FI Lane D D2: the durable, immutable record "
        "that a human submitted one platform-deepagent turn, written before the AGENT_TURN fleet "
        "task is enqueued. It is the authority for constitution.actor_id and for "
        "agent_turn.submitted_by_user_id — a worker never takes identity from a queue payload. "
        "Execution state is derived (fleet_task + agent_finalization_commit), never stored here.'"
    )
    # Submission order within one thread — the exact key the single-flight dispatcher reads
    # (``ORDER BY requested_at, turn_id``) and the ordering guarantee charter §3.5 requires.
    op.execute(
        "CREATE INDEX agent_turn_submission_thread_order "
        "ON agent_turn_submission (workspace_id, thread_id, requested_at, turn_id)"
    )
    # Immutable by trigger, like the 13 agent-plane receipt tables (migration 7e9269ed8a81).
    op.execute(
        "CREATE TRIGGER agent_turn_submission_append_only "
        "BEFORE UPDATE OR DELETE ON agent_turn_submission "
        "FOR EACH ROW EXECUTE FUNCTION execution_reject_append_only_mutation()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS agent_turn_submission_append_only ON agent_turn_submission"
    )
    op.execute("DROP INDEX IF EXISTS agent_turn_submission_thread_order")
    op.execute("DROP TABLE IF EXISTS agent_turn_submission")

    # Postgres cannot drop an enum label, so the honest reverse is to rebuild the type without it —
    # and to refuse loudly rather than silently discard work if any task still names the value.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM fleet_task WHERE kind::text = 'agent_turn') THEN
                RAISE EXCEPTION
                    'cannot downgrade Lane D D2 while agent_turn fleet tasks exist';
            END IF;
        END $$
        """
    )
    op.execute("ALTER TYPE fleet_task_kind RENAME TO fleet_task_kind_lane_d_d2")
    op.execute(
        "CREATE TYPE fleet_task_kind AS ENUM "
        "('drive_run', 'account_job', 'execute_graph', 'entity_research_job')"
    )
    op.execute(
        """
        ALTER TABLE fleet_task
        ALTER COLUMN kind TYPE fleet_task_kind
        USING kind::text::fleet_task_kind
        """
    )
    op.execute("DROP TYPE fleet_task_kind_lane_d_d2")
