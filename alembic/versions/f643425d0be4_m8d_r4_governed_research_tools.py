"""m8d r4 governed research tools

Revision ID: f643425d0be4
Revises: ac980e12eb5e
Create Date: 2026-08-05 22:19:17.235747+00:00

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
revision: str = "f643425d0be4"
down_revision: str | None = "ac980e12eb5e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE entity_research_tool_request (
            tool_request_id            uuid PRIMARY KEY,
            agent_turn_id              uuid NOT NULL,
            agent_execution_id         uuid NOT NULL,
            tool_event_id              uuid NOT NULL UNIQUE
                                       REFERENCES entity_research_agent_event (event_id)
                                       ON DELETE RESTRICT,
            raw_tool_call_id           text NOT NULL,
            research_run_id            uuid NOT NULL
                                       REFERENCES entity_research_run (research_run_id)
                                       ON DELETE RESTRICT,
            job_id                     uuid NOT NULL REFERENCES entity_research_job (job_id)
                                       ON DELETE RESTRICT,
            subject_type               text NOT NULL,
            target_entity_id           uuid NOT NULL,
            parent_account_id          uuid,
            workspace_id               text NOT NULL,
            project_id                 text NOT NULL,
            product_id                 text NOT NULL,
            project_run_id             uuid NOT NULL,
            tool_name                  text NOT NULL,
            tool_version               integer NOT NULL,
            tool_input_sha256          text NOT NULL,
            field_plan_ref             text NOT NULL,
            source_plan_ref            text NOT NULL,
            field_keys                 text[] NOT NULL,
            source_keys                text[] NOT NULL,
            questions                  text[] NOT NULL,
            budget_reservation_key     text NOT NULL,
            idempotency_key            text NOT NULL,
            parent_operation_ref       text,
            parent_observation_ref     text,
            follow_up_reason           text,
            created_at                 timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT entity_research_tool_request_turn_fk
                FOREIGN KEY (agent_turn_id, agent_execution_id)
                REFERENCES entity_research_agent_turn (agent_turn_id, agent_execution_id)
                ON DELETE RESTRICT,
            CONSTRAINT entity_research_tool_request_call_unique
                UNIQUE (agent_turn_id, raw_tool_call_id),
            CONSTRAINT entity_research_tool_request_subject
                CHECK (subject_type IN ('account', 'contact')),
            CONSTRAINT entity_research_tool_request_parent_shape CHECK (
                (subject_type = 'account' AND parent_account_id IS NULL) OR
                (subject_type = 'contact' AND parent_account_id IS NOT NULL)
            ),
            CONSTRAINT entity_research_tool_request_nonempty CHECK (
                length(btrim(raw_tool_call_id)) > 0 AND length(btrim(tool_name)) > 0
                AND length(btrim(field_plan_ref)) > 0
                AND length(btrim(source_plan_ref)) > 0
                AND length(btrim(budget_reservation_key)) > 0
                AND length(btrim(idempotency_key)) > 0
                AND cardinality(field_keys) > 0 AND cardinality(source_keys) > 0
                AND cardinality(questions) > 0
            ),
            CONSTRAINT entity_research_tool_request_version CHECK (tool_version >= 1),
            CONSTRAINT entity_research_tool_request_hash
                CHECK (tool_input_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT entity_research_tool_request_follow_up_shape CHECK (
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
        )
        """
    )
    op.execute(
        "CREATE INDEX entity_research_tool_request_job_history "
        "ON entity_research_tool_request (job_id, created_at, tool_request_id)"
    )
    op.execute(
        """
        CREATE FUNCTION entity_research_validate_tool_request() RETURNS trigger AS $$
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
    op.execute(
        "CREATE TRIGGER entity_research_tool_request_authority "
        "BEFORE INSERT ON entity_research_tool_request FOR EACH ROW "
        "EXECUTE FUNCTION entity_research_validate_tool_request()"
    )

    op.execute(
        """
        CREATE TABLE entity_research_provider_observation (
            observation_id             uuid PRIMARY KEY,
            tool_request_id            uuid NOT NULL
                                       REFERENCES entity_research_tool_request (tool_request_id)
                                       ON DELETE RESTRICT,
            operation_id               uuid NOT NULL,
            external_workspace_id      text NOT NULL,
            disposition                text NOT NULL,
            created_at                 timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT entity_research_provider_observation_operation_fk
                FOREIGN KEY (operation_id, external_workspace_id)
                REFERENCES external_research_operation (id, workspace_id)
                ON DELETE RESTRICT,
            CONSTRAINT entity_research_provider_observation_unique
                UNIQUE (tool_request_id, operation_id),
            CONSTRAINT entity_research_provider_observation_disposition
                CHECK (disposition IN ('caused', 'replay_observation', 'joined_observation'))
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX entity_research_provider_single_cause "
        "ON entity_research_provider_observation (operation_id) WHERE disposition = 'caused'"
    )
    op.execute(
        """
        CREATE FUNCTION entity_research_validate_provider_observation() RETURNS trigger AS $$
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
                  AND (
                      NEW.disposition <> 'caused'
                      OR operation_row.created_at >= request_row.created_at
                  )
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
        "CREATE TRIGGER entity_research_provider_observation_authority "
        "BEFORE INSERT ON entity_research_provider_observation FOR EACH ROW "
        "EXECUTE FUNCTION entity_research_validate_provider_observation()"
    )

    op.execute(
        """
        CREATE TABLE entity_research_result (
            result_id                   uuid PRIMARY KEY,
            tool_request_id             uuid NOT NULL
                                        REFERENCES entity_research_tool_request (tool_request_id)
                                        ON DELETE RESTRICT,
            provider_observation_id     uuid NOT NULL UNIQUE
                                        REFERENCES entity_research_provider_observation
                                        (observation_id) ON DELETE RESTRICT,
            operation_id                uuid NOT NULL,
            snapshot_id                 uuid NOT NULL,
            workspace_id                text NOT NULL,
            subject_type                text NOT NULL,
            target_entity_id            uuid NOT NULL,
            result_artifact_key         text NOT NULL,
            result_sha256               text NOT NULL,
            delivery                    text NOT NULL,
            requested_field_keys        text[] NOT NULL,
            created_at                  timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT entity_research_result_operation_fk
                FOREIGN KEY (operation_id, workspace_id)
                REFERENCES external_research_operation (id, workspace_id)
                ON DELETE RESTRICT,
            CONSTRAINT entity_research_result_snapshot_fk
                FOREIGN KEY (snapshot_id, workspace_id)
                REFERENCES external_research_snapshot (id, workspace_id)
                ON DELETE RESTRICT,
            CONSTRAINT entity_research_result_artifact_fk
                FOREIGN KEY (result_artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id)
                ON DELETE RESTRICT,
            CONSTRAINT entity_research_result_operation_once
                UNIQUE (tool_request_id, operation_id),
            CONSTRAINT entity_research_result_subject
                CHECK (subject_type IN ('account', 'contact')),
            CONSTRAINT entity_research_result_delivery
                CHECK (delivery IN ('inline_complete', 'indexed_complete')),
            CONSTRAINT entity_research_result_hash
                CHECK (result_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT entity_research_result_fields
                CHECK (cardinality(requested_field_keys) > 0)
        )
        """
    )
    op.execute(
        "CREATE INDEX entity_research_result_subject_history "
        "ON entity_research_result (workspace_id, target_entity_id, created_at, result_id)"
    )
    op.execute(
        """
        CREATE TABLE entity_research_result_field (
            result_id                   uuid NOT NULL REFERENCES entity_research_result (result_id)
                                        ON DELETE RESTRICT,
            ordinal                     integer NOT NULL,
            field_key                   text NOT NULL,
            outcome                     text NOT NULL,
            claim_delta                 text NOT NULL,
            claim_refs                  uuid[] NOT NULL DEFAULT '{}',
            decision_refs               text[] NOT NULL DEFAULT '{}',
            value_artifact_key          text,
            workspace_id                text NOT NULL,
            verification_status         text NOT NULL,
            created_at                  timestamptz NOT NULL DEFAULT now(),

            PRIMARY KEY (result_id, ordinal),
            UNIQUE (result_id, field_key),
            CONSTRAINT entity_research_result_field_value_fk
                FOREIGN KEY (value_artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id)
                ON DELETE RESTRICT,
            CONSTRAINT entity_research_result_field_ordinal CHECK (ordinal >= 0),
            CONSTRAINT entity_research_result_field_outcome CHECK (
                outcome IN ('found', 'null', 'unsupported', 'conflict', 'rejected')
            ),
            CONSTRAINT entity_research_result_field_delta CHECK (
                claim_delta IN ('accepted', 'corroborating', 'conflicting', 'rejected', 'none')
            ),
            CONSTRAINT entity_research_result_field_shape CHECK (
                (outcome IN ('null', 'unsupported') AND claim_delta = 'none') OR
                (outcome = 'found' AND claim_delta IN ('accepted', 'corroborating')
                    AND cardinality(claim_refs) > 0) OR
                (outcome = 'conflict' AND claim_delta = 'conflicting'
                    AND cardinality(claim_refs) > 0) OR
                (outcome = 'rejected' AND claim_delta = 'rejected'
                    AND cardinality(decision_refs) > 0)
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE entity_research_result_evidence (
            evidence_id                 uuid NOT NULL,
            result_id                   uuid NOT NULL,
            field_ordinal               integer NOT NULL,
            evidence_ordinal            integer NOT NULL,
            artifact_key                text NOT NULL,
            workspace_id                text NOT NULL,
            source_key                  text NOT NULL,
            source_url                  text,
            provider_source_id          text,
            evidence_span_sha256        text NOT NULL,
            created_at                  timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT entity_research_result_evidence_field_fk
                FOREIGN KEY (result_id, field_ordinal)
                REFERENCES entity_research_result_field (result_id, ordinal)
                ON DELETE RESTRICT,
            CONSTRAINT entity_research_result_evidence_artifact_fk
                FOREIGN KEY (artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id)
                ON DELETE RESTRICT,
            PRIMARY KEY (result_id, field_ordinal, evidence_ordinal),
            CONSTRAINT entity_research_result_evidence_ordinal CHECK (evidence_ordinal >= 0),
            CONSTRAINT entity_research_result_evidence_source
                CHECK (source_url IS NOT NULL OR provider_source_id IS NOT NULL),
            CONSTRAINT entity_research_result_evidence_hash
                CHECK (evidence_span_sha256 ~ '^[0-9a-f]{64}$')
        )
        """
    )
    op.execute(
        "CREATE INDEX entity_research_result_evidence_ref "
        "ON entity_research_result_evidence (evidence_id, workspace_id)"
    )

    op.execute(
        """
        CREATE FUNCTION reject_entity_research_tool_projection_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'entity research tool/result history is append-only';
        END
        $$
        """
    )
    for table in (
        "entity_research_tool_request",
        "entity_research_provider_observation",
        "entity_research_result",
        "entity_research_result_field",
        "entity_research_result_evidence",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_entity_research_tool_projection_mutation()"
        )


def downgrade() -> None:
    for table in (
        "entity_research_result_evidence",
        "entity_research_result_field",
        "entity_research_result",
        "entity_research_provider_observation",
        "entity_research_tool_request",
    ):
        op.execute(f"DROP TRIGGER {table}_append_only ON {table}")
    op.execute("DROP FUNCTION reject_entity_research_tool_projection_mutation")
    op.execute(
        "DROP TRIGGER entity_research_tool_request_authority ON entity_research_tool_request"
    )
    op.execute("DROP FUNCTION entity_research_validate_tool_request")
    op.execute("DROP TABLE entity_research_result_evidence")
    op.execute("DROP TABLE entity_research_result_field")
    op.execute("DROP TABLE entity_research_result")
    op.execute(
        "DROP TRIGGER entity_research_provider_observation_authority "
        "ON entity_research_provider_observation"
    )
    op.execute("DROP FUNCTION entity_research_validate_provider_observation")
    op.execute("DROP TABLE entity_research_provider_observation")
    op.execute("DROP TABLE entity_research_tool_request")
