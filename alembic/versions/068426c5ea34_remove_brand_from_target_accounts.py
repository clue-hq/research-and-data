"""remove brand from target accounts

Revision ID: 068426c5ea34
Revises: 799564102709
Create Date: 2026-07-24 08:17:03.382427+00:00

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

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "068426c5ea34"
down_revision: str | None = "799564102709"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Target accounts are workspace-local research entities, not sender-brand resources. Brand
    # selection belongs to ``project``. Remove both the impossible ownership relationship and its
    # now-redundant shape check before dropping the column.
    op.drop_constraint("account_entity_brand_fk", "account_entity", type_="foreignkey")
    op.drop_constraint("account_entity_brand_needs_workspace", "account_entity", type_="check")
    op.drop_column("account_entity", "brand_id")


def downgrade() -> None:
    # Restore the exact transitional shape introduced by 50b778e4009a. The column was nullable
    # and never stamped by research, so no backfill is needed to reconstruct that old contract.
    op.add_column("account_entity", sa.Column("brand_id", sa.Text(), nullable=True))
    op.create_foreign_key(
        "account_entity_brand_fk",
        "account_entity",
        "brand",
        ["brand_id", "workspace_id"],
        ["brand_id", "workspace_id"],
    )
    op.create_check_constraint(
        "account_entity_brand_needs_workspace",
        "account_entity",
        "brand_id IS NULL OR workspace_id IS NOT NULL",
    )
    op.execute(
        "COMMENT ON COLUMN account_entity.brand_id IS 'Workspace-local brand the account belongs "
        "to (composite-FK anchored to workspace_id). Nullable legacy-compatible; the research-side "
        "stamping + domain/registry re-scoping is follow-up work in the research lane.'"
    )
