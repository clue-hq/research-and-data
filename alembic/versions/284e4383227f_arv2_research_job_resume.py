"""arv2 research job resume: restart counter and resume audit

Revision ID: 284e4383227f
Revises: ecc5f641c0d9
Create Date: 2026-10-14

Spec docs/superpowers/specs/2026-10-14-arv2-research-job-resume-design.md §3.2 and §3.5:
``restart_count`` gives a job a fresh conversation identity without a new job; every resume and
restart writes one ``arv2_research_job_resume`` row (who, why, attempt, any allowance top-up).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "284e4383227f"
down_revision: str | None = "ecc5f641c0d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE arv2_research_job ADD COLUMN restart_count integer NOT NULL DEFAULT 0")
    op.execute(
        "ALTER TABLE arv2_research_job ADD CONSTRAINT arv2_research_job_restart_count "
        "CHECK (restart_count >= 0)"
    )
    op.execute("""CREATE TABLE arv2_research_job_resume (
        resume_id uuid PRIMARY KEY,
        workspace_id text NOT NULL,
        job_id uuid NOT NULL REFERENCES arv2_research_job(job_id),
        attempt_before integer NOT NULL,
        actor text NOT NULL,
        reason text NOT NULL,
        restarted boolean NOT NULL,
        top_up_model_calls integer NOT NULL DEFAULT 0,
        top_up_tool_calls integer NOT NULL DEFAULT 0,
        top_up_delegations integer NOT NULL DEFAULT 0,
        top_up_runtime_ms bigint NOT NULL DEFAULT 0,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT arv2_research_job_resume_reason CHECK (length(btrim(reason)) > 0),
        CONSTRAINT arv2_research_job_resume_actor CHECK (length(btrim(actor)) > 0),
        CONSTRAINT arv2_research_job_resume_top_up CHECK (
            top_up_model_calls >= 0 AND top_up_tool_calls >= 0
            AND top_up_delegations >= 0 AND top_up_runtime_ms >= 0)
    )""")
    op.execute(
        "CREATE INDEX arv2_research_job_resume_job "
        "ON arv2_research_job_resume(workspace_id, job_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE arv2_research_job_resume")
    op.execute("ALTER TABLE arv2_research_job DROP CONSTRAINT arv2_research_job_restart_count")
    op.execute("ALTER TABLE arv2_research_job DROP COLUMN restart_count")
