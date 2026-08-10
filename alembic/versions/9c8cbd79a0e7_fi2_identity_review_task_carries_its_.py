"""fi2 identity review task carries its project

Revision ID: 9c8cbd79a0e7
Revises: 21552956dc51
Create Date: 2026-08-08

FI-2 P1 (spec §2), closing the review-resolution membership hole. An admission that lands in the
M2 mid-band enqueues a review task and admits **nothing** — so it can join no project. When a human
later resolves that task, the resolution creates or merges into a real account, but
``identity_review_task`` carried only ``workspace_id`` and ``subject_entity_id``: the project that
was discovering when the ambiguity arose was lost, so the resolved account could never join it.

One nullable column fixes it at the source. ``project_id`` is stamped at **enqueue** time from the
admitting caller's own ``project_id`` (the same value it would have written the membership with),
so the membership and the admission can never disagree about which project claimed the account.
``resolve_merge_into`` / ``resolve_create_new_entity`` then write the membership in the resolution's
own transaction.

* **Nullable, and NULL is a first-class state**: a task enqueued by a projectless admission (or one
  that predates this migration) resolves exactly as it does today — degrade, never fail.
* **Named composite FK** ``(project_id, workspace_id) -> project (project_id, workspace_id)`` —
  the same anchor ``project_account`` uses, so a task can never name a project from another
  workspace. ``workspace_id`` is nullable on this table, and a composite FK under the default
  MATCH SIMPLE is simply not enforced when any column is NULL — which is the wanted behaviour for
  the legacy unscoped tasks the ``ReviewTaskUnscopedError`` path already handles.
* **Named CHECK** ``identity_review_task_project_requires_workspace`` — a project without a
  workspace would be a membership no lens read could ever anchor (the same guard idiom as
  ``run_lineage_project_requires_project_id``). Existing rows all have ``project_id IS NULL``, so
  the CHECK is satisfiable without a backfill.

No backfill: an already-open legacy task has no recoverable project (that is the very gap), and per
the B3 synthetic-data ruling the dev databases are reset rather than backfilled.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9c8cbd79a0e7"
down_revision: str | None = "21552956dc51"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE identity_review_task ADD COLUMN project_id text")
    op.execute(
        "COMMENT ON COLUMN identity_review_task.project_id IS 'FI-2 P1: the project the admitting "
        "caller was discovering for when this ambiguity was enqueued. NULL = a projectless "
        "(workspace-level) admission, or a task predating the column; the resolution then writes "
        "no project_account membership.'"
    )
    op.execute(
        "ALTER TABLE identity_review_task ADD CONSTRAINT "
        "identity_review_task_project_requires_workspace "
        "CHECK (project_id IS NULL OR workspace_id IS NOT NULL)"
    )
    op.execute(
        "ALTER TABLE identity_review_task ADD CONSTRAINT identity_review_task_project_ws_fk "
        "FOREIGN KEY (project_id, workspace_id) REFERENCES project (project_id, workspace_id)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE identity_review_task DROP CONSTRAINT identity_review_task_project_ws_fk"
    )
    op.execute(
        "ALTER TABLE identity_review_task DROP CONSTRAINT "
        "identity_review_task_project_requires_workspace"
    )
    op.execute("ALTER TABLE identity_review_task DROP COLUMN project_id")
