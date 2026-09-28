"""Scope opted-in person research to the account without duplicating contact identity.

Revision ID: 4005ff9c331c
Revises: d21f35762d71
"""

from collections.abc import Sequence

from alembic import op

revision: str = "4005ff9c331c"
down_revision: str | None = "d21f35762d71"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP INDEX arv2_research_job_subject_once")
    op.execute("""CREATE UNIQUE INDEX arv2_research_job_subject_once ON arv2_research_job
        (run_id,subject_type,COALESCE(subject_entity_id,account_entity_id),
         COALESCE(CASE WHEN input_refs->>'subject_scope'='account' THEN account_entity_id END,
                  '00000000-0000-0000-0000-000000000000'::uuid))""")


def downgrade() -> None:
    # Refuse a downgrade with distinct live account-scoped jobs; never delete research history.
    op.execute("DROP INDEX arv2_research_job_subject_once")
    op.execute("""CREATE UNIQUE INDEX arv2_research_job_subject_once ON arv2_research_job
        (run_id,subject_type,COALESCE(subject_entity_id,account_entity_id))""")
