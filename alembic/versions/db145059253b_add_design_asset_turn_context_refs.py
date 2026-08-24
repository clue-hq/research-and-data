"""add design asset turn context refs

Revision ID: db145059253b
Revises: 54ae25174405
Create Date: 2026-08-23 19:08:07.053328+00:00

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
revision: str = "db145059253b"
down_revision: str | None = "54ae25174405"
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
        "CHECK (object_type IN "
        "('account', 'contact', 'design_document', 'design_node', 'design_asset'))"
    )
    op.execute(
        "COMMENT ON TABLE agent_turn_submission_context_ref IS "
        "'Ordered, immutable account, contact, design-document, design-node, or design-asset "
        "references captured with one human chat submission. Design assets are accepted only "
        "as ready image references for an open scene-design leg.'"
    )


def downgrade() -> None:
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
