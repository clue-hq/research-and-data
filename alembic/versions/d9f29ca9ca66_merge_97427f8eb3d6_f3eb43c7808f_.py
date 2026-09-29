"""merge 97427f8eb3d6+f3eb43c7808f: discovery searches and account reconciliation checkpoints

Revision ID: d9f29ca9ca66
Revises: 97427f8eb3d6, f3eb43c7808f
Create Date: 2026-09-28 14:20:49.174231+00:00

Joins the two heads the ``codex/ai-ark-committee-discovery-spec`` merge produced, both built on
``4c916b02ed9b``: ``97427f8eb3d6`` (discovery searches — one webset per search) and
``f3eb43c7808f`` (focused account reconciliation checkpoints). They touch disjoint tables, so the
join carries no schema of its own.

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
revision: str = "d9f29ca9ca66"
down_revision: str | None = ("97427f8eb3d6", "f3eb43c7808f")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
