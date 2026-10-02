"""design leg documents

Revision ID: b9c5e4829868
Revises: d659c2d2b537
Create Date: 2026-09-19 15:32:38.475489+00:00

Spec 2026-09-19 §3.2: one open leg holds a SET of documents. ``design_leg.document_id`` keeps
meaning position 0 so every single-document reader is unchanged; this table is the set.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b9c5e4829868"
down_revision: str | None = "d659c2d2b537"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ``leg_id`` is uuid to match ``design_leg.id`` (migration 549de68ae3b9); a text column
    # cannot carry the composite FK to ``design_leg_workspace_anchor``.
    op.execute(
        """
        CREATE TABLE design_leg_document (
            leg_id        uuid NOT NULL,
            workspace_id  text NOT NULL,
            document_id   text NOT NULL,
            position      integer NOT NULL,
            note          text NOT NULL DEFAULT '',
            created_at    timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT design_leg_document_pkey PRIMARY KEY (leg_id, position),
            CONSTRAINT design_leg_document_one_per_leg UNIQUE (leg_id, document_id),
            CONSTRAINT design_leg_document_position CHECK (position >= 0),
            CONSTRAINT design_leg_document_leg_fk
                FOREIGN KEY (leg_id, workspace_id) REFERENCES design_leg (id, workspace_id),
            CONSTRAINT design_leg_document_document_fk
                FOREIGN KEY (document_id, workspace_id)
                REFERENCES design_document (id, workspace_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX design_leg_document_by_document "
        "ON design_leg_document (workspace_id, document_id)"
    )
    op.execute(
        "COMMENT ON TABLE design_leg_document IS 'The documents one design leg works on, in "
        "birth order (spec 2026-09-19 §3.2). design_leg.document_id is position 0.'"
    )
    # Backfill: every existing leg that pins a document is a one-document leg.
    op.execute(
        """
        INSERT INTO design_leg_document (leg_id, workspace_id, document_id, position, note)
        SELECT l.id, l.workspace_id, l.document_id, 0, ''
        FROM design_leg l
        JOIN design_document d ON d.id = l.document_id AND d.workspace_id = l.workspace_id
        WHERE l.document_id IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE design_leg_document")
