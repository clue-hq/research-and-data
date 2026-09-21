"""arv2 display page fleet kind

Revision ID: fd8795c4fd5a
Revises: 5cac3234cfb3
Create Date: 2026-09-21 18:48:32.426448+00:00

The fleet_task_kind enum gains ``arv2_display_page`` (spec 2026-09-12 §2): the account overview is
written when the account job settles, contact pages on the first open of their account, stale
pages whenever a read finds them. ADD VALUE appends, which is what the in-order parity test wants.

Conventions every migration must honour (docs/specs/M00-foundations-and-shared-contracts.md §M0.3;
see src/clue_research/db/README.md "Migration conventions checklist"):
- Append-only: claim history supersedes via ``superseded_by``; never UPDATE a value column in place.
- UTC ``timestamptz`` for time columns (e.g. ``observed_at`` / ``collected_at``).
- JSONB ``value_json`` payloads, with real indexed columns on the hot query keys (``entity_id`` …).
- Everything keys on a resolved ``entity_id`` — never a free-text name.
- Forward + reverse: ``downgrade()`` must cleanly reverse ``upgrade()`` (CI runs up → down → up).

Reversibility follows the ``2cd622be2da0`` precedent exactly: PostgreSQL cannot drop an enum
label, so ``downgrade()`` refuses while any ``arv2_display_page`` task exists and otherwise
rebuilds the type without the label (rename → CREATE → ALTER COLUMN … USING → DROP).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fd8795c4fd5a"
down_revision: str | None = "5cac3234cfb3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The label set BEFORE this migration — what ``downgrade()`` restores. Mirrors
#: ``clue_fleet.enums.FleetTaskKind`` minus ``ARV2_DISPLAY_PAGE``.
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
)


def upgrade() -> None:
    # ADD VALUE is safe inside alembic's transaction because nothing here USES the label (the
    # 2cd622be2da0 precedent).
    op.execute("ALTER TYPE fleet_task_kind ADD VALUE IF NOT EXISTS 'arv2_display_page'")


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM fleet_task WHERE kind::text = 'arv2_display_page') THEN
                RAISE EXCEPTION 'cannot downgrade while arv2_display_page fleet tasks exist';
            END IF;
        END $$
        """
    )
    labels = ", ".join(f"'{k}'" for k in _KINDS_BEFORE)
    op.execute("ALTER TYPE fleet_task_kind RENAME TO fleet_task_kind_display")
    op.execute(f"CREATE TYPE fleet_task_kind AS ENUM ({labels})")
    op.execute(
        "ALTER TABLE fleet_task ALTER COLUMN kind TYPE fleet_task_kind "
        "USING kind::text::fleet_task_kind"
    )
    op.execute("DROP TYPE fleet_task_kind_display")
