"""project document turn context refs

Revision ID: 9289d41e9a60
Revises: e8fdb29cd532
Create Date: 2026-09-17 05:56:09.229679+00:00

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
revision: str = "9289d41e9a60"
down_revision: str | None = "e8fdb29cd532"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PREVIOUS = "('account', 'contact', 'design_document', 'design_node', 'design_asset')"
_CURRENT = (
    "('account', 'contact', 'design_document', 'design_node', 'design_asset', 'project_document')"
)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE agent_turn_submission_context_ref "
        "DROP CONSTRAINT agent_turn_submission_context_ref_type"
    )
    op.execute(
        "ALTER TABLE agent_turn_submission_context_ref "
        "ADD CONSTRAINT agent_turn_submission_context_ref_type "
        f"CHECK (object_type IN {_CURRENT})"
    )
    op.execute(
        "COMMENT ON TABLE agent_turn_submission_context_ref IS "
        "'Ordered, immutable account, contact, design-document, design-node, design-asset, or "
        "project-document references captured with one human chat submission. Design assets are "
        "accepted only as ready image references for an open scene-design leg; project documents "
        "are Gallery files pinned to the version the user tagged.'"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE agent_turn_submission_context_ref "
        "DROP CONSTRAINT agent_turn_submission_context_ref_type"
    )
    op.execute(
        "ALTER TABLE agent_turn_submission_context_ref "
        "ADD CONSTRAINT agent_turn_submission_context_ref_type "
        f"CHECK (object_type IN {_PREVIOUS})"
    )
    op.execute(
        "COMMENT ON TABLE agent_turn_submission_context_ref IS "
        "'Ordered, immutable account, contact, design-document, design-node, or design-asset "
        "references captured with one human chat submission. Design assets are accepted only "
        "as ready image references for an open scene-design leg.'"
    )
