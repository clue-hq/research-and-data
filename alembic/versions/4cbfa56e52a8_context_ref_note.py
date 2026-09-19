"""context ref note

Revision ID: 4cbfa56e52a8
Revises: 8079022e5802
Create Date: 2026-09-04

A context ref may now carry the marketer's own words about *that* ref.

The web editor lets a marketer annotate an element on the page ("1. Make this shorter") and send
the annotated selection to chat. Until now the submission captured only *which* objects were
selected; the instruction survived, if at all, inside the free-text message, where nothing bound
it to the ref it was about. The note belongs on the ref row: it is per-ref human intent, ordered
with the selection, and it must replay exactly — a retried turn, and an out-of-scope leg close
that re-offers the captured bytes under a derived identity, both rebuild their refs from these
rows.

Nullable and unbackfilled on purpose: every ref written before this migration genuinely had no
note, and inventing one would put words in a human's mouth. The 2,000-character bound lives on
the ``DomainObjectRef`` / ``ContextRefRequest`` contracts rather than in a CHECK, matching how the
sibling text on this path is bounded.

``agent_turn_submission_context_ref`` is append-only by trigger (UPDATE and DELETE are refused);
adding a column is DDL and is unaffected by it.

Hand-written and reversible: ``downgrade()`` drops the column (CI runs up -> down -> up).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4cbfa56e52a8"
down_revision: str | None = "8079022e5802"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_turn_submission_context_ref",
        sa.Column("note", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_turn_submission_context_ref", "note")
