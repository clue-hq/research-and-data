"""agent model call langfuse ids

Revision ID: b7193eb28363
Revises: d36bc7d32c9a
Create Date: 2026-09-14 21:34:43.622197+00:00

Lane 3 slice 3 (the Langfuse design note §3.8, D4). The LangChain handler reports every graph
model call to Langfuse as a generation; the durable recorder stamps that generation's trace and
observation ids on the receipt so a row in the cost read opens the tree it came from. Both are
nullable text: a turn run with Langfuse off, and every row written before this migration, is
NULL/NULL.

Reversible: the downgrade drops both columns; no other row data is touched.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7193eb28363"
down_revision: str | None = "d36bc7d32c9a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE agent_model_call "
        "ADD COLUMN langfuse_trace_id text, "
        "ADD COLUMN langfuse_observation_id text"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE agent_model_call "
        "DROP COLUMN langfuse_observation_id, "
        "DROP COLUMN langfuse_trace_id"
    )
