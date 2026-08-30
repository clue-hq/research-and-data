"""design document thumbnail cache index

Revision ID: be0659753362
Revises: 4c02d8eac29a
Create Date: 2026-08-30 21:14:03.394175+00:00

One row per ``(workspace, document, version)`` naming the blob-store digest that holds the
rendered PNG a gallery card shows. **Deliberately FK-free, both ways.** No FK to the ``artifact``
row, because a design blob is content-addressed per workspace and a dangling digest is repaired
by regenerating the thumbnail at read time — a constraint would turn a self-healing miss into a
write failure. No FK to ``design_document`` either: this is a pure cache, and a cache must never
be the thing that blocks a document delete.

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
revision: str = "be0659753362"
down_revision: str | None = "4c02d8eac29a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "design_document_thumbnail",
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("document_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "document_id",
            "version",
            name="pk_design_document_thumbnail",
        ),
    )


def downgrade() -> None:
    op.drop_table("design_document_thumbnail")
