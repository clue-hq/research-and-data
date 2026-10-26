"""agent workspace snapshot and project library epoch

Revision ID: cd9c1e49f6af
Revises: c87ba03cfc4e
Create Date: 2026-10-22 10:00:00.000000+00:00

F3 Phase 1 (docs/superpowers/specs/agent-workspace/2026-10-21-agent-workspace-durability-design.md,
WS-1; plan docs/superpowers/plans/2026-10-22-agent-workspace-phase-1-core.md, Task 1).

``agent_workspace_snapshot`` is the version record of one chat's agent folders (``scratch/ reads/
work/ outputs/``): which file list in the artifact store is the chat's current snapshot. A turn
records the version it restored and moves the record at its end with a compare-and-set
(``version = <restored>`` → ``version + 1``; the first save inserts version 1), only while its
worker still holds the chat's fleet lease. The row deliberately has no foreign key to
``agent_thread``: research, delegation and onboarding threads keep snapshots under the same key and
have no ``agent_thread`` row of their own.

``project_library_epoch`` is a counter the project library digest includes (ruling AW-20). A
privacy erasure that changes a library file without moving any row the digest reads bumps it, so
every chat's own copy of the library resyncs on its next turn.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cd9c1e49f6af"
down_revision: str | None = "c87ba03cfc4e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE agent_workspace_snapshot (
            workspace_id          text        NOT NULL,
            thread_id             text        NOT NULL,
            project_id            text        NOT NULL,
            version               integer     NOT NULL,
            manifest_artifact_key text        NOT NULL,
            manifest_sha256       text        NOT NULL,
            last_activity_at      timestamptz NOT NULL DEFAULT now(),
            updated_at            timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT agent_workspace_snapshot_pkey PRIMARY KEY (workspace_id, thread_id),
            CONSTRAINT agent_workspace_snapshot_version_positive CHECK (version >= 1),
            CONSTRAINT agent_workspace_snapshot_manifest_sha_shape
                CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$')
        )
        """
    )
    op.execute(
        """
        CREATE TABLE project_library_epoch (
            workspace_id text        NOT NULL,
            project_id   text        NOT NULL,
            epoch        bigint      NOT NULL DEFAULT 1,
            updated_at   timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT project_library_epoch_pkey PRIMARY KEY (workspace_id, project_id),
            CONSTRAINT project_library_epoch_positive CHECK (epoch >= 1)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE project_library_epoch")
    op.execute("DROP TABLE agent_workspace_snapshot")
