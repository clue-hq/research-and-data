"""distinguish cancelled agent turns

Revision ID: 5d7ab295742b
Revises: 39513bbba38a
Create Date: 2026-08-10 05:48:24.883587+00:00

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
revision: str = "5d7ab295742b"
down_revision: str | None = "39513bbba38a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("agent_turn_event_status", "agent_turn_event", type_="check")
    op.create_check_constraint(
        "agent_turn_event_status",
        "agent_turn_event",
        "status IN ('requested', 'context_ready', 'running', 'awaiting_input', "
        "'completed', 'failed', 'cancelled', 'abandoned', 'privacy_tombstoned')",
    )


def downgrade() -> None:
    # Older builds have no cancelled state. Preserve the terminal event and its exact reason while
    # degrading its classification to the previous generic unfinalized bucket.
    op.execute("UPDATE agent_turn_event SET status='abandoned' WHERE status='cancelled'")
    op.drop_constraint("agent_turn_event_status", "agent_turn_event", type_="check")
    op.create_check_constraint(
        "agent_turn_event_status",
        "agent_turn_event",
        "status IN ('requested', 'context_ready', 'running', 'awaiting_input', "
        "'completed', 'failed', 'abandoned', 'privacy_tombstoned')",
    )
