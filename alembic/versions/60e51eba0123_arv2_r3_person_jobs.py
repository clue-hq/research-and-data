"""arv2 r3 person jobs

Revision ID: 60e51eba0123
Revises: 0622104be021
Create Date: 2026-09-08 22:48:26.665263+00:00

Track R (ARV2 research), R3 — a job row learns *what* it researches:

1. ``subject_type`` — ``account`` (the R2 job, and the default every existing row takes) or
   ``person`` (an R3 committee member). The account a person job belongs to stays in
   ``account_entity_id``, so a person job is still scoped, indexed and joined like its siblings.

2. ``subject_entity_id`` — the contact a person job researches, and nothing at all for an account
   job. ``arv2_research_job_subject`` makes that biconditional: a person job without its contact,
   or an account job carrying one, is unrepresentable rather than merely discouraged.

3. ``profile_sha256`` — the agent profile *this job* was pinned to. The run's pin says what the
   launch signed off on; a person job is queued later, by the committee step, and may run a
   different profile, so replay reads the job's own copy rather than inferring it from the run.

Uniqueness moves from the account to the subject: ``arv2_research_job_once (run_id,
account_entity_id)`` allowed exactly one job per account, which would refuse the second committee
member. The replacement is the expression index ``arv2_research_job_subject_once (run_id,
subject_type, COALESCE(subject_entity_id, account_entity_id))`` — still one account job per run,
now also one job per person per run, and the two kinds cannot collide with each other.

Conventions every migration must honour (docs/specs/M00-foundations-and-shared-contracts.md §M0.3;
see src/clue_research/db/README.md "Migration conventions checklist"):
- Append-only: claim history supersedes via ``superseded_by``; never UPDATE a value column in place.
- UTC ``timestamptz`` for time columns (e.g. ``observed_at`` / ``collected_at``).
- JSONB ``value_json`` payloads, with real indexed columns on the hot query keys (``entity_id`` …).
- Everything keys on a resolved ``entity_id`` — never a free-text name.
- Forward + reverse: ``downgrade()`` must cleanly reverse ``upgrade()`` (CI runs up → down → up).

Reversibility follows the ``a3602967bb73`` precedent: the reverse of this migration cannot express
a person job at all, so ``downgrade()`` refuses while any ``subject_type = 'person'`` row exists
rather than dropping the column out from under it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "60e51eba0123"
down_revision: str | None = "0622104be021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "arv2_research_job",
        sa.Column("subject_type", sa.Text(), nullable=False, server_default="account"),
    )
    op.add_column("arv2_research_job", sa.Column("subject_entity_id", sa.Uuid(), nullable=True))
    op.add_column("arv2_research_job", sa.Column("profile_sha256", sa.Text(), nullable=True))
    op.execute(
        "ALTER TABLE arv2_research_job ADD CONSTRAINT arv2_research_job_subject_type "
        "CHECK (subject_type IN ('account', 'person'))"
    )
    op.execute(
        "ALTER TABLE arv2_research_job ADD CONSTRAINT arv2_research_job_subject "
        "CHECK ((subject_type = 'person') = (subject_entity_id IS NOT NULL))"
    )
    op.drop_constraint("arv2_research_job_once", "arv2_research_job", type_="unique")
    op.execute(
        "CREATE UNIQUE INDEX arv2_research_job_subject_once ON arv2_research_job "
        "(run_id, subject_type, COALESCE(subject_entity_id, account_entity_id))"
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM arv2_research_job WHERE subject_type = 'person') THEN
                RAISE EXCEPTION 'cannot downgrade R3 while person research jobs exist';
            END IF;
        END $$
        """
    )
    op.execute("DROP INDEX arv2_research_job_subject_once")
    op.execute(
        "ALTER TABLE arv2_research_job ADD CONSTRAINT arv2_research_job_once "
        "UNIQUE (run_id, account_entity_id)"
    )
    op.execute("ALTER TABLE arv2_research_job DROP CONSTRAINT arv2_research_job_subject")
    op.execute("ALTER TABLE arv2_research_job DROP CONSTRAINT arv2_research_job_subject_type")
    op.drop_column("arv2_research_job", "profile_sha256")
    op.drop_column("arv2_research_job", "subject_entity_id")
    op.drop_column("arv2_research_job", "subject_type")
