"""harden m8d r0 r4 authority and state

Revision ID: 5764311c620d
Revises: f643425d0be4
Create Date: 2026-08-06 00:04:24.420017+00:00

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
revision: str = "5764311c620d"
down_revision: str | None = "f643425d0be4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # R0: persist the executable field->source relation and the exact prior result supplied to a
    # follow-up.  Fields and sources as independent arrays admitted an unauthorized cross-product.
    op.execute(
        "ALTER TABLE entity_research_tool_request "
        "ADD COLUMN field_source_authority jsonb NOT NULL DEFAULT '[]'::jsonb, "
        "ADD COLUMN prior_result_sha256 text, "
        "ADD COLUMN prior_research_context text"
    )
    op.execute(
        "ALTER TABLE entity_research_tool_request "
        "DROP CONSTRAINT entity_research_tool_request_nonempty, "
        "DROP CONSTRAINT entity_research_tool_request_follow_up_shape"
    )
    op.execute(
        """
        ALTER TABLE entity_research_tool_request
        ADD CONSTRAINT entity_research_tool_request_nonempty CHECK (
            length(btrim(raw_tool_call_id)) > 0 AND length(btrim(tool_name)) > 0
            AND length(btrim(field_plan_ref)) > 0
            AND length(btrim(source_plan_ref)) > 0
            AND length(btrim(budget_reservation_key)) > 0
            AND length(btrim(idempotency_key)) > 0
            AND cardinality(source_keys) > 0 AND cardinality(questions) > 0
            AND jsonb_typeof(field_source_authority) = 'array'
            AND (
                (tool_name = 'discover_buying_committee' AND cardinality(field_keys) = 0
                 AND field_source_authority = '[]'::jsonb)
                OR
                (tool_name <> 'discover_buying_committee' AND cardinality(field_keys) > 0
                 AND jsonb_array_length(field_source_authority) > 0)
            )
        ),
        ADD CONSTRAINT entity_research_tool_request_follow_up_shape CHECK (
            (
                parent_operation_ref IS NULL AND parent_observation_ref IS NULL
                AND follow_up_reason IS NULL AND prior_result_sha256 IS NULL
                AND prior_research_context IS NULL
            ) OR (
                length(btrim(parent_operation_ref)) > 0
                AND length(btrim(parent_observation_ref)) > 0
                AND follow_up_reason IN (
                    'new_angle', 'evidence_verification', 'contradiction_resolution',
                    'identity_disambiguation', 'remaining_gap'
                )
                AND prior_result_sha256 ~ '^[0-9a-f]{64}$'
                AND length(btrim(prior_research_context)) > 0
            )
        )
        """
    )

    # R2/R3: the initial state is immutable authority; current state evolves as durable tool
    # observations/results are added. Finalization and job events are immutable history too.
    op.execute("ALTER TABLE entity_research_job ADD COLUMN initial_state_sha256 text")
    op.execute("UPDATE entity_research_job SET initial_state_sha256=current_state_sha256")
    op.execute(
        "ALTER TABLE entity_research_job ALTER COLUMN initial_state_sha256 SET NOT NULL, "
        "ADD CONSTRAINT entity_research_job_initial_state_sha "
        "CHECK (initial_state_sha256 ~ '^[0-9a-f]{64}$')"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_entity_research_authority_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_TABLE_NAME = 'entity_research_run' THEN
                IF ROW(NEW.run_kind, NEW.subject_type, NEW.workspace_id, NEW.project_id,
                       NEW.product_id, NEW.project_run_id, NEW.selection_id, NEW.lifecycle_json,
                       NEW.lifecycle_sha256, NEW.budget_envelope_ref, NEW.budget_cap_cents,
                       NEW.concurrency_limit)
                   IS DISTINCT FROM
                   ROW(OLD.run_kind, OLD.subject_type, OLD.workspace_id, OLD.project_id,
                       OLD.product_id, OLD.project_run_id, OLD.selection_id, OLD.lifecycle_json,
                       OLD.lifecycle_sha256, OLD.budget_envelope_ref, OLD.budget_cap_cents,
                       OLD.concurrency_limit) THEN
                    RAISE EXCEPTION 'entity research run authority is immutable';
                END IF;
            ELSE
                IF ROW(NEW.research_run_id, NEW.subject_type, NEW.subject_entity_id,
                       NEW.parent_account_id, NEW.workspace_id, NEW.project_id, NEW.product_id,
                       NEW.project_run_id, NEW.authorization_json, NEW.authorization_sha256,
                       NEW.priority, NEW.budget_envelope_ref, NEW.budget_cap_cents,
                       NEW.checkpoint_thread_id, NEW.initial_state_sha256)
                   IS DISTINCT FROM
                   ROW(OLD.research_run_id, OLD.subject_type, OLD.subject_entity_id,
                       OLD.parent_account_id, OLD.workspace_id, OLD.project_id, OLD.product_id,
                       OLD.project_run_id, OLD.authorization_json, OLD.authorization_sha256,
                       OLD.priority, OLD.budget_envelope_ref, OLD.budget_cap_cents,
                       OLD.checkpoint_thread_id, OLD.initial_state_sha256) THEN
                    RAISE EXCEPTION 'entity research job authority is immutable';
                END IF;
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_entity_research_job_history_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'entity research finalization and job-event history is append-only';
        END
        $$
        """
    )
    for table in ("entity_research_job_finalization", "entity_research_job_event"):
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_entity_research_job_history_mutation()"
        )

    # R4: a provider-neutral operation bridge is the authority seam. Provider-specific ledgers own
    # wire state and are read through adapters; the agent/tool tables retain only opaque refs.
    op.execute(
        """
        CREATE TABLE entity_research_provider_operation (
            operation_ref       text PRIMARY KEY,
            provider_kind       text NOT NULL,
            workspace_id        text NOT NULL,
            project_id          text NOT NULL,
            project_run_id      uuid NOT NULL,
            subject_type        text NOT NULL,
            target_entity_id    uuid NOT NULL,
            parent_account_id   uuid,
            source_key          text NOT NULL,
            field_keys          text[] NOT NULL DEFAULT '{}',
            request_artifact_ref text NOT NULL,
            reserved_at         timestamptz NOT NULL,
            dispatched_at       timestamptz,
            CONSTRAINT entity_research_provider_operation_nonempty CHECK (
                length(btrim(operation_ref)) > 0 AND length(btrim(provider_kind)) > 0
                AND length(btrim(source_key)) > 0 AND length(btrim(request_artifact_ref)) > 0
            ),
            CONSTRAINT entity_research_provider_operation_subject
                CHECK (subject_type IN ('account', 'contact')),
            CONSTRAINT entity_research_provider_operation_parent CHECK (
                (subject_type='account' AND parent_account_id IS NULL) OR
                (subject_type='contact' AND parent_account_id IS NOT NULL)
            ),
            CONSTRAINT entity_research_provider_operation_dispatch_order
                CHECK (dispatched_at IS NULL OR dispatched_at >= reserved_at)
        )
        """
    )
    op.execute(
        """
        INSERT INTO entity_research_provider_operation
            (operation_ref, provider_kind, workspace_id, project_id, project_run_id,
             subject_type, target_entity_id, parent_account_id, source_key,
             request_artifact_ref, reserved_at, dispatched_at)
        SELECT 'external-research-operation:' || operation.id::text,
               'external_research', operation.workspace_id, operation.project_id,
               operation.project_run_id, operation.subject_kind::text,
               CASE WHEN operation.subject_kind='account' THEN operation.account_id
                    ELSE operation.contact_id END,
               CASE WHEN operation.subject_kind='contact' THEN operation.account_id ELSE NULL END,
               operation.source_key, 'artifact:' || operation.request_artifact_key,
               operation.created_at,
               (SELECT min(attempt.dispatched_at) FROM external_research_attempt attempt
                WHERE attempt.operation_id=operation.id AND attempt.dispatched_at IS NOT NULL)
        FROM external_research_operation operation
        """
    )
    op.execute(
        """
        CREATE FUNCTION protect_entity_research_provider_operation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP='INSERT' THEN
                IF cardinality(NEW.field_keys) IS DISTINCT FROM (
                    SELECT count(DISTINCT field_key) FROM unnest(NEW.field_keys) field_key
                ) OR EXISTS (
                    SELECT 1 FROM unnest(NEW.field_keys) field_key
                    WHERE field_key NOT LIKE NEW.subject_type || '.%'
                ) THEN
                    RAISE EXCEPTION 'provider operation contains invalid field authority';
                END IF;
                RETURN NEW;
            END IF;
            IF TG_OP='DELETE' OR
               ROW(NEW.operation_ref, NEW.provider_kind, NEW.workspace_id, NEW.project_id,
                   NEW.project_run_id, NEW.subject_type, NEW.target_entity_id,
                   NEW.parent_account_id, NEW.source_key, NEW.field_keys,
                   NEW.request_artifact_ref,
                   NEW.reserved_at)
               IS DISTINCT FROM
               ROW(OLD.operation_ref, OLD.provider_kind, OLD.workspace_id, OLD.project_id,
                   OLD.project_run_id, OLD.subject_type, OLD.target_entity_id,
                   OLD.parent_account_id, OLD.source_key, OLD.field_keys,
                   OLD.request_artifact_ref,
                   OLD.reserved_at) OR
               (OLD.dispatched_at IS NOT NULL AND
                NEW.dispatched_at IS DISTINCT FROM OLD.dispatched_at)
            THEN RAISE EXCEPTION 'provider operation authority is immutable';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER entity_research_provider_operation_immutable "
        "BEFORE INSERT OR UPDATE OR DELETE ON entity_research_provider_operation FOR EACH ROW "
        "EXECUTE FUNCTION protect_entity_research_provider_operation()"
    )
    op.execute(
        "DROP TRIGGER entity_research_provider_observation_authority "
        "ON entity_research_provider_observation"
    )
    op.execute("DROP INDEX entity_research_provider_single_cause")
    op.execute(
        "ALTER TABLE entity_research_provider_observation "
        "DROP CONSTRAINT entity_research_provider_observation_unique, "
        "ADD COLUMN provider_operation_ref text"
    )
    op.execute(
        "ALTER TABLE entity_research_provider_observation "
        "DISABLE TRIGGER entity_research_provider_observation_append_only"
    )
    op.execute(
        "UPDATE entity_research_provider_observation "
        "SET provider_operation_ref='external-research-operation:' || operation_id::text"
    )
    op.execute(
        "ALTER TABLE entity_research_provider_observation "
        "ENABLE TRIGGER entity_research_provider_observation_append_only"
    )
    op.execute(
        "ALTER TABLE entity_research_provider_observation "
        "ALTER COLUMN provider_operation_ref SET NOT NULL, "
        "ALTER COLUMN operation_id DROP NOT NULL, "
        "ADD CONSTRAINT entity_research_provider_observation_provider_fk "
        "FOREIGN KEY (provider_operation_ref) REFERENCES entity_research_provider_operation "
        "(operation_ref) ON DELETE RESTRICT, "
        "ADD CONSTRAINT entity_research_provider_observation_provider_unique "
        "UNIQUE (tool_request_id, provider_operation_ref)"
    )
    op.execute(
        "CREATE UNIQUE INDEX entity_research_provider_single_cause "
        "ON entity_research_provider_observation (provider_operation_ref) "
        "WHERE disposition='caused'"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION entity_research_validate_provider_observation()
        RETURNS trigger AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM entity_research_tool_request request_row
                JOIN entity_research_provider_operation operation_row
                  ON operation_row.operation_ref=NEW.provider_operation_ref
                WHERE request_row.tool_request_id=NEW.tool_request_id
                  AND request_row.workspace_id=operation_row.workspace_id
                  AND request_row.project_id=operation_row.project_id
                  AND request_row.project_run_id=operation_row.project_run_id
                  AND request_row.subject_type=operation_row.subject_type
                  AND request_row.target_entity_id=operation_row.target_entity_id
                  AND request_row.parent_account_id IS NOT DISTINCT FROM
                      operation_row.parent_account_id
                  AND operation_row.source_key=ANY(request_row.source_keys)
                  AND request_row.field_keys @> operation_row.field_keys
                  AND NOT EXISTS (
                      SELECT 1 FROM unnest(operation_row.field_keys) operation_field
                      WHERE NOT EXISTS (
                          SELECT 1
                          FROM jsonb_array_elements(request_row.field_source_authority) authority
                          WHERE authority->>'field_key'=operation_field
                            AND authority->'source_keys' ? operation_row.source_key
                      )
                  )
                  AND (NEW.disposition <> 'caused'
                       OR operation_row.reserved_at >= request_row.created_at)
            ) THEN
                RAISE EXCEPTION 'provider observation crosses governed tool request authority';
            END IF;
            IF NEW.disposition='caused' AND EXISTS (
                SELECT 1 FROM entity_research_provider_operation operation_row
                WHERE operation_row.operation_ref=NEW.provider_operation_ref
                  AND operation_row.dispatched_at IS NOT NULL
            ) THEN
                RAISE EXCEPTION 'provider causation must be recorded before dispatch';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER entity_research_provider_observation_authority "
        "BEFORE INSERT ON entity_research_provider_observation FOR EACH ROW "
        "EXECUTE FUNCTION entity_research_validate_provider_observation()"
    )

    op.execute(
        "ALTER TABLE entity_research_result "
        "DROP CONSTRAINT entity_research_result_operation_once, "
        "DROP CONSTRAINT entity_research_result_fields, "
        "ADD COLUMN provider_operation_ref text, ADD COLUMN provider_snapshot_ref text"
    )
    op.execute(
        "ALTER TABLE entity_research_result DISABLE TRIGGER entity_research_result_append_only"
    )
    op.execute(
        "UPDATE entity_research_result SET "
        "provider_operation_ref='external-research-operation:' || operation_id::text, "
        "provider_snapshot_ref='external-research-snapshot:' || snapshot_id::text"
    )
    op.execute(
        "ALTER TABLE entity_research_result ENABLE TRIGGER entity_research_result_append_only"
    )
    op.execute(
        "ALTER TABLE entity_research_result "
        "ALTER COLUMN provider_operation_ref SET NOT NULL, "
        "ALTER COLUMN provider_snapshot_ref SET NOT NULL, "
        "ALTER COLUMN operation_id DROP NOT NULL, ALTER COLUMN snapshot_id DROP NOT NULL, "
        "ADD CONSTRAINT entity_research_result_provider_operation_fk "
        "FOREIGN KEY (provider_operation_ref) REFERENCES entity_research_provider_operation "
        "(operation_ref) ON DELETE RESTRICT, "
        "ADD CONSTRAINT entity_research_result_provider_operation_once "
        "UNIQUE (tool_request_id, provider_operation_ref), "
        "ADD CONSTRAINT entity_research_result_payload CHECK ("
        "cardinality(requested_field_keys) > 0 OR subject_type='account')"
    )
    op.execute(
        "ALTER TABLE entity_research_result_field "
        "ADD COLUMN subject_type text, ADD COLUMN target_entity_id uuid, "
        "ADD COLUMN parent_account_id uuid"
    )
    op.execute(
        "ALTER TABLE entity_research_result_field "
        "DISABLE TRIGGER entity_research_result_field_append_only"
    )
    op.execute(
        """
        UPDATE entity_research_result_field field_row SET
            subject_type=result.subject_type,
            target_entity_id=result.target_entity_id,
            parent_account_id=CASE WHEN result.subject_type='contact'
                                   THEN request_row.parent_account_id ELSE NULL END
        FROM entity_research_result result
        JOIN entity_research_tool_request request_row
          ON request_row.tool_request_id=result.tool_request_id
        WHERE field_row.result_id=result.result_id
        """
    )
    op.execute(
        "ALTER TABLE entity_research_result_field "
        "ENABLE TRIGGER entity_research_result_field_append_only"
    )
    op.execute(
        "ALTER TABLE entity_research_result_field "
        "ALTER COLUMN subject_type SET NOT NULL, ALTER COLUMN target_entity_id SET NOT NULL, "
        "ADD CONSTRAINT entity_research_result_field_subject "
        "CHECK (subject_type IN ('account','contact')), "
        "ADD CONSTRAINT entity_research_result_field_parent CHECK ("
        "(subject_type='account' AND parent_account_id IS NULL) OR "
        "(subject_type='contact' AND parent_account_id IS NOT NULL))"
    )

    # R3/DSAR: journal rows remain durable audit facts, but their personal payload has a single
    # fail-closed redaction transition. Exact LangGraph checkpoint rows are deleted by the DSAR op.
    op.execute("ALTER TABLE entity_research_agent_turn ADD COLUMN erased_at timestamptz")
    op.execute("ALTER TABLE entity_research_agent_event ADD COLUMN payload_erased_at timestamptz")
    op.execute(
        "ALTER TABLE entity_research_agent_turn "
        "DROP CONSTRAINT entity_research_agent_turn_context_scope"
    )
    op.execute(
        """
        ALTER TABLE entity_research_agent_turn
        ADD CONSTRAINT entity_research_agent_turn_context_scope CHECK (
            (erased_at IS NOT NULL AND context_json=jsonb_build_object('erased', true)) OR (
                erased_at IS NULL AND (
                    context_json->>'agent_execution_id' = agent_execution_id::text AND
                    context_json->>'agent_turn_id' = agent_turn_id::text AND
                    context_json->>'role' = role AND
                    context_json->>'subject_type' = subject_type AND
                    context_json->>'subject_entity_id' = target_entity_id::text AND
                    context_json->>'job_id' = job_id::text AND
                    context_json->>'research_run_id' = research_run_id::text AND
                    context_json->>'workspace_id' = workspace_id::text AND
                    context_json->>'project_id' = project_id::text AND
                    context_json->>'product_id' = product_id::text AND
                    context_json->>'project_run_id' = project_run_id::text AND
                    context_json->>'checkpoint_thread_id' = checkpoint_thread_id
                ) IS TRUE
            )
        )
        """
    )
    op.execute("DROP TRIGGER entity_research_agent_turn_append_only ON entity_research_agent_turn")
    op.execute(
        "DROP TRIGGER entity_research_agent_event_append_only ON entity_research_agent_event"
    )
    op.execute("DROP FUNCTION reject_entity_research_agent_journal_mutation")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION protect_entity_research_agent_turn_redaction()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP='DELETE' THEN
                RAISE EXCEPTION 'entity research agent journal is append-only';
            END IF;
            IF OLD.erased_at IS NULL AND NEW.erased_at IS NOT NULL
               AND NEW.context_json=jsonb_build_object('erased', true)
               AND ROW(NEW.agent_turn_id, NEW.agent_execution_id, NEW.job_id,
                       NEW.research_run_id, NEW.role, NEW.subject_type, NEW.target_entity_id,
                       NEW.parent_account_id, NEW.workspace_id, NEW.project_id, NEW.product_id,
                       NEW.project_run_id, NEW.checkpoint_thread_id,
                       NEW.parent_agent_execution_id, NEW.parent_agent_turn_id, NEW.facet_key,
                       NEW.facet_depth, NEW.context_sha256, NEW.resource_manifest_json,
                       NEW.resource_manifest_sha256, NEW.tool_manifest_json,
                       NEW.tool_manifest_sha256, NEW.system_prompt_sha256, NEW.started_at)
                  IS NOT DISTINCT FROM
                  ROW(OLD.agent_turn_id, OLD.agent_execution_id, OLD.job_id,
                       OLD.research_run_id, OLD.role, OLD.subject_type, OLD.target_entity_id,
                       OLD.parent_account_id, OLD.workspace_id, OLD.project_id, OLD.product_id,
                       OLD.project_run_id, OLD.checkpoint_thread_id,
                       OLD.parent_agent_execution_id, OLD.parent_agent_turn_id, OLD.facet_key,
                       OLD.facet_depth, OLD.context_sha256, OLD.resource_manifest_json,
                       OLD.resource_manifest_sha256, OLD.tool_manifest_json,
                       OLD.tool_manifest_sha256, OLD.system_prompt_sha256, OLD.started_at)
            THEN RETURN NEW;
            END IF;
            RAISE EXCEPTION 'entity research agent journal is append-only';
        END
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION protect_entity_research_agent_event_redaction()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP='DELETE' THEN
                RAISE EXCEPTION 'entity research agent journal is append-only';
            END IF;
            IF OLD.payload_erased_at IS NULL AND NEW.payload_erased_at IS NOT NULL
               AND NEW.payload_json=jsonb_build_object('erased', true)
               AND ROW(NEW.event_id, NEW.event_seq, NEW.agent_turn_id, NEW.agent_execution_id,
                       NEW.event_kind, NEW.tool_call_id, NEW.tool_name, NEW.tool_version,
                       NEW.tool_input_sha256, NEW.occurred_at)
                  IS NOT DISTINCT FROM
                  ROW(OLD.event_id, OLD.event_seq, OLD.agent_turn_id, OLD.agent_execution_id,
                       OLD.event_kind, OLD.tool_call_id, OLD.tool_name, OLD.tool_version,
                       OLD.tool_input_sha256, OLD.occurred_at)
            THEN RETURN NEW;
            END IF;
            RAISE EXCEPTION 'entity research agent journal is append-only';
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER entity_research_agent_turn_append_only BEFORE UPDATE OR DELETE "
        "ON entity_research_agent_turn FOR EACH ROW "
        "EXECUTE FUNCTION protect_entity_research_agent_turn_redaction()"
    )
    op.execute(
        "CREATE TRIGGER entity_research_agent_event_append_only BEFORE UPDATE OR DELETE "
        "ON entity_research_agent_event FOR EACH ROW "
        "EXECUTE FUNCTION protect_entity_research_agent_event_redaction()"
    )

    # Replace R4's provider-specific tool-request trigger after all ref columns exist.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION entity_research_validate_tool_request() RETURNS trigger AS $$
        DECLARE authority_fields text[]; authority_sources text[];
        BEGIN
            IF EXISTS (
                SELECT 1 FROM unnest(NEW.field_keys) AS field_key
                WHERE field_key NOT LIKE NEW.subject_type || '.%'
            ) THEN RAISE EXCEPTION 'governed tool request contains a cross-axis field'; END IF;
            SELECT coalesce(array_agg(value->>'field_key' ORDER BY value->>'field_key'), '{}')
              INTO authority_fields FROM jsonb_array_elements(NEW.field_source_authority) value;
            SELECT coalesce(array_agg(DISTINCT source ORDER BY source), '{}')
              INTO authority_sources FROM jsonb_array_elements(NEW.field_source_authority) value,
              LATERAL jsonb_array_elements_text(value->'source_keys') source;
            IF NEW.tool_name <> 'discover_buying_committee' AND (
                (SELECT array_agg(value ORDER BY value) FROM unnest(NEW.field_keys) value)
                    IS DISTINCT FROM authority_fields OR
                (SELECT array_agg(value ORDER BY value) FROM unnest(NEW.source_keys) value)
                    IS DISTINCT FROM authority_sources
            ) THEN RAISE EXCEPTION 'field-source authority differs from requested fields/sources';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM entity_research_agent_turn turn_row
                JOIN entity_research_agent_event event_row
                  ON event_row.event_id=NEW.tool_event_id
                 AND event_row.agent_turn_id=turn_row.agent_turn_id
                 AND event_row.agent_execution_id=turn_row.agent_execution_id
                WHERE turn_row.agent_turn_id=NEW.agent_turn_id
                  AND turn_row.agent_execution_id=NEW.agent_execution_id
                  AND turn_row.job_id=NEW.job_id AND turn_row.research_run_id=NEW.research_run_id
                  AND turn_row.subject_type=NEW.subject_type
                  AND turn_row.target_entity_id=NEW.target_entity_id
                  AND turn_row.parent_account_id IS NOT DISTINCT FROM NEW.parent_account_id
                  AND turn_row.workspace_id=NEW.workspace_id
                  AND turn_row.project_id=NEW.project_id AND turn_row.product_id=NEW.product_id
                  AND turn_row.project_run_id=NEW.project_run_id
                  AND turn_row.context_json->'tool_names' ? NEW.tool_name
                  AND NOT EXISTS (
                      SELECT 1 FROM unnest(NEW.field_keys) requested_field
                      WHERE NOT (turn_row.context_json->'admitted_field_keys' ? requested_field)
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM unnest(NEW.source_keys) requested_source
                      WHERE NOT (turn_row.context_json->'admitted_source_keys' ? requested_source)
                  )
                  AND NOT EXISTS (
                      SELECT 1
                      FROM jsonb_array_elements(NEW.field_source_authority) requested_authority
                      WHERE NOT EXISTS (
                          SELECT 1
                          FROM jsonb_array_elements(
                              turn_row.context_json->'field_source_authority'
                          ) admitted_authority
                          WHERE admitted_authority->>'field_key' =
                                requested_authority->>'field_key'
                            AND NOT EXISTS (
                                SELECT 1
                                FROM jsonb_array_elements_text(
                                    requested_authority->'source_keys'
                                ) requested_source
                                WHERE NOT (
                                    admitted_authority->'source_keys' ? requested_source
                                )
                            )
                      )
                  )
                  AND (
                      NEW.parent_operation_ref IS NOT NULL OR NOT EXISTS (
                          SELECT 1 FROM unnest(NEW.questions) requested_question
                          WHERE NOT (
                              turn_row.context_json->'research_questions' ? requested_question
                          )
                      )
                  )
                  AND event_row.event_kind='tool_started'
                  AND event_row.tool_call_id=NEW.raw_tool_call_id
                  AND event_row.tool_name=NEW.tool_name
                  AND event_row.tool_version=NEW.tool_version
                  AND event_row.tool_input_sha256=NEW.tool_input_sha256
                  AND event_row.occurred_at <= NEW.created_at
            ) THEN RAISE EXCEPTION 'governed tool request differs from admitted journal'; END IF;
            IF NEW.parent_operation_ref IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM entity_research_result parent_result
                JOIN entity_research_tool_request parent_request
                  ON parent_request.tool_request_id=parent_result.tool_request_id
                WHERE NEW.parent_operation_ref=parent_result.provider_operation_ref
                  AND NEW.parent_observation_ref='research-result:' || parent_result.result_id::text
                  AND NEW.prior_result_sha256=parent_result.result_sha256
                  AND parent_request.research_run_id=NEW.research_run_id
                  AND parent_request.job_id=NEW.job_id
                  AND parent_request.subject_type=NEW.subject_type
                  AND parent_request.target_entity_id=NEW.target_entity_id
                  AND parent_request.workspace_id=NEW.workspace_id
                  AND parent_result.created_at <= NEW.created_at
            ) THEN RAISE EXCEPTION 'follow-up parent observation crosses exact job authority';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER entity_research_agent_event_append_only ON entity_research_agent_event"
    )
    op.execute("DROP TRIGGER entity_research_agent_turn_append_only ON entity_research_agent_turn")
    # ``IF EXISTS`` also lets a development database created by an earlier draft of this
    # revision downgrade cleanly; released fresh installs always contain both functions.
    op.execute("DROP FUNCTION IF EXISTS protect_entity_research_agent_event_redaction")
    op.execute("DROP FUNCTION IF EXISTS protect_entity_research_agent_turn_redaction")
    op.execute(
        "ALTER TABLE entity_research_agent_turn "
        "DROP CONSTRAINT entity_research_agent_turn_context_scope"
    )
    op.execute("ALTER TABLE entity_research_agent_event DROP COLUMN payload_erased_at")
    op.execute("ALTER TABLE entity_research_agent_turn DROP COLUMN erased_at")
    op.execute(
        """
        ALTER TABLE entity_research_agent_turn
        ADD CONSTRAINT entity_research_agent_turn_context_scope CHECK ((
            context_json->>'agent_execution_id' = agent_execution_id::text AND
            context_json->>'agent_turn_id' = agent_turn_id::text AND
            context_json->>'role' = role AND
            context_json->>'subject_type' = subject_type AND
            context_json->>'subject_entity_id' = target_entity_id::text AND
            context_json->>'job_id' = job_id::text AND
            context_json->>'research_run_id' = research_run_id::text AND
            context_json->>'workspace_id' = workspace_id::text AND
            context_json->>'project_id' = project_id::text AND
            context_json->>'product_id' = product_id::text AND
            context_json->>'project_run_id' = project_run_id::text AND
            context_json->>'checkpoint_thread_id' = checkpoint_thread_id
        ) IS TRUE)
        """
    )
    op.execute("DROP FUNCTION IF EXISTS reject_entity_research_agent_journal_mutation")
    op.execute(
        """
        CREATE FUNCTION reject_entity_research_agent_journal_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'entity research agent journal is append-only'; END $$
        """
    )
    op.execute(
        "CREATE TRIGGER entity_research_agent_turn_append_only BEFORE UPDATE OR DELETE "
        "ON entity_research_agent_turn FOR EACH ROW "
        "EXECUTE FUNCTION reject_entity_research_agent_journal_mutation()"
    )
    op.execute(
        "CREATE TRIGGER entity_research_agent_event_append_only BEFORE UPDATE OR DELETE "
        "ON entity_research_agent_event FOR EACH ROW "
        "EXECUTE FUNCTION reject_entity_research_agent_journal_mutation()"
    )
    op.execute(
        "ALTER TABLE entity_research_result_field "
        "DROP CONSTRAINT entity_research_result_field_parent, "
        "DROP CONSTRAINT entity_research_result_field_subject, "
        "DROP COLUMN parent_account_id, DROP COLUMN target_entity_id, DROP COLUMN subject_type"
    )
    op.execute(
        "ALTER TABLE entity_research_result "
        "DROP CONSTRAINT entity_research_result_payload, "
        "DROP CONSTRAINT entity_research_result_provider_operation_once, "
        "DROP CONSTRAINT entity_research_result_provider_operation_fk, "
        "DROP COLUMN provider_snapshot_ref, DROP COLUMN provider_operation_ref, "
        "ALTER COLUMN snapshot_id SET NOT NULL, ALTER COLUMN operation_id SET NOT NULL, "
        "ADD CONSTRAINT entity_research_result_operation_once "
        "UNIQUE (tool_request_id, operation_id), "
        "ADD CONSTRAINT entity_research_result_fields CHECK (cardinality(requested_field_keys)>0)"
    )
    op.execute(
        "DROP TRIGGER entity_research_provider_observation_authority "
        "ON entity_research_provider_observation"
    )
    op.execute("DROP INDEX entity_research_provider_single_cause")
    op.execute(
        "ALTER TABLE entity_research_provider_observation "
        "DROP CONSTRAINT entity_research_provider_observation_provider_unique, "
        "DROP CONSTRAINT entity_research_provider_observation_provider_fk, "
        "DROP COLUMN provider_operation_ref, ALTER COLUMN operation_id SET NOT NULL, "
        "ADD CONSTRAINT entity_research_provider_observation_unique "
        "UNIQUE (tool_request_id, operation_id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX entity_research_provider_single_cause "
        "ON entity_research_provider_observation(operation_id) WHERE disposition='caused'"
    )
    op.execute(
        "DROP TRIGGER entity_research_provider_operation_immutable "
        "ON entity_research_provider_operation"
    )
    op.execute("DROP FUNCTION protect_entity_research_provider_operation")
    op.execute("DROP TABLE entity_research_provider_operation")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION entity_research_validate_provider_observation()
        RETURNS trigger AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM entity_research_tool_request request_row
                JOIN external_research_operation operation_row
                  ON operation_row.id = NEW.operation_id
                 AND operation_row.workspace_id = NEW.external_workspace_id
                WHERE request_row.tool_request_id = NEW.tool_request_id
                  AND request_row.workspace_id = operation_row.workspace_id
                  AND request_row.project_id = operation_row.project_id
                  AND request_row.project_run_id = operation_row.project_run_id
                  AND request_row.subject_type = operation_row.subject_kind::text
                  AND request_row.target_entity_id = CASE
                      WHEN operation_row.subject_kind = 'account'
                      THEN operation_row.account_id ELSE operation_row.contact_id END
                  AND operation_row.account_id = CASE
                      WHEN operation_row.subject_kind = 'account'
                      THEN request_row.target_entity_id ELSE request_row.parent_account_id END
                  AND operation_row.source_key = ANY(request_row.source_keys)
                  AND (NEW.disposition <> 'caused'
                       OR operation_row.created_at >= request_row.created_at)
            ) THEN
                RAISE EXCEPTION 'provider observation crosses governed tool request authority';
            END IF;
            IF NEW.disposition = 'caused' AND EXISTS (
                SELECT 1 FROM external_research_attempt attempt
                WHERE attempt.operation_id = NEW.operation_id
                  AND attempt.dispatched_at IS NOT NULL
            ) THEN
                RAISE EXCEPTION 'provider causation must be recorded before dispatch';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER entity_research_provider_observation_authority BEFORE INSERT "
        "ON entity_research_provider_observation FOR EACH ROW "
        "EXECUTE FUNCTION entity_research_validate_provider_observation()"
    )
    for table in ("entity_research_job_event", "entity_research_job_finalization"):
        op.execute(f"DROP TRIGGER {table}_append_only ON {table}")
    op.execute("DROP FUNCTION reject_entity_research_job_history_mutation")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_entity_research_authority_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_TABLE_NAME = 'entity_research_run' THEN
                IF ROW(NEW.run_kind, NEW.subject_type, NEW.workspace_id, NEW.project_id,
                       NEW.product_id, NEW.project_run_id, NEW.selection_id, NEW.lifecycle_json,
                       NEW.lifecycle_sha256, NEW.budget_envelope_ref, NEW.budget_cap_cents,
                       NEW.concurrency_limit)
                   IS DISTINCT FROM
                   ROW(OLD.run_kind, OLD.subject_type, OLD.workspace_id, OLD.project_id,
                       OLD.product_id, OLD.project_run_id, OLD.selection_id, OLD.lifecycle_json,
                       OLD.lifecycle_sha256, OLD.budget_envelope_ref, OLD.budget_cap_cents,
                       OLD.concurrency_limit) THEN
                    RAISE EXCEPTION 'entity research run authority is immutable';
                END IF;
            ELSE
                IF ROW(NEW.research_run_id, NEW.subject_type, NEW.subject_entity_id,
                       NEW.parent_account_id, NEW.workspace_id, NEW.project_id, NEW.product_id,
                       NEW.project_run_id, NEW.authorization_json, NEW.authorization_sha256,
                       NEW.priority, NEW.budget_envelope_ref, NEW.budget_cap_cents,
                       NEW.checkpoint_thread_id)
                   IS DISTINCT FROM
                   ROW(OLD.research_run_id, OLD.subject_type, OLD.subject_entity_id,
                       OLD.parent_account_id, OLD.workspace_id, OLD.project_id, OLD.product_id,
                       OLD.project_run_id, OLD.authorization_json, OLD.authorization_sha256,
                       OLD.priority, OLD.budget_envelope_ref, OLD.budget_cap_cents,
                       OLD.checkpoint_thread_id) THEN
                    RAISE EXCEPTION 'entity research job authority is immutable';
                END IF;
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "ALTER TABLE entity_research_job DROP CONSTRAINT entity_research_job_initial_state_sha, "
        "DROP COLUMN initial_state_sha256"
    )
    op.execute(
        "ALTER TABLE entity_research_tool_request "
        "DROP CONSTRAINT entity_research_tool_request_follow_up_shape, "
        "DROP CONSTRAINT entity_research_tool_request_nonempty, "
        "DROP COLUMN prior_research_context, DROP COLUMN prior_result_sha256, "
        "DROP COLUMN field_source_authority"
    )
    op.execute(
        """
        ALTER TABLE entity_research_tool_request
        ADD CONSTRAINT entity_research_tool_request_nonempty CHECK (
            length(btrim(raw_tool_call_id)) > 0 AND length(btrim(tool_name)) > 0
            AND length(btrim(field_plan_ref)) > 0
            AND length(btrim(source_plan_ref)) > 0
            AND length(btrim(budget_reservation_key)) > 0
            AND length(btrim(idempotency_key)) > 0
            AND cardinality(field_keys) > 0 AND cardinality(source_keys) > 0
            AND cardinality(questions) > 0
        ),
        ADD CONSTRAINT entity_research_tool_request_follow_up_shape CHECK (
            (
                parent_operation_ref IS NULL AND parent_observation_ref IS NULL
                AND follow_up_reason IS NULL
            ) OR (
                length(btrim(parent_operation_ref)) > 0
                AND length(btrim(parent_observation_ref)) > 0
                AND follow_up_reason IN (
                    'new_angle', 'evidence_verification', 'contradiction_resolution',
                    'identity_disambiguation', 'remaining_gap'
                )
            )
        )
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION entity_research_validate_tool_request() RETURNS trigger AS $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM unnest(NEW.field_keys) AS field_key
                WHERE field_key NOT LIKE NEW.subject_type || '.%'
            ) THEN
                RAISE EXCEPTION 'governed tool request contains a cross-axis field';
            END IF;
            IF NOT EXISTS (
                SELECT 1
                FROM entity_research_agent_turn turn_row
                JOIN entity_research_agent_event event_row
                  ON event_row.event_id = NEW.tool_event_id
                 AND event_row.agent_turn_id = turn_row.agent_turn_id
                 AND event_row.agent_execution_id = turn_row.agent_execution_id
                WHERE turn_row.agent_turn_id = NEW.agent_turn_id
                  AND turn_row.agent_execution_id = NEW.agent_execution_id
                  AND turn_row.job_id = NEW.job_id
                  AND turn_row.research_run_id = NEW.research_run_id
                  AND turn_row.subject_type = NEW.subject_type
                  AND turn_row.target_entity_id = NEW.target_entity_id
                  AND turn_row.parent_account_id IS NOT DISTINCT FROM NEW.parent_account_id
                  AND turn_row.workspace_id = NEW.workspace_id
                  AND turn_row.project_id = NEW.project_id
                  AND turn_row.product_id = NEW.product_id
                  AND turn_row.project_run_id = NEW.project_run_id
                  AND event_row.event_kind = 'tool_started'
                  AND event_row.tool_call_id = NEW.raw_tool_call_id
                  AND event_row.tool_name = NEW.tool_name
                  AND event_row.tool_version = NEW.tool_version
                  AND event_row.tool_input_sha256 = NEW.tool_input_sha256
                  AND event_row.occurred_at <= NEW.created_at
            ) THEN
                RAISE EXCEPTION 'governed tool request differs from its admitted tool journal';
            END IF;
            IF NEW.parent_operation_ref IS NOT NULL AND NOT EXISTS (
                SELECT 1
                FROM entity_research_result parent_result
                JOIN entity_research_tool_request parent_request
                  ON parent_request.tool_request_id = parent_result.tool_request_id
                WHERE NEW.parent_operation_ref =
                      'external-research-operation:' || parent_result.operation_id::text
                  AND NEW.parent_observation_ref =
                      'research-result:' || parent_result.result_id::text
                  AND parent_request.research_run_id = NEW.research_run_id
                  AND parent_request.job_id = NEW.job_id
                  AND parent_request.subject_type = NEW.subject_type
                  AND parent_request.target_entity_id = NEW.target_entity_id
                  AND parent_request.workspace_id = NEW.workspace_id
                  AND parent_result.created_at <= NEW.created_at
            ) THEN
                RAISE EXCEPTION 'follow-up parent observation crosses exact job authority';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
