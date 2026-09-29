"""merge custom-domain and ai-ark lineages

Revision ID: c16e1ae684b3
Revises: aaff3d831895, 97427f8eb3d6
Create Date: 2026-09-28 16:54:56.335901+00:00

Conventions every migration must honour (docs/specs/M00-foundations-and-shared-contracts.md §M0.3;
see src/clue_research/db/README.md "Migration conventions checklist"):
- Append-only: claim history supersedes via ``superseded_by``; never UPDATE a value column in place.
- UTC ``timestamptz`` for time columns (e.g. ``observed_at`` / ``collected_at``).
- JSONB ``value_json`` payloads, with real indexed columns on the hot query keys (``entity_id`` …).
- Everything keys on a resolved ``entity_id`` — never a free-text name.
- Forward + reverse: ``downgrade()`` must cleanly reverse ``upgrade()`` (CI runs up → down → up).

Joins the custom-domain lineage (``aaff3d831895``, ``workspace_hostname``) with the ai-ark /
F5 lineage (``97427f8eb3d6``, which carries ``design_workspace_handle``) after the 2026-09-28
branch merge. No schema change; the reconciliation itself is the next revision.
"""

from __future__ import annotations

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "c16e1ae684b3"
down_revision: str | None = ("aaff3d831895", "97427f8eb3d6")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
