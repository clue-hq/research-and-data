"""committee snapshot provider uniqueness only for assigned operations

Revision ID: 0296c177772f
Revises: ab295072ba84
Create Date: 2026-08-19 17:31:00.252854+00:00

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
revision: str = "0296c177772f"
down_revision: str | None = "ab295072ba84"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Scope provider-operation uniqueness to assigned operations only.

    ``UNIQUE NULLS NOT DISTINCT (source_key, provider_operation_id)`` allowed exactly one
    NULL-operation snapshot per source key across the whole database, forever: a terminally
    failed pre-dispatch snapshot (live: the 2026-08-19 Sumble People 402, failed_terminal /
    not_charged) occupies the slot and every later pre-dispatch snapshot for that source —
    any workspace, any account — violates the constraint. The dedup this constraint exists
    for is one snapshot per *assigned* provider operation, so it becomes a partial unique
    index over the non-null rows.
    """

    op.execute(
        "ALTER TABLE committee_acquisition_snapshot "
        "DROP CONSTRAINT committee_acquisition_snapshot_provider_unique"
    )
    op.execute(
        "CREATE UNIQUE INDEX committee_acquisition_snapshot_provider_unique "
        "ON committee_acquisition_snapshot (source_key, provider_operation_id) "
        "WHERE provider_operation_id IS NOT NULL"
    )


def downgrade() -> None:
    # Recreating the NULLS NOT DISTINCT constraint fails if more than one NULL-operation
    # snapshot per source key exists (the state the upgrade exists to permit); that loud
    # failure is correct rather than silently deleting rows.
    op.execute("DROP INDEX committee_acquisition_snapshot_provider_unique")
    op.execute(
        "ALTER TABLE committee_acquisition_snapshot "
        "ADD CONSTRAINT committee_acquisition_snapshot_provider_unique "
        "UNIQUE NULLS NOT DISTINCT (source_key, provider_operation_id)"
    )
