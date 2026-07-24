"""C5.3 generic work fleet and lease-generation fences.

Revision ID: d9b39fb407ed
Revises: 128c83d5e151
Create Date: 2026-07-24 18:17:37.454029+00:00

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
revision: str = "d9b39fb407ed"
down_revision: str | None = "128c83d5e151"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Generalize only fleet-owned identifiers; research domain tables are untouched."""
    op.execute("ALTER TYPE fleet_task_kind ADD VALUE IF NOT EXISTS 'execute_graph'")

    op.execute("ALTER TABLE run_lease RENAME TO work_lease")
    op.execute("ALTER TABLE work_lease RENAME COLUMN project_run_id TO work_id")
    op.execute("ALTER TABLE work_lease RENAME CONSTRAINT run_lease_pkey TO work_lease_pkey")
    op.execute(
        """
        ALTER TABLE work_lease
        ADD COLUMN generation bigint NOT NULL DEFAULT 1,
        ADD CONSTRAINT work_lease_generation_positive CHECK (generation >= 1)
        """
    )

    op.execute("DROP INDEX fleet_task_run")
    op.execute("ALTER TABLE fleet_task DROP CONSTRAINT fleet_task_dedup")
    op.execute("ALTER TABLE fleet_task RENAME COLUMN project_run_id TO work_id")
    op.execute(
        "ALTER TABLE fleet_task ADD CONSTRAINT fleet_task_dedup UNIQUE (kind, work_id, dedup_key)"
    )
    op.execute("CREATE INDEX fleet_task_work ON fleet_task (work_id, kind, priority, enqueue_seq)")

    op.execute(
        """
        ALTER TABLE execution_cursor
        ADD COLUMN lease_generation bigint,
        ADD CONSTRAINT execution_cursor_lease_generation_positive
            CHECK (lease_generation IS NULL OR lease_generation >= 1)
        """
    )
    op.execute("ALTER TABLE execution ADD COLUMN parameter_artifact_key text")
    op.execute(
        """
        ALTER TABLE execution
        ADD CONSTRAINT execution_parameter_artifact_fk
            FOREIGN KEY (parameter_artifact_key, workspace_id)
            REFERENCES artifact (storage_key, workspace_id)
        """
    )
    op.execute("ALTER TABLE execution_node DROP CONSTRAINT execution_node_tool_shape")
    op.execute(
        """
        ALTER TABLE execution_node
        ADD COLUMN ordinal bigint NOT NULL DEFAULT 0,
        ADD COLUMN depth int NOT NULL DEFAULT 0,
        ADD COLUMN definition_json jsonb NOT NULL DEFAULT '{}'::jsonb,
        ADD CONSTRAINT execution_node_ordinal_nonnegative CHECK (ordinal >= 0),
        ADD CONSTRAINT execution_node_depth_nonnegative CHECK (depth >= 0),
        ADD CONSTRAINT execution_node_definition_object
            CHECK (jsonb_typeof(definition_json) = 'object'),
        ADD CONSTRAINT execution_node_tool_shape CHECK (
            (
                kind = 'tool'
                AND tool_name IS NOT NULL
                AND tool_version IS NOT NULL
                AND input_schema_sha256 IS NOT NULL
                AND output_schema_sha256 IS NOT NULL
                AND (
                    (
                        parameter_artifact_key IS NULL
                        AND parameter_sha256 IS NULL
                    )
                    OR (
                        parameter_artifact_key IS NOT NULL
                        AND parameter_sha256 IS NOT NULL
                    )
                )
            )
            OR (
                kind <> 'tool'
                AND tool_name IS NULL
                AND tool_version IS NULL
                AND parameter_artifact_key IS NULL
                AND parameter_sha256 IS NULL
                AND input_schema_sha256 IS NULL
                AND output_schema_sha256 IS NULL
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX execution_node_ready_order "
        "ON execution_node (execution_id, ordinal, node_key)"
    )
    op.execute(
        "CREATE UNIQUE INDEX execution_artifact_one_parameter_per_node "
        "ON execution_artifact_ref (execution_id, node_id) WHERE role = 'parameter'"
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM execution_node
                WHERE kind = 'tool' AND parameter_artifact_key IS NULL
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade C5.3 while pre-materialized tool nodes exist';
            END IF;
        END $$;
        """
    )
    op.execute("DROP INDEX execution_artifact_one_parameter_per_node")
    op.execute("DROP INDEX execution_node_ready_order")
    op.execute("ALTER TABLE execution_node DROP CONSTRAINT execution_node_tool_shape")
    op.execute("ALTER TABLE execution_node DROP CONSTRAINT execution_node_definition_object")
    op.execute("ALTER TABLE execution_node DROP CONSTRAINT execution_node_depth_nonnegative")
    op.execute("ALTER TABLE execution_node DROP CONSTRAINT execution_node_ordinal_nonnegative")
    op.execute("ALTER TABLE execution_node DROP COLUMN definition_json")
    op.execute("ALTER TABLE execution_node DROP COLUMN depth")
    op.execute("ALTER TABLE execution_node DROP COLUMN ordinal")
    op.execute(
        """
        ALTER TABLE execution_node
        ADD CONSTRAINT execution_node_tool_shape CHECK (
            (
                kind = 'tool'
                AND tool_name IS NOT NULL
                AND tool_version IS NOT NULL
                AND parameter_artifact_key IS NOT NULL
                AND parameter_sha256 IS NOT NULL
                AND input_schema_sha256 IS NOT NULL
                AND output_schema_sha256 IS NOT NULL
            )
            OR (kind <> 'tool' AND tool_name IS NULL AND tool_version IS NULL)
        )
        """
    )
    op.execute("ALTER TABLE execution DROP CONSTRAINT execution_parameter_artifact_fk")
    op.execute("ALTER TABLE execution DROP COLUMN parameter_artifact_key")
    op.execute(
        "ALTER TABLE execution_cursor DROP CONSTRAINT execution_cursor_lease_generation_positive"
    )
    op.execute("ALTER TABLE execution_cursor DROP COLUMN lease_generation")

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM fleet_task WHERE kind::text = 'execute_graph') THEN
                RAISE EXCEPTION
                    'cannot downgrade C5.3 while execute_graph fleet tasks exist';
            END IF;
        END $$;
        """
    )
    op.execute("DROP INDEX fleet_task_work")
    op.execute("ALTER TABLE fleet_task DROP CONSTRAINT fleet_task_dedup")
    op.execute("ALTER TABLE fleet_task RENAME COLUMN work_id TO project_run_id")
    op.execute(
        "ALTER TABLE fleet_task ADD CONSTRAINT fleet_task_dedup "
        "UNIQUE (kind, project_run_id, dedup_key)"
    )
    op.execute(
        "CREATE INDEX fleet_task_run ON fleet_task (project_run_id, kind, priority, enqueue_seq)"
    )

    op.execute("ALTER TABLE work_lease DROP CONSTRAINT work_lease_generation_positive")
    op.execute("ALTER TABLE work_lease DROP COLUMN generation")
    op.execute("ALTER TABLE work_lease RENAME CONSTRAINT work_lease_pkey TO run_lease_pkey")
    op.execute("ALTER TABLE work_lease RENAME COLUMN work_id TO project_run_id")
    op.execute("ALTER TABLE work_lease RENAME TO run_lease")

    op.execute("ALTER TYPE fleet_task_kind RENAME TO fleet_task_kind_c5_3")
    op.execute("CREATE TYPE fleet_task_kind AS ENUM ('drive_run', 'account_job')")
    op.execute(
        """
        ALTER TABLE fleet_task
        ALTER COLUMN kind TYPE fleet_task_kind
        USING kind::text::fleet_task_kind
        """
    )
    op.execute("DROP TYPE fleet_task_kind_c5_3")
