"""Shared active research runtime across attempts; idle time between continuations is free.

Revision ID: d21f35762d71
Revises: 369f195d9976
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d21f35762d71"
down_revision: str | None = "369f195d9976"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""ALTER TABLE arv2_quality_allowance
        ADD COLUMN max_runtime_ms bigint NOT NULL DEFAULT 1800000,
        ADD COLUMN runtime_used_ms bigint NOT NULL DEFAULT 0,
        ADD COLUMN runtime_started_at timestamptz,
        ADD COLUMN runtime_owner_token uuid,
        ADD CONSTRAINT quality_allowance_runtime CHECK (
            max_runtime_ms>0 AND runtime_used_ms BETWEEN 0 AND max_runtime_ms
            AND ((runtime_started_at IS NULL)=(runtime_owner_token IS NULL)))""")


def downgrade() -> None:
    op.execute("""ALTER TABLE arv2_quality_allowance DROP CONSTRAINT quality_allowance_runtime,
        DROP COLUMN runtime_owner_token,DROP COLUMN runtime_started_at,
        DROP COLUMN runtime_used_ms,DROP COLUMN max_runtime_ms""")
