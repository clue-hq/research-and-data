"""durable agent turn context scope pins

Revision ID: d3672ccf43cc
Revises: b2f815da0f31
Create Date: 2026-08-14 18:28:32.951748+00:00

Conventions every migration must honour (docs/specs/M00-foundations-and-shared-contracts.md §M0.3;
see src/clue_research/db/README.md "Migration conventions checklist"):
- Append-only: claim history supersedes via ``superseded_by``; never UPDATE a value column in place.
- UTC ``timestamptz`` for time columns (e.g. ``observed_at`` / ``collected_at``).
- JSONB ``value_json`` payloads, with real indexed columns on the hot query keys (``entity_id`` …).
- Everything keys on a resolved ``entity_id`` — never a free-text name.
- Forward + reverse: ``downgrade()`` must cleanly reverse ``upgrade()`` (CI runs up → down → up).

FI production deepagent context composition **S3.1**. A fleet attempt used to resolve the
project/client/Client-KB tuple into an in-memory dataclass. A worker crash before finalization
could therefore retry the same turn against a newer background-recon version. This migration
adds one immutable, workspace-scoped scope receipt per submitted turn. It is written before card
composition or model/tool execution and reused by every later attempt.

``knowledge_scope_policy_version`` makes the semantic part of the pin replayable too: V1 means
that Client-KB cards and S4 reads are company/account-wide (the ``product_id IS NULL`` marker).
The project's confirmed product is pinned separately and does not silently filter Client-KB.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d3672ccf43cc"
down_revision: str | None = "b2f815da0f31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE agent_turn_scope_pin (
            turn_id                         uuid PRIMARY KEY,
            workspace_id                    text NOT NULL,
            project_id                      text NOT NULL,
            project_name                    text NOT NULL,
            project_status                  text NOT NULL,
            brand_id                        text NOT NULL,
            product_id                      text,
            client_entity_id                uuid,
            client_kb_version               integer,
            knowledge_scope_policy_version  text NOT NULL,
            pinned_at                       timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT agent_turn_scope_pin_submission_fk
                FOREIGN KEY (turn_id, workspace_id)
                REFERENCES agent_turn_submission (turn_id, workspace_id),
            CONSTRAINT agent_turn_scope_pin_project_fk
                FOREIGN KEY (project_id, workspace_id)
                REFERENCES project (project_id, workspace_id),
            CONSTRAINT agent_turn_scope_pin_brand_fk
                FOREIGN KEY (brand_id, workspace_id)
                REFERENCES brand (brand_id, workspace_id),
            CONSTRAINT agent_turn_scope_pin_product_fk
                FOREIGN KEY (product_id, workspace_id)
                REFERENCES product (product_id, workspace_id),
            CONSTRAINT agent_turn_scope_pin_client_fk
                FOREIGN KEY (client_entity_id, workspace_id)
                REFERENCES account_entity (id, workspace_id),
            CONSTRAINT agent_turn_scope_pin_identity_nonempty CHECK (
                length(btrim(workspace_id)) > 0
                AND length(btrim(project_id)) > 0
                AND length(btrim(project_name)) > 0
                AND length(btrim(project_status)) > 0
                AND length(btrim(brand_id)) > 0
                AND (product_id IS NULL OR length(btrim(product_id)) > 0)
                AND length(btrim(knowledge_scope_policy_version)) > 0
            ),
            CONSTRAINT agent_turn_scope_pin_client_version CHECK (
                client_kb_version IS NULL OR (
                    client_entity_id IS NOT NULL AND client_kb_version >= 1
                )
            )
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE agent_turn_scope_pin IS 'FI S3.1: immutable context scope receipt "
        "created by the AGENT_TURN worker before composition. Every retry, governed Client-KB "
        "tool call and finalization for the turn uses this exact workspace/project/client/version "
        "pin; background recon can only affect a later turn.'"
    )
    op.execute(
        "COMMENT ON COLUMN agent_turn_scope_pin.knowledge_scope_policy_version IS 'Versioned "
        "interpretation of the Client-KB pin. company-account-wide-v1 means only product_id IS "
        "NULL knowledge is admissible; confirmed project product remains a separate scope.'"
    )
    op.execute(
        "CREATE INDEX agent_turn_scope_pin_client_version "
        "ON agent_turn_scope_pin (workspace_id, client_entity_id, client_kb_version) "
        "WHERE client_entity_id IS NOT NULL"
    )
    op.execute(
        "CREATE TRIGGER agent_turn_scope_pin_append_only "
        "BEFORE UPDATE OR DELETE ON agent_turn_scope_pin "
        "FOR EACH ROW EXECUTE FUNCTION execution_reject_append_only_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS agent_turn_scope_pin_append_only ON agent_turn_scope_pin")
    op.execute("DROP INDEX IF EXISTS agent_turn_scope_pin_client_version")
    op.execute("DROP TABLE IF EXISTS agent_turn_scope_pin")
