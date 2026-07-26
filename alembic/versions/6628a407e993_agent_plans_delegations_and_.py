"""agent plans delegations and finalization authority

Revision ID: 6628a407e993
Revises: 7e9269ed8a81
Create Date: 2026-07-26 08:09:50.811476+00:00

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
revision: str = "6628a407e993"
down_revision: str | None = "7e9269ed8a81"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE agent_plan (
            id                         uuid PRIMARY KEY,
            turn_id                    uuid NOT NULL,
            execution_id               uuid NOT NULL,
            workspace_id               text NOT NULL,
            role                       text NOT NULL,
            proposal_artifact_key      text NOT NULL,
            proposal_sha256             text NOT NULL,
            validated_artifact_key     text NOT NULL,
            validated_sha256            text NOT NULL,
            resource_manifest_sha256   text NOT NULL,
            max_parallelism            int NOT NULL,
            estimated_cost_millicents  bigint NOT NULL,
            budget_limit_millicents    bigint NOT NULL,
            validated_at               timestamptz NOT NULL,

            CONSTRAINT agent_plan_turn_fk
                FOREIGN KEY (turn_id, execution_id, workspace_id)
                REFERENCES agent_turn (id, execution_id, workspace_id),
            CONSTRAINT agent_plan_execution_fk
                FOREIGN KEY (execution_id, workspace_id)
                REFERENCES execution (id, workspace_id),
            CONSTRAINT agent_plan_proposal_artifact_fk
                FOREIGN KEY (proposal_artifact_key) REFERENCES artifact (storage_key),
            CONSTRAINT agent_plan_validated_artifact_fk
                FOREIGN KEY (validated_artifact_key) REFERENCES artifact (storage_key),
            CONSTRAINT agent_plan_workspace_anchor UNIQUE (id, workspace_id),
            CONSTRAINT agent_plan_role CHECK (
                role IN ('head_of_abm', 'research', 'content_drafter', 'reviewer',
                         'account_research')
            ),
            CONSTRAINT agent_plan_hashes CHECK (
                proposal_sha256 ~ '^[0-9a-f]{64}$'
                AND validated_sha256 ~ '^[0-9a-f]{64}$'
                AND resource_manifest_sha256 ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT agent_plan_artifact_scope CHECK (
                proposal_artifact_key = workspace_id || '/' || proposal_sha256
                AND validated_artifact_key = workspace_id || '/' || validated_sha256
            ),
            CONSTRAINT agent_plan_limits CHECK (
                max_parallelism BETWEEN 1 AND 32
                AND estimated_cost_millicents >= 0
                AND budget_limit_millicents >= estimated_cost_millicents
            )
        )
        """
    )
    op.execute("CREATE INDEX agent_plan_turn_validated ON agent_plan (turn_id, validated_at, id)")
    op.execute(
        """
        CREATE TABLE agent_plan_event (
            seq          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            event_id     uuid NOT NULL UNIQUE,
            plan_id      uuid NOT NULL,
            workspace_id text NOT NULL,
            status       text NOT NULL,
            reason_code  text,
            created_at   timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT agent_plan_event_plan_fk
                FOREIGN KEY (plan_id, workspace_id)
                REFERENCES agent_plan (id, workspace_id),
            CONSTRAINT agent_plan_event_status CHECK (
                status IN ('validated', 'running', 'completed', 'failed', 'abandoned')
            ),
            CONSTRAINT agent_plan_event_reason CHECK (
                (status IN ('failed', 'abandoned') AND reason_code IS NOT NULL)
                OR (status NOT IN ('failed', 'abandoned') AND reason_code IS NULL)
            )
        )
        """
    )
    op.execute("CREATE INDEX agent_plan_event_effective ON agent_plan_event (plan_id, seq DESC)")
    op.execute(
        """
        CREATE TABLE agent_plan_operation (
            plan_id                     uuid NOT NULL,
            workspace_id                text NOT NULL,
            ordinal                     int NOT NULL,
            node_key                    text NOT NULL,
            operation_id                uuid NOT NULL,
            kind                        text NOT NULL,
            address                     text NOT NULL,
            parameter_artifact_key      text NOT NULL,
            parameter_sha256             text NOT NULL,
            estimated_cost_millicents   bigint NOT NULL,
            authority_sha256             text NOT NULL,

            CONSTRAINT agent_plan_operation_pk PRIMARY KEY (plan_id, node_key),
            CONSTRAINT agent_plan_operation_ordinal_unique UNIQUE (plan_id, ordinal),
            CONSTRAINT agent_plan_operation_identity_unique UNIQUE (operation_id),
            CONSTRAINT agent_plan_operation_plan_fk
                FOREIGN KEY (plan_id, workspace_id)
                REFERENCES agent_plan (id, workspace_id),
            CONSTRAINT agent_plan_operation_artifact_fk
                FOREIGN KEY (parameter_artifact_key) REFERENCES artifact (storage_key),
            CONSTRAINT agent_plan_operation_kind CHECK (kind IN ('tool', 'delegation')),
            CONSTRAINT agent_plan_operation_ordinal CHECK (
                ordinal >= 0 AND estimated_cost_millicents >= 0
            ),
            CONSTRAINT agent_plan_operation_hashes CHECK (
                parameter_sha256 ~ '^[0-9a-f]{64}$'
                AND authority_sha256 ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT agent_plan_operation_artifact_scope CHECK (
                parameter_artifact_key = workspace_id || '/' || parameter_sha256
            ),
            CONSTRAINT agent_plan_operation_address CHECK (
                length(btrim(node_key)) > 0 AND length(btrim(address)) > 0
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE agent_plan_dependency (
            plan_id            uuid NOT NULL,
            workspace_id       text NOT NULL,
            node_key           text NOT NULL,
            dependency_node_key text NOT NULL,
            ordinal            int NOT NULL,

            CONSTRAINT agent_plan_dependency_pk PRIMARY KEY (
                plan_id, node_key, dependency_node_key
            ),
            CONSTRAINT agent_plan_dependency_position UNIQUE (plan_id, node_key, ordinal),
            CONSTRAINT agent_plan_dependency_node_fk
                FOREIGN KEY (plan_id, node_key)
                REFERENCES agent_plan_operation (plan_id, node_key),
            CONSTRAINT agent_plan_dependency_target_fk
                FOREIGN KEY (plan_id, dependency_node_key)
                REFERENCES agent_plan_operation (plan_id, node_key),
            CONSTRAINT agent_plan_dependency_plan_fk
                FOREIGN KEY (plan_id, workspace_id)
                REFERENCES agent_plan (id, workspace_id),
            CONSTRAINT agent_plan_dependency_shape CHECK (
                ordinal >= 0 AND node_key <> dependency_node_key
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE agent_tool_result (
            operation_id       uuid PRIMARY KEY,
            plan_id            uuid NOT NULL,
            node_key           text NOT NULL,
            workspace_id       text NOT NULL,
            tool_address       text NOT NULL,
            result_artifact_key text NOT NULL,
            result_sha256       text NOT NULL,
            replayed           boolean NOT NULL,
            reference_count    int NOT NULL,
            completed_at       timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT agent_tool_result_operation_fk
                FOREIGN KEY (operation_id) REFERENCES agent_plan_operation (operation_id),
            CONSTRAINT agent_tool_result_node_fk
                FOREIGN KEY (plan_id, node_key)
                REFERENCES agent_plan_operation (plan_id, node_key),
            CONSTRAINT agent_tool_result_plan_fk
                FOREIGN KEY (plan_id, workspace_id)
                REFERENCES agent_plan (id, workspace_id),
            CONSTRAINT agent_tool_result_artifact_fk
                FOREIGN KEY (result_artifact_key) REFERENCES artifact (storage_key),
            CONSTRAINT agent_tool_result_sha CHECK (result_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT agent_tool_result_scope CHECK (
                result_artifact_key = workspace_id || '/' || result_sha256
            ),
            CONSTRAINT agent_tool_result_count CHECK (reference_count >= 0)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE agent_delegation (
            id                         uuid PRIMARY KEY,
            plan_id                    uuid NOT NULL,
            node_key                   text NOT NULL,
            operation_id               uuid NOT NULL UNIQUE,
            turn_id                    uuid NOT NULL,
            workspace_id               text NOT NULL,
            parent_execution_id        uuid NOT NULL,
            child_execution_id         uuid NOT NULL,
            parent_role                text NOT NULL,
            child_role                 text NOT NULL,
            task_artifact_key          text NOT NULL,
            task_sha256                 text NOT NULL,
            child_budget_artifact_key  text NOT NULL,
            child_budget_sha256         text NOT NULL,
            resource_manifest_key      text NOT NULL,
            resource_manifest_artifact_sha256 text NOT NULL,
            resource_manifest_sha256   text NOT NULL,
            depth                      int NOT NULL,
            created_at                 timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT agent_delegation_plan_node_fk
                FOREIGN KEY (plan_id, node_key)
                REFERENCES agent_plan_operation (plan_id, node_key),
            CONSTRAINT agent_delegation_turn_fk
                FOREIGN KEY (turn_id, parent_execution_id, workspace_id)
                REFERENCES agent_turn (id, execution_id, workspace_id),
            CONSTRAINT agent_delegation_parent_execution_fk
                FOREIGN KEY (parent_execution_id, workspace_id)
                REFERENCES execution (id, workspace_id),
            CONSTRAINT agent_delegation_task_fk
                FOREIGN KEY (task_artifact_key) REFERENCES artifact (storage_key),
            CONSTRAINT agent_delegation_budget_fk
                FOREIGN KEY (child_budget_artifact_key) REFERENCES artifact (storage_key),
            CONSTRAINT agent_delegation_manifest_fk
                FOREIGN KEY (resource_manifest_key) REFERENCES artifact (storage_key),
            CONSTRAINT agent_delegation_workspace_anchor UNIQUE (id, workspace_id),
            CONSTRAINT agent_delegation_roles CHECK (
                parent_role IN ('head_of_abm', 'research', 'content_drafter', 'reviewer',
                                'account_research')
                AND child_role IN ('head_of_abm', 'research', 'content_drafter', 'reviewer',
                                   'account_research')
                AND parent_role <> child_role
            ),
            CONSTRAINT agent_delegation_depth CHECK (depth BETWEEN 1 AND 4),
            CONSTRAINT agent_delegation_hashes CHECK (
                task_sha256 ~ '^[0-9a-f]{64}$'
                AND child_budget_sha256 ~ '^[0-9a-f]{64}$'
                AND resource_manifest_artifact_sha256 ~ '^[0-9a-f]{64}$'
                AND resource_manifest_sha256 ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT agent_delegation_artifact_scope CHECK (
                task_artifact_key = workspace_id || '/' || task_sha256
                AND child_budget_artifact_key = workspace_id || '/' || child_budget_sha256
                AND resource_manifest_key =
                    workspace_id || '/' || resource_manifest_artifact_sha256
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX agent_delegation_parent ON agent_delegation "
        "(parent_execution_id, created_at, id)"
    )
    op.execute(
        """
        CREATE TABLE agent_delegation_path_grant (
            delegation_id uuid NOT NULL,
            workspace_id  text NOT NULL,
            ordinal       int NOT NULL,
            path          text NOT NULL,

            CONSTRAINT agent_delegation_path_grant_pk PRIMARY KEY (delegation_id, ordinal),
            CONSTRAINT agent_delegation_path_grant_unique UNIQUE (delegation_id, path),
            CONSTRAINT agent_delegation_path_grant_fk
                FOREIGN KEY (delegation_id, workspace_id)
                REFERENCES agent_delegation (id, workspace_id),
            CONSTRAINT agent_delegation_path_shape CHECK (
                ordinal >= 0 AND length(btrim(path)) > 0
                AND path !~ '(^/|(^|/)\\.\\.?(/|$)|\\\\)'
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE agent_delegation_domain_ref (
            delegation_id uuid NOT NULL,
            workspace_id  text NOT NULL,
            ref_role      text NOT NULL,
            ordinal       int NOT NULL,
            object_type   text NOT NULL,
            object_id     text NOT NULL,
            object_version bigint,

            CONSTRAINT agent_delegation_domain_ref_pk PRIMARY KEY (
                delegation_id, ref_role, ordinal
            ),
            CONSTRAINT agent_delegation_domain_ref_fk
                FOREIGN KEY (delegation_id, workspace_id)
                REFERENCES agent_delegation (id, workspace_id),
            CONSTRAINT agent_delegation_domain_ref_role CHECK (
                ref_role IN ('grant', 'result')
            ),
            CONSTRAINT agent_delegation_domain_ref_shape CHECK (
                ordinal >= 0 AND length(btrim(object_type)) > 0
                AND length(btrim(object_id)) > 0
                AND (object_version IS NULL OR object_version >= 1)
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE agent_delegation_event (
            seq           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            event_id      uuid NOT NULL UNIQUE,
            delegation_id uuid NOT NULL,
            workspace_id  text NOT NULL,
            status        text NOT NULL,
            spend_millicents bigint NOT NULL DEFAULT 0,
            reason_code   text,
            created_at    timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT agent_delegation_event_fk
                FOREIGN KEY (delegation_id, workspace_id)
                REFERENCES agent_delegation (id, workspace_id),
            CONSTRAINT agent_delegation_event_status CHECK (
                status IN ('requested', 'child_started', 'completed', 'awaiting_input',
                           'blocked', 'failed', 'abandoned')
            ),
            CONSTRAINT agent_delegation_event_shape CHECK (
                spend_millicents >= 0
                AND ((status IN ('failed', 'abandoned') AND reason_code IS NOT NULL)
                     OR (status NOT IN ('failed', 'abandoned') AND reason_code IS NULL))
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX agent_delegation_event_effective "
        "ON agent_delegation_event (delegation_id, seq DESC)"
    )
    op.execute(
        """
        CREATE TABLE agent_delegation_result (
            delegation_id            uuid PRIMARY KEY,
            workspace_id             text NOT NULL,
            child_execution_id       uuid NOT NULL,
            status                   text NOT NULL,
            finalization_artifact_key text NOT NULL,
            finalization_sha256       text NOT NULL,
            spend_millicents         bigint NOT NULL,
            completed_at             timestamptz NOT NULL,

            CONSTRAINT agent_delegation_result_fk
                FOREIGN KEY (delegation_id, workspace_id)
                REFERENCES agent_delegation (id, workspace_id),
            CONSTRAINT agent_delegation_result_execution_fk
                FOREIGN KEY (child_execution_id, workspace_id)
                REFERENCES execution (id, workspace_id),
            CONSTRAINT agent_delegation_result_artifact_fk
                FOREIGN KEY (finalization_artifact_key) REFERENCES artifact (storage_key),
            CONSTRAINT agent_delegation_result_status CHECK (
                status IN ('completed', 'awaiting_input', 'blocked', 'failed')
            ),
            CONSTRAINT agent_delegation_result_sha CHECK (
                finalization_sha256 ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT agent_delegation_result_scope CHECK (
                finalization_artifact_key = workspace_id || '/' || finalization_sha256
            ),
            CONSTRAINT agent_delegation_result_spend CHECK (spend_millicents >= 0)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE agent_delegation_output_ref (
            delegation_id uuid NOT NULL,
            workspace_id  text NOT NULL,
            ordinal       int NOT NULL,
            artifact_key  text NOT NULL,
            artifact_sha256 text NOT NULL,

            CONSTRAINT agent_delegation_output_ref_pk PRIMARY KEY (delegation_id, ordinal),
            CONSTRAINT agent_delegation_output_ref_result_fk
                FOREIGN KEY (delegation_id) REFERENCES agent_delegation_result (delegation_id),
            CONSTRAINT agent_delegation_output_ref_delegation_fk
                FOREIGN KEY (delegation_id, workspace_id)
                REFERENCES agent_delegation (id, workspace_id),
            CONSTRAINT agent_delegation_output_ref_artifact_fk
                FOREIGN KEY (artifact_key) REFERENCES artifact (storage_key),
            CONSTRAINT agent_delegation_output_ref_shape CHECK (
                ordinal >= 0 AND artifact_sha256 ~ '^[0-9a-f]{64}$'
                AND artifact_key = workspace_id || '/' || artifact_sha256
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE agent_finalization_commit (
            finalization_id      uuid PRIMARY KEY,
            turn_id              uuid NOT NULL UNIQUE,
            execution_id         uuid NOT NULL UNIQUE,
            workspace_id         text NOT NULL,
            envelope_artifact_key text NOT NULL,
            envelope_sha256       text NOT NULL,
            committed_at         timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT agent_finalization_commit_finalization_fk
                FOREIGN KEY (finalization_id, workspace_id)
                REFERENCES agent_finalization (id, workspace_id),
            CONSTRAINT agent_finalization_commit_turn_fk
                FOREIGN KEY (turn_id, execution_id, workspace_id)
                REFERENCES agent_turn (id, execution_id, workspace_id),
            CONSTRAINT agent_finalization_commit_artifact_fk
                FOREIGN KEY (envelope_artifact_key) REFERENCES artifact (storage_key),
            CONSTRAINT agent_finalization_commit_sha CHECK (
                envelope_sha256 ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT agent_finalization_commit_scope CHECK (
                envelope_artifact_key = workspace_id || '/' || envelope_sha256
            )
        )
        """
    )

    for table in (
        "agent_plan",
        "agent_plan_event",
        "agent_plan_operation",
        "agent_plan_dependency",
        "agent_tool_result",
        "agent_delegation",
        "agent_delegation_path_grant",
        "agent_delegation_domain_ref",
        "agent_delegation_event",
        "agent_delegation_result",
        "agent_delegation_output_ref",
        "agent_finalization_commit",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_append_only "
            f"BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION execution_reject_append_only_mutation()"
        )


def downgrade() -> None:
    for table in (
        "agent_finalization_commit",
        "agent_delegation_output_ref",
        "agent_delegation_result",
        "agent_delegation_event",
        "agent_delegation_domain_ref",
        "agent_delegation_path_grant",
        "agent_delegation",
        "agent_tool_result",
        "agent_plan_dependency",
        "agent_plan_operation",
        "agent_plan_event",
        "agent_plan",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
        op.execute(f"DROP TABLE IF EXISTS {table}")
