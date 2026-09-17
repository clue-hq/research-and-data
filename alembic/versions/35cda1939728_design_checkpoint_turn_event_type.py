"""Scene live-streaming rung A — the ``design.checkpoint`` turn event type.

The design agent has committed its work in progress mid-run since P0.4, marking each commit on
the design run's slice of ``run_event``. Rung A forwards those marks onto the leg's chat thread
so the canvas can follow a run instead of waiting for it, and the chat stream's ``event_type``
vocabulary is closed by a CHECK — so widening that CHECK is the whole migration. The vocabulary
here must stay equal to ``clue_api.chat.turn_events.TurnEventType``; the lane-D3 suite's
constraint-definition test is the parity guard.

Downgrade deletes any checkpoint frames first (they would violate the narrowed CHECK), which is
honest for the same reason delta 8's downgrade was: the stream is a prunable transport buffer,
not the record. The versions those frames announced live on ``design_document`` and on the design
run's own event stream, neither of which this migration touches.

Revision ID: 35cda1939728
Revises: 6eff96862040
Create Date: 2026-09-02
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "35cda1939728"
down_revision: str | None = "6eff96862040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The vocabulary at ``a051af925d00`` (the 98a5ddafa21b base plus delta 8's leg lifecycle),
#: verbatim.
_EXISTING_EVENT_TYPES = (
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
    "leg.opened",
    "leg.awaiting_user",
    "leg.closed",
    "leg.reopened",
)

#: Rung A's addition.
_DESIGN_EVENT_TYPES = ("design.checkpoint",)


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.execute("ALTER TABLE agent_turn_event_stream DROP CONSTRAINT agent_turn_event_stream_type")
    op.execute(
        "ALTER TABLE agent_turn_event_stream ADD CONSTRAINT agent_turn_event_stream_type "
        f"CHECK (event_type IN ({_quoted(_EXISTING_EVENT_TYPES + _DESIGN_EVENT_TYPES)}))"
    )


def downgrade() -> None:
    op.execute(
        f"DELETE FROM agent_turn_event_stream WHERE event_type IN ({_quoted(_DESIGN_EVENT_TYPES)})"
    )
    op.execute("ALTER TABLE agent_turn_event_stream DROP CONSTRAINT agent_turn_event_stream_type")
    op.execute(
        "ALTER TABLE agent_turn_event_stream ADD CONSTRAINT agent_turn_event_stream_type "
        f"CHECK (event_type IN ({_quoted(_EXISTING_EVENT_TYPES)}))"
    )
