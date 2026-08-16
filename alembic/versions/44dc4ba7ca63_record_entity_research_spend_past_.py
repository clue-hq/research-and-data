"""record entity research spend past disabled caps

Revision ID: 44dc4ba7ca63
Revises: 064ad0f43519
Create Date: 2026-08-16 10:58:12.220083+00:00

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
revision: str = "44dc4ba7ca63"
down_revision: str | None = "064ad0f43519"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("entity_research_run", "entity_research_job"):
        constraint = f"{table}_budget_nonnegative"
        op.drop_constraint(constraint, table, type_="check")
        op.create_check_constraint(
            constraint,
            table,
            "budget_cap_cents >= 0 AND spent_cents >= 0",
        )


def downgrade() -> None:
    for table in ("entity_research_job", "entity_research_run"):
        constraint = f"{table}_budget_nonnegative"
        op.drop_constraint(constraint, table, type_="check")
        op.create_check_constraint(
            constraint,
            table,
            "budget_cap_cents >= 0 AND spent_cents >= 0 AND spent_cents <= budget_cap_cents",
        )
