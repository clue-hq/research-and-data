"""d4 identity review lineage

Revision ID: 413e800f79b5
Revises: fe7d6c0aee8a
Create Date: 2026-08-02 23:21:29.529197+00:00

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
revision: str = "413e800f79b5"
down_revision: str | None = "fe7d6c0aee8a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE discovery_wake_outbox DROP CONSTRAINT discovery_wake_outbox_reason")
    op.execute(
        "ALTER TABLE discovery_wake_outbox ADD CONSTRAINT discovery_wake_outbox_reason "
        "CHECK (reason IN ('scheduled_poll', 'provider_event', 'manual_reconcile', "
        "'crash_recovery', 'field_materialization'))"
    )
    # PostgreSQL cannot remove an enum label on downgrade. Rebuild the type in both directions so
    # this migration remains genuinely reversible rather than relying on ALTER TYPE ADD VALUE.
    op.execute(
        "ALTER TABLE discovery_candidate_link DROP CONSTRAINT discovery_candidate_link_shape"
    )
    op.execute("ALTER TABLE discovery_candidate_link ALTER COLUMN admission_status DROP DEFAULT")
    op.execute(
        "ALTER TYPE discovery_candidate_admission_state "
        "RENAME TO discovery_candidate_admission_state_pre_d4"
    )
    op.execute(
        "CREATE TYPE discovery_candidate_admission_state AS ENUM "
        "('pending', 'review_required', 'admitted', 'merged', 'excluded')"
    )
    op.execute(
        "ALTER TABLE discovery_candidate_link ALTER COLUMN admission_status TYPE "
        "discovery_candidate_admission_state USING "
        "admission_status::text::discovery_candidate_admission_state"
    )
    op.execute("DROP TYPE discovery_candidate_admission_state_pre_d4")
    op.execute(
        "ALTER TABLE discovery_candidate_link ALTER COLUMN admission_status SET DEFAULT 'pending'"
    )
    op.execute(
        "ALTER TABLE identity_review_task ADD CONSTRAINT "
        "identity_review_task_workspace_anchor UNIQUE (id, workspace_id)"
    )
    op.execute("ALTER TABLE discovery_candidate_link ADD COLUMN review_task_id uuid")
    op.execute(
        "ALTER TABLE discovery_candidate_link ADD CONSTRAINT "
        "discovery_candidate_review_task_workspace_fk "
        "FOREIGN KEY (review_task_id, workspace_id) "
        "REFERENCES identity_review_task(id, workspace_id)"
    )
    op.execute(
        """
        ALTER TABLE discovery_candidate_link
        ADD CONSTRAINT discovery_candidate_link_shape CHECK (
            (admission_status = 'pending' AND account_entity_id IS NULL
                AND survivor_entity_id IS NULL AND disposition_reason IS NULL
                AND review_task_id IS NULL)
            OR (admission_status = 'review_required' AND account_entity_id IS NULL
                AND survivor_entity_id IS NULL AND disposition_reason IS NULL
                AND review_task_id IS NOT NULL)
            OR (admission_status = 'admitted' AND account_entity_id IS NOT NULL
                AND survivor_entity_id = account_entity_id AND disposition_reason IS NULL
                )
            OR (admission_status = 'merged' AND account_entity_id IS NOT NULL
                AND survivor_entity_id IS NOT NULL
                AND survivor_entity_id <> account_entity_id
                AND disposition_reason IS NOT NULL)
            OR (admission_status = 'excluded' AND account_entity_id IS NULL
                AND survivor_entity_id IS NULL AND disposition_reason IS NOT NULL
                )
        )
        """
    )
    op.execute(
        "CREATE INDEX discovery_candidate_review_task ON discovery_candidate_link "
        "(review_task_id) WHERE review_task_id IS NOT NULL"
    )


def downgrade() -> None:
    # The old schema has no durable review state. Preserve its only safe blocking equivalent:
    # review-required rows return to anonymous pending rows rather than being admitted/excluded.
    op.execute(
        "UPDATE discovery_candidate_link SET admission_status = 'pending', review_task_id = NULL "
        "WHERE admission_status = 'review_required'"
    )
    op.execute("ALTER TABLE discovery_wake_outbox DROP CONSTRAINT discovery_wake_outbox_reason")
    op.execute(
        "UPDATE discovery_wake_outbox SET reason = 'manual_reconcile' "
        "WHERE reason = 'field_materialization'"
    )
    op.execute(
        "ALTER TABLE discovery_wake_outbox ADD CONSTRAINT discovery_wake_outbox_reason "
        "CHECK (reason IN ('scheduled_poll', 'provider_event', 'manual_reconcile', "
        "'crash_recovery'))"
    )
    op.execute("DROP INDEX IF EXISTS discovery_candidate_review_task")
    op.execute(
        "ALTER TABLE discovery_candidate_link DROP CONSTRAINT discovery_candidate_link_shape"
    )
    op.execute(
        "ALTER TABLE discovery_candidate_link "
        "DROP CONSTRAINT discovery_candidate_review_task_workspace_fk"
    )
    op.execute("ALTER TABLE discovery_candidate_link DROP COLUMN review_task_id")
    op.execute(
        "ALTER TABLE identity_review_task DROP CONSTRAINT identity_review_task_workspace_anchor"
    )
    op.execute("ALTER TABLE discovery_candidate_link ALTER COLUMN admission_status DROP DEFAULT")
    op.execute(
        "ALTER TYPE discovery_candidate_admission_state "
        "RENAME TO discovery_candidate_admission_state_d4"
    )
    op.execute(
        "CREATE TYPE discovery_candidate_admission_state AS ENUM "
        "('pending', 'admitted', 'merged', 'excluded')"
    )
    op.execute(
        "ALTER TABLE discovery_candidate_link ALTER COLUMN admission_status TYPE "
        "discovery_candidate_admission_state USING "
        "admission_status::text::discovery_candidate_admission_state"
    )
    op.execute("DROP TYPE discovery_candidate_admission_state_d4")
    op.execute(
        "ALTER TABLE discovery_candidate_link ALTER COLUMN admission_status SET DEFAULT 'pending'"
    )
    op.execute(
        """
        ALTER TABLE discovery_candidate_link
        ADD CONSTRAINT discovery_candidate_link_shape CHECK (
            (admission_status = 'pending' AND account_entity_id IS NULL
                AND survivor_entity_id IS NULL AND disposition_reason IS NULL)
            OR (admission_status = 'admitted' AND account_entity_id IS NOT NULL
                AND survivor_entity_id = account_entity_id AND disposition_reason IS NULL)
            OR (admission_status = 'merged' AND account_entity_id IS NOT NULL
                AND survivor_entity_id IS NOT NULL
                AND survivor_entity_id <> account_entity_id
                AND disposition_reason IS NOT NULL)
            OR (admission_status = 'excluded' AND account_entity_id IS NULL
                AND survivor_entity_id IS NULL AND disposition_reason IS NOT NULL)
        )
        """
    )
