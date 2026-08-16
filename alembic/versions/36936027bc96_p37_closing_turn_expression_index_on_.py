"""P3.7 — the closing-turn expression index on the design-leg exit journal.

Two readers key on ``summary_refs->>'closing_turn_id'``: the ``finish_design_leg`` replay
lookup (P3.5) and the P3.7 routing fallback that re-delivers a crash-retried closing turn
to the design runner — the latter runs once per no-open-leg turn, so it must be an index
probe, not a journal scan.

Revision ID: 36936027bc96
Revises: a051af925d00
Create Date: 2026-08-14
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "36936027bc96"
down_revision: str | None = "a051af925d00"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX design_leg_exit_journal_closing_turn "
        "ON design_leg_exit_journal (workspace_id, (summary_refs->>'closing_turn_id'))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX design_leg_exit_journal_closing_turn")
