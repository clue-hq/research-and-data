"""s2b sumble committee acquisition ledger

Revision ID: f8a81c7e1563
Revises: bd0b7e62a2b4
Create Date: 2026-08-03 15:58:10.189032+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "f8a81c7e1563"
down_revision: str | None = "bd0b7e62a2b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE committee_acquisition_state AS ENUM ("
        "'planned', 'acquiring_teams', 'submitting_people', 'waiting_external', "
        "'polling_people', 'ready', 'failed_terminal', 'spend_outcome_unknown', 'cancelled')"
    )
    op.execute(
        "CREATE TYPE committee_snapshot_state AS ENUM ("
        "'planned', 'dispatching', 'waiting_external', 'succeeded', "
        "'failed_terminal', 'spend_outcome_unknown')"
    )
    op.execute(
        "CREATE TYPE committee_spend_outcome AS ENUM ("
        "'not_dispatched', 'unknown', 'not_charged', 'charged')"
    )
    op.execute(
        "CREATE TYPE committee_attempt_kind AS ENUM ("
        "'teams_search', 'people_submit', 'people_poll')"
    )
    op.execute(
        "CREATE TYPE committee_attempt_state AS ENUM ("
        "'dispatching', 'responded', 'spend_outcome_unknown')"
    )
    op.execute(
        """
        CREATE TABLE committee_acquisition_operation (
            id                          uuid NOT NULL,
            workspace_id                text NOT NULL,
            project_id                  text NOT NULL,
            project_run_id              uuid NOT NULL,
            icp_key                     text NOT NULL,
            icp_version                 integer NOT NULL,
            discovery_batch_id          uuid NOT NULL,
            discovery_seal_sha256       text NOT NULL,
            account_id                  uuid NOT NULL,
            tier_claim_id               uuid NOT NULL,
            committee_plan_ref          text NOT NULL,
            research_direction_ref      text,
            organization_identity_ref   text NOT NULL,
            provider_organization_id    text NOT NULL,
            provider_api_version        text NOT NULL,
            provider_contract_version   text NOT NULL,
            pricing_policy_version      text NOT NULL,
            committee_policy_version    text NOT NULL,
            observation_window          text NOT NULL,
            request_fingerprint         text NOT NULL,
            request_json                jsonb NOT NULL,
            state                       committee_acquisition_state NOT NULL,
            spend_outcome               committee_spend_outcome NOT NULL,
            input_artifact_key          text NOT NULL,
            receipt_manifest_key        text,
            provider_units_reserved     numeric NOT NULL DEFAULT 0,
            provider_units_charged      numeric NOT NULL DEFAULT 0,
            cost_cents_reserved         numeric NOT NULL DEFAULT 0,
            cost_cents_charged          numeric NOT NULL DEFAULT 0,
            next_poll_at                timestamptz,
            failure_code                text,
            started_at                  timestamptz,
            terminal_at                 timestamptz,
            created_at                  timestamptz NOT NULL DEFAULT now(),
            updated_at                  timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT committee_acquisition_operation_pkey PRIMARY KEY (id),
            CONSTRAINT committee_acquisition_operation_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT committee_acquisition_operation_run_fk
                FOREIGN KEY (project_run_id, workspace_id, project_id)
                REFERENCES project_run (id, workspace_id, project_id),
            CONSTRAINT committee_acquisition_operation_seal_fk
                FOREIGN KEY (discovery_batch_id, workspace_id, discovery_seal_sha256)
                REFERENCES discovery_batch_seal (batch_id, workspace_id, seal_sha256),
            CONSTRAINT committee_acquisition_operation_account_fk
                FOREIGN KEY (account_id, workspace_id)
                REFERENCES account_entity (id, workspace_id),
            CONSTRAINT committee_acquisition_operation_tier_fk FOREIGN KEY (tier_claim_id)
                REFERENCES claim (id),
            CONSTRAINT committee_acquisition_operation_input_fk
                FOREIGN KEY (input_artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT committee_acquisition_operation_receipt_fk
                FOREIGN KEY (receipt_manifest_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT committee_acquisition_operation_anchor UNIQUE (id, workspace_id),
            CONSTRAINT committee_acquisition_operation_request_unique
                UNIQUE (workspace_id, account_id, request_fingerprint, observation_window),
            CONSTRAINT committee_acquisition_operation_hashes CHECK (
                request_fingerprint ~ '^[0-9a-f]{64}$'
                AND discovery_seal_sha256 ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT committee_acquisition_operation_request_object
                CHECK (jsonb_typeof(request_json) = 'object'),
            CONSTRAINT committee_acquisition_operation_costs_nonnegative CHECK (
                provider_units_reserved >= 0 AND provider_units_charged >= 0
                AND cost_cents_reserved >= 0 AND cost_cents_charged >= 0
            ),
            CONSTRAINT committee_acquisition_operation_costs_bounded CHECK (
                provider_units_charged <= provider_units_reserved
                AND cost_cents_charged <= cost_cents_reserved
            ),
            CONSTRAINT committee_acquisition_operation_unknown_spend CHECK (
                (state = 'spend_outcome_unknown') = (spend_outcome = 'unknown')
            ),
            CONSTRAINT committee_acquisition_operation_poll_shape CHECK (
                (state = 'waiting_external') = (next_poll_at IS NOT NULL)
            ),
            CONSTRAINT committee_acquisition_operation_terminal_time CHECK (
                (state IN ('ready', 'failed_terminal', 'spend_outcome_unknown', 'cancelled'))
                = (terminal_at IS NOT NULL)
            ),
            CONSTRAINT committee_acquisition_operation_ready_evidence CHECK (
                state <> 'ready' OR receipt_manifest_key IS NOT NULL
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX committee_acquisition_poll_due ON committee_acquisition_operation "
        "(next_poll_at, id) WHERE state='waiting_external' AND next_poll_at IS NOT NULL"
    )
    op.execute(
        """
        CREATE TABLE committee_acquisition_snapshot (
            operation_id               uuid NOT NULL,
            workspace_id               text NOT NULL,
            account_id                 uuid NOT NULL,
            source_key                 text NOT NULL,
            request_fingerprint         text NOT NULL,
            state                      committee_snapshot_state NOT NULL,
            spend_outcome              committee_spend_outcome NOT NULL,
            request_artifact_key        text NOT NULL,
            response_artifact_key       text,
            provider_operation_id       text,
            provider_status             text,
            provider_units_reserved     numeric NOT NULL DEFAULT 0,
            provider_units_charged      numeric NOT NULL DEFAULT 0,
            credits_remaining           integer,
            cost_cents_charged          numeric NOT NULL DEFAULT 0,
            failure_code                text,
            created_at                  timestamptz NOT NULL DEFAULT now(),
            updated_at                  timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT committee_acquisition_snapshot_pkey PRIMARY KEY (operation_id, source_key),
            CONSTRAINT committee_acquisition_snapshot_operation_fk
                FOREIGN KEY (operation_id, workspace_id)
                REFERENCES committee_acquisition_operation (id, workspace_id),
            CONSTRAINT committee_acquisition_snapshot_account_fk
                FOREIGN KEY (account_id, workspace_id)
                REFERENCES account_entity (id, workspace_id),
            CONSTRAINT committee_acquisition_snapshot_request_fk
                FOREIGN KEY (request_artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT committee_acquisition_snapshot_response_fk
                FOREIGN KEY (response_artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT committee_acquisition_snapshot_source CHECK (
                source_key IN ('sumble_teams', 'sumble_people')
            ),
            CONSTRAINT committee_acquisition_snapshot_request_unique
                UNIQUE (workspace_id, source_key, request_fingerprint),
            CONSTRAINT committee_acquisition_snapshot_provider_unique
                UNIQUE NULLS NOT DISTINCT (source_key, provider_operation_id),
            CONSTRAINT committee_acquisition_snapshot_hash CHECK (
                request_fingerprint ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT committee_acquisition_snapshot_costs CHECK (
                provider_units_reserved >= 0 AND provider_units_charged >= 0
                AND provider_units_charged <= provider_units_reserved
                AND cost_cents_charged >= 0 AND credits_remaining >= 0
            ),
            CONSTRAINT committee_acquisition_snapshot_unknown_spend CHECK (
                (state = 'spend_outcome_unknown') = (spend_outcome = 'unknown')
            ),
            CONSTRAINT committee_acquisition_snapshot_wait_evidence CHECK (
                state <> 'waiting_external' OR (
                    provider_operation_id IS NOT NULL
                    AND provider_status IN ('pending', 'running')
                    AND response_artifact_key IS NOT NULL
                )
            ),
            CONSTRAINT committee_acquisition_snapshot_success_evidence CHECK (
                state <> 'succeeded' OR (
                    response_artifact_key IS NOT NULL AND provider_status = 'succeeded'
                )
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE committee_acquisition_attempt (
            operation_id               uuid NOT NULL,
            workspace_id               text NOT NULL,
            ordinal                    integer NOT NULL,
            source_key                 text NOT NULL,
            kind                       committee_attempt_kind NOT NULL,
            state                      committee_attempt_state NOT NULL,
            request_artifact_key        text NOT NULL,
            response_artifact_key       text,
            provider_operation_id       text,
            provider_status             text,
            provider_units_charged      numeric NOT NULL DEFAULT 0,
            credits_remaining           integer,
            failure_code                text,
            dispatched_at               timestamptz NOT NULL DEFAULT now(),
            completed_at                timestamptz,

            CONSTRAINT committee_acquisition_attempt_pkey PRIMARY KEY (operation_id, ordinal),
            CONSTRAINT committee_acquisition_attempt_operation_fk
                FOREIGN KEY (operation_id, workspace_id)
                REFERENCES committee_acquisition_operation (id, workspace_id),
            CONSTRAINT committee_acquisition_attempt_request_fk
                FOREIGN KEY (request_artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT committee_acquisition_attempt_response_fk
                FOREIGN KEY (response_artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT committee_acquisition_attempt_ordinal CHECK (ordinal >= 0),
            CONSTRAINT committee_acquisition_attempt_source CHECK (
                source_key IN ('sumble_teams', 'sumble_people')
            ),
            CONSTRAINT committee_acquisition_attempt_costs CHECK (
                provider_units_charged >= 0 AND credits_remaining >= 0
            ),
            CONSTRAINT committee_acquisition_attempt_terminal_shape CHECK (
                (state <> 'dispatching') = (completed_at IS NOT NULL)
            ),
            CONSTRAINT committee_acquisition_attempt_response_shape CHECK (
                state <> 'responded' OR response_artifact_key IS NOT NULL
            ),
            CONSTRAINT committee_acquisition_attempt_unknown_shape CHECK (
                state <> 'spend_outcome_unknown' OR failure_code IS NOT NULL
            )
        )
        """
    )
    op.execute(
        """
        CREATE FUNCTION committee_acquisition_validate_tier_claim() RETURNS trigger AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM claim
                 WHERE id = NEW.tier_claim_id
                   AND workspace_id = NEW.workspace_id
                   AND entity_id = NEW.account_id
                   AND field_key = 'account.scoring.tier'
                   AND superseded_by IS NULL
            ) THEN
                RAISE EXCEPTION 'committee tier claim must be live and match its account';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER committee_acquisition_tier_claim_lineage BEFORE INSERT OR UPDATE OF "
        "tier_claim_id, workspace_id, account_id ON committee_acquisition_operation FOR EACH ROW "
        "EXECUTE FUNCTION committee_acquisition_validate_tier_claim()"
    )
    op.execute(
        """
        CREATE FUNCTION committee_acquisition_validate_ready() RETURNS trigger AS $$
        BEGIN
            IF NEW.state = 'ready' AND (
                (SELECT count(*) FROM committee_acquisition_snapshot
                  WHERE operation_id = NEW.id AND state = 'succeeded') <> 2
                OR EXISTS (
                    SELECT 1 FROM committee_acquisition_snapshot
                     WHERE operation_id = NEW.id
                       AND source_key NOT IN ('sumble_teams', 'sumble_people')
                )
            ) THEN
                RAISE EXCEPTION 'committee acquisition ready requires Teams and People snapshots';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER committee_acquisition_ready_barrier BEFORE UPDATE OF state "
        "ON committee_acquisition_operation FOR EACH ROW "
        "EXECUTE FUNCTION committee_acquisition_validate_ready()"
    )
    op.execute(
        """
        CREATE FUNCTION committee_acquisition_reject_operation_mutation() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'committee acquisition operations cannot be deleted';
            END IF;
            IF NEW.workspace_id <> OLD.workspace_id
               OR NEW.project_id <> OLD.project_id
               OR NEW.project_run_id <> OLD.project_run_id
               OR NEW.icp_key <> OLD.icp_key
               OR NEW.icp_version <> OLD.icp_version
               OR NEW.discovery_batch_id <> OLD.discovery_batch_id
               OR NEW.discovery_seal_sha256 <> OLD.discovery_seal_sha256
               OR NEW.account_id <> OLD.account_id
               OR NEW.tier_claim_id <> OLD.tier_claim_id
               OR NEW.committee_plan_ref <> OLD.committee_plan_ref
               OR NEW.research_direction_ref IS DISTINCT FROM OLD.research_direction_ref
               OR NEW.organization_identity_ref <> OLD.organization_identity_ref
               OR NEW.provider_organization_id <> OLD.provider_organization_id
               OR NEW.provider_api_version <> OLD.provider_api_version
               OR NEW.provider_contract_version <> OLD.provider_contract_version
               OR NEW.pricing_policy_version <> OLD.pricing_policy_version
               OR NEW.committee_policy_version <> OLD.committee_policy_version
               OR NEW.observation_window <> OLD.observation_window
               OR NEW.request_fingerprint <> OLD.request_fingerprint
               OR NEW.request_json <> OLD.request_json
               OR NEW.input_artifact_key <> OLD.input_artifact_key
               OR NEW.provider_units_reserved <> OLD.provider_units_reserved
               OR NEW.cost_cents_reserved <> OLD.cost_cents_reserved THEN
                RAISE EXCEPTION 'committee acquisition request lineage is immutable';
            END IF;
            IF OLD.state IN ('ready', 'failed_terminal', 'spend_outcome_unknown', 'cancelled')
               AND NEW IS DISTINCT FROM OLD THEN
                RAISE EXCEPTION 'terminal committee acquisition operation is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER committee_acquisition_operation_immutable BEFORE UPDATE OR DELETE "
        "ON committee_acquisition_operation FOR EACH ROW "
        "EXECUTE FUNCTION committee_acquisition_reject_operation_mutation()"
    )
    op.execute(
        """
        CREATE FUNCTION committee_acquisition_reject_snapshot_mutation() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'committee acquisition snapshots cannot be deleted';
            END IF;
            IF OLD.state IN ('succeeded', 'failed_terminal', 'spend_outcome_unknown')
               AND NEW IS DISTINCT FROM OLD THEN
                RAISE EXCEPTION 'terminal committee acquisition snapshot is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER committee_acquisition_snapshot_immutable BEFORE UPDATE OR DELETE "
        "ON committee_acquisition_snapshot FOR EACH ROW "
        "EXECUTE FUNCTION committee_acquisition_reject_snapshot_mutation()"
    )
    op.execute(
        """
        CREATE FUNCTION committee_acquisition_reject_attempt_mutation() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'committee acquisition attempts cannot be deleted';
            END IF;
            IF OLD.state <> 'dispatching' AND NEW IS DISTINCT FROM OLD THEN
                RAISE EXCEPTION 'terminal committee acquisition attempt is immutable';
            END IF;
            IF NEW.operation_id <> OLD.operation_id
               OR NEW.workspace_id <> OLD.workspace_id
               OR NEW.ordinal <> OLD.ordinal
               OR NEW.source_key <> OLD.source_key
               OR NEW.kind <> OLD.kind
               OR NEW.request_artifact_key <> OLD.request_artifact_key
               OR NEW.dispatched_at <> OLD.dispatched_at THEN
                RAISE EXCEPTION 'committee acquisition dispatch lineage is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER committee_acquisition_attempt_immutable BEFORE UPDATE OR DELETE "
        "ON committee_acquisition_attempt FOR EACH ROW "
        "EXECUTE FUNCTION committee_acquisition_reject_attempt_mutation()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER committee_acquisition_attempt_immutable ON committee_acquisition_attempt"
    )
    op.execute("DROP FUNCTION committee_acquisition_reject_attempt_mutation()")
    op.execute(
        "DROP TRIGGER committee_acquisition_snapshot_immutable ON committee_acquisition_snapshot"
    )
    op.execute("DROP FUNCTION committee_acquisition_reject_snapshot_mutation()")
    op.execute(
        "DROP TRIGGER committee_acquisition_operation_immutable ON committee_acquisition_operation"
    )
    op.execute("DROP FUNCTION committee_acquisition_reject_operation_mutation()")
    op.execute(
        "DROP TRIGGER committee_acquisition_ready_barrier ON committee_acquisition_operation"
    )
    op.execute("DROP FUNCTION committee_acquisition_validate_ready()")
    op.execute(
        "DROP TRIGGER committee_acquisition_tier_claim_lineage ON committee_acquisition_operation"
    )
    op.execute("DROP FUNCTION committee_acquisition_validate_tier_claim()")
    op.execute("DROP INDEX committee_acquisition_poll_due")
    op.execute("DROP TABLE committee_acquisition_attempt")
    op.execute("DROP TABLE committee_acquisition_snapshot")
    op.execute("DROP TABLE committee_acquisition_operation")
    op.execute("DROP TYPE committee_attempt_state")
    op.execute("DROP TYPE committee_attempt_kind")
    op.execute("DROP TYPE committee_spend_outcome")
    op.execute("DROP TYPE committee_snapshot_state")
    op.execute("DROP TYPE committee_acquisition_state")
