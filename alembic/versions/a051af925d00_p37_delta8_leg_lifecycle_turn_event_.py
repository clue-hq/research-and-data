"""P3.7 delta 8 — leg lifecycle event types on the chat turn stream.

PD-part3 §3-8: the design-leg lifecycle (opened / awaiting user / closed / reopened) rides
the same ``agent_turn_event_stream`` the transcript and speaker chip follow, so widening the
closed ``event_type`` CHECK is the whole migration. ``run_event.subject_kind`` is untouched,
exactly as the delta promises. The vocabulary here must stay equal to
``clue_api.chat.turn_events.TurnEventType`` — the lane-D3 suite's every-type insert is the
parity guard.

Downgrade deletes any leg frames first (they would violate the narrowed CHECK), which is
honest: the stream is a prunable transport buffer, not the record — the leg transitions
themselves live on ``design_leg`` and its exit journal.

Revision ID: a051af925d00
Revises: 65880921cd52
Create Date: 2026-08-14
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a051af925d00"
down_revision: str | None = "65880921cd52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The 98a5ddafa21b vocabulary, verbatim.
_BASE_EVENT_TYPES = (
    "turn.accepted",
    "turn.started",
    "turn.awaiting_input",
    "turn.completed",
    "turn.failed",
    "turn.cancelled",
    "turn.retrying",
    "part.created",
    "part.updated",
    "part.completed",
    "part.failed",
    "part.reset",
    "text.start",
    "text.delta",
    "text.end",
    "stream.reset",
)

#: Delta 8's additions.
_LEG_EVENT_TYPES = (
    "leg.opened",
    "leg.awaiting_user",
    "leg.closed",
    "leg.reopened",
)


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.execute("ALTER TABLE agent_turn_event_stream DROP CONSTRAINT agent_turn_event_stream_type")
    op.execute(
        "ALTER TABLE agent_turn_event_stream ADD CONSTRAINT agent_turn_event_stream_type "
        f"CHECK (event_type IN ({_quoted(_BASE_EVENT_TYPES + _LEG_EVENT_TYPES)}))"
    )


def downgrade() -> None:
    op.execute(
        f"DELETE FROM agent_turn_event_stream WHERE event_type IN ({_quoted(_LEG_EVENT_TYPES)})"
    )
    op.execute("ALTER TABLE agent_turn_event_stream DROP CONSTRAINT agent_turn_event_stream_type")
    op.execute(
        "ALTER TABLE agent_turn_event_stream ADD CONSTRAINT agent_turn_event_stream_type "
        f"CHECK (event_type IN ({_quoted(_BASE_EVENT_TYPES)}))"
    )
