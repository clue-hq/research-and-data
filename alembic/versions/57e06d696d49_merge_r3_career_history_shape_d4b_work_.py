"""merge r3 career history shape + d4b work_email verdict join

Revision ID: 57e06d696d49
Revises: 7c4f1a2b9d63, 63294c3ce019
Create Date: 2026-09-09 19:38:11.308352+00:00

The R3 lane (`60e51eba0123` person jobs → `7c4f1a2b9d63` career-history shape) and the D4-b lane
(`7332ac974920` work_email verdict → `63294c3ce019` join) both chained off the R2/O3/O4 join and
meet here. Each lane's registry swap is a different `field_definition` row, so there is nothing to
reconcile: this revision only gives Alembic one head again.

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
revision: str = "57e06d696d49"
down_revision: str | None = ("7c4f1a2b9d63", "63294c3ce019")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
