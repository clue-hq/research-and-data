"""add design node turn context refs

Revision ID: 54ae25174405
Revises: a1c5b9842f0e
Create Date: 2026-08-23 18:21:55.292933+00:00

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
revision: str = "54ae25174405"
down_revision: str | None = "a1c5b9842f0e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE agent_turn_submission_context_ref "
        "DROP CONSTRAINT agent_turn_submission_context_ref_type"
    )
    op.execute(
        "ALTER TABLE agent_turn_submission_context_ref "
        "ADD CONSTRAINT agent_turn_submission_context_ref_type "
        "CHECK (object_type IN ('account', 'contact', 'design_document', 'design_node'))"
    )
    op.execute(
        "COMMENT ON TABLE agent_turn_submission_context_ref IS "
        "'Ordered, immutable account, contact, design-document, or design-node references "
        "captured with one human chat submission. Design nodes are interpreted only beside "
        "the exact versioned document on the thread open design leg.'"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE agent_turn_submission_context_ref "
        "DROP CONSTRAINT agent_turn_submission_context_ref_type"
    )
    op.execute(
        "ALTER TABLE agent_turn_submission_context_ref "
        "ADD CONSTRAINT agent_turn_submission_context_ref_type "
        "CHECK (object_type IN ('account', 'contact', 'design_document'))"
    )
    op.execute(
        "COMMENT ON TABLE agent_turn_submission_context_ref IS "
        "'Ordered, immutable account, contact, or design-document references supplied with "
        "one human chat submission.'"
    )
