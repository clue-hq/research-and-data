"""design site session

Revision ID: db05b93f7377
Revises: d20a3b374a89
Create Date: 2026-10-16 13:19:57.052546+00:00

Site-turn durability (docs/superpowers/plans/2026-10-16-site-turn-durability.md §2.4, Task 5,
finding K4-5): a website's session files (``plan.md``, ``history.md``, ``fetched/``) are ONE copy
per site with a version number. The copy itself stays the existing content-addressed manifest
bundle; this row is only the pointer to the current one.

A request records the version it started from; at its end it moves the pointer with a
compare-and-set (``version = <started from>`` → ``version + 1``; the first save inserts version 1).
A worker whose local copy is stale therefore reloads the newer copy instead of overwriting it.
Sites with no row yet keep the old "newest run row" lookup until their first save writes one; old
data is not migrated.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "db05b93f7377"
down_revision: str | None = "d20a3b374a89"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE design_site_session (
            workspace_id    text        NOT NULL,
            document_id     text        NOT NULL,
            version         integer     NOT NULL,
            manifest_sha256 text        NOT NULL,
            updated_at      timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT design_site_session_pkey PRIMARY KEY (workspace_id, document_id),
            CONSTRAINT design_site_session_document_fk FOREIGN KEY (document_id, workspace_id)
                REFERENCES design_document (id, workspace_id) ON DELETE CASCADE,
            CONSTRAINT design_site_session_version_positive CHECK (version >= 1),
            CONSTRAINT design_site_session_manifest_sha_shape
                CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$')
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE design_site_session")
