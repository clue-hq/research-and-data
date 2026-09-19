"""design_document_user_mark — per-user saved / last-viewed marks (artifacts-page spec §4.2)

Revision ID: 323081354b51
Revises: 5f2bd1b4b82d
Create Date: 2026-09-16 05:53:49.962800+00:00

User metadata about a design document, never document state: one row per (workspace, user,
document). Cascades on document delete; the user row is never deleted, so erasure deletes marks
explicitly (clue_auth.store.erase_platform_user).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "323081354b51"
down_revision: str | None = "5f2bd1b4b82d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE design_document_user_mark (
            workspace_id   text        NOT NULL,
            user_id        text        NOT NULL,
            document_id    text        NOT NULL,
            saved          boolean     NOT NULL DEFAULT false,
            last_viewed_at timestamptz NULL,
            updated_at     timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT design_document_user_mark_pkey
                PRIMARY KEY (workspace_id, user_id, document_id),
            CONSTRAINT design_document_user_mark_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT design_document_user_mark_user_fk FOREIGN KEY (user_id)
                REFERENCES platform_user (user_id),
            CONSTRAINT design_document_user_mark_document_fk FOREIGN KEY (document_id, workspace_id)
                REFERENCES design_document (id, workspace_id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        "CREATE INDEX design_document_user_mark_by_user "
        "ON design_document_user_mark (workspace_id, user_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE design_document_user_mark")
