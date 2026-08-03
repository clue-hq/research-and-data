"""e1 targeted enrichment ledger

Revision ID: f2c0b2ed21dd
Revises: 44ca5271670f
Create Date: 2026-08-03 09:10:59.828358+00:00

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
revision: str = "f2c0b2ed21dd"
down_revision: str | None = "44ca5271670f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE targeted_enrichment_state AS ENUM ("
        "'planned', 'submitting', 'provider_running', 'reconciling', 'materializing', "
        "'waiting_external', 'succeeded', 'failed_retryable', 'failed_terminal', "
        "'spend_outcome_unknown', 'cancelled')"
    )
    op.execute(
        "CREATE TYPE targeted_enrichment_spend_outcome AS ENUM ("
        "'not_dispatched', 'unknown', 'not_charged', 'charged')"
    )
    op.execute(
        "CREATE TYPE targeted_enrichment_field_state AS ENUM ("
        "'pending', 'resolved', 'confirmed_missing', 'import_unresolved', 'failed_terminal')"
    )
    # A composite unique anchor lets every E1 operation prove that its stored seal hash belongs to
    # the same workspace/batch instead of merely referencing some globally unique seal.
    op.execute(
        "ALTER TABLE discovery_batch_seal ADD CONSTRAINT "
        "discovery_batch_seal_lineage_unique UNIQUE (batch_id, workspace_id, seal_sha256)"
    )
    op.execute(
        """
        CREATE TABLE targeted_enrichment_operation (
            id                         uuid NOT NULL,
            workspace_id               text NOT NULL,
            project_id                 text NOT NULL,
            project_run_id             uuid NOT NULL,
            icp_key                    text NOT NULL,
            icp_version                integer NOT NULL,
            discovery_batch_id         uuid NOT NULL,
            discovery_seal_sha256      text NOT NULL,
            source_key                 text NOT NULL,
            provider_api_version       text NOT NULL,
            provider_contract_version  text NOT NULL,
            pricing_policy_version     text NOT NULL,
            field_policy_version       text NOT NULL,
            observation_window         text NOT NULL,
            request_fingerprint        text NOT NULL,
            request_json               jsonb NOT NULL,
            provider_external_id       text NOT NULL,
            state                      targeted_enrichment_state NOT NULL DEFAULT 'planned',
            spend_outcome              targeted_enrichment_spend_outcome NOT NULL
                                       DEFAULT 'not_dispatched',
            import_id                  text,
            provider_operation_id      text,
            input_artifact_key         text NOT NULL,
            csv_artifact_key           text NOT NULL,
            submitted_receipt_ref      text,
            final_receipt_ref          text,
            raw_response_manifest_key  text,
            provider_units_reserved    numeric NOT NULL DEFAULT 0,
            provider_units_charged     numeric NOT NULL DEFAULT 0,
            cost_cents_reserved        numeric NOT NULL DEFAULT 0,
            cost_cents_charged         numeric NOT NULL DEFAULT 0,
            next_poll_at               timestamptz,
            failure_code               text,
            started_at                 timestamptz,
            terminal_at                timestamptz,
            created_at                 timestamptz NOT NULL DEFAULT now(),
            updated_at                 timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT targeted_enrichment_operation_pkey PRIMARY KEY (id),
            CONSTRAINT targeted_enrichment_operation_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT targeted_enrichment_operation_run_fk
                FOREIGN KEY (project_run_id, workspace_id, project_id)
                REFERENCES project_run (id, workspace_id, project_id),
            CONSTRAINT targeted_enrichment_operation_seal_fk
                FOREIGN KEY (discovery_batch_id, workspace_id, discovery_seal_sha256)
                REFERENCES discovery_batch_seal (batch_id, workspace_id, seal_sha256),
            CONSTRAINT targeted_enrichment_operation_workspace_anchor UNIQUE (id, workspace_id),
            CONSTRAINT targeted_enrichment_operation_request_unique
                UNIQUE (workspace_id, source_key, request_fingerprint, observation_window),
            CONSTRAINT targeted_enrichment_operation_external_unique
                UNIQUE (source_key, provider_external_id),
            CONSTRAINT targeted_enrichment_operation_provider_unique
                UNIQUE (source_key, provider_operation_id),
            CONSTRAINT targeted_enrichment_operation_icp_positive CHECK (icp_version >= 1),
            CONSTRAINT targeted_enrichment_operation_hashes CHECK (
                request_fingerprint ~ '^[0-9a-f]{64}$'
                AND discovery_seal_sha256 ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT targeted_enrichment_operation_request_object
                CHECK (jsonb_typeof(request_json) = 'object'),
            CONSTRAINT targeted_enrichment_operation_costs_nonnegative CHECK (
                provider_units_reserved >= 0 AND provider_units_charged >= 0
                AND cost_cents_reserved >= 0 AND cost_cents_charged >= 0
            ),
            CONSTRAINT targeted_enrichment_operation_costs_within_reservation CHECK (
                provider_units_charged <= provider_units_reserved
                AND cost_cents_charged <= cost_cents_reserved
            ),
            CONSTRAINT targeted_enrichment_operation_unknown_spend CHECK (
                (state = 'spend_outcome_unknown') = (spend_outcome = 'unknown')
            ),
            CONSTRAINT targeted_enrichment_operation_not_charged_zero CHECK (
                spend_outcome <> 'not_charged'
                OR (provider_units_charged = 0 AND cost_cents_charged = 0)
            ),
            CONSTRAINT targeted_enrichment_operation_terminal_time CHECK (
                (state IN ('succeeded', 'failed_terminal', 'cancelled'))
                = (terminal_at IS NOT NULL)
            ),
            CONSTRAINT targeted_enrichment_operation_success_evidence CHECK (
                state <> 'succeeded' OR (
                    spend_outcome = 'charged' AND provider_operation_id IS NOT NULL
                    AND submitted_receipt_ref IS NOT NULL AND final_receipt_ref IS NOT NULL
                    AND raw_response_manifest_key IS NOT NULL
                )
            ),
            CONSTRAINT targeted_enrichment_operation_input_fk
                FOREIGN KEY (input_artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT targeted_enrichment_operation_csv_fk
                FOREIGN KEY (csv_artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT targeted_enrichment_operation_submit_receipt_fk
                FOREIGN KEY (submitted_receipt_ref, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT targeted_enrichment_operation_final_receipt_fk
                FOREIGN KEY (final_receipt_ref, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT targeted_enrichment_operation_manifest_fk
                FOREIGN KEY (raw_response_manifest_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX targeted_enrichment_operation_poll_due ON targeted_enrichment_operation "
        "(next_poll_at, id) WHERE next_poll_at IS NOT NULL AND state IN "
        "('provider_running', 'waiting_external', 'reconciling')"
    )
    op.execute(
        """
        CREATE TABLE targeted_enrichment_artifact (
            operation_id       uuid NOT NULL,
            workspace_id       text NOT NULL,
            ordinal            integer NOT NULL,
            artifact_kind      text NOT NULL,
            artifact_key       text NOT NULL,
            content_sha256     text NOT NULL,
            provider_request_id text,
            created_at         timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT targeted_enrichment_artifact_pkey PRIMARY KEY (operation_id, ordinal),
            CONSTRAINT targeted_enrichment_artifact_operation_fk
                FOREIGN KEY (operation_id, workspace_id)
                REFERENCES targeted_enrichment_operation (id, workspace_id),
            CONSTRAINT targeted_enrichment_artifact_storage_fk
                FOREIGN KEY (artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT targeted_enrichment_artifact_event_unique
                UNIQUE NULLS NOT DISTINCT (
                    operation_id, artifact_kind, content_sha256, provider_request_id
                ),
            CONSTRAINT targeted_enrichment_artifact_ordinal_nonnegative CHECK (ordinal >= 0),
            CONSTRAINT targeted_enrichment_artifact_sha CHECK (
                content_sha256 ~ '^[0-9a-f]{64}$'
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE targeted_enrichment_target (
            operation_id  uuid NOT NULL,
            workspace_id  text NOT NULL,
            account_id    uuid NOT NULL,
            identifier_url text NOT NULL,
            tier_claim_id uuid NOT NULL,
            ordinal       integer NOT NULL,
            created_at    timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT targeted_enrichment_target_pkey PRIMARY KEY (operation_id, account_id),
            CONSTRAINT targeted_enrichment_target_operation_fk
                FOREIGN KEY (operation_id, workspace_id)
                REFERENCES targeted_enrichment_operation (id, workspace_id),
            CONSTRAINT targeted_enrichment_target_account_fk
                FOREIGN KEY (account_id, workspace_id)
                REFERENCES account_entity (id, workspace_id),
            CONSTRAINT targeted_enrichment_target_tier_claim_fk FOREIGN KEY (tier_claim_id)
                REFERENCES claim (id),
            CONSTRAINT targeted_enrichment_target_url_unique
                UNIQUE (operation_id, identifier_url),
            CONSTRAINT targeted_enrichment_target_ordinal_unique UNIQUE (operation_id, ordinal),
            CONSTRAINT targeted_enrichment_target_ordinal_nonnegative CHECK (ordinal >= 0)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE targeted_enrichment_item_snapshot (
            operation_id       uuid NOT NULL,
            workspace_id       text NOT NULL,
            provider_item_id   text NOT NULL,
            source_entity_id   text NOT NULL,
            account_id         uuid NOT NULL,
            raw_artifact_key   text NOT NULL,
            item_sha256        text NOT NULL,
            observed_at        timestamptz NOT NULL,
            materialized_at    timestamptz,
            created_at         timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT targeted_enrichment_item_pkey
                PRIMARY KEY (operation_id, provider_item_id),
            CONSTRAINT targeted_enrichment_item_operation_fk
                FOREIGN KEY (operation_id, workspace_id)
                REFERENCES targeted_enrichment_operation (id, workspace_id),
            CONSTRAINT targeted_enrichment_item_target_fk
                FOREIGN KEY (operation_id, account_id)
                REFERENCES targeted_enrichment_target (operation_id, account_id),
            CONSTRAINT targeted_enrichment_item_artifact_fk
                FOREIGN KEY (raw_artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT targeted_enrichment_item_source_unique
                UNIQUE (operation_id, source_entity_id),
            CONSTRAINT targeted_enrichment_item_account_unique
                UNIQUE (operation_id, account_id),
            CONSTRAINT targeted_enrichment_item_sha CHECK (item_sha256 ~ '^[0-9a-f]{64}$')
        )
        """
    )
    op.execute(
        """
        CREATE TABLE targeted_enrichment_field_result (
            operation_id      uuid NOT NULL,
            workspace_id      text NOT NULL,
            account_id        uuid NOT NULL,
            field_key         text NOT NULL,
            state             targeted_enrichment_field_state NOT NULL DEFAULT 'pending',
            provider_item_id  text,
            item_artifact_key text,
            claim_id          uuid,
            reason_code       text,
            updated_at        timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT targeted_enrichment_field_result_pkey
                PRIMARY KEY (operation_id, account_id, field_key),
            CONSTRAINT targeted_enrichment_field_result_target_fk
                FOREIGN KEY (operation_id, account_id)
                REFERENCES targeted_enrichment_target (operation_id, account_id),
            CONSTRAINT targeted_enrichment_field_result_operation_fk
                FOREIGN KEY (operation_id, workspace_id)
                REFERENCES targeted_enrichment_operation (id, workspace_id),
            CONSTRAINT targeted_enrichment_field_result_item_fk
                FOREIGN KEY (operation_id, provider_item_id)
                REFERENCES targeted_enrichment_item_snapshot (operation_id, provider_item_id),
            CONSTRAINT targeted_enrichment_field_result_artifact_fk
                FOREIGN KEY (item_artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT targeted_enrichment_field_result_claim_fk FOREIGN KEY (claim_id)
                REFERENCES claim (id),
            CONSTRAINT targeted_enrichment_field_result_resolved_shape CHECK (
                (state = 'resolved') = (
                    provider_item_id IS NOT NULL AND item_artifact_key IS NOT NULL
                    AND claim_id IS NOT NULL
                )
            ),
            CONSTRAINT targeted_enrichment_field_result_nonresolved_reason CHECK (
                state = 'resolved' OR reason_code IS NOT NULL
            )
        )
        """
    )
    op.execute(
        """
        CREATE FUNCTION targeted_enrichment_reject_request_mutation() RETURNS trigger AS $$
        BEGIN
            IF NEW.workspace_id <> OLD.workspace_id
               OR NEW.project_id <> OLD.project_id
               OR NEW.project_run_id <> OLD.project_run_id
               OR NEW.icp_key <> OLD.icp_key
               OR NEW.icp_version <> OLD.icp_version
               OR NEW.discovery_batch_id <> OLD.discovery_batch_id
               OR NEW.discovery_seal_sha256 <> OLD.discovery_seal_sha256
               OR NEW.source_key <> OLD.source_key
               OR NEW.provider_api_version <> OLD.provider_api_version
               OR NEW.provider_contract_version <> OLD.provider_contract_version
               OR NEW.pricing_policy_version <> OLD.pricing_policy_version
               OR NEW.field_policy_version <> OLD.field_policy_version
               OR NEW.observation_window <> OLD.observation_window
               OR NEW.request_fingerprint <> OLD.request_fingerprint
               OR NEW.request_json <> OLD.request_json
               OR NEW.provider_external_id <> OLD.provider_external_id
               OR NEW.input_artifact_key <> OLD.input_artifact_key
               OR NEW.csv_artifact_key <> OLD.csv_artifact_key
               OR NEW.provider_units_reserved <> OLD.provider_units_reserved
               OR NEW.cost_cents_reserved <> OLD.cost_cents_reserved THEN
                RAISE EXCEPTION 'targeted enrichment request lineage is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER targeted_enrichment_operation_request_immutable "
        "BEFORE UPDATE ON targeted_enrichment_operation FOR EACH ROW "
        "EXECUTE FUNCTION targeted_enrichment_reject_request_mutation()"
    )
    op.execute(
        """
        CREATE FUNCTION targeted_enrichment_require_complete_success() RETURNS trigger AS $$
        DECLARE
            expected_fields integer;
            actual_fields integer;
            pending_fields integer;
        BEGIN
            IF NEW.state = 'succeeded' AND OLD.state <> 'succeeded' THEN
                expected_fields := jsonb_array_length(NEW.request_json -> 'targets')
                    * jsonb_array_length(NEW.request_json -> 'fields');
                SELECT count(*), count(*) FILTER (WHERE state = 'pending')
                  INTO actual_fields, pending_fields
                  FROM targeted_enrichment_field_result
                 WHERE operation_id = NEW.id AND workspace_id = NEW.workspace_id;
                IF actual_fields <> expected_fields OR pending_fields <> 0 THEN
                    RAISE EXCEPTION
                        'targeted enrichment cannot succeed before every field is terminal';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER targeted_enrichment_operation_success_complete "
        "BEFORE UPDATE ON targeted_enrichment_operation FOR EACH ROW "
        "EXECUTE FUNCTION targeted_enrichment_require_complete_success()"
    )
    op.execute(
        """
        CREATE FUNCTION targeted_enrichment_guard_field_result() RETURNS trigger AS $$
        DECLARE
            operation_state targeted_enrichment_state;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'targeted enrichment field outcomes cannot be deleted';
            END IF;
            SELECT state INTO operation_state
              FROM targeted_enrichment_operation
             WHERE id = COALESCE(NEW.operation_id, OLD.operation_id)
               AND workspace_id = COALESCE(NEW.workspace_id, OLD.workspace_id);
            IF TG_OP = 'INSERT' THEN
                IF operation_state <> 'planned' THEN
                    RAISE EXCEPTION
                        'targeted enrichment fields must be declared during reservation';
                END IF;
                RETURN NEW;
            END IF;
            IF OLD.state <> 'pending'
               OR operation_state IN (
                    'succeeded', 'failed_terminal', 'spend_outcome_unknown', 'cancelled'
               ) THEN
                RAISE EXCEPTION 'terminal targeted enrichment field outcome is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER targeted_enrichment_field_result_guard "
        "BEFORE INSERT OR UPDATE OR DELETE ON targeted_enrichment_field_result FOR EACH ROW "
        "EXECUTE FUNCTION targeted_enrichment_guard_field_result()"
    )
    for table in (
        "targeted_enrichment_target",
        "targeted_enrichment_artifact",
        "targeted_enrichment_item_snapshot",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION discovery_reject_immutable_mutation()"
        )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER targeted_enrichment_item_snapshot_immutable "
        "ON targeted_enrichment_item_snapshot"
    )
    op.execute(
        "DROP TRIGGER targeted_enrichment_artifact_immutable ON targeted_enrichment_artifact"
    )
    op.execute("DROP TRIGGER targeted_enrichment_target_immutable ON targeted_enrichment_target")
    op.execute(
        "DROP TRIGGER targeted_enrichment_operation_request_immutable "
        "ON targeted_enrichment_operation"
    )
    op.execute(
        "DROP TRIGGER targeted_enrichment_operation_success_complete "
        "ON targeted_enrichment_operation"
    )
    op.execute(
        "DROP TRIGGER targeted_enrichment_field_result_guard ON targeted_enrichment_field_result"
    )
    op.execute("DROP FUNCTION targeted_enrichment_guard_field_result()")
    op.execute("DROP FUNCTION targeted_enrichment_require_complete_success()")
    op.execute("DROP FUNCTION targeted_enrichment_reject_request_mutation()")
    op.execute("DROP TABLE targeted_enrichment_field_result")
    op.execute("DROP TABLE targeted_enrichment_item_snapshot")
    op.execute("DROP TABLE targeted_enrichment_target")
    op.execute("DROP TABLE targeted_enrichment_artifact")
    op.execute("DROP TABLE targeted_enrichment_operation")
    op.execute(
        "ALTER TABLE discovery_batch_seal DROP CONSTRAINT discovery_batch_seal_lineage_unique"
    )
    op.execute("DROP TYPE targeted_enrichment_field_state")
    op.execute("DROP TYPE targeted_enrichment_spend_outcome")
    op.execute("DROP TYPE targeted_enrichment_state")
