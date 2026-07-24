"""merge phase c1 c2 c3

Revision ID: fc1f3d22a167
Revises: 2211464d398f, 316c84a7a3a4, 5ab2d13ca389
Create Date: 2026-07-24 14:12:33.119644+00:00

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

# revision identifiers, used by Alembic.
revision: str = "fc1f3d22a167"
down_revision: str | tuple[str, ...] | None = (
    "2211464d398f",
    "316c84a7a3a4",
    "5ab2d13ca389",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
