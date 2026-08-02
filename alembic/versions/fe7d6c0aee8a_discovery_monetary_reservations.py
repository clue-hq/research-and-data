"""discovery monetary reservations

Revision ID: fe7d6c0aee8a
Revises: 283ab57486e8
Create Date: 2026-08-02 22:46:06.994919+00:00

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
revision: str = "fe7d6c0aee8a"
down_revision: str | None = "283ab57486e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE discovery_batch ADD COLUMN cost_cents_reserved numeric NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE discovery_operation ADD COLUMN cost_cents_reserved numeric NOT NULL DEFAULT 0"
    )
    op.execute("ALTER TABLE discovery_batch DROP CONSTRAINT discovery_batch_cost_nonnegative")
    op.execute(
        "ALTER TABLE discovery_batch ADD CONSTRAINT discovery_batch_cost_nonnegative "
        "CHECK (cost_cents_reserved >= 0 AND cost_cents_charged >= 0)"
    )
    op.execute(
        "ALTER TABLE discovery_operation DROP CONSTRAINT discovery_operation_cost_nonnegative"
    )
    op.execute(
        "ALTER TABLE discovery_operation ADD CONSTRAINT discovery_operation_cost_nonnegative "
        "CHECK (cost_cents_reserved >= 0 AND cost_cents_charged >= 0)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE discovery_operation DROP CONSTRAINT discovery_operation_cost_nonnegative"
    )
    op.execute(
        "ALTER TABLE discovery_operation ADD CONSTRAINT discovery_operation_cost_nonnegative "
        "CHECK (cost_cents_charged >= 0)"
    )
    op.execute("ALTER TABLE discovery_batch DROP CONSTRAINT discovery_batch_cost_nonnegative")
    op.execute(
        "ALTER TABLE discovery_batch ADD CONSTRAINT discovery_batch_cost_nonnegative "
        "CHECK (cost_cents_charged >= 0)"
    )
    op.execute("ALTER TABLE discovery_operation DROP COLUMN cost_cents_reserved")
    op.execute("ALTER TABLE discovery_batch DROP COLUMN cost_cents_reserved")
