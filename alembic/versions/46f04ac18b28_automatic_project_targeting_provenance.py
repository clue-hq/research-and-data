"""automatic project targeting provenance

Revision ID: 46f04ac18b28
Revises: 403bce58bdcf
Create Date: 2026-09-21 18:04:56.376703+00:00

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
revision: str = "46f04ac18b28"
down_revision: str | None = "403bce58bdcf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("project_product", sa.Column("confirmation_turn_id", sa.UUID(), nullable=True))
    op.alter_column("project_product", "gate_id", nullable=True)
    op.create_check_constraint(
        "project_product_confirmation_source",
        "project_product",
        "(gate_id IS NOT NULL) <> (confirmation_turn_id IS NOT NULL)",
    )

    # Like gate_id, the turn coordinate is not a FK into the API-owned turn ledger.
    # The composition root derives it from a durable submission in the same workspace.
    op.execute(
        "COMMENT ON COLUMN project_product.confirmation_turn_id IS "
        "'Automatic confirmation by this durable turn; no human gate answer.'"
    )


def downgrade() -> None:
    # Refuse rather than erase or relabel automatic decisions as human gate answers.
    # With no automatic rows, this reverses cleanly; deployed data requires a forward fix.
    op.alter_column("project_product", "gate_id", nullable=False)
    op.drop_constraint("project_product_confirmation_source", "project_product", type_="check")
    op.drop_column("project_product", "confirmation_turn_id")
