"""design document thumbnail cache index

Revision ID: be0659753362
Revises: 4c02d8eac29a
Create Date: 2026-08-30 21:14:03.394175+00:00

One table, ``design_document_thumbnail``: one row per ``(workspace, document, version)`` naming
the blob-store digest that holds the rendered PNG a gallery card shows. The bytes themselves live
where every other design blob lives — platform storage under ``{workspace_id}/design/{sha256}`` —
so this table holds no image data, only the pointer that saves a re-render.

**Deliberately FK-free, both ways.** No FK to the ``artifact`` row, because a design blob is
content-addressed per workspace and a dangling digest is repaired by regenerating the thumbnail at
read time — a constraint would turn a self-healing miss into a write failure. No FK to
``design_document`` either: this is a pure cache, and a cache must never be the thing that blocks
a document delete.

**Tenancy is structural**, the way every design table added since the D1 port keys itself: the
primary key leads with ``workspace_id``, so one tenant's cached thumbnail is neither readable nor
overwritable from another workspace even for an identical document id. Rows for superseded
versions are simply kept — pruning is future work, not something a read path should be doing.

Hand-written and reversible: ``downgrade()`` drops the table (CI runs up -> down -> up). No data
migration is owed — the cache is born empty and fills itself on the first gallery read.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "be0659753362"
down_revision: str | None = "4c02d8eac29a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE design_document_thumbnail (
            workspace_id text NOT NULL,
            document_id  text NOT NULL,
            version      integer NOT NULL,
            sha256       text NOT NULL,
            media_type   text NOT NULL,
            created_at   timestamptz NOT NULL DEFAULT now(),

            -- Workspace-first, so a tenant's slot is its own. See the docstring.
            CONSTRAINT pk_design_document_thumbnail
                PRIMARY KEY (workspace_id, document_id, version)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE design_document_thumbnail IS 'Gallery-card thumbnail cache: one row "
        "per (workspace, document, version) naming the design-blob digest that holds the "
        "rendered PNG. Pointer rows only — the bytes live in platform storage under "
        "{workspace_id}/design/{sha256}. No foreign keys by design, in either direction: a "
        "dangling digest is repaired by regenerating the thumbnail on the next read, and a pure "
        "cache must never block a document delete.'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE design_document_thumbnail")
