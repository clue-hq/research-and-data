"""external research acquisition ledger

Revision ID: bc0612c57713
Revises: 5330703a78a3
Create Date: 2026-08-04 09:04:17.002875+00:00

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
revision: str = "bc0612c57713"
down_revision: str | None = "5330703a78a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE TYPE external_research_subject_kind AS ENUM ('account', 'contact')")
    op.execute(
        "CREATE TYPE external_research_operation_state AS ENUM ("
        "'planned', 'dispatching', 'ready', 'failed_terminal', "
        "'spend_outcome_unknown', 'cancelled')"
    )
    op.execute(
        "CREATE TYPE external_research_attempt_state AS ENUM ("
        "'dispatching', 'responded', 'failed_pre_dispatch', 'failed_terminal', "
        "'spend_outcome_unknown')"
    )
    op.execute(
        "CREATE TYPE external_research_spend_outcome AS ENUM ("
        "'not_dispatched', 'not_charged', 'provider_reported', 'unknown')"
    )
    op.execute(
        "CREATE TYPE external_research_reconciliation_state AS ENUM ("
        "'not_required', 'pending_provider_billing', 'reconciled')"
    )
    op.execute(
        """
        CREATE TABLE external_research_operation (
            id                       uuid NOT NULL,
            workspace_id             text NOT NULL,
            project_id               text NOT NULL,
            project_run_id           uuid NOT NULL,
            subject_kind             external_research_subject_kind NOT NULL,
            account_id               uuid,
            contact_id               uuid,
            icp_key                  text NOT NULL,
            icp_version              integer NOT NULL,
            research_directive_id    uuid NOT NULL,
            research_directive_version integer NOT NULL,
            research_directive_sha256 text NOT NULL,
            research_override_id     uuid,
            research_override_sha256 text,
            source_key               text NOT NULL,
            observation_window       text NOT NULL,
            freshness_policy_ref     text NOT NULL,
            freshness_seconds        integer NOT NULL,
            request_fingerprint      text NOT NULL,
            wire_request_sha256      text NOT NULL,
            request_json             jsonb NOT NULL,
            state                    external_research_operation_state NOT NULL,
            spend_outcome            external_research_spend_outcome NOT NULL,
            request_artifact_key     text NOT NULL,
            cost_cents_reserved      numeric NOT NULL,
            provider_request_id      text,
            dispatch_lease_expires_at timestamptz,
            fresh_until              timestamptz,
            failure_code             text,
            failure_detail           text,
            started_at               timestamptz,
            terminal_at              timestamptz,
            created_at               timestamptz NOT NULL DEFAULT now(),
            updated_at               timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT external_research_operation_pkey PRIMARY KEY (id),
            CONSTRAINT external_research_operation_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT external_research_operation_run_fk
                FOREIGN KEY (project_run_id, workspace_id, project_id)
                REFERENCES project_run (id, workspace_id, project_id),
            CONSTRAINT external_research_operation_account_fk
                FOREIGN KEY (account_id, workspace_id)
                REFERENCES account_entity (id, workspace_id),
            CONSTRAINT external_research_operation_contact_fk
                FOREIGN KEY (contact_id, workspace_id)
                REFERENCES contact_entity (id, workspace_id),
            CONSTRAINT external_research_operation_source_fk FOREIGN KEY (source_key)
                REFERENCES source_manifest (source_key),
            CONSTRAINT external_research_operation_directive_account_fk
                FOREIGN KEY (research_directive_id, account_id)
                REFERENCES account_research_directive_account (directive_id, account_id),
            CONSTRAINT external_research_operation_request_artifact_fk
                FOREIGN KEY (request_artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT external_research_operation_anchor UNIQUE (id, workspace_id),
            CONSTRAINT external_research_operation_request_unique
                UNIQUE (workspace_id, source_key, request_fingerprint, observation_window),
            CONSTRAINT external_research_operation_subject_shape CHECK (
                (subject_kind = 'account' AND account_id IS NOT NULL AND contact_id IS NULL)
                OR (subject_kind = 'contact' AND account_id IS NOT NULL AND contact_id IS NOT NULL)
            ),
            CONSTRAINT external_research_operation_versions CHECK (
                icp_version >= 1 AND research_directive_version >= 1
                AND freshness_seconds >= 1
            ),
            CONSTRAINT external_research_operation_hashes CHECK (
                request_fingerprint ~ '^[0-9a-f]{64}$'
                AND wire_request_sha256 ~ '^[0-9a-f]{64}$'
                AND research_directive_sha256 ~ '^[0-9a-f]{64}$'
                AND (research_override_sha256 IS NULL
                     OR research_override_sha256 ~ '^[0-9a-f]{64}$')
            ),
            CONSTRAINT external_research_operation_override_shape CHECK (
                (research_override_id IS NULL) = (research_override_sha256 IS NULL)
            ),
            CONSTRAINT external_research_operation_nonempty CHECK (
                length(btrim(source_key)) > 0
                AND length(btrim(observation_window)) > 0
                AND length(btrim(freshness_policy_ref)) > 0
            ),
            CONSTRAINT external_research_operation_request_object
                CHECK (jsonb_typeof(request_json) = 'object'),
            CONSTRAINT external_research_operation_cost CHECK (cost_cents_reserved >= 0),
            CONSTRAINT external_research_operation_dispatch_shape CHECK (
                (state = 'dispatching') = (dispatch_lease_expires_at IS NOT NULL)
            ),
            CONSTRAINT external_research_operation_unknown_spend CHECK (
                (state = 'spend_outcome_unknown') = (spend_outcome = 'unknown')
            ),
            CONSTRAINT external_research_operation_terminal_shape CHECK (
                (state IN ('ready', 'failed_terminal', 'spend_outcome_unknown', 'cancelled'))
                = (terminal_at IS NOT NULL)
            ),
            CONSTRAINT external_research_operation_ready_shape CHECK (
                state <> 'ready' OR (
                    spend_outcome = 'provider_reported'
                    AND provider_request_id IS NOT NULL
                    AND fresh_until IS NOT NULL
                )
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX external_research_ready_reuse ON external_research_operation "
        "(workspace_id, account_id, source_key, fresh_until DESC) WHERE state='ready'"
    )
    op.execute(
        "CREATE INDEX external_research_dispatch_lease ON external_research_operation "
        "(dispatch_lease_expires_at, id) WHERE state='dispatching'"
    )
    op.execute(
        """
        CREATE TABLE external_research_attempt (
            operation_id              uuid NOT NULL,
            workspace_id              text NOT NULL,
            ordinal                   integer NOT NULL,
            state                     external_research_attempt_state NOT NULL,
            request_artifact_key      text NOT NULL,
            response_artifact_key     text,
            provider_request_id       text,
            failure_code              text,
            failure_detail            text,
            dispatch_lease_expires_at timestamptz,
            dispatched_at             timestamptz,
            completed_at              timestamptz,

            CONSTRAINT external_research_attempt_pkey PRIMARY KEY (operation_id, ordinal),
            CONSTRAINT external_research_attempt_operation_fk
                FOREIGN KEY (operation_id, workspace_id)
                REFERENCES external_research_operation (id, workspace_id),
            CONSTRAINT external_research_attempt_request_fk
                FOREIGN KEY (request_artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT external_research_attempt_response_fk
                FOREIGN KEY (response_artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT external_research_attempt_ordinal CHECK (ordinal >= 0),
            CONSTRAINT external_research_attempt_dispatch_shape CHECK (
                (state = 'dispatching') = (dispatch_lease_expires_at IS NOT NULL)
                AND (state IN (
                    'dispatching', 'responded', 'failed_terminal', 'spend_outcome_unknown'
                ))
                    = (dispatched_at IS NOT NULL)
            ),
            CONSTRAINT external_research_attempt_terminal_shape CHECK (
                (state <> 'dispatching') = (completed_at IS NOT NULL)
            ),
            CONSTRAINT external_research_attempt_response_shape CHECK (
                state <> 'responded' OR response_artifact_key IS NOT NULL
            ),
            CONSTRAINT external_research_attempt_failure_shape CHECK (
                state NOT IN ('failed_pre_dispatch', 'spend_outcome_unknown')
                OR failure_code IS NOT NULL
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE external_research_snapshot (
            id                         uuid NOT NULL,
            operation_id               uuid NOT NULL,
            workspace_id               text NOT NULL,
            account_id                 uuid NOT NULL,
            source_key                 text NOT NULL,
            request_fingerprint        text NOT NULL,
            request_artifact_key       text NOT NULL,
            response_artifact_key      text NOT NULL,
            normalization_artifact_key text NOT NULL,
            provider_request_id        text NOT NULL,
            provider_reported_cost_cents numeric NOT NULL,
            all_null                   boolean NOT NULL,
            fresh_until                timestamptz NOT NULL,
            created_at                 timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT external_research_snapshot_pkey PRIMARY KEY (id),
            CONSTRAINT external_research_snapshot_operation_unique UNIQUE (operation_id),
            CONSTRAINT external_research_snapshot_anchor UNIQUE (id, workspace_id),
            CONSTRAINT external_research_snapshot_operation_fk
                FOREIGN KEY (operation_id, workspace_id)
                REFERENCES external_research_operation (id, workspace_id),
            CONSTRAINT external_research_snapshot_account_fk
                FOREIGN KEY (account_id, workspace_id)
                REFERENCES account_entity (id, workspace_id),
            CONSTRAINT external_research_snapshot_request_fk
                FOREIGN KEY (request_artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT external_research_snapshot_response_fk
                FOREIGN KEY (response_artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT external_research_snapshot_normalization_fk
                FOREIGN KEY (normalization_artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT external_research_snapshot_hash CHECK (
                request_fingerprint ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT external_research_snapshot_cost CHECK (
                provider_reported_cost_cents >= 0
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE external_research_result_artifact (
            snapshot_id        uuid NOT NULL,
            workspace_id       text NOT NULL,
            ordinal            integer NOT NULL,
            artifact_key       text NOT NULL,
            source_url         text NOT NULL,
            source_title       text NOT NULL,
            created_at         timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT external_research_result_artifact_pkey
                PRIMARY KEY (snapshot_id, ordinal),
            CONSTRAINT external_research_result_artifact_snapshot_fk
                FOREIGN KEY (snapshot_id, workspace_id)
                REFERENCES external_research_snapshot (id, workspace_id),
            CONSTRAINT external_research_result_artifact_artifact_fk
                FOREIGN KEY (artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT external_research_result_artifact_ordinal CHECK (ordinal >= 0),
            CONSTRAINT external_research_result_artifact_unique_url
                UNIQUE (snapshot_id, source_url),
            CONSTRAINT external_research_result_artifact_nonempty CHECK (
                length(btrim(source_url)) > 0 AND length(btrim(source_title)) > 0
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE external_research_receipt (
            id                         uuid NOT NULL,
            operation_id               uuid NOT NULL,
            workspace_id               text NOT NULL,
            source_key                 text NOT NULL,
            provider_request_id        text NOT NULL,
            cost_cents_reserved        numeric NOT NULL,
            provider_reported_cost_cents numeric NOT NULL,
            settled_cost_cents         numeric NOT NULL,
            currency                   text NOT NULL DEFAULT 'USD',
            provider_value_is_estimate boolean NOT NULL DEFAULT true,
            reconciliation_state       external_research_reconciliation_state NOT NULL,
            receipt_artifact_key       text NOT NULL,
            created_at                 timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT external_research_receipt_pkey PRIMARY KEY (id),
            CONSTRAINT external_research_receipt_operation_unique UNIQUE (operation_id),
            CONSTRAINT external_research_receipt_operation_fk
                FOREIGN KEY (operation_id, workspace_id)
                REFERENCES external_research_operation (id, workspace_id),
            CONSTRAINT external_research_receipt_artifact_fk
                FOREIGN KEY (receipt_artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT external_research_receipt_costs CHECK (
                cost_cents_reserved >= 0
                AND provider_reported_cost_cents >= 0
                AND settled_cost_cents >= 0
                AND settled_cost_cents <= cost_cents_reserved
            ),
            CONSTRAINT external_research_receipt_currency CHECK (currency = 'USD')
        )
        """
    )
    op.execute(
        """
        CREATE FUNCTION external_research_validate_directive() RETURNS trigger AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM account_research_directive directive
                WHERE directive.directive_id = NEW.research_directive_id
                  AND directive.workspace_id = NEW.workspace_id
                  AND directive.project_id = NEW.project_id
                  AND directive.icp_key = NEW.icp_key
                  AND directive.icp_version = NEW.icp_version
                  AND directive.version = NEW.research_directive_version
                  AND directive.canonical_json_sha256 = NEW.research_directive_sha256
                  AND directive.status IN ('confirmed', 'superseded')
            ) THEN
                RAISE EXCEPTION 'external research requires the exact confirmed directive';
            END IF;
            IF NEW.research_override_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM account_research_directive_override override_row
                WHERE override_row.override_id = NEW.research_override_id
                  AND override_row.directive_id = NEW.research_directive_id
                  AND override_row.workspace_id = NEW.workspace_id
                  AND override_row.account_id = NEW.account_id
                  AND override_row.canonical_json_sha256 = NEW.research_override_sha256
            ) THEN
                RAISE EXCEPTION 'external research requires the exact directive override';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER external_research_directive_lineage BEFORE INSERT OR UPDATE OF "
        "research_directive_id, research_directive_version, research_directive_sha256, "
        "research_override_id, research_override_sha256, workspace_id, project_id, account_id "
        "ON external_research_operation FOR EACH ROW "
        "EXECUTE FUNCTION external_research_validate_directive()"
    )
    op.execute(
        """
        CREATE FUNCTION external_research_validate_ready() RETURNS trigger AS $$
        BEGIN
            IF NEW.state = 'ready' AND (
                NOT EXISTS (
                    SELECT 1 FROM external_research_snapshot snapshot
                    WHERE snapshot.operation_id = NEW.id
                      AND snapshot.workspace_id = NEW.workspace_id
                      AND snapshot.provider_request_id = NEW.provider_request_id
                )
                OR NOT EXISTS (
                    SELECT 1 FROM external_research_receipt receipt
                    WHERE receipt.operation_id = NEW.id
                      AND receipt.workspace_id = NEW.workspace_id
                      AND receipt.provider_request_id = NEW.provider_request_id
                )
                OR NOT EXISTS (
                    SELECT 1 FROM external_research_attempt attempt
                    WHERE attempt.operation_id = NEW.id
                      AND attempt.state = 'responded'
                      AND attempt.provider_request_id = NEW.provider_request_id
                )
            ) THEN
                RAISE EXCEPTION 'ready external research requires snapshot, receipt, and response';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER external_research_ready_barrier BEFORE UPDATE OF state "
        "ON external_research_operation FOR EACH ROW "
        "EXECUTE FUNCTION external_research_validate_ready()"
    )
    op.execute(
        """
        CREATE FUNCTION external_research_reject_operation_mutation() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'external research operations cannot be deleted';
            END IF;
            IF NEW.workspace_id <> OLD.workspace_id
               OR NEW.project_id <> OLD.project_id
               OR NEW.project_run_id <> OLD.project_run_id
               OR NEW.subject_kind <> OLD.subject_kind
               OR NEW.account_id IS DISTINCT FROM OLD.account_id
               OR NEW.contact_id IS DISTINCT FROM OLD.contact_id
               OR NEW.icp_key <> OLD.icp_key
               OR NEW.icp_version <> OLD.icp_version
               OR NEW.research_directive_id <> OLD.research_directive_id
               OR NEW.research_directive_version <> OLD.research_directive_version
               OR NEW.research_directive_sha256 <> OLD.research_directive_sha256
               OR NEW.research_override_id IS DISTINCT FROM OLD.research_override_id
               OR NEW.research_override_sha256 IS DISTINCT FROM OLD.research_override_sha256
               OR NEW.source_key <> OLD.source_key
               OR NEW.observation_window <> OLD.observation_window
               OR NEW.freshness_policy_ref <> OLD.freshness_policy_ref
               OR NEW.freshness_seconds <> OLD.freshness_seconds
               OR NEW.request_fingerprint <> OLD.request_fingerprint
               OR NEW.wire_request_sha256 <> OLD.wire_request_sha256
               OR NEW.request_json <> OLD.request_json
               OR NEW.request_artifact_key <> OLD.request_artifact_key
               OR NEW.cost_cents_reserved <> OLD.cost_cents_reserved THEN
                RAISE EXCEPTION 'external research request lineage is immutable';
            END IF;
            IF OLD.state IN ('ready', 'failed_terminal', 'spend_outcome_unknown', 'cancelled')
               AND NEW IS DISTINCT FROM OLD THEN
                RAISE EXCEPTION 'terminal external research operation is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER external_research_operation_immutable BEFORE UPDATE OR DELETE "
        "ON external_research_operation FOR EACH ROW "
        "EXECUTE FUNCTION external_research_reject_operation_mutation()"
    )
    op.execute(
        """
        CREATE FUNCTION external_research_reject_attempt_mutation() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'external research attempts cannot be deleted';
            END IF;
            IF NEW.operation_id <> OLD.operation_id
               OR NEW.workspace_id <> OLD.workspace_id
               OR NEW.ordinal <> OLD.ordinal
               OR NEW.request_artifact_key <> OLD.request_artifact_key
               OR (
                   NEW.dispatched_at IS DISTINCT FROM OLD.dispatched_at
                   AND NOT (
                       OLD.state = 'dispatching'
                       AND NEW.state = 'failed_pre_dispatch'
                       AND NEW.dispatched_at IS NULL
                   )
               ) THEN
                RAISE EXCEPTION 'external research attempt lineage is immutable';
            END IF;
            IF OLD.state <> 'dispatching' AND NEW IS DISTINCT FROM OLD THEN
                RAISE EXCEPTION 'terminal external research attempt is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER external_research_attempt_immutable BEFORE UPDATE OR DELETE "
        "ON external_research_attempt FOR EACH ROW "
        "EXECUTE FUNCTION external_research_reject_attempt_mutation()"
    )
    for table in (
        "external_research_snapshot",
        "external_research_result_artifact",
        "external_research_receipt",
    ):
        op.execute(
            f"""
            CREATE FUNCTION {table}_immutable() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION '{table} rows are immutable';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION {table}_immutable()"
        )


def downgrade() -> None:
    for table in (
        "external_research_receipt",
        "external_research_result_artifact",
        "external_research_snapshot",
    ):
        op.execute(f"DROP TRIGGER {table}_immutable ON {table}")
        op.execute(f"DROP FUNCTION {table}_immutable()")
    op.execute(
        "DROP TRIGGER IF EXISTS external_research_attempt_immutable ON external_research_attempt"
    )
    op.execute("DROP FUNCTION IF EXISTS external_research_reject_attempt_mutation()")
    op.execute("DROP TRIGGER external_research_operation_immutable ON external_research_operation")
    op.execute("DROP FUNCTION external_research_reject_operation_mutation()")
    op.execute(
        "DROP TRIGGER IF EXISTS external_research_ready_barrier ON external_research_operation"
    )
    op.execute("DROP FUNCTION IF EXISTS external_research_validate_ready()")
    op.execute("DROP TRIGGER external_research_directive_lineage ON external_research_operation")
    op.execute("DROP FUNCTION external_research_validate_directive()")
    op.execute("DROP TABLE external_research_receipt")
    op.execute("DROP TABLE external_research_result_artifact")
    op.execute("DROP TABLE external_research_snapshot")
    op.execute("DROP TABLE external_research_attempt")
    op.execute("DROP INDEX external_research_dispatch_lease")
    op.execute("DROP INDEX external_research_ready_reuse")
    op.execute("DROP TABLE external_research_operation")
    op.execute("DROP TYPE external_research_reconciliation_state")
    op.execute("DROP TYPE external_research_spend_outcome")
    op.execute("DROP TYPE external_research_attempt_state")
    op.execute("DROP TYPE external_research_operation_state")
    op.execute("DROP TYPE external_research_subject_kind")
