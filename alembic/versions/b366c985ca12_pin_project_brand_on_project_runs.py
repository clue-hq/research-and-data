"""pin project brand on project runs

Revision ID: b366c985ca12
Revises: 068426c5ea34
Create Date: 2026-07-24 08:32:52.298040+00:00

Conventions every migration must honour (docs/specs/M00-foundations-and-shared-contracts.md §M0.3;
see src/clue_research/db/README.md "Migration conventions checklist"):
- Append-only: claim history supersedes via ``superseded_by``; never UPDATE a value column in place.
- UTC ``timestamptz`` for time columns (e.g. ``observed_at`` / ``collected_at``).
- JSONB ``value_json`` payloads, with real indexed columns on the hot query keys (``entity_id`` …).
- Everything keys on a resolved ``entity_id`` — never a free-text name.
- Forward + reverse: ``downgrade()`` must cleanly reverse ``upgrade()`` (CI runs up → down → up).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b366c985ca12"
down_revision: str | None = "068426c5ea34"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Runs execute for one project and pin the sender brand selected by that project. Existing
    # rows can be upgraded only when their project already belongs to the run's workspace.
    op.execute("ALTER TABLE project_run ADD COLUMN brand_id text")
    op.execute(
        """
        UPDATE project_run AS run
        SET brand_id = project.brand_id
        FROM project
        WHERE run.project_id = project.project_id
          AND run.workspace_id = project.workspace_id
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM project_run
                WHERE project_id IS NULL OR brand_id IS NULL
            ) THEN
                RAISE EXCEPTION
                    'project_run contains development rows without a same-workspace project; '
                    'run `make db-fresh && make migrate` before upgrading';
            END IF;
        END
        $$;
        """
    )

    # The triple anchor makes the run's project/workspace/brand selection one indivisible FK.
    # A different brand from the same workspace is still rejected.
    op.create_unique_constraint(
        "project_run_context_anchor",
        "project",
        ["project_id", "workspace_id", "brand_id"],
    )
    op.drop_constraint("project_run_project_fk", "project_run", type_="foreignkey")
    op.alter_column("project_run", "project_id", nullable=False)
    op.alter_column("project_run", "brand_id", nullable=False)
    op.create_foreign_key(
        "project_run_project_context_fk",
        "project_run",
        "project",
        ["project_id", "workspace_id", "brand_id"],
        ["project_id", "workspace_id", "brand_id"],
    )
    op.drop_index("project_run_project", table_name="project_run")
    op.create_index("project_run_project", "project_run", ["project_id"])
    op.execute(
        "COMMENT ON COLUMN project_run.brand_id IS 'Sender brand selected by project_id and pinned "
        "for this run; the composite project context FK prevents caller-supplied drift.'"
    )


def downgrade() -> None:
    op.drop_index("project_run_project", table_name="project_run")
    op.create_index(
        "project_run_project",
        "project_run",
        ["project_id"],
        postgresql_where=sa.text("project_id IS NOT NULL"),
    )
    op.drop_constraint("project_run_project_context_fk", "project_run", type_="foreignkey")
    op.alter_column("project_run", "project_id", nullable=True)
    op.create_foreign_key(
        "project_run_project_fk",
        "project_run",
        "project",
        ["project_id"],
        ["project_id"],
    )
    op.drop_column("project_run", "brand_id")
    op.drop_constraint("project_run_context_anchor", "project", type_="unique")
