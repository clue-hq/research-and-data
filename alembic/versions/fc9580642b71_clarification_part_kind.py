"""clarification part kind

Revision ID: fc9580642b71
Revises: c937a6b69e8a
Create Date: 2026-09-20 00:00:00.000000+00:00

Spec 2026-09-20 (design clarification cards) §2.1. The design runtime may ask the user up to four
clarifying questions before it designs; the leg runner carries them to the chat as a new transcript
part kind, ``clarification``. ``agent_turn_event_stream.part_kind`` is closed by the CHECK migration
``98a5ddafa21b`` created, so the new kind is admitted by replacing that CHECK with the same list
plus ``'clarification'``.

**The downgrade is dev-only-reversible.** It restores the pre-clarification list verbatim, so it
fails loudly if any ``clarification`` frame has already been emitted. That is the honest behaviour
for a closed vocabulary — a transport buffer holding a value the constraint forbids would be worse
than a refused reversal — and the buffer is prunable, so a developer who needs the reversal deletes
those frames first.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fc9580642b71"
down_revision: str | None = "c937a6b69e8a"
branch_labels: str | None = None
depends_on: str | None = None


#: The §3.1 domain part vocabulary as ``98a5ddafa21b`` left it — the downgrade target.
_PART_KINDS_BEFORE = (
    "text",
    "reasoning",
    "agent_activity",
    "tool",
    "task",
    "plan",
    "gate",
    "sources",
    "action",
)

#: ...and with the clarification card of spec 2026-09-20 §2.1.
_PART_KINDS_AFTER = (*_PART_KINDS_BEFORE, "clarification")


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _recreate_check(values: tuple[str, ...]) -> None:
    op.execute(
        "ALTER TABLE agent_turn_event_stream "
        "DROP CONSTRAINT IF EXISTS agent_turn_event_stream_part_kind"
    )
    op.execute(
        f"""
        ALTER TABLE agent_turn_event_stream
            ADD CONSTRAINT agent_turn_event_stream_part_kind
            CHECK (part_kind IS NULL OR part_kind IN ({_quoted(values)}))
        """
    )


def upgrade() -> None:
    _recreate_check(_PART_KINDS_AFTER)


def downgrade() -> None:
    _recreate_check(_PART_KINDS_BEFORE)
