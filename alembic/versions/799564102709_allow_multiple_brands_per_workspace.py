"""allow multiple brands per workspace

Revision ID: 799564102709
Revises: 82a80fb80c9e
Create Date: 2026-07-24 08:07:11.051327+00:00

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
revision: str = "799564102709"
down_revision: str | None = "82a80fb80c9e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Brand kits are workspace-owned, but a workspace may own many of them. The existing
    # ``brand_workspace_anchor`` remains in place so product/project composite FKs still make
    # cross-workspace brand selection structurally impossible.
    op.drop_constraint("brand_one_per_workspace", "brand", type_="unique")


def downgrade() -> None:
    # The old shape cannot represent multiple brands. Refuse a lossy downgrade instead of
    # guessing which brand (and dependent products/projects) should survive.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM brand
                GROUP BY workspace_id
                HAVING count(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'cannot restore brand_one_per_workspace while a workspace owns multiple brands';
            END IF;
        END
        $$;
        """
    )
    op.create_unique_constraint("brand_one_per_workspace", "brand", ["workspace_id"])
