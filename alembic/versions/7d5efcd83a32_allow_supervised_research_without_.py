"""Allow explicit zero runtime allowance for supervised research.

Revision ID: 7d5efcd83a32
Revises: 16bfa50620f4
"""

from collections.abc import Sequence

from alembic import op

revision: str = "7d5efcd83a32"
down_revision: str | None = "16bfa50620f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE arv2_quality_allowance DROP CONSTRAINT quality_allowance_runtime")
    op.execute("""ALTER TABLE arv2_quality_allowance ADD CONSTRAINT quality_allowance_runtime
        CHECK (max_runtime_ms>=0 AND runtime_used_ms>=0
        AND (max_runtime_ms=0 OR runtime_used_ms<=max_runtime_ms)
        AND ((runtime_started_at IS NULL)=(runtime_owner_token IS NULL)))""")


def downgrade() -> None:
    # Preserve elapsed usage when restoring the old strictly positive allowance contract.
    op.execute("ALTER TABLE arv2_quality_allowance DROP CONSTRAINT quality_allowance_runtime")
    op.execute("""UPDATE arv2_quality_allowance
        SET max_runtime_ms=GREATEST(1800000,runtime_used_ms)
        WHERE max_runtime_ms=0""")
    op.execute("""ALTER TABLE arv2_quality_allowance ADD CONSTRAINT quality_allowance_runtime
        CHECK (max_runtime_ms>0 AND runtime_used_ms BETWEEN 0 AND max_runtime_ms
        AND ((runtime_started_at IS NULL)=(runtime_owner_token IS NULL)))""")
