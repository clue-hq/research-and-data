"""projects directory and home

Revision ID: 5358a2422cb2
Revises: d659c2d2b537
Create Date: 2026-09-19 17:14:36.129202+00:00

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

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5358a2422cb2"
down_revision: str | None = "d659c2d2b537"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE project
            ADD COLUMN description text        NOT NULL DEFAULT '',
            ADD COLUMN pinned      boolean     NOT NULL DEFAULT false,
            ADD COLUMN kind        text        NOT NULL DEFAULT 'marketing',
            ADD COLUMN updated_at  timestamptz NOT NULL DEFAULT now(),
            ADD COLUMN archived_at timestamptz,
            ADD CONSTRAINT project_kind CHECK (kind IN ('marketing', 'system')),
            ADD CONSTRAINT project_description_length CHECK (char_length(description) <= 2000)
        """
    )
    op.execute("UPDATE project SET updated_at = created_at")
    # The per-brand onboarding scope anchors (onboarding_synthesis_wiring.onboarding_project_id)
    # were born archived before `kind` existed; this is the one and only prefix read.
    op.execute(
        "UPDATE project SET kind = 'system', archived_at = created_at "
        "WHERE project_id LIKE 'prj_onb_%'"
    )
    op.execute(
        "UPDATE project SET archived_at = created_at "
        "WHERE status = 'archived' AND archived_at IS NULL"
    )
    op.execute(
        "ALTER TABLE project ADD CONSTRAINT project_archived_at_iff "
        "CHECK ((status = 'archived') = (archived_at IS NOT NULL))"
    )
    op.execute(
        "CREATE INDEX project_directory_page ON project "
        "(workspace_id, kind, status, pinned DESC, updated_at DESC, project_id DESC)"
    )
    op.execute(
        "ALTER TABLE memory ADD COLUMN source_thread_id text, "
        "ADD CONSTRAINT memory_source_thread_fk FOREIGN KEY (source_thread_id) "
        "REFERENCES agent_thread (id)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE memory DROP CONSTRAINT memory_source_thread_fk, DROP COLUMN source_thread_id"
    )
    op.execute("DROP INDEX project_directory_page")
    op.execute(
        """
        ALTER TABLE project
            DROP CONSTRAINT project_archived_at_iff,
            DROP CONSTRAINT project_description_length,
            DROP CONSTRAINT project_kind,
            DROP COLUMN archived_at,
            DROP COLUMN updated_at,
            DROP COLUMN kind,
            DROP COLUMN pinned,
            DROP COLUMN description
        """
    )
