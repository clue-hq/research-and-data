"""design video rendition

Revision ID: 6fb438905f96
Revises: db05b93f7377
Create Date: 2026-10-17 06:32:21.694718+00:00

Brand facts from captured sections
(docs/superpowers/plans/2026-10-17-brand-facts-from-captured-sections.md, Task 4, controller
ruling 2026-10-17): a captured video's poster (a JPEG of the frame at 1 s) and, for a file over
1.5 MB, one smaller rendition, both made with ffmpeg at capture and stored as blobs of the
workspace. This row names them by the video's own digest, beside the fragment: the fragment
payload is immutable and content-addressed, so the facts never go into it. A re-capture skips a
digest that has a row. Either digest may be NULL (a small video has no rendition; a poster ffmpeg
could not cut has none), never both.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "6fb438905f96"
down_revision: str | None = "db05b93f7377"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE design_video_rendition (
            workspace_id     text        NOT NULL,
            video_digest     text        NOT NULL,
            poster_digest    text,
            rendition_digest text,
            created_at       timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT design_video_rendition_pkey PRIMARY KEY (workspace_id, video_digest),
            CONSTRAINT design_video_rendition_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id) ON DELETE CASCADE,
            CONSTRAINT design_video_rendition_video_shape CHECK (video_digest ~ '^[0-9a-f]{64}$'),
            CONSTRAINT design_video_rendition_poster_shape
                CHECK (poster_digest IS NULL OR poster_digest ~ '^[0-9a-f]{64}$'),
            CONSTRAINT design_video_rendition_rendition_shape
                CHECK (rendition_digest IS NULL OR rendition_digest ~ '^[0-9a-f]{64}$'),
            CONSTRAINT design_video_rendition_names_something
                CHECK (poster_digest IS NOT NULL OR rendition_digest IS NOT NULL)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE design_video_rendition")
