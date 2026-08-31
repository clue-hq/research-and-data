"""workspace client context binding

Revision ID: b2f815da0f31
Revises: 9aacba7cea99
Create Date: 2026-08-14 12:34:55.188523+00:00

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
revision: str = "b2f815da0f31"
down_revision: str | None = "9aacba7cea99"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE workspace_client_binding (
            workspace_id        text NOT NULL,
            client_entity_id    uuid NOT NULL,
            source_recon_run_id uuid,
            created_at          timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT workspace_client_binding_pkey PRIMARY KEY (workspace_id),
            CONSTRAINT workspace_client_binding_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT workspace_client_binding_client_fk
                FOREIGN KEY (client_entity_id, workspace_id)
                REFERENCES account_entity (id, workspace_id),
            CONSTRAINT workspace_client_binding_recon_fk
                FOREIGN KEY (source_recon_run_id, workspace_id)
                REFERENCES recon_run (id, workspace_id)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE workspace_client_binding IS "
        "'One immutable customer/client entity inherited by every project in a workspace; "
        "created by trusted onboarding recon, never inferred from a project turn.'"
    )
    op.execute(
        "CREATE INDEX workspace_client_binding_client_lookup "
        "ON workspace_client_binding (client_entity_id, workspace_id)"
    )
    # Historical development/accepted onboarding runs can be adopted only when the workspace has
    # exactly one observed client identity. Ambiguous workspaces stay honestly unbound and require
    # an explicit operator decision; the migration never guesses which customer the workspace is.
    op.execute(
        """
        INSERT INTO workspace_client_binding (
            workspace_id, client_entity_id, source_recon_run_id, created_at
        )
        SELECT candidate.workspace_id,
               candidate.client_entity_ids[1],
               latest.id,
               latest.created_at
        FROM (
            SELECT run.workspace_id,
                   array_agg(DISTINCT run.client_entity_id) AS client_entity_ids
            FROM recon_run AS run
            JOIN account_entity AS entity
              ON entity.id = run.client_entity_id
             AND entity.workspace_id = run.workspace_id
             AND entity.merged_into IS NULL
            WHERE run.client_entity_id IS NOT NULL
            GROUP BY run.workspace_id
            HAVING count(DISTINCT client_entity_id) = 1
        ) AS candidate
        JOIN LATERAL (
            SELECT id, created_at
            FROM recon_run
            WHERE workspace_id = candidate.workspace_id
              AND client_entity_id = candidate.client_entity_ids[1]
            ORDER BY created_at DESC, id DESC
            LIMIT 1
        ) AS latest ON TRUE
        ON CONFLICT (workspace_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE workspace_client_binding")
