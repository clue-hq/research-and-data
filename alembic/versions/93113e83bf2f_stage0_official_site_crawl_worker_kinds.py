"""stage0 official site crawl worker kinds

Revision ID: 93113e83bf2f
Revises: 6e7ba5968751
Create Date: 2026-08-14 02:34:22.931828+00:00

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
revision: str = "93113e83bf2f"
down_revision: str | None = "6e7ba5968751"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Appends preserve the enum ordering mirrored by ``FleetTaskKind``. Neither kind authorizes
    # provider spend by itself; settings-gated API/fleet composition controls origination.
    op.execute("ALTER TYPE fleet_task_kind ADD VALUE IF NOT EXISTS 'stage0_recon'")
    op.execute("ALTER TYPE fleet_task_kind ADD VALUE IF NOT EXISTS 'official_site_crawl'")


def downgrade() -> None:
    # PostgreSQL cannot remove enum labels. Refuse if retained work still uses either C6 kind,
    # then rebuild the pre-C6 type exactly and preserve every existing task row.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM fleet_task
                WHERE kind::text IN ('stage0_recon', 'official_site_crawl')
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade C6 while Stage-0 recon/crawl fleet tasks exist';
            END IF;
        END $$
        """
    )
    op.execute("ALTER TYPE fleet_task_kind RENAME TO fleet_task_kind_stage0_c6")
    op.execute(
        "CREATE TYPE fleet_task_kind AS ENUM "
        "('drive_run', 'account_job', 'execute_graph', 'entity_research_job', 'agent_turn')"
    )
    op.execute(
        """
        ALTER TABLE fleet_task
        ALTER COLUMN kind TYPE fleet_task_kind
        USING kind::text::fleet_task_kind
        """
    )
    op.execute("DROP TYPE fleet_task_kind_stage0_c6")
