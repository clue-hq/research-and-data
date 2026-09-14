"""agent model call cost usd

Revision ID: d36bc7d32c9a
Revises: 639d081ad799
Create Date: 2026-09-14 11:51:31.596521+00:00

Lane 3 slice 1 (telemetry and cost design note §5.5). ``agent_model_call`` was born with
``cost_millicredits``, deliberately written as 0 until the credits milestone owns the
cents→millicredits policy. The gateway already measures every answer's cost and stamps it on the
response metadata (``clue_cost_cents`` / ``clue_cost_source``); the ARV2 research agent already
records that figure on its ledger rows. This migration gives the conversation-turn receipt the same
two facts so the cost read never reports a turn as free.

Both columns are nullable: every row written before this migration is NULL/NULL, which the read
reports as "unpriced before d36bc7d32c9a" rather than as zero. ``cost_source`` is bounded to the
gateway's three words (``clue_gateway.metadata.CostSource`` — ``metered`` / ``estimate`` /
``unpriced``); ``free`` is the provider ledger's label and never applies to a model call.

Reversible: the downgrade drops the CHECK and both columns; no row data outside them is touched.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d36bc7d32c9a"
down_revision: str | None = "639d081ad799"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE agent_model_call "
        "ADD COLUMN cost_usd numeric(12, 6), "
        "ADD COLUMN cost_source text, "
        "ADD CONSTRAINT agent_model_call_cost_source CHECK ("
        "cost_source IS NULL OR cost_source IN ('metered', 'estimate', 'unpriced'))"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE agent_model_call "
        "DROP CONSTRAINT agent_model_call_cost_source, "
        "DROP COLUMN cost_source, "
        "DROP COLUMN cost_usd"
    )
