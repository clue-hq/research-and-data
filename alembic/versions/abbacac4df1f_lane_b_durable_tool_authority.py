"""lane b durable tool authority

Revision ID: abbacac4df1f
Revises: 9398ae4467e3
Create Date: 2026-08-08 12:57:21.490459+00:00

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
revision: str = "abbacac4df1f"
down_revision: str | None = "9398ae4467e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE workspace_membership ADD CONSTRAINT "
        "workspace_membership_actor_anchor UNIQUE (membership_id, user_id)"
    )
    op.execute(
        """
        CREATE TABLE execution_node_authority (
            node_id                uuid PRIMARY KEY,
            execution_id           uuid NOT NULL,
            authority_workspace_id text,
            invocation_actor       text NOT NULL,
            principal_kind         text,
            actor_id               text,
            membership_id          text,
            action_ref             text,
            created_at             timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT execution_node_authority_node_fk
                FOREIGN KEY (node_id, execution_id)
                REFERENCES execution_node (id, execution_id),
            CONSTRAINT execution_node_authority_execution_workspace_fk
                FOREIGN KEY (execution_id, authority_workspace_id)
                REFERENCES execution (id, workspace_id),
            CONSTRAINT execution_node_authority_membership_workspace_fk
                FOREIGN KEY (membership_id, authority_workspace_id)
                REFERENCES workspace_membership (membership_id, workspace_id),
            CONSTRAINT execution_node_authority_membership_actor_fk
                FOREIGN KEY (membership_id, actor_id)
                REFERENCES workspace_membership (membership_id, user_id),
            CONSTRAINT execution_node_authority_invocation_actor_check CHECK (
                invocation_actor IN ('human', 'agent')
            ),
            CONSTRAINT execution_node_authority_principal_kind_check CHECK (
                principal_kind IS NULL OR principal_kind IN ('human', 'service')
            ),
            CONSTRAINT execution_node_authority_authenticated_shape CHECK (
                (principal_kind IS NULL
                    AND authority_workspace_id IS NULL
                    AND membership_id IS NULL)
                OR (
                    principal_kind = 'human'
                    AND invocation_actor = 'human'
                    AND authority_workspace_id IS NOT NULL
                    AND actor_id IS NOT NULL
                    AND membership_id IS NOT NULL
                )
                OR (
                    principal_kind = 'service'
                    AND invocation_actor = 'agent'
                    AND authority_workspace_id IS NOT NULL
                    AND actor_id IS NOT NULL
                    AND membership_id IS NULL
                )
            ),
            CONSTRAINT execution_node_authority_actor_id_nonempty CHECK (
                actor_id IS NULL OR length(btrim(actor_id)) > 0
            ),
            CONSTRAINT execution_node_authority_membership_id_nonempty CHECK (
                membership_id IS NULL OR length(btrim(membership_id)) > 0
            ),
            CONSTRAINT execution_node_authority_action_ref_nonempty CHECK (
                action_ref IS NULL OR length(btrim(action_ref)) > 0
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX execution_node_authority_actor_audit "
        "ON execution_node_authority (principal_kind, actor_id, created_at DESC) "
        "WHERE principal_kind IS NOT NULL"
    )
    op.execute(
        "CREATE TRIGGER execution_node_authority_append_only "
        "BEFORE UPDATE OR DELETE ON execution_node_authority FOR EACH ROW "
        "EXECUTE FUNCTION execution_reject_append_only_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER execution_node_authority_append_only ON execution_node_authority")
    op.execute("DROP INDEX execution_node_authority_actor_audit")
    op.execute("DROP TABLE execution_node_authority")
    op.execute("ALTER TABLE workspace_membership DROP CONSTRAINT workspace_membership_actor_anchor")
