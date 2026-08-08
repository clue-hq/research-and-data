"""fi2 l2 entity research job subject entity index

Revision ID: 870fe4f2af87
Revises: 9c8cbd79a0e7
Create Date: 2026-08-08

FI-1 finding **L2** (`docs/specs/FI-accounts-contacts-contract-gap-review.md` §L2, scheduled in
§"Backend fixes to schedule regardless"): ``entity_research_job`` carries no index on
``subject_entity_id``, so *any* per-account research-status read is a sequential scan of the job
table.

The FI-2 slice-1 accounts list (`docs/specs/FI-2-workspace-account-layer.md` §7) makes that read
hot: every row's ``researchStatus`` comes from aggregating this table by subject account, for a
page of accounts at a time. The table's existing indexes cannot serve it —
``entity_research_job_drain`` is led by ``research_run_id`` and ``entity_research_job_scope`` by
``workspace_id`` (with ``subject_entity_id`` in neither), and the
``entity_research_job_subject_once`` unique constraint is ``(research_run_id, subject_entity_id)``,
again wrong-order for a subject-first lookup.

One plain btree on ``subject_entity_id`` alone: the list read arrives with a set of account ids and
no run to anchor on, and the workspace scoping is already enforced through ``account_entity`` (the
slice-0 rule that a claim/entity read is scoped by the *entity*, never by a reuse-class column), so
a composite leading with ``workspace_id`` would not be usable for the subject-keyed probe. Pure
index addition: no column, constraint, enum, or data change, and ``downgrade()`` drops exactly what
``upgrade()`` created.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "870fe4f2af87"
down_revision: str | None = "9c8cbd79a0e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX entity_research_job_subject_entity ON entity_research_job (subject_entity_id)"
    )
    op.execute(
        "COMMENT ON INDEX entity_research_job_subject_entity IS 'FI-1 L2: subject-keyed probe for "
        "the FI-2 slice-1 accounts-list research-status aggregation; the drain/scope indexes lead "
        "with research_run_id/workspace_id and cannot serve it.'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX entity_research_job_subject_entity")
