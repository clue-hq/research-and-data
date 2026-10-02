"""design_document.archived_at — the library's archive state (artifacts-page spec 2026-09-15 §4.1)

Revision ID: 5f2bd1b4b82d
Revises: b7193eb28363
Create Date: 2026-09-16 05:50:32.625881+00:00

One nullable column. Archiving is a gallery/library state: an archived document leaves the
per-project feed and the Archived collection lists it. Publish is independent (founder ruling
2026-09-15). Reversible: downgrade drops the column.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5f2bd1b4b82d"
down_revision: str | None = "b7193eb28363"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE design_document ADD COLUMN archived_at timestamptz NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE design_document DROP COLUMN archived_at")
