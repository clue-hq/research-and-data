"""fi2 project account membership

Revision ID: 61b00ee9c70a
Revises: 9a21734d9406
Create Date: 2026-08-08 09:12:15.612237+00:00

FI-2 pillar P1 (``docs/specs/FI-2-workspace-account-layer.md`` §2): the account↔project junction.
Accounts are workspace-global (one spine, R1); *which projects target an account* is real,
queryable state (R4) rather than folklore recomputed from discovery lineage. This table is the
project lens's membership half — ``projects[]`` and ``primaryProjectId`` on the frontend account
row read from here, ``primaryProjectId`` being the earliest ``added_at`` (a recorded policy).

Both composite FKs are real: ``account_entity_workspace_anchor UNIQUE (id, workspace_id)``
(migration ``50b778e4009a``) and ``project_workspace_anchor UNIQUE (project_id, workspace_id)``
(migration ``8aba77245267``) exist, so a membership can never name an account or a project from
another workspace — the cross-workspace shape is unrepresentable, not merely validated. (The spec
writes the project FK as ``project (id, workspace_id)``; the real column is ``project.project_id``.)

``added_via`` is text + a named CHECK rather than a DB enum (no new enum types), mirroring
``clue_research.membership.ADDED_VIA``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "61b00ee9c70a"
down_revision: str | None = "9a21734d9406"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE project_account (
            workspace_id      text        NOT NULL,
            project_id        text        NOT NULL,
            account_entity_id uuid        NOT NULL,
            added_via         text        NOT NULL,
            added_at          timestamptz NOT NULL,

            CONSTRAINT project_account_pkey
                PRIMARY KEY (workspace_id, project_id, account_entity_id),
            CONSTRAINT project_account_added_via_check
                CHECK (added_via IN ('discovered','imported','manual','directive')),
            -- Composite FKs: the membership, the account, and the project share one workspace.
            CONSTRAINT project_account_account_ws_fk FOREIGN KEY (account_entity_id, workspace_id)
                REFERENCES account_entity (id, workspace_id),
            CONSTRAINT project_account_project_ws_fk FOREIGN KEY (project_id, workspace_id)
                REFERENCES project (project_id, workspace_id)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE project_account IS 'FI-2 P1: which projects target which accounts. "
        "One row per (workspace, project, account); the first add wins (added_via/added_at record "
        "the first channel and time). Earliest added_at = the primaryProjectId policy.'"
    )
    # The account-first read (``projects_for_accounts``: an account row's projects[]) does not hit
    # the (workspace, project, account) PK prefix — this index is its access path.
    op.execute(
        "CREATE INDEX project_account_by_account ON project_account "
        "(workspace_id, account_entity_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE project_account")
