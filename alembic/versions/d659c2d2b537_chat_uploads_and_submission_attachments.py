"""chat uploads and submission attachments

Revision ID: d659c2d2b537
Revises: be968ae45500
Create Date: 2026-09-18 09:45:47.142803+00:00

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
revision: str = "d659c2d2b537"
down_revision: str | None = "be968ae45500"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE chat_upload (
            upload_id            uuid PRIMARY KEY,
            workspace_id         text NOT NULL,
            uploaded_by_user_id  text NOT NULL,
            filename             text NOT NULL,
            media_type           text NOT NULL,
            artifact_key         text NOT NULL REFERENCES artifact (storage_key),
            sha256               text NOT NULL,
            byte_count           bigint NOT NULL,
            created_at           timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT chat_upload_sha CHECK (sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT chat_upload_scope CHECK (artifact_key = workspace_id || '/' || sha256),
            CONSTRAINT chat_upload_filename CHECK (
                length(btrim(filename)) > 0 AND position('/' in filename) = 0
            ),
            CONSTRAINT chat_upload_bytes CHECK (byte_count >= 0)
        )
        """
    )
    op.execute("CREATE INDEX chat_upload_workspace ON chat_upload (workspace_id, created_at DESC)")
    op.execute(
        "COMMENT ON TABLE chat_upload IS 'One file a human uploaded for a chat message: the "
        "filename beside the content-addressed artifact the bytes live under (spec 2026-09-18).'"
    )
    op.execute(
        """
        CREATE TABLE agent_turn_submission_attachment (
            turn_id        uuid NOT NULL,
            workspace_id   text NOT NULL,
            ordinal        integer NOT NULL,
            upload_id      uuid NOT NULL REFERENCES chat_upload (upload_id),
            artifact_key   text NOT NULL,
            sha256         text NOT NULL,
            media_type     text NOT NULL,
            byte_count     bigint NOT NULL,
            filename       text NOT NULL,
            created_at     timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (turn_id, ordinal),
            CONSTRAINT agent_turn_submission_attachment_submission_fk
                FOREIGN KEY (turn_id, workspace_id)
                REFERENCES agent_turn_submission (turn_id, workspace_id),
            CONSTRAINT agent_turn_submission_attachment_ordinal CHECK (ordinal >= 0),
            CONSTRAINT agent_turn_submission_attachment_once UNIQUE (turn_id, upload_id)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE agent_turn_submission_attachment IS 'Ordered, immutable uploads "
        "captured with one human chat submission (spec 2026-09-18).'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE agent_turn_submission_attachment")
    op.execute("DROP INDEX chat_upload_workspace")
    op.execute("DROP TABLE chat_upload")
