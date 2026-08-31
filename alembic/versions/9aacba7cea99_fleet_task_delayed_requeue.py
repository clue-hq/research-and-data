"""fleet task delayed requeue

Revision ID: 9aacba7cea99
Revises: a57463ec42ea
Create Date: 2026-08-14 09:43:12.369055+00:00

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
revision: str = "9aacba7cea99"
down_revision: str | None = "a57463ec42ea"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE fleet_task ADD COLUMN available_at timestamptz NOT NULL DEFAULT now()")
    op.execute(
        "COMMENT ON COLUMN fleet_task.available_at IS "
        "'DB-clock eligibility boundary for durable delayed requeue; queued tasks are claimable "
        "only at or after this timestamp.'"
    )
    op.execute("DROP INDEX fleet_task_claim_next")
    op.execute(
        "CREATE INDEX fleet_task_claim_next "
        "ON fleet_task (kind, priority, enqueue_seq) INCLUDE (available_at) "
        "WHERE status IN ('queued', 'claimed')"
    )


def downgrade() -> None:
    op.execute("DROP INDEX fleet_task_claim_next")
    op.execute(
        "CREATE INDEX fleet_task_claim_next "
        "ON fleet_task (kind, priority, enqueue_seq) "
        "WHERE status IN ('queued', 'claimed')"
    )
    op.execute("ALTER TABLE fleet_task DROP COLUMN available_at")
