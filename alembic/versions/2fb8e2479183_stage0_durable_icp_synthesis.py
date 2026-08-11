"""stage0 durable icp synthesis

Revision ID: 2fb8e2479183
Revises: 5d7ab295742b
Create Date: 2026-08-11 18:41:21.292767+00:00

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
revision: str = "2fb8e2479183"
down_revision: str | None = "5d7ab295742b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE stage0_icp_synthesis (
            operation_id          uuid PRIMARY KEY,
            workspace_id          text NOT NULL,
            brand_id              text NOT NULL,
            project_id            text NOT NULL,
            readiness_decision_id uuid NOT NULL,
            client_entity_id      uuid NOT NULL,
            client_kb_version     int NOT NULL,
            product_id            text NOT NULL,
            icp_spec_refs         jsonb NOT NULL,
            excluded_statement_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
            created_at            timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT stage0_icp_synthesis_kb_version_positive
                CHECK (client_kb_version >= 1),
            CONSTRAINT stage0_icp_synthesis_refs_array
                CHECK (jsonb_typeof(icp_spec_refs) = 'array'
                       AND jsonb_array_length(icp_spec_refs) >= 1),
            CONSTRAINT stage0_icp_synthesis_excluded_array
                CHECK (jsonb_typeof(excluded_statement_ids) = 'array'),
            CONSTRAINT stage0_icp_synthesis_workspace_fk
                FOREIGN KEY (workspace_id) REFERENCES workspace (workspace_id),
            CONSTRAINT stage0_icp_synthesis_client_fk
                FOREIGN KEY (client_entity_id, workspace_id)
                REFERENCES account_entity (id, workspace_id),
            CONSTRAINT stage0_icp_synthesis_readiness_fk
                FOREIGN KEY (
                    readiness_decision_id, workspace_id, brand_id, product_id, project_id
                ) REFERENCES readiness_decision (
                    id, workspace_id, brand_id, product_id, project_id
                )
        )
        """
    )
    op.execute(
        "CREATE INDEX stage0_icp_synthesis_project_latest "
        "ON stage0_icp_synthesis (workspace_id, project_id, created_at DESC)"
    )
    op.execute(
        """
        CREATE FUNCTION stage0_icp_synthesis_reject_update() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'stage0_icp_synthesis is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER stage0_icp_synthesis_immutable "
        "BEFORE UPDATE OR DELETE ON stage0_icp_synthesis "
        "FOR EACH ROW EXECUTE FUNCTION stage0_icp_synthesis_reject_update()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS stage0_icp_synthesis_immutable ON stage0_icp_synthesis")
    op.execute("DROP FUNCTION IF EXISTS stage0_icp_synthesis_reject_update()")
    op.execute("DROP INDEX IF EXISTS stage0_icp_synthesis_project_latest")
    op.execute("DROP TABLE IF EXISTS stage0_icp_synthesis")
