"""crm write fleet kind

Revision ID: a3b587b8fdfd
Revises: ebf28e41a6a4
Create Date: 2026-10-21

The fleet_task_kind enum gains ``crm_write`` (CRM integration Phase 2): one background task sends a
proposal's covered writes to the CRM, in order, and reads each one back. ADD VALUE appends, which
is what the in-order parity test wants.

Reversibility follows the ``fd8795c4fd5a`` precedent: PostgreSQL cannot drop an enum label, so
``downgrade()`` refuses while any ``crm_write`` task exists and otherwise rebuilds the type without
the label (rename → CREATE → ALTER COLUMN … USING → DROP).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "a3b587b8fdfd"
down_revision: str | None = "ebf28e41a6a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The label set BEFORE this migration — what ``downgrade()`` restores. Mirrors
#: ``clue_fleet.enums.FleetTaskKind`` minus ``CRM_WRITE``.
_KINDS_BEFORE = (
    "drive_run",
    "account_job",
    "execute_graph",
    "entity_research_job",
    "agent_turn",
    "stage0_recon",
    "official_site_crawl",
    "design_job",
    "onboarding_run",
    "arv2_account_research",
    "arv2_discovery",
    "arv2_display_page",
    "product_page_write",
)


def upgrade() -> None:
    op.execute("ALTER TYPE fleet_task_kind ADD VALUE IF NOT EXISTS 'crm_write'")


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM fleet_task WHERE kind::text = 'crm_write') THEN
                RAISE EXCEPTION 'cannot downgrade while crm_write fleet tasks exist';
            END IF;
        END $$
        """
    )
    labels = ", ".join(f"'{k}'" for k in _KINDS_BEFORE)
    op.execute("ALTER TYPE fleet_task_kind RENAME TO fleet_task_kind_crm_write")
    op.execute(f"CREATE TYPE fleet_task_kind AS ENUM ({labels})")
    op.execute(
        "ALTER TABLE fleet_task ALTER COLUMN kind TYPE fleet_task_kind "
        "USING kind::text::fleet_task_kind"
    )
    op.execute("DROP TYPE fleet_task_kind_crm_write")
