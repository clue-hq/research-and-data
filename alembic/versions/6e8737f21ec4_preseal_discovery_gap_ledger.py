"""preseal discovery gap ledger

Revision ID: 6e8737f21ec4
Revises: bd0b7e62a2b4
Create Date: 2026-08-03 15:41:43.194520+00:00

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
revision: str = "6e8737f21ec4"
down_revision: str | None = "bd0b7e62a2b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE discovery_gap_operation_state AS ENUM ("
        "'planned', 'dispatching', 'materializing', 'succeeded', 'failed_retryable', "
        "'failed_terminal', 'spend_outcome_unknown', 'cancelled')"
    )
    op.execute(
        "CREATE TYPE discovery_gap_spend_outcome AS ENUM ("
        "'not_dispatched', 'unknown', 'not_charged', 'charged')"
    )
    op.execute(
        "CREATE TYPE discovery_gap_field_state AS ENUM ("
        "'pending', 'resolved', 'confirmed_missing', 'corroborated', 'conflict', "
        "'blocked_by_policy', 'failed_terminal')"
    )
    op.execute(
        """
        CREATE TABLE discovery_gap_operation (
            id                        uuid NOT NULL,
            workspace_id              text NOT NULL,
            project_id                text NOT NULL,
            project_run_id            uuid NOT NULL,
            icp_key                   text NOT NULL,
            icp_version               integer NOT NULL,
            discovery_batch_id        uuid NOT NULL,
            account_id                uuid NOT NULL,
            primary_domain            text NOT NULL,
            source_key                text NOT NULL,
            provider_api_version      text NOT NULL,
            provider_contract_version text NOT NULL,
            pricing_policy_version    text NOT NULL,
            field_policy_version      text NOT NULL,
            observation_window        text NOT NULL,
            request_fingerprint       text NOT NULL,
            request_json              jsonb NOT NULL,
            state                     discovery_gap_operation_state NOT NULL,
            spend_outcome             discovery_gap_spend_outcome NOT NULL,
            request_artifact_key      text NOT NULL,
            response_artifact_key     text,
            receipt_artifact_key      text,
            provider_request_id       text,
            provider_units_reserved  numeric NOT NULL DEFAULT 0,
            provider_units_charged   numeric NOT NULL DEFAULT 0,
            credits_remaining         integer,
            cost_cents_reserved       numeric NOT NULL DEFAULT 0,
            cost_cents_charged        numeric NOT NULL DEFAULT 0,
            failure_code              text,
            started_at                timestamptz,
            terminal_at               timestamptz,
            created_at                timestamptz NOT NULL DEFAULT now(),
            updated_at                timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT discovery_gap_operation_pkey PRIMARY KEY (id),
            CONSTRAINT discovery_gap_operation_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT discovery_gap_operation_run_fk
                FOREIGN KEY (project_run_id, workspace_id, project_id)
                REFERENCES project_run (id, workspace_id, project_id),
            CONSTRAINT discovery_gap_operation_batch_fk
                FOREIGN KEY (discovery_batch_id, workspace_id)
                REFERENCES discovery_batch (id, workspace_id),
            CONSTRAINT discovery_gap_operation_account_fk
                FOREIGN KEY (account_id, workspace_id)
                REFERENCES account_entity (id, workspace_id),
            CONSTRAINT discovery_gap_operation_workspace_anchor UNIQUE (id, workspace_id),
            CONSTRAINT discovery_gap_operation_request_unique UNIQUE (
                workspace_id, discovery_batch_id, account_id, source_key, observation_window
            ),
            CONSTRAINT discovery_gap_operation_icp_positive CHECK (icp_version >= 1),
            CONSTRAINT discovery_gap_operation_hash CHECK (
                request_fingerprint ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT discovery_gap_operation_request_object
                CHECK (jsonb_typeof(request_json) = 'object'),
            CONSTRAINT discovery_gap_operation_costs_nonnegative CHECK (
                provider_units_reserved >= 0 AND provider_units_charged >= 0
                AND cost_cents_reserved >= 0 AND cost_cents_charged >= 0
            ),
            CONSTRAINT discovery_gap_operation_bounded_charge CHECK (
                provider_units_charged <= provider_units_reserved
            ),
            CONSTRAINT discovery_gap_operation_credits_remaining CHECK (
                credits_remaining IS NULL OR credits_remaining >= 0
            ),
            CONSTRAINT discovery_gap_operation_unknown_spend CHECK (
                (state = 'spend_outcome_unknown') = (spend_outcome = 'unknown')
            ),
            CONSTRAINT discovery_gap_operation_terminal_time CHECK (
                (state IN ('succeeded', 'failed_terminal', 'spend_outcome_unknown', 'cancelled'))
                = (terminal_at IS NOT NULL)
            ),
            CONSTRAINT discovery_gap_operation_success_evidence CHECK (
                state <> 'succeeded' OR (
                    spend_outcome = 'charged' AND response_artifact_key IS NOT NULL
                    AND receipt_artifact_key IS NOT NULL AND provider_request_id IS NOT NULL
                )
            ),
            CONSTRAINT discovery_gap_operation_request_artifact_fk
                FOREIGN KEY (request_artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT discovery_gap_operation_response_artifact_fk
                FOREIGN KEY (response_artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT discovery_gap_operation_receipt_artifact_fk
                FOREIGN KEY (receipt_artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX discovery_gap_operation_batch_state ON discovery_gap_operation "
        "(workspace_id, discovery_batch_id, state)"
    )
    op.execute(
        """
        CREATE TABLE discovery_gap_field_result (
            operation_id          uuid NOT NULL,
            workspace_id          text NOT NULL,
            discovery_batch_id    uuid NOT NULL,
            account_id            uuid NOT NULL,
            logical_field_key     text NOT NULL,
            field_key             text NOT NULL,
            source_key            text NOT NULL,
            expected_value_credits numeric NOT NULL,
            basis_claim_ids       jsonb NOT NULL DEFAULT '[]'::jsonb,
            source_item_ids       jsonb NOT NULL DEFAULT '[]'::jsonb,
            state                 discovery_gap_field_state NOT NULL,
            provider_claim_id     uuid,
            current_claim_id      uuid,
            conflicting_claim_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
            reason_code           text NOT NULL,
            created_at            timestamptz NOT NULL DEFAULT now(),
            updated_at            timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT discovery_gap_field_result_pkey
                PRIMARY KEY (operation_id, logical_field_key),
            CONSTRAINT discovery_gap_field_result_operation_fk
                FOREIGN KEY (operation_id, workspace_id)
                REFERENCES discovery_gap_operation (id, workspace_id),
            CONSTRAINT discovery_gap_field_result_batch_fk
                FOREIGN KEY (discovery_batch_id, workspace_id)
                REFERENCES discovery_batch (id, workspace_id),
            CONSTRAINT discovery_gap_field_result_account_fk
                FOREIGN KEY (account_id, workspace_id)
                REFERENCES account_entity (id, workspace_id),
            CONSTRAINT discovery_gap_field_result_target_unique UNIQUE (
                workspace_id, discovery_batch_id, account_id, logical_field_key
            ),
            CONSTRAINT discovery_gap_field_result_expected_positive
                CHECK (expected_value_credits > 0),
            CONSTRAINT discovery_gap_field_result_arrays CHECK (
                jsonb_typeof(basis_claim_ids) = 'array'
                AND jsonb_typeof(source_item_ids) = 'array'
                AND jsonb_typeof(conflicting_claim_ids) = 'array'
            ),
            CONSTRAINT discovery_gap_field_result_shape CHECK (
                (state = 'pending' AND provider_claim_id IS NULL)
                OR (state IN ('resolved', 'corroborated') AND provider_claim_id IS NOT NULL)
                OR (state = 'conflict' AND provider_claim_id IS NOT NULL
                    AND jsonb_array_length(conflicting_claim_ids) > 0)
                OR (state IN ('confirmed_missing', 'blocked_by_policy', 'failed_terminal')
                    AND provider_claim_id IS NULL)
            ),
            CONSTRAINT discovery_gap_field_result_provider_claim_fk
                FOREIGN KEY (provider_claim_id) REFERENCES claim (id),
            CONSTRAINT discovery_gap_field_result_current_claim_fk
                FOREIGN KEY (current_claim_id) REFERENCES claim (id)
        )
        """
    )
    op.execute(
        """
        CREATE FUNCTION discovery_gap_validate_operation_insert() RETURNS trigger AS $$
        DECLARE
            candidate text;
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM discovery_batch batch
                JOIN project_run run
                  ON run.id = batch.project_run_id
                 AND run.workspace_id = batch.workspace_id
                 AND run.project_id = batch.project_id
                WHERE batch.id = NEW.discovery_batch_id
                  AND batch.workspace_id = NEW.workspace_id
                  AND batch.project_run_id = NEW.project_run_id
                  AND batch.project_id = NEW.project_id
                  AND batch.icp_key = NEW.icp_key
                  AND batch.icp_version = NEW.icp_version
                  AND batch.state NOT IN ('sealed', 'cancelled_unsealed', 'failed_terminal')
                  AND batch.sealed_at IS NULL
                  AND run.status = 'active'
                  AND run.phase = 'discovery'
                  AND NOT EXISTS (
                      SELECT 1 FROM discovery_batch newer
                      WHERE newer.workspace_id = batch.workspace_id
                        AND newer.project_run_id = batch.project_run_id
                        AND newer.generation > batch.generation
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM discovery_batch_seal seal
                      WHERE seal.batch_id = batch.id AND seal.workspace_id = batch.workspace_id
                  )
            ) THEN
                RAISE EXCEPTION 'discovery-gap requires active current unsealed batch';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM discovery_candidate_link candidate
                WHERE candidate.workspace_id = NEW.workspace_id
                  AND candidate.batch_id = NEW.discovery_batch_id
                  AND candidate.survivor_entity_id = NEW.account_id
                  AND candidate.admission_status IN ('admitted', 'merged')
            ) THEN
                RAISE EXCEPTION 'discovery-gap account is not an admitted batch survivor';
            END IF;
            IF NEW.request_json ->> 'workspace_id' IS DISTINCT FROM NEW.workspace_id
               OR NEW.request_json ->> 'project_id' IS DISTINCT FROM NEW.project_id
               OR NEW.request_json ->> 'project_run_id' IS DISTINCT FROM NEW.project_run_id::text
               OR NEW.request_json ->> 'icp_key' IS DISTINCT FROM NEW.icp_key
               OR (NEW.request_json ->> 'icp_version')::integer IS DISTINCT FROM NEW.icp_version
               OR NEW.request_json ->> 'discovery_batch_id' IS DISTINCT FROM
                  NEW.discovery_batch_id::text
               OR NEW.request_json ->> 'account_id' IS DISTINCT FROM NEW.account_id::text
               OR NEW.request_json ->> 'primary_domain' IS DISTINCT FROM NEW.primary_domain
               OR NEW.request_json ->> 'source_key' IS DISTINCT FROM NEW.source_key
               OR NEW.request_json ->> 'provider_api_version' IS DISTINCT FROM
                  NEW.provider_api_version
               OR NEW.request_json ->> 'provider_contract_version' IS DISTINCT FROM
                  NEW.provider_contract_version
               OR NEW.request_json ->> 'pricing_policy_version' IS DISTINCT FROM
                  NEW.pricing_policy_version
               OR NEW.request_json ->> 'field_policy_version' IS DISTINCT FROM
                  NEW.field_policy_version
               OR NEW.request_json ->> 'observation_window' IS DISTINCT FROM
                  NEW.observation_window
               OR jsonb_typeof(NEW.request_json -> 'required_criteria') IS DISTINCT FROM 'array'
               OR jsonb_array_length(NEW.request_json -> 'required_criteria') = 0
               OR jsonb_typeof(NEW.request_json -> 'eligibility_claim_ids') IS DISTINCT FROM 'array'
               OR jsonb_array_length(NEW.request_json -> 'eligibility_claim_ids') = 0
               OR jsonb_typeof(NEW.request_json -> 'fields') IS DISTINCT FROM 'array'
               OR jsonb_array_length(NEW.request_json -> 'fields') = 0
            THEN
                RAISE EXCEPTION 'discovery-gap request JSON differs from indexed lineage';
            END IF;
            FOR candidate IN
                SELECT jsonb_array_elements_text(NEW.request_json -> 'eligibility_claim_ids')
            LOOP
                IF NOT EXISTS (
                    SELECT 1
                    FROM claim eligibility
                    JOIN discovery_item_snapshot item
                      ON item.workspace_id = NEW.workspace_id
                     AND item.raw_artifact_key = eligibility.artifact_key
                    JOIN discovery_candidate_link link
                      ON link.workspace_id = item.workspace_id
                     AND link.item_snapshot_id = item.id
                     AND link.batch_id = NEW.discovery_batch_id
                    WHERE eligibility.id = candidate::uuid
                      AND eligibility.entity_id = NEW.account_id
                      AND eligibility.field_key = 'core.discovery_provenance'
                      AND (eligibility.workspace_id = NEW.workspace_id
                           OR (eligibility.workspace_id IS NULL
                               AND eligibility.reuse_scope = 'public_footprint'))
                      AND link.survivor_entity_id = NEW.account_id
                      AND link.admission_status IN ('admitted', 'merged')
                ) THEN
                    RAISE EXCEPTION 'discovery-gap eligibility claim lineage mismatch';
                END IF;
            END LOOP;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER discovery_gap_operation_insert_guard BEFORE INSERT "
        "ON discovery_gap_operation FOR EACH ROW "
        "EXECUTE FUNCTION discovery_gap_validate_operation_insert()"
    )
    op.execute(
        """
        CREATE FUNCTION discovery_gap_validate_field() RETURNS trigger AS $$
        DECLARE
            candidate text;
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM discovery_gap_operation operation
                WHERE operation.id = NEW.operation_id
                  AND operation.workspace_id = NEW.workspace_id
                  AND operation.discovery_batch_id = NEW.discovery_batch_id
                  AND operation.account_id = NEW.account_id
                  AND operation.source_key = NEW.source_key
            ) THEN
                RAISE EXCEPTION 'discovery-gap field lineage differs from its operation';
            END IF;
            IF TG_OP = 'INSERT' AND NOT EXISTS (
                SELECT 1 FROM discovery_field_resolution resolution
                WHERE resolution.workspace_id = NEW.workspace_id
                  AND resolution.batch_id = NEW.discovery_batch_id
                  AND resolution.account_entity_id = NEW.account_id
                  AND resolution.logical_field_key = NEW.logical_field_key
                  AND resolution.state = 'pending'
            ) THEN
                RAISE EXCEPTION 'discovery-gap field requires a pending discovery resolution';
            END IF;
            IF NEW.provider_claim_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM claim
                WHERE id = NEW.provider_claim_id AND entity_id = NEW.account_id
                  AND field_key = NEW.field_key AND source_key = NEW.source_key
                  AND (workspace_id = NEW.workspace_id
                       OR (workspace_id IS NULL AND reuse_scope = 'public_footprint'))
            ) THEN
                RAISE EXCEPTION 'discovery-gap provider claim lineage mismatch';
            END IF;
            IF NEW.current_claim_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM claim
                WHERE id = NEW.current_claim_id AND entity_id = NEW.account_id
                  AND field_key = NEW.field_key
                  AND (workspace_id = NEW.workspace_id
                       OR (workspace_id IS NULL AND reuse_scope = 'public_footprint'))
            ) THEN
                RAISE EXCEPTION 'discovery-gap current claim lineage mismatch';
            END IF;
            FOR candidate IN SELECT jsonb_array_elements_text(NEW.basis_claim_ids)
            LOOP
                IF NOT EXISTS (
                    SELECT 1
                    FROM discovery_field_resolution resolution
                    JOIN discovery_field_claim edge
                      ON edge.workspace_id = resolution.workspace_id
                     AND edge.resolution_id = resolution.id
                    WHERE resolution.workspace_id = NEW.workspace_id
                      AND resolution.batch_id = NEW.discovery_batch_id
                      AND resolution.account_entity_id = NEW.account_id
                      AND resolution.logical_field_key = NEW.logical_field_key
                      AND edge.claim_id = candidate::uuid
                ) THEN
                    RAISE EXCEPTION 'discovery-gap basis claim lineage mismatch';
                END IF;
            END LOOP;
            FOR candidate IN SELECT jsonb_array_elements_text(NEW.source_item_ids)
            LOOP
                IF NOT EXISTS (
                    SELECT 1
                    FROM discovery_field_resolution resolution
                    JOIN discovery_field_source_item edge
                      ON edge.workspace_id = resolution.workspace_id
                     AND edge.resolution_id = resolution.id
                    JOIN discovery_candidate_link link
                      ON link.workspace_id = edge.workspace_id
                     AND link.batch_id = resolution.batch_id
                     AND link.item_snapshot_id = edge.item_snapshot_id
                    WHERE resolution.workspace_id = NEW.workspace_id
                      AND resolution.batch_id = NEW.discovery_batch_id
                      AND resolution.account_entity_id = NEW.account_id
                      AND resolution.logical_field_key = NEW.logical_field_key
                      AND edge.item_snapshot_id = candidate::uuid
                      AND link.survivor_entity_id = NEW.account_id
                      AND link.admission_status IN ('admitted', 'merged')
                ) THEN
                    RAISE EXCEPTION 'discovery-gap source item lineage mismatch';
                END IF;
            END LOOP;
            FOR candidate IN SELECT jsonb_array_elements_text(NEW.conflicting_claim_ids)
            LOOP
                IF NOT EXISTS (
                    SELECT 1 FROM claim WHERE id = candidate::uuid AND entity_id = NEW.account_id
                      AND field_key = NEW.field_key
                      AND (workspace_id = NEW.workspace_id
                           OR (workspace_id IS NULL AND reuse_scope = 'public_footprint'))
                ) THEN
                    RAISE EXCEPTION 'discovery-gap conflicting claim lineage mismatch';
                END IF;
            END LOOP;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER discovery_gap_field_lineage BEFORE INSERT OR UPDATE OF "
        "provider_claim_id, current_claim_id, basis_claim_ids, source_item_ids, "
        "conflicting_claim_ids, "
        "workspace_id, discovery_batch_id, account_id, logical_field_key, field_key, source_key "
        "ON discovery_gap_field_result FOR EACH ROW EXECUTE FUNCTION discovery_gap_validate_field()"
    )
    op.execute(
        """
        CREATE FUNCTION discovery_gap_validate_success() RETURNS trigger AS $$
        BEGIN
            IF NEW.state = 'succeeded' THEN
                IF NOT EXISTS (
                    SELECT 1 FROM discovery_gap_field_result
                    WHERE operation_id = NEW.id AND workspace_id = NEW.workspace_id
                ) OR EXISTS (
                    SELECT 1 FROM discovery_gap_field_result
                    WHERE operation_id = NEW.id AND workspace_id = NEW.workspace_id
                      AND state IN ('pending', 'blocked_by_policy', 'failed_terminal')
                ) THEN
                    RAISE EXCEPTION 'discovery-gap success requires terminal fields';
                END IF;
                IF EXISTS (
                    SELECT 1
                    FROM discovery_gap_field_result field
                    LEFT JOIN discovery_field_resolution resolution
                      ON resolution.workspace_id = field.workspace_id
                     AND resolution.batch_id = field.discovery_batch_id
                     AND resolution.account_entity_id = field.account_id
                     AND resolution.logical_field_key = field.logical_field_key
                    WHERE field.operation_id = NEW.id
                      AND (
                        resolution.id IS NULL
                        OR (field.state IN ('resolved', 'corroborated')
                            AND (resolution.state <> 'resolved'
                                 OR resolution.winning_claim_id IS DISTINCT FROM
                                    COALESCE(field.current_claim_id, field.provider_claim_id)))
                        OR (field.state = 'conflict' AND resolution.state <> 'conflict')
                        OR (field.state = 'confirmed_missing'
                            AND resolution.state <> 'confirmed_missing')
                      )
                ) THEN
                    RAISE EXCEPTION 'discovery-gap success requires reconciled resolutions';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER discovery_gap_success_barrier BEFORE UPDATE OF state "
        "ON discovery_gap_operation FOR EACH ROW EXECUTE FUNCTION discovery_gap_validate_success()"
    )
    op.execute(
        """
        CREATE FUNCTION discovery_gap_reject_terminal_mutation() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'discovery-gap operations cannot be deleted';
            END IF;
            IF OLD.state IN ('succeeded', 'failed_terminal', 'spend_outcome_unknown', 'cancelled')
               AND NEW IS DISTINCT FROM OLD THEN
                RAISE EXCEPTION 'terminal discovery-gap operation is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER discovery_gap_operation_terminal_immutable BEFORE UPDATE OR DELETE "
        "ON discovery_gap_operation FOR EACH ROW "
        "EXECUTE FUNCTION discovery_gap_reject_terminal_mutation()"
    )
    op.execute(
        """
        CREATE FUNCTION discovery_gap_reject_field_terminal_mutation() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'discovery-gap field outcomes cannot be deleted';
            END IF;
            IF OLD.state <> 'pending' AND NEW IS DISTINCT FROM OLD THEN
                RAISE EXCEPTION 'terminal discovery-gap field outcome is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER discovery_gap_field_terminal_immutable BEFORE UPDATE OR DELETE "
        "ON discovery_gap_field_result FOR EACH ROW "
        "EXECUTE FUNCTION discovery_gap_reject_field_terminal_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER discovery_gap_field_terminal_immutable ON discovery_gap_field_result")
    op.execute("DROP FUNCTION discovery_gap_reject_field_terminal_mutation()")
    op.execute("DROP TRIGGER discovery_gap_operation_terminal_immutable ON discovery_gap_operation")
    op.execute("DROP FUNCTION discovery_gap_reject_terminal_mutation()")
    op.execute("DROP TRIGGER discovery_gap_success_barrier ON discovery_gap_operation")
    op.execute("DROP FUNCTION discovery_gap_validate_success()")
    op.execute("DROP TRIGGER discovery_gap_field_lineage ON discovery_gap_field_result")
    op.execute("DROP FUNCTION discovery_gap_validate_field()")
    op.execute("DROP TRIGGER discovery_gap_operation_insert_guard ON discovery_gap_operation")
    op.execute("DROP FUNCTION discovery_gap_validate_operation_insert()")
    op.execute("DROP TABLE discovery_gap_field_result")
    op.execute("DROP INDEX discovery_gap_operation_batch_state")
    op.execute("DROP TABLE discovery_gap_operation")
    op.execute("DROP TYPE discovery_gap_field_state")
    op.execute("DROP TYPE discovery_gap_spend_outcome")
    op.execute("DROP TYPE discovery_gap_operation_state")
