"""agent_turn_event_stream: a partial index for the thread stream's lifecycle poll

Revision ID: c87ba03cfc4e
Revises: 8c3e73eb83b2
Create Date: 2026-10-21 15:45:54+00:00

CRM trial 1, F2 (R-10.1), final review finding #4. Each open chat polls its thread once a second
for the lifecycle frames (``turn.*``) after its cursor. Its cursor only moves over lifecycle
frames, so without this index every poll during a long turn re-reads every text delta and part
frame written since that turn started. The partial index holds only the lifecycle frames, so the
poll reads only what it sends. The table is pruned to 24 h, so building it is cheap.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c87ba03cfc4e"
down_revision: str | None = "8c3e73eb83b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX agent_turn_event_stream_thread_lifecycle "
        "ON agent_turn_event_stream (workspace_id, thread_id, event_id) "
        "WHERE event_type IN ('turn.accepted', 'turn.started', 'turn.awaiting_input', "
        "'turn.completed', 'turn.failed', 'turn.cancelled', 'turn.retrying')"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS agent_turn_event_stream_thread_lifecycle")
