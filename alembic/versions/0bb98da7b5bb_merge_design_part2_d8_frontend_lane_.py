"""merge design part2 d8 + frontend lane heads

Revision ID: 0bb98da7b5bb
Revises: 6f81d8fd729a, 5d7ab295742b
Create Date: 2026-08-10 20:40:14.739683+00:00

The frontend×design integration join (2026-08-11): `integration/frontend-design-part-ii` merges
`origin/main` (frontend-integration lanes B/D/E + FI-2; head ``5d7ab295742b``) into the design
Part-II line (D0–D8; head ``6f81d8fd729a``). Both chains root at ``c6d84aa84b79``; this no-op
revision restores the single head per the house convention (parallel branches → ``alembic merge``,
never a hand-renumber).

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
revision: str = "0bb98da7b5bb"
down_revision: str | None = ("6f81d8fd729a", "5d7ab295742b")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
