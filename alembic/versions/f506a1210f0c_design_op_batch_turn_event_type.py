"""Scene live-streaming rung B — the ``design.op_batch`` turn event type.

Rung A carried the design run's mid-run CHECKPOINT marks onto the leg's chat thread, so the
canvas could pin a durable version instead of waiting out the whole generation. Rung B carries
the mutations *between* those checkpoints: each op-bearing sink event forwards as one
``design.op_batch`` frame with the batch it applied and the position that batch ends at in the
run's operation ledger. The chat stream's ``event_type`` vocabulary is closed by a CHECK, so
widening that CHECK is the whole migration — the same shape ``35cda1939728`` had one rung ago.

The vocabulary here must stay equal to ``clue_api.chat.turn_events.TurnEventType``; the lane-D3
suite's constraint-definition test is the parity guard.

Downgrade deletes any op-batch frames first (they would violate the narrowed CHECK), which is
honest for the same reason rung A's downgrade was: the stream is a prunable transport buffer, not
the record. An op batch is the *least* authoritative thing on it — it announces work that is not
yet durable — so nothing is lost that the document, the checkpoint frames, and the design run's
own event stream do not still hold.

Revision ID: f506a1210f0c
Revises: 35cda1939728
Create Date: 2026-09-02
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f506a1210f0c"
down_revision: str | None = "35cda1939728"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The vocabulary at ``35cda1939728`` (the 98a5ddafa21b base, delta 8's leg lifecycle, and rung
#: A's checkpoint), verbatim.
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
    "design.checkpoint",
)

#: Rung B's addition.
_DESIGN_EVENT_TYPES = ("design.op_batch",)


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
