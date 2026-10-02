"""arv2: research job stage — where a job is, for the research progress card

Revision ID: c90aaea30a88
Revises: 2cd622be2da0
Create Date: 2026-09-11 23:37:00.471985+00:00

Spec 2026-09-12 (research progress card) §1. The account driver stamps ``stage`` at four points:
``deep_research`` when the job is claimed, ``synthesis`` when the agent's finalize tool lands,
``committee`` when the committee step starts, ``member_research`` when the person jobs are
offered. A person job stamps ``deep_research`` and ``synthesis``. Terminal rows keep their last
stage. Nullable: every row that predates this migration, and a job nothing has claimed yet.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c90aaea30a88"
down_revision: str | None = "2cd622be2da0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STAGES = "('deep_research', 'synthesis', 'committee', 'member_research')"


def upgrade() -> None:
    op.execute("ALTER TABLE arv2_research_job ADD COLUMN stage text")
    op.execute(
        "ALTER TABLE arv2_research_job ADD CONSTRAINT arv2_research_job_stage "
        f"CHECK (stage IS NULL OR stage IN {_STAGES})"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE arv2_research_job DROP CONSTRAINT arv2_research_job_stage")
    op.execute("ALTER TABLE arv2_research_job DROP COLUMN stage")
