"""M8C C5 selected-contact channel enrichment and validation ledger.

Revision ID: fd8d61eb482f
Revises: f9281fac77e1
Create Date: 2026-08-05 09:44:10+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "fd8d61eb482f"
down_revision: str | None = "f9281fac77e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE TYPE contact_channel_kind AS ENUM ('email', 'phone')")
    op.execute(
        "CREATE TYPE contact_channel_operation_state AS ENUM ("
        "'planned', 'submitting', 'waiting_external', 'ready_to_validate', 'validating', "
        "'succeeded', 'rejected', "
        "'failed_retryable', 'failed_terminal', 'spend_outcome_unknown', 'cancelled')"
    )
    op.execute(
        "CREATE TYPE contact_channel_spend_outcome AS ENUM ("
        "'not_dispatched', 'unknown', 'not_charged', 'charged')"
    )
    op.execute(
        """
        CREATE TABLE contact_channel_operation (
            id uuid NOT NULL,
            workspace_id text NOT NULL,
            project_id text NOT NULL,
            project_run_id uuid NOT NULL,
            account_id uuid NOT NULL,
            contact_id uuid NOT NULL,
            selection_id uuid NOT NULL,
            selection_sha256 text NOT NULL,
            contact_intent_sha256 text NOT NULL,
            channel contact_channel_kind NOT NULL,
            field_key text NOT NULL,
            acquisition_source_key text NOT NULL,
            validation_source_key text NOT NULL,
            observation_window text NOT NULL,
            request_fingerprint text NOT NULL,
            request_json jsonb NOT NULL,
            provider_external_id text NOT NULL,
            state contact_channel_operation_state NOT NULL DEFAULT 'planned',
            acquisition_spend_outcome contact_channel_spend_outcome NOT NULL
                                      DEFAULT 'not_dispatched',
            validation_spend_outcome contact_channel_spend_outcome NOT NULL
                                     DEFAULT 'not_dispatched',
            input_artifact_key text NOT NULL,
            csv_artifact_key text NOT NULL,
            provider_import_id text,
            provider_operation_id text,
            observed_claim_id uuid,
            observation_artifact_key text,
            validation_artifact_key text,
            receipt_artifact_key text,
            acquisition_units_charged numeric NOT NULL DEFAULT 0,
            acquisition_cost_cents_charged numeric NOT NULL DEFAULT 0,
            validation_units_charged numeric NOT NULL DEFAULT 0,
            validation_cost_cents_charged numeric NOT NULL DEFAULT 0,
            validation_json jsonb,
            next_poll_at timestamptz,
            failure_code text,
            started_at timestamptz,
            terminal_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT contact_channel_operation_pkey PRIMARY KEY (id),
            CONSTRAINT contact_channel_operation_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT contact_channel_operation_run_fk
                FOREIGN KEY (project_run_id, workspace_id, project_id)
                REFERENCES project_run (id, workspace_id, project_id),
            CONSTRAINT contact_channel_operation_account_fk
                FOREIGN KEY (account_id, workspace_id)
                REFERENCES account_entity (id, workspace_id),
            CONSTRAINT contact_channel_operation_contact_fk
                FOREIGN KEY (contact_id, workspace_id)
                REFERENCES contact_entity (id, workspace_id),
            CONSTRAINT contact_channel_operation_acquisition_source_fk
                FOREIGN KEY (acquisition_source_key) REFERENCES source_manifest (source_key),
            CONSTRAINT contact_channel_operation_validation_source_fk
                FOREIGN KEY (validation_source_key) REFERENCES source_manifest (source_key),
            CONSTRAINT contact_channel_operation_observed_claim_fk
                FOREIGN KEY (observed_claim_id) REFERENCES claim (id),
            CONSTRAINT contact_channel_operation_input_artifact_fk
                FOREIGN KEY (input_artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT contact_channel_operation_csv_artifact_fk
                FOREIGN KEY (csv_artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT contact_channel_operation_observation_artifact_fk
                FOREIGN KEY (observation_artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT contact_channel_operation_validation_artifact_fk
                FOREIGN KEY (validation_artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT contact_channel_operation_receipt_artifact_fk
                FOREIGN KEY (receipt_artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT contact_channel_operation_workspace_anchor UNIQUE (id, workspace_id),
            CONSTRAINT contact_channel_operation_request_unique UNIQUE (
                workspace_id, acquisition_source_key, request_fingerprint, observation_window
            ),
            CONSTRAINT contact_channel_operation_external_unique UNIQUE (
                acquisition_source_key, provider_external_id
            ),
            CONSTRAINT contact_channel_operation_provider_unique UNIQUE (
                acquisition_source_key, provider_operation_id
            ),
            CONSTRAINT contact_channel_operation_hashes CHECK (
                selection_sha256 ~ '^[0-9a-f]{64}$'
                AND contact_intent_sha256 ~ '^[0-9a-f]{64}$'
                AND request_fingerprint ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT contact_channel_operation_field_matches CHECK (
                (channel='email' AND field_key='core.work_email')
                OR (channel='phone' AND field_key='core.direct_phone')
            ),
            CONSTRAINT contact_channel_operation_independent_source CHECK (
                acquisition_source_key <> validation_source_key
            ),
            CONSTRAINT contact_channel_operation_request_object CHECK (
                jsonb_typeof(request_json)='object'
            ),
            CONSTRAINT contact_channel_operation_validation_object CHECK (
                validation_json IS NULL OR jsonb_typeof(validation_json)='object'
            ),
            CONSTRAINT contact_channel_operation_costs_nonnegative CHECK (
                acquisition_units_charged >= 0 AND acquisition_cost_cents_charged >= 0
                AND validation_units_charged >= 0 AND validation_cost_cents_charged >= 0
            ),
            CONSTRAINT contact_channel_operation_unknown_spend CHECK (
                state <> 'spend_outcome_unknown'
                OR acquisition_spend_outcome='unknown' OR validation_spend_outcome='unknown'
            ),
            CONSTRAINT contact_channel_operation_terminal_time CHECK (
                (state IN ('succeeded', 'rejected', 'failed_terminal', 'cancelled'))
                = (terminal_at IS NOT NULL)
            ),
            CONSTRAINT contact_channel_operation_terminal_validation CHECK (
                state NOT IN ('succeeded', 'rejected')
                OR (observed_claim_id IS NOT NULL AND validation_json IS NOT NULL
                    AND validation_artifact_key IS NOT NULL AND receipt_artifact_key IS NOT NULL)
            ),
            CONSTRAINT contact_channel_operation_acquired_evidence CHECK (
                state NOT IN ('ready_to_validate', 'validating', 'succeeded', 'rejected')
                OR (acquisition_spend_outcome='charged' AND observed_claim_id IS NOT NULL
                    AND observation_artifact_key IS NOT NULL)
            ),
            CONSTRAINT contact_channel_operation_success_validated CHECK (
                state <> 'succeeded'
                OR (validation_spend_outcome='charged'
                    AND validation_json->>'state' IN ('validated', 'verified_identity')
                    AND validation_json->>'use_decision'='allowed')
            ),
            CONSTRAINT contact_channel_operation_rejected_validation CHECK (
                state <> 'rejected' OR validation_json->>'state'='rejected'
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX contact_channel_operation_due ON contact_channel_operation "
        "(next_poll_at, id) WHERE next_poll_at IS NOT NULL "
        "AND state IN ('waiting_external', 'ready_to_validate', 'validating')"
    )
    op.execute(
        "CREATE INDEX contact_channel_operation_subject ON contact_channel_operation "
        "(workspace_id, contact_id, channel, created_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE contact_channel_reuse (
            id bigserial NOT NULL,
            workspace_id text NOT NULL,
            project_id text NOT NULL,
            project_run_id uuid NOT NULL,
            selection_id uuid NOT NULL,
            selection_sha256 text NOT NULL,
            request_fingerprint text NOT NULL,
            observation_window text NOT NULL,
            request_json jsonb NOT NULL,
            source_operation_id uuid NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT contact_channel_reuse_pkey PRIMARY KEY (id),
            CONSTRAINT contact_channel_reuse_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT contact_channel_reuse_run_fk
                FOREIGN KEY (project_run_id, workspace_id, project_id)
                REFERENCES project_run (id, workspace_id, project_id),
            CONSTRAINT contact_channel_reuse_operation_fk
                FOREIGN KEY (source_operation_id, workspace_id)
                REFERENCES contact_channel_operation (id, workspace_id),
            CONSTRAINT contact_channel_reuse_request_unique
                UNIQUE (workspace_id, request_fingerprint),
            CONSTRAINT contact_channel_reuse_hashes CHECK (
                selection_sha256 ~ '^[0-9a-f]{64}$'
                AND request_fingerprint ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT contact_channel_reuse_request_object CHECK (
                jsonb_typeof(request_json)='object'
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE contact_channel_artifact (
            operation_id uuid NOT NULL,
            workspace_id text NOT NULL,
            ordinal integer NOT NULL,
            artifact_kind text NOT NULL,
            artifact_key text NOT NULL,
            content_sha256 text NOT NULL,
            provider_request_id text,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT contact_channel_artifact_pkey PRIMARY KEY (operation_id, ordinal),
            CONSTRAINT contact_channel_artifact_operation_fk
                FOREIGN KEY (operation_id, workspace_id)
                REFERENCES contact_channel_operation (id, workspace_id),
            CONSTRAINT contact_channel_artifact_artifact_fk
                FOREIGN KEY (artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT contact_channel_artifact_ordinal CHECK (ordinal >= 0),
            CONSTRAINT contact_channel_artifact_sha CHECK (
                content_sha256 ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT contact_channel_artifact_kind CHECK (length(btrim(artifact_kind)) > 0)
        )
        """
    )
    op.execute(
        """
        CREATE FUNCTION contact_channel_reuse_guard() RETURNS trigger AS $$
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'contact channel reuse receipts are append-only';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM contact_channel_operation operation
                WHERE operation.id=NEW.source_operation_id
                  AND operation.workspace_id=NEW.workspace_id
                  AND operation.state='succeeded'
                  AND operation.account_id=(NEW.request_json->>'account_id')::uuid
                  AND operation.contact_id=(NEW.request_json->>'contact_id')::uuid
                  AND operation.channel=(NEW.request_json->>'channel')::contact_channel_kind
                  AND operation.field_key=NEW.request_json->>'field_key'
                  AND operation.acquisition_source_key=
                      NEW.request_json->>'acquisition_source_key'
                  AND operation.validation_source_key=
                      NEW.request_json->>'validation_source_key'
            ) THEN
                RAISE EXCEPTION 'contact channel reuse crosses its validated source operation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER contact_channel_reuse_immutable "
        "BEFORE INSERT OR UPDATE OR DELETE ON contact_channel_reuse FOR EACH ROW "
        "EXECUTE FUNCTION contact_channel_reuse_guard()"
    )
    op.execute(
        """
        CREATE TABLE contact_channel_suppression (
            workspace_id text NOT NULL,
            contact_id uuid NOT NULL,
            channel contact_channel_kind NOT NULL,
            reason text NOT NULL,
            operation_id uuid,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT contact_channel_suppression_pkey
                PRIMARY KEY (workspace_id, contact_id, channel),
            CONSTRAINT contact_channel_suppression_contact_fk
                FOREIGN KEY (contact_id, workspace_id)
                REFERENCES contact_entity (id, workspace_id),
            CONSTRAINT contact_channel_suppression_operation_fk
                FOREIGN KEY (operation_id, workspace_id)
                REFERENCES contact_channel_operation (id, workspace_id),
            CONSTRAINT contact_channel_suppression_reason CHECK (
                reason IN ('objection', 'erasure', 'retention_expiry')
            )
        )
        """
    )
    op.execute(
        """
        CREATE FUNCTION contact_channel_validate_canonical_subject() RETURNS trigger AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM account_entity account
                JOIN contact_entity contact
                  ON contact.account_entity_id=account.id
                 AND contact.workspace_id=account.workspace_id
                WHERE account.id=NEW.account_id AND account.workspace_id=NEW.workspace_id
                  AND account.merged_into IS NULL
                  AND contact.id=NEW.contact_id AND contact.merged_into IS NULL
                  AND contact.linkedin_url IS NOT NULL
            ) THEN
                RAISE EXCEPTION 'contact channel operation requires canonical strong contact';
            END IF;
            IF NEW.observed_claim_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM claim
                WHERE id=NEW.observed_claim_id
                  AND entity_id=NEW.contact_id
                  AND entity_type='contact'
                  AND field_key=NEW.field_key
                  AND workspace_id=NEW.workspace_id
                  AND source_key=NEW.acquisition_source_key
                  AND source_operation_ref=NEW.id::text
                  AND artifact_key=NEW.observation_artifact_key
                  AND identity_binding='weak'
                  AND reuse_scope='tenant_private'
            ) THEN
                RAISE EXCEPTION 'contact channel observed claim crosses its frozen subject';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER contact_channel_canonical_subject BEFORE INSERT OR UPDATE "
        "ON contact_channel_operation FOR EACH ROW "
        "EXECUTE FUNCTION contact_channel_validate_canonical_subject()"
    )
    op.execute(
        """
        CREATE FUNCTION contact_channel_request_immutable() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'contact channel operations are append-only';
            END IF;
            IF ROW(OLD.workspace_id, OLD.project_id, OLD.project_run_id, OLD.account_id,
                   OLD.contact_id, OLD.selection_id, OLD.selection_sha256,
                   OLD.contact_intent_sha256, OLD.channel, OLD.field_key,
                   OLD.acquisition_source_key, OLD.validation_source_key,
                   OLD.observation_window, OLD.request_fingerprint, OLD.request_json,
                   OLD.provider_external_id, OLD.input_artifact_key, OLD.csv_artifact_key)
               IS DISTINCT FROM
               ROW(NEW.workspace_id, NEW.project_id, NEW.project_run_id, NEW.account_id,
                   NEW.contact_id, NEW.selection_id, NEW.selection_sha256,
                   NEW.contact_intent_sha256, NEW.channel, NEW.field_key,
                   NEW.acquisition_source_key, NEW.validation_source_key,
                   NEW.observation_window, NEW.request_fingerprint, NEW.request_json,
                   NEW.provider_external_id, NEW.input_artifact_key, NEW.csv_artifact_key) THEN
                RAISE EXCEPTION 'contact channel immutable request changed';
            END IF;
            IF OLD.terminal_at IS NOT NULL AND ROW(OLD.*) IS DISTINCT FROM ROW(NEW.*) THEN
                RAISE EXCEPTION 'terminal contact channel operation is immutable';
            END IF;
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER contact_channel_request_immutable BEFORE UPDATE OR DELETE "
        "ON contact_channel_operation FOR EACH ROW "
        "EXECUTE FUNCTION contact_channel_request_immutable()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER contact_channel_request_immutable ON contact_channel_operation")
    op.execute("DROP FUNCTION contact_channel_request_immutable()")
    op.execute("DROP TRIGGER contact_channel_canonical_subject ON contact_channel_operation")
    op.execute("DROP FUNCTION contact_channel_validate_canonical_subject()")
    op.execute("DROP TRIGGER contact_channel_reuse_immutable ON contact_channel_reuse")
    op.execute("DROP FUNCTION contact_channel_reuse_guard()")
    op.execute("DROP TABLE contact_channel_suppression")
    op.execute("DROP TABLE contact_channel_artifact")
    op.execute("DROP TABLE contact_channel_reuse")
    op.execute("DROP INDEX contact_channel_operation_subject")
    op.execute("DROP INDEX contact_channel_operation_due")
    op.execute("DROP TABLE contact_channel_operation")
    op.execute("DROP TYPE contact_channel_spend_outcome")
    op.execute("DROP TYPE contact_channel_operation_state")
    op.execute("DROP TYPE contact_channel_kind")
