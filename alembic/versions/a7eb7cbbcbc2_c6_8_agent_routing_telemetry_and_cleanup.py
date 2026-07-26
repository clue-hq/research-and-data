"""c6_8 agent routing telemetry and cleanup

Revision ID: a7eb7cbbcbc2
Revises: 6e30fac321bf
Create Date: 2026-07-26 12:51:23.308578+00:00

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
revision: str = "a7eb7cbbcbc2"
down_revision: str | None = "6e30fac321bf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION c68_reject_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'C6.8 routing and operations receipts are append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "ALTER TABLE agent_model_call "
        "ADD COLUMN cache_read_input_tokens integer NOT NULL DEFAULT 0, "
        "ADD COLUMN cache_creation_input_tokens integer NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE agent_model_call ADD CONSTRAINT agent_model_call_cache_counts "
        "CHECK (cache_read_input_tokens >= 0 AND cache_creation_input_tokens >= 0 "
        "AND cache_read_input_tokens <= input_tokens)"
    )
    op.execute(
        """
        CREATE TABLE agent_runtime_route (
            id uuid PRIMARY KEY,
            workspace_id text NOT NULL REFERENCES workspace (workspace_id),
            surface text NOT NULL,
            subject_id text NOT NULL,
            owner text NOT NULL,
            selection_source text NOT NULL,
            cohort_bucket integer,
            configured_percent integer NOT NULL,
            config_sha256 text NOT NULL,
            decided_at timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT agent_runtime_route_subject UNIQUE (workspace_id, surface, subject_id),
            CONSTRAINT agent_runtime_route_surface
                CHECK (surface IN ('stage0', 'account_research')),
            CONSTRAINT agent_runtime_route_owner CHECK (owner IN ('legacy', 'deepagent')),
            CONSTRAINT agent_runtime_route_source
                CHECK (selection_source IN
                    ('master_disabled', 'surface_disabled', 'allowlist', 'percentage',
                     'not_selected')),
            CONSTRAINT agent_runtime_route_bucket
                CHECK (cohort_bucket IS NULL OR cohort_bucket BETWEEN 0 AND 99),
            CONSTRAINT agent_runtime_route_percent
                CHECK (configured_percent BETWEEN 0 AND 100),
            CONSTRAINT agent_runtime_route_hash CHECK (config_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT agent_runtime_route_source_shape CHECK (
                (selection_source='allowlist' AND owner='deepagent')
                OR (selection_source='percentage' AND owner='deepagent'
                    AND cohort_bucket IS NOT NULL AND cohort_bucket < configured_percent)
                OR (selection_source IN
                    ('master_disabled', 'surface_disabled', 'not_selected')
                    AND owner='legacy')
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX agent_runtime_route_workspace "
        "ON agent_runtime_route (workspace_id, surface, decided_at)"
    )
    op.execute(
        """
        CREATE TABLE agent_workspace_usage (
            turn_id uuid PRIMARY KEY,
            workspace_id text NOT NULL,
            file_count integer NOT NULL,
            total_bytes bigint NOT NULL,
            output_file_count integer NOT NULL,
            output_bytes bigint NOT NULL,
            max_file_count integer NOT NULL,
            max_total_bytes bigint NOT NULL,
            recorded_at timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT agent_workspace_usage_turn_fk
                FOREIGN KEY (turn_id, workspace_id) REFERENCES agent_turn (id, workspace_id),
            CONSTRAINT agent_workspace_usage_counts CHECK (
                file_count >= 0 AND total_bytes >= 0
                AND output_file_count >= 0 AND output_bytes >= 0
                AND output_file_count <= file_count AND output_bytes <= total_bytes
                AND max_file_count >= file_count AND max_total_bytes >= total_bytes
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE agent_workspace_cleanup_event (
            id uuid PRIMARY KEY,
            turn_id uuid NOT NULL,
            execution_id uuid NOT NULL,
            workspace_id text NOT NULL,
            workspace_root_id text NOT NULL,
            action text NOT NULL,
            reason_code text NOT NULL,
            removed boolean NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT agent_workspace_cleanup_turn_unique UNIQUE (turn_id, action),
            CONSTRAINT agent_workspace_cleanup_turn_fk
                FOREIGN KEY (turn_id, execution_id, workspace_id)
                REFERENCES agent_turn (id, execution_id, workspace_id),
            CONSTRAINT agent_workspace_cleanup_action
                CHECK (action IN ('terminal_retention_purge', 'materialization_failure_purge')),
            CONSTRAINT agent_workspace_cleanup_nonempty CHECK (
                length(btrim(workspace_root_id)) > 0 AND length(btrim(reason_code)) > 0
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX agent_workspace_cleanup_scope "
        "ON agent_workspace_cleanup_event (workspace_id, created_at)"
    )
    for table in (
        "agent_runtime_route",
        "agent_workspace_usage",
        "agent_workspace_cleanup_event",
    ):
        for operation in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER {table}_no_{operation.lower()} "
                f"BEFORE {operation} ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION c68_reject_mutation()"
            )


def downgrade() -> None:
    for table in (
        "agent_workspace_cleanup_event",
        "agent_workspace_usage",
        "agent_runtime_route",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_delete ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_update ON {table}")
        op.execute(f"DROP TABLE IF EXISTS {table}")
    op.execute(
        "ALTER TABLE agent_model_call DROP CONSTRAINT IF EXISTS agent_model_call_cache_counts"
    )
    op.execute(
        "ALTER TABLE agent_model_call "
        "DROP COLUMN IF EXISTS cache_creation_input_tokens, "
        "DROP COLUMN IF EXISTS cache_read_input_tokens"
    )
    op.execute("DROP FUNCTION IF EXISTS c68_reject_mutation")
