"""C5.1 append-only execution journal and dormant later-slice tables.

Revision ID: 128c83d5e151
Revises: 1b71451d48cd
Create Date: 2026-07-24

The graph/event history is immutable. ``execution_cursor`` is the one rebuildable mutable
materialization. Recipe/supervisor/control tables are created now so C5 has one coherent schema;
their behavior lands in later slices.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "128c83d5e151"
down_revision: str | None = "1b71451d48cd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_APPEND_ONLY_TABLES = (
    "recipe",
    "recipe_revision",
    "recipe_revision_event",
    "execution",
    "execution_node",
    "execution_edge",
    "execution_pin",
    "execution_attempt",
    "execution_event",
    "execution_artifact_ref",
    "project_run_execution_owner",
    "supervisor_observation",
    "supervisor_diagnosis",
    "run_control_event",
)


def _install_append_only_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION execution_reject_append_only_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in _APPEND_ONLY_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_append_only "
            f"BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION execution_reject_append_only_mutation()"
        )


def _drop_append_only_guards() -> None:
    for table in reversed(_APPEND_ONLY_TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
    op.execute("DROP FUNCTION IF EXISTS execution_reject_append_only_mutation()")


def upgrade() -> None:
    # Composite anchors make every cross-table workspace relationship structural.
    op.create_unique_constraint(
        "project_run_execution_anchor",
        "project_run",
        ["id", "workspace_id", "project_id"],
    )
    op.create_unique_constraint(
        "artifact_execution_anchor",
        "artifact",
        ["storage_key", "workspace_id"],
    )

    op.execute(
        """
        CREATE TABLE recipe (
            id           uuid PRIMARY KEY,
            recipe_key   text NOT NULL,
            scope_type   text NOT NULL,
            workspace_id text,
            created_at   timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT recipe_scope_type CHECK (scope_type IN ('system', 'workspace')),
            CONSTRAINT recipe_scope_coherent CHECK (
                (scope_type = 'system' AND workspace_id IS NULL)
                OR (scope_type = 'workspace' AND workspace_id IS NOT NULL)
            ),
            CONSTRAINT recipe_key_nonempty CHECK (length(btrim(recipe_key)) > 0),
            CONSTRAINT recipe_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT recipe_scope_key_unique
                UNIQUE NULLS NOT DISTINCT (scope_type, workspace_id, recipe_key)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE recipe_revision (
            id                       uuid PRIMARY KEY,
            recipe_id                uuid NOT NULL,
            version                  int NOT NULL,
            executor_protocol        int NOT NULL,
            parameter_schema_json    jsonb NOT NULL,
            graph_json               jsonb NOT NULL,
            compatibility_json       jsonb NOT NULL,
            requested_memory_types   jsonb NOT NULL DEFAULT '[]'::jsonb,
            max_nodes                int NOT NULL,
            max_depth                int NOT NULL,
            max_fanout               int NOT NULL,
            source_execution_id      uuid,
            definition_sha256        text NOT NULL,
            created_by               text NOT NULL,
            created_at               timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT recipe_revision_recipe_fk FOREIGN KEY (recipe_id)
                REFERENCES recipe (id),
            CONSTRAINT recipe_revision_version_positive CHECK (version >= 1),
            CONSTRAINT recipe_revision_protocol_positive CHECK (executor_protocol >= 1),
            CONSTRAINT recipe_revision_parameter_object CHECK (
                jsonb_typeof(parameter_schema_json) = 'object'
            ),
            CONSTRAINT recipe_revision_graph_object CHECK (jsonb_typeof(graph_json) = 'object'),
            CONSTRAINT recipe_revision_compatibility_object CHECK (
                jsonb_typeof(compatibility_json) = 'object'
            ),
            CONSTRAINT recipe_revision_memory_array CHECK (
                jsonb_typeof(requested_memory_types) = 'array'
            ),
            CONSTRAINT recipe_revision_envelopes_positive CHECK (
                max_nodes >= 1 AND max_depth >= 1 AND max_fanout >= 1
            ),
            CONSTRAINT recipe_revision_sha CHECK (
                definition_sha256 ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT recipe_revision_actor CHECK (
                created_by IN ('human', 'agent', 'system')
            ),
            CONSTRAINT recipe_revision_version_unique UNIQUE (recipe_id, version),
            CONSTRAINT recipe_revision_definition_unique UNIQUE (recipe_id, definition_sha256)
        )
        """
    )
    op.execute(
        "CREATE INDEX recipe_revision_recipe_version ON recipe_revision (recipe_id, version DESC)"
    )
    op.execute(
        """
        CREATE TABLE recipe_revision_event (
            seq                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            recipe_revision_id uuid NOT NULL,
            event_type         text NOT NULL,
            actor              text NOT NULL,
            reason_code        text,
            created_at         timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT recipe_revision_event_revision_fk FOREIGN KEY (recipe_revision_id)
                REFERENCES recipe_revision (id),
            CONSTRAINT recipe_revision_event_type CHECK (
                event_type IN ('proposed', 'promoted', 'retired', 'superseded')
            ),
            CONSTRAINT recipe_revision_event_actor CHECK (
                actor IN ('human', 'agent', 'system')
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX recipe_revision_event_effective "
        "ON recipe_revision_event (recipe_revision_id, seq DESC)"
    )

    op.execute(
        """
        CREATE TABLE execution (
            id                      uuid PRIMARY KEY,
            workspace_id            text NOT NULL,
            project_id              text,
            project_run_id          uuid,
            recipe_revision_id      uuid,
            parent_execution_id     uuid,
            started_by              text NOT NULL,
            started_at              timestamptz NOT NULL DEFAULT now(),
            parameter_manifest_hash text NOT NULL,
            pin_manifest_hash       text NOT NULL,

            CONSTRAINT execution_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT execution_project_fk FOREIGN KEY (project_id, workspace_id)
                REFERENCES project (project_id, workspace_id),
            CONSTRAINT execution_project_run_fk
                FOREIGN KEY (project_run_id, workspace_id, project_id)
                REFERENCES project_run (id, workspace_id, project_id),
            CONSTRAINT execution_recipe_revision_fk FOREIGN KEY (recipe_revision_id)
                REFERENCES recipe_revision (id),
            CONSTRAINT execution_parent_fk FOREIGN KEY (parent_execution_id, workspace_id)
                REFERENCES execution (id, workspace_id),
            CONSTRAINT execution_run_requires_project CHECK (
                project_run_id IS NULL OR project_id IS NOT NULL
            ),
            CONSTRAINT execution_actor CHECK (
                started_by IN ('human', 'agent', 'system')
            ),
            CONSTRAINT execution_parameter_manifest_sha CHECK (
                parameter_manifest_hash ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT execution_pin_manifest_sha CHECK (
                pin_manifest_hash ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT execution_workspace_anchor UNIQUE (id, workspace_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX execution_workspace_started ON execution (workspace_id, started_at DESC)"
    )
    op.execute(
        "ALTER TABLE recipe_revision ADD CONSTRAINT recipe_revision_source_execution_fk "
        "FOREIGN KEY (source_execution_id) REFERENCES execution (id)"
    )

    op.execute(
        """
        CREATE TABLE execution_cursor (
            execution_id      uuid PRIMARY KEY,
            status            text NOT NULL,
            state_version     bigint NOT NULL DEFAULT 0,
            active_node_count int NOT NULL DEFAULT 0,
            last_event_seq    bigint,
            updated_at        timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT execution_cursor_execution_fk FOREIGN KEY (execution_id)
                REFERENCES execution (id),
            CONSTRAINT execution_cursor_status CHECK (
                status IN ('queued', 'running', 'awaiting_input', 'paused', 'completed', 'failed')
            ),
            CONSTRAINT execution_cursor_version_nonnegative CHECK (state_version >= 0),
            CONSTRAINT execution_cursor_active_nonnegative CHECK (active_node_count >= 0)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE execution_node (
            id                     uuid PRIMARY KEY,
            execution_id           uuid NOT NULL,
            node_key               text NOT NULL,
            kind                   text NOT NULL,
            tool_name              text,
            tool_version           text,
            operation_id           uuid NOT NULL,
            parameter_artifact_key text,
            parameter_sha256       text,
            input_schema_sha256    text,
            output_schema_sha256   text,
            display_params_json    jsonb NOT NULL DEFAULT '{}'::jsonb,
            declared_by_node_id    uuid,
            created_at             timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT execution_node_execution_fk FOREIGN KEY (execution_id)
                REFERENCES execution (id),
            CONSTRAINT execution_node_declared_by_fk
                FOREIGN KEY (declared_by_node_id, execution_id)
                REFERENCES execution_node (id, execution_id),
            CONSTRAINT execution_node_parameter_artifact_fk FOREIGN KEY (parameter_artifact_key)
                REFERENCES artifact (storage_key),
            CONSTRAINT execution_node_kind CHECK (
                kind IN ('tool', 'gate', 'map', 'barrier', 'activity')
            ),
            CONSTRAINT execution_node_tool_shape CHECK (
                (kind = 'tool'
                    AND tool_name IS NOT NULL
                    AND tool_version IS NOT NULL
                    AND parameter_artifact_key IS NOT NULL
                    AND parameter_sha256 IS NOT NULL
                    AND input_schema_sha256 IS NOT NULL
                    AND output_schema_sha256 IS NOT NULL)
                OR (kind <> 'tool' AND tool_name IS NULL AND tool_version IS NULL)
            ),
            CONSTRAINT execution_node_parameter_sha CHECK (
                parameter_sha256 IS NULL OR parameter_sha256 ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT execution_node_input_schema_sha CHECK (
                input_schema_sha256 IS NULL OR input_schema_sha256 ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT execution_node_output_schema_sha CHECK (
                output_schema_sha256 IS NULL OR output_schema_sha256 ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT execution_node_display_object CHECK (
                jsonb_typeof(display_params_json) = 'object'
            ),
            CONSTRAINT execution_node_key_nonempty CHECK (length(btrim(node_key)) > 0),
            CONSTRAINT execution_node_address_nonempty CHECK (
                (tool_name IS NULL OR length(btrim(tool_name)) > 0)
                AND (tool_version IS NULL OR length(btrim(tool_version)) > 0)
            ),
            CONSTRAINT execution_node_key_unique UNIQUE (execution_id, node_key),
            CONSTRAINT execution_node_operation_unique UNIQUE (execution_id, operation_id),
            CONSTRAINT execution_node_context_anchor UNIQUE (id, execution_id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE execution_edge (
            execution_id uuid NOT NULL,
            from_node_id uuid NOT NULL,
            to_node_id   uuid NOT NULL,
            edge_kind    text NOT NULL,
            binding_json jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at   timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT execution_edge_from_fk FOREIGN KEY (from_node_id, execution_id)
                REFERENCES execution_node (id, execution_id),
            CONSTRAINT execution_edge_to_fk FOREIGN KEY (to_node_id, execution_id)
                REFERENCES execution_node (id, execution_id),
            CONSTRAINT execution_edge_kind CHECK (
                edge_kind IN ('dependency', 'data', 'parent')
            ),
            CONSTRAINT execution_edge_binding_object CHECK (
                jsonb_typeof(binding_json) = 'object'
            ),
            CONSTRAINT execution_edge_no_self CHECK (from_node_id <> to_node_id),
            CONSTRAINT execution_edge_pkey
                PRIMARY KEY (execution_id, from_node_id, to_node_id, edge_kind)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE execution_pin (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            execution_id    uuid NOT NULL,
            node_id         uuid,
            kind            text NOT NULL,
            key             text NOT NULL,
            version         text,
            digest          text NOT NULL,
            resolved_status text NOT NULL,
            metadata_json   jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at      timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT execution_pin_execution_fk FOREIGN KEY (execution_id)
                REFERENCES execution (id),
            CONSTRAINT execution_pin_node_fk FOREIGN KEY (node_id, execution_id)
                REFERENCES execution_node (id, execution_id),
            CONSTRAINT execution_pin_digest_nonempty CHECK (length(btrim(digest)) > 0),
            CONSTRAINT execution_pin_identity_nonempty CHECK (
                length(btrim(kind)) > 0 AND length(btrim(key)) > 0
                AND length(btrim(resolved_status)) > 0
            ),
            CONSTRAINT execution_pin_metadata_object CHECK (
                jsonb_typeof(metadata_json) = 'object'
            ),
            CONSTRAINT execution_pin_identity_unique
                UNIQUE NULLS NOT DISTINCT (execution_id, node_id, kind, key)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE execution_attempt (
            id               uuid PRIMARY KEY,
            execution_id     uuid NOT NULL,
            node_id          uuid NOT NULL,
            attempt          int NOT NULL,
            worker_id        text,
            lease_generation bigint,
            started_at       timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT execution_attempt_node_fk FOREIGN KEY (node_id, execution_id)
                REFERENCES execution_node (id, execution_id),
            CONSTRAINT execution_attempt_number_positive CHECK (attempt >= 1),
            CONSTRAINT execution_attempt_lease_nonnegative CHECK (
                lease_generation IS NULL OR lease_generation >= 0
            ),
            CONSTRAINT execution_attempt_number_unique UNIQUE (node_id, attempt),
            CONSTRAINT execution_attempt_context_anchor
                UNIQUE (id, execution_id, node_id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE execution_event (
            seq          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            execution_id uuid NOT NULL,
            node_id      uuid,
            attempt_id   uuid,
            event_type   text NOT NULL,
            actor        text NOT NULL,
            payload_json jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at   timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT execution_event_execution_fk FOREIGN KEY (execution_id)
                REFERENCES execution (id),
            CONSTRAINT execution_event_node_fk FOREIGN KEY (node_id, execution_id)
                REFERENCES execution_node (id, execution_id),
            CONSTRAINT execution_event_attempt_fk
                FOREIGN KEY (attempt_id, execution_id, node_id)
                REFERENCES execution_attempt (id, execution_id, node_id),
            CONSTRAINT execution_event_attempt_requires_node CHECK (
                attempt_id IS NULL OR node_id IS NOT NULL
            ),
            CONSTRAINT execution_event_type CHECK (
                event_type IN (
                    'execution.queued', 'execution.started', 'execution.paused',
                    'execution.resumed', 'execution.completed', 'execution.failed',
                    'node.scheduled', 'node.started', 'node.blocked', 'node.completed',
                    'node.failed', 'node.abandoned', 'gate.opened', 'gate.decided',
                    'steering.before', 'steering.after', 'supervisor.observed',
                    'supervisor.diagnosed', 'supervisor.actioned'
                )
            ),
            CONSTRAINT execution_event_actor CHECK (
                actor IN ('human', 'agent', 'system')
            ),
            CONSTRAINT execution_event_payload_object CHECK (
                jsonb_typeof(payload_json) = 'object'
            )
        )
        """
    )
    op.execute("CREATE INDEX execution_event_execution_seq ON execution_event (execution_id, seq)")
    op.execute(
        "CREATE INDEX execution_event_effective "
        "ON execution_event (execution_id, event_type, seq DESC)"
    )
    op.execute(
        "CREATE UNIQUE INDEX execution_event_node_terminal_once "
        "ON execution_event (node_id) "
        "WHERE event_type IN ('node.completed', 'node.blocked')"
    )
    op.execute(
        "CREATE UNIQUE INDEX execution_event_execution_terminal_once "
        "ON execution_event (execution_id) "
        "WHERE node_id IS NULL "
        "AND event_type IN ('execution.completed', 'execution.failed')"
    )

    op.execute(
        """
        CREATE TABLE execution_artifact_ref (
            id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            execution_id   uuid NOT NULL,
            node_id        uuid NOT NULL,
            workspace_id   text NOT NULL,
            artifact_key   text NOT NULL,
            role           text NOT NULL,
            content_sha256 text NOT NULL,
            created_at     timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT execution_artifact_ref_execution_fk
                FOREIGN KEY (execution_id, workspace_id)
                REFERENCES execution (id, workspace_id),
            CONSTRAINT execution_artifact_ref_node_fk FOREIGN KEY (node_id, execution_id)
                REFERENCES execution_node (id, execution_id),
            CONSTRAINT execution_artifact_ref_artifact_fk
                FOREIGN KEY (artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT execution_artifact_ref_role CHECK (
                role IN ('parameter', 'input', 'output')
            ),
            CONSTRAINT execution_artifact_ref_sha CHECK (
                content_sha256 ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT execution_artifact_ref_unique
                UNIQUE (execution_id, node_id, artifact_key, role)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE project_run_execution_owner (
            project_run_id uuid PRIMARY KEY,
            execution_id   uuid NOT NULL,
            workspace_id   text NOT NULL,
            project_id     text NOT NULL,
            routing_mode   text NOT NULL,
            attached_at    timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT project_run_execution_owner_run_fk
                FOREIGN KEY (project_run_id, workspace_id, project_id)
                REFERENCES project_run (id, workspace_id, project_id),
            CONSTRAINT project_run_execution_owner_execution_fk
                FOREIGN KEY (execution_id, workspace_id)
                REFERENCES execution (id, workspace_id),
            CONSTRAINT project_run_execution_owner_mode CHECK (routing_mode = 'recipe'),
            CONSTRAINT project_run_execution_owner_execution_unique UNIQUE (execution_id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE supervisor_observation (
            id                      uuid PRIMARY KEY,
            execution_id            uuid NOT NULL,
            workspace_id            text NOT NULL,
            project_run_id          uuid,
            project_id              text,
            policy_version          text NOT NULL,
            aggregate_snapshot_json jsonb NOT NULL,
            trigger_codes_json      jsonb NOT NULL DEFAULT '[]'::jsonb,
            created_at              timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT supervisor_observation_execution_fk
                FOREIGN KEY (execution_id, workspace_id)
                REFERENCES execution (id, workspace_id),
            CONSTRAINT supervisor_observation_project_run_fk
                FOREIGN KEY (project_run_id, workspace_id, project_id)
                REFERENCES project_run (id, workspace_id, project_id),
            CONSTRAINT supervisor_observation_run_context CHECK (
                project_run_id IS NULL OR project_id IS NOT NULL
            ),
            CONSTRAINT supervisor_observation_snapshot_object CHECK (
                jsonb_typeof(aggregate_snapshot_json) = 'object'
            ),
            CONSTRAINT supervisor_observation_triggers_array CHECK (
                jsonb_typeof(trigger_codes_json) = 'array'
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE supervisor_diagnosis (
            id                   uuid PRIMARY KEY,
            observation_id       uuid NOT NULL,
            requested_model      text NOT NULL,
            answering_model      text NOT NULL,
            prompt_version       text NOT NULL,
            diagnosis_codes_json jsonb NOT NULL,
            affected_refs_json   jsonb NOT NULL,
            confidence           numeric NOT NULL,
            created_at           timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT supervisor_diagnosis_observation_fk FOREIGN KEY (observation_id)
                REFERENCES supervisor_observation (id),
            CONSTRAINT supervisor_diagnosis_codes_array CHECK (
                jsonb_typeof(diagnosis_codes_json) = 'array'
            ),
            CONSTRAINT supervisor_diagnosis_refs_array CHECK (
                jsonb_typeof(affected_refs_json) = 'array'
            ),
            CONSTRAINT supervisor_diagnosis_confidence CHECK (
                confidence >= 0 AND confidence <= 1
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE run_control_event (
            seq             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            execution_id    uuid NOT NULL,
            workspace_id    text NOT NULL,
            control_kind    text NOT NULL,
            subject_ref     text NOT NULL,
            action          text NOT NULL,
            before_json     jsonb NOT NULL DEFAULT '{}'::jsonb,
            after_json      jsonb NOT NULL DEFAULT '{}'::jsonb,
            reason_code     text NOT NULL,
            observation_id  uuid,
            diagnosis_id    uuid,
            actor           text NOT NULL,
            created_at      timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT run_control_event_execution_fk
                FOREIGN KEY (execution_id, workspace_id)
                REFERENCES execution (id, workspace_id),
            CONSTRAINT run_control_event_observation_fk FOREIGN KEY (observation_id)
                REFERENCES supervisor_observation (id),
            CONSTRAINT run_control_event_diagnosis_fk FOREIGN KEY (diagnosis_id)
                REFERENCES supervisor_diagnosis (id),
            CONSTRAINT run_control_event_kind CHECK (
                control_kind IN (
                    'account_quarantine', 'source_breaker', 'envelope', 'escalation'
                )
            ),
            CONSTRAINT run_control_event_action CHECK (
                action IN ('apply', 'release', 'acknowledge')
            ),
            CONSTRAINT run_control_event_actor CHECK (
                actor IN ('human', 'agent', 'system')
            ),
            CONSTRAINT run_control_event_before_object CHECK (
                jsonb_typeof(before_json) = 'object'
            ),
            CONSTRAINT run_control_event_after_object CHECK (
                jsonb_typeof(after_json) = 'object'
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX run_control_event_effective "
        "ON run_control_event (execution_id, control_kind, subject_ref, seq DESC)"
    )

    # The existing SSE outbox gains an execution ref. Existing project-run events stay valid.
    op.execute("ALTER TABLE run_event ADD COLUMN execution_id uuid")
    op.execute(
        "ALTER TABLE run_event ADD CONSTRAINT run_event_execution_fk "
        "FOREIGN KEY (execution_id, workspace_id) REFERENCES execution (id, workspace_id)"
    )
    op.execute(
        "CREATE INDEX run_event_workspace_execution_seq "
        "ON run_event (workspace_id, execution_id, seq) WHERE execution_id IS NOT NULL"
    )

    _install_append_only_guards()


def downgrade() -> None:
    _drop_append_only_guards()

    op.execute("DROP INDEX IF EXISTS run_event_workspace_execution_seq")
    op.execute("ALTER TABLE run_event DROP CONSTRAINT IF EXISTS run_event_execution_fk")
    op.execute("ALTER TABLE run_event DROP COLUMN IF EXISTS execution_id")

    op.execute("DROP INDEX IF EXISTS run_control_event_effective")
    op.execute("DROP TABLE IF EXISTS run_control_event")
    op.execute("DROP TABLE IF EXISTS supervisor_diagnosis")
    op.execute("DROP TABLE IF EXISTS supervisor_observation")
    op.execute("DROP TABLE IF EXISTS project_run_execution_owner")
    op.execute("DROP TABLE IF EXISTS execution_artifact_ref")
    op.execute("DROP INDEX IF EXISTS execution_event_execution_terminal_once")
    op.execute("DROP INDEX IF EXISTS execution_event_node_terminal_once")
    op.execute("DROP INDEX IF EXISTS execution_event_effective")
    op.execute("DROP INDEX IF EXISTS execution_event_execution_seq")
    op.execute("DROP TABLE IF EXISTS execution_event")
    op.execute("DROP TABLE IF EXISTS execution_attempt")
    op.execute("DROP TABLE IF EXISTS execution_pin")
    op.execute("DROP TABLE IF EXISTS execution_edge")
    op.execute("DROP TABLE IF EXISTS execution_node")
    op.execute("DROP TABLE IF EXISTS execution_cursor")
    op.execute(
        "ALTER TABLE recipe_revision DROP CONSTRAINT IF EXISTS recipe_revision_source_execution_fk"
    )
    op.execute("DROP INDEX IF EXISTS execution_workspace_started")
    op.execute("DROP TABLE IF EXISTS execution")
    op.execute("DROP INDEX IF EXISTS recipe_revision_event_effective")
    op.execute("DROP TABLE IF EXISTS recipe_revision_event")
    op.execute("DROP INDEX IF EXISTS recipe_revision_recipe_version")
    op.execute("DROP TABLE IF EXISTS recipe_revision")
    op.execute("DROP TABLE IF EXISTS recipe")

    op.drop_constraint("artifact_execution_anchor", "artifact", type_="unique")
    op.drop_constraint("project_run_execution_anchor", "project_run", type_="unique")
