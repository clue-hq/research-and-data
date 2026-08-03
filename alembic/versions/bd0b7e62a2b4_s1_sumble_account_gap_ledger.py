"""s1 sumble account gap ledger

Revision ID: bd0b7e62a2b4
Revises: fffa2a8ba17c
Create Date: 2026-08-03 12:28:46.378093+00:00

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
revision: str = "bd0b7e62a2b4"
down_revision: str | None = "fffa2a8ba17c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE account_gap_operation_state AS ENUM ("
        "'planned', 'acquiring', 'materializing', 'succeeded', 'failed_retryable', "
        "'failed_terminal', 'spend_outcome_unknown', 'cancelled')"
    )
    op.execute(
        "CREATE TYPE account_gap_snapshot_state AS ENUM ("
        "'planned', 'dispatching', 'succeeded', 'not_applicable', 'failed_retryable', "
        "'failed_terminal', 'spend_outcome_unknown')"
    )
    op.execute(
        "CREATE TYPE account_gap_spend_outcome AS ENUM ("
        "'not_dispatched', 'unknown', 'not_charged', 'charged')"
    )
    op.execute(
        "CREATE TYPE account_gap_field_state AS ENUM ("
        "'pending', 'resolved', 'confirmed_missing', 'corroborated', 'conflict', "
        "'failed_terminal')"
    )
    op.execute(
        """
        CREATE TABLE account_gap_operation (
            id                       uuid NOT NULL,
            workspace_id             text NOT NULL,
            project_id               text NOT NULL,
            project_run_id           uuid NOT NULL,
            icp_key                  text NOT NULL,
            icp_version              integer NOT NULL,
            discovery_batch_id       uuid NOT NULL,
            discovery_seal_sha256    text NOT NULL,
            account_id               uuid NOT NULL,
            primary_domain           text NOT NULL,
            tier_claim_id            uuid NOT NULL,
            provider_api_version     text NOT NULL,
            provider_contract_version text NOT NULL,
            pricing_policy_version   text NOT NULL,
            field_policy_version     text NOT NULL,
            observation_window       text NOT NULL,
            request_fingerprint      text NOT NULL,
            request_json             jsonb NOT NULL,
            state                    account_gap_operation_state NOT NULL,
            spend_outcome            account_gap_spend_outcome NOT NULL,
            input_artifact_key       text NOT NULL,
            receipt_manifest_key     text,
            provider_units_reserved numeric NOT NULL DEFAULT 0,
            provider_units_charged  numeric NOT NULL DEFAULT 0,
            cost_cents_reserved      numeric NOT NULL DEFAULT 0,
            cost_cents_charged       numeric NOT NULL DEFAULT 0,
            unbounded_call_approved  boolean NOT NULL DEFAULT false,
            failure_code             text,
            started_at               timestamptz,
            terminal_at              timestamptz,
            created_at               timestamptz NOT NULL DEFAULT now(),
            updated_at               timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT account_gap_operation_pkey PRIMARY KEY (id),
            CONSTRAINT account_gap_operation_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT account_gap_operation_run_fk
                FOREIGN KEY (project_run_id, workspace_id, project_id)
                REFERENCES project_run (id, workspace_id, project_id),
            CONSTRAINT account_gap_operation_seal_fk
                FOREIGN KEY (discovery_batch_id, workspace_id, discovery_seal_sha256)
                REFERENCES discovery_batch_seal (batch_id, workspace_id, seal_sha256),
            CONSTRAINT account_gap_operation_account_fk
                FOREIGN KEY (account_id, workspace_id)
                REFERENCES account_entity (id, workspace_id),
            CONSTRAINT account_gap_operation_workspace_anchor UNIQUE (id, workspace_id),
            CONSTRAINT account_gap_operation_request_unique UNIQUE (
                workspace_id, account_id, request_fingerprint, observation_window
            ),
            CONSTRAINT account_gap_operation_icp_positive CHECK (icp_version >= 1),
            CONSTRAINT account_gap_operation_hashes CHECK (
                request_fingerprint ~ '^[0-9a-f]{64}$'
                AND discovery_seal_sha256 ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT account_gap_operation_request_object
                CHECK (jsonb_typeof(request_json) = 'object'),
            CONSTRAINT account_gap_operation_costs_nonnegative CHECK (
                provider_units_reserved >= 0 AND provider_units_charged >= 0
                AND cost_cents_reserved >= 0 AND cost_cents_charged >= 0
            ),
            CONSTRAINT account_gap_operation_bounded_charge CHECK (
                unbounded_call_approved OR provider_units_charged <= provider_units_reserved
            ),
            CONSTRAINT account_gap_operation_unknown_spend CHECK (
                (state = 'spend_outcome_unknown') = (spend_outcome = 'unknown')
            ),
            CONSTRAINT account_gap_operation_terminal_time CHECK (
                (state IN ('succeeded', 'failed_terminal', 'spend_outcome_unknown', 'cancelled'))
                = (terminal_at IS NOT NULL)
            ),
            CONSTRAINT account_gap_operation_success_evidence CHECK (
                state <> 'succeeded' OR (
                    spend_outcome = 'charged' AND receipt_manifest_key IS NOT NULL
                )
            ),
            CONSTRAINT account_gap_operation_input_fk
                FOREIGN KEY (input_artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT account_gap_operation_receipt_fk
                FOREIGN KEY (receipt_manifest_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE account_gap_snapshot (
            operation_id             uuid NOT NULL,
            workspace_id             text NOT NULL,
            account_id               uuid NOT NULL,
            source_key               text NOT NULL,
            request_fingerprint      text NOT NULL,
            state                    account_gap_snapshot_state NOT NULL,
            spend_outcome            account_gap_spend_outcome NOT NULL,
            request_artifact_key     text NOT NULL,
            response_artifact_key    text,
            provider_request_id      text,
            provider_units_reserved numeric NOT NULL DEFAULT 0,
            provider_units_charged  numeric NOT NULL DEFAULT 0,
            credits_remaining        integer,
            cost_cents_charged       numeric NOT NULL DEFAULT 0,
            unbounded_call_approved  boolean NOT NULL DEFAULT false,
            failure_code             text,
            started_at               timestamptz,
            terminal_at              timestamptz,
            created_at               timestamptz NOT NULL DEFAULT now(),
            updated_at               timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT account_gap_snapshot_pkey PRIMARY KEY (operation_id, source_key),
            CONSTRAINT account_gap_snapshot_operation_fk
                FOREIGN KEY (operation_id, workspace_id)
                REFERENCES account_gap_operation (id, workspace_id),
            CONSTRAINT account_gap_snapshot_account_fk
                FOREIGN KEY (account_id, workspace_id)
                REFERENCES account_entity (id, workspace_id),
            CONSTRAINT account_gap_snapshot_request_unique UNIQUE (
                workspace_id, account_id, source_key, request_fingerprint
            ),
            CONSTRAINT account_gap_snapshot_hash CHECK (
                request_fingerprint ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT account_gap_snapshot_costs_nonnegative CHECK (
                provider_units_reserved >= 0 AND provider_units_charged >= 0
                AND cost_cents_charged >= 0
            ),
            CONSTRAINT account_gap_snapshot_bounded_charge CHECK (
                unbounded_call_approved OR provider_units_charged <= provider_units_reserved
            ),
            CONSTRAINT account_gap_snapshot_credits_remaining CHECK (
                credits_remaining IS NULL OR credits_remaining >= 0
            ),
            CONSTRAINT account_gap_snapshot_unknown_spend CHECK (
                (state = 'spend_outcome_unknown') = (spend_outcome = 'unknown')
            ),
            CONSTRAINT account_gap_snapshot_terminal_time CHECK (
                (state IN ('succeeded', 'not_applicable', 'failed_terminal',
                           'spend_outcome_unknown'))
                = (terminal_at IS NOT NULL)
            ),
            CONSTRAINT account_gap_snapshot_success_evidence CHECK (
                state <> 'succeeded' OR (
                    spend_outcome = 'charged' AND response_artifact_key IS NOT NULL
                    AND provider_request_id IS NOT NULL
                )
            ),
            CONSTRAINT account_gap_snapshot_not_applicable_shape CHECK (
                state <> 'not_applicable' OR (
                    spend_outcome = 'not_charged' AND response_artifact_key IS NULL
                    AND provider_request_id IS NULL AND provider_units_charged = 0
                    AND cost_cents_charged = 0
                )
            ),
            CONSTRAINT account_gap_snapshot_request_artifact_fk
                FOREIGN KEY (request_artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT account_gap_snapshot_response_artifact_fk
                FOREIGN KEY (response_artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE account_gap_field_result (
            operation_id          uuid NOT NULL,
            workspace_id          text NOT NULL,
            account_id            uuid NOT NULL,
            field_key             text NOT NULL,
            source_key            text NOT NULL,
            selection_reason      text NOT NULL,
            expected_value_credits numeric NOT NULL,
            basis_claim_ids       jsonb NOT NULL DEFAULT '[]'::jsonb,
            state                 account_gap_field_state NOT NULL,
            sumble_claim_id       uuid,
            current_claim_id      uuid,
            conflicting_claim_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
            reason_code           text,
            created_at            timestamptz NOT NULL DEFAULT now(),
            updated_at            timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT account_gap_field_result_pkey PRIMARY KEY (operation_id, field_key),
            CONSTRAINT account_gap_field_result_operation_fk
                FOREIGN KEY (operation_id, workspace_id)
                REFERENCES account_gap_operation (id, workspace_id),
            CONSTRAINT account_gap_field_result_account_fk
                FOREIGN KEY (account_id, workspace_id)
                REFERENCES account_entity (id, workspace_id),
            CONSTRAINT account_gap_field_result_expected_nonnegative
                CHECK (expected_value_credits >= 0),
            CONSTRAINT account_gap_field_result_basis_array
                CHECK (jsonb_typeof(basis_claim_ids) = 'array'),
            CONSTRAINT account_gap_field_result_conflict_array
                CHECK (jsonb_typeof(conflicting_claim_ids) = 'array'),
            CONSTRAINT account_gap_field_result_shape CHECK (
                (state = 'pending' AND sumble_claim_id IS NULL)
                OR (state IN ('resolved', 'corroborated') AND sumble_claim_id IS NOT NULL)
                OR (state = 'conflict' AND sumble_claim_id IS NOT NULL
                    AND jsonb_array_length(conflicting_claim_ids) > 0)
                OR (state IN ('confirmed_missing', 'failed_terminal')
                    AND sumble_claim_id IS NULL)
            ),
            CONSTRAINT account_gap_field_result_sumble_claim_fk
                FOREIGN KEY (sumble_claim_id) REFERENCES claim (id),
            CONSTRAINT account_gap_field_result_current_claim_fk
                FOREIGN KEY (current_claim_id) REFERENCES claim (id)
        )
        """
    )

    op.execute(
        """
        CREATE FUNCTION account_gap_validate_tier_claim() RETURNS trigger AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM claim
                 WHERE id = NEW.tier_claim_id
                   AND workspace_id = NEW.workspace_id
                   AND entity_id = NEW.account_id
                   AND field_key = 'account.scoring.tier'
                   AND superseded_by IS NULL
            ) THEN
                RAISE EXCEPTION 'account-gap tier claim must be live and match its account';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER account_gap_tier_claim_lineage BEFORE INSERT OR UPDATE OF "
        "tier_claim_id, workspace_id, account_id ON account_gap_operation FOR EACH ROW "
        "EXECUTE FUNCTION account_gap_validate_tier_claim()"
    )
    op.execute(
        """
        CREATE FUNCTION account_gap_validate_result_claims() RETURNS trigger AS $$
        DECLARE
            candidate text;
        BEGIN
            IF NEW.sumble_claim_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM claim WHERE id = NEW.sumble_claim_id
                  AND entity_id = NEW.account_id AND field_key = NEW.field_key
                  AND source_key = NEW.source_key
                  AND (workspace_id = NEW.workspace_id
                       OR (workspace_id IS NULL AND reuse_scope = 'public_footprint'))
            ) THEN
                RAISE EXCEPTION 'account-gap Sumble claim lineage mismatch';
            END IF;
            IF NEW.current_claim_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM claim WHERE id = NEW.current_claim_id
                  AND entity_id = NEW.account_id AND field_key = NEW.field_key
                  AND (workspace_id = NEW.workspace_id
                       OR (workspace_id IS NULL AND reuse_scope = 'public_footprint'))
            ) THEN
                RAISE EXCEPTION 'account-gap current claim lineage mismatch';
            END IF;
            FOR candidate IN SELECT jsonb_array_elements_text(NEW.basis_claim_ids)
            LOOP
                IF NOT EXISTS (
                    SELECT 1 FROM claim WHERE id = candidate::uuid
                      AND entity_id = NEW.account_id AND field_key = NEW.field_key
                      AND (workspace_id = NEW.workspace_id
                           OR (workspace_id IS NULL AND reuse_scope = 'public_footprint'))
                ) THEN
                    RAISE EXCEPTION 'account-gap basis claim lineage mismatch';
                END IF;
            END LOOP;
            FOR candidate IN SELECT jsonb_array_elements_text(NEW.conflicting_claim_ids)
            LOOP
                IF NOT EXISTS (
                    SELECT 1 FROM claim WHERE id = candidate::uuid
                      AND entity_id = NEW.account_id AND field_key = NEW.field_key
                      AND (workspace_id = NEW.workspace_id
                           OR (workspace_id IS NULL AND reuse_scope = 'public_footprint'))
                ) THEN
                    RAISE EXCEPTION 'account-gap conflicting claim lineage mismatch';
                END IF;
            END LOOP;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER account_gap_result_claim_lineage BEFORE INSERT OR UPDATE OF "
        "sumble_claim_id, current_claim_id, basis_claim_ids, conflicting_claim_ids, "
        "workspace_id, account_id, field_key, source_key "
        "ON account_gap_field_result FOR EACH ROW "
        "EXECUTE FUNCTION account_gap_validate_result_claims()"
    )
    op.execute(
        """
        CREATE FUNCTION account_gap_reject_overlapping_field() RETURNS trigger AS $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM account_gap_field_result prior
                JOIN account_gap_operation prior_op ON prior_op.id = prior.operation_id
                JOIN account_gap_operation new_op ON new_op.id = NEW.operation_id
                WHERE prior.workspace_id = NEW.workspace_id
                  AND prior.account_id = NEW.account_id
                  AND prior.field_key = NEW.field_key
                  AND prior.operation_id <> NEW.operation_id
                  AND prior_op.observation_window = new_op.observation_window
            ) THEN
                RAISE EXCEPTION 'account-gap field already acquired in this observation window';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER account_gap_field_no_overlap BEFORE INSERT ON account_gap_field_result "
        "FOR EACH ROW EXECUTE FUNCTION account_gap_reject_overlapping_field()"
    )
    op.execute(
        """
        CREATE FUNCTION account_gap_validate_success() RETURNS trigger AS $$
        BEGIN
            IF NEW.state = 'succeeded' THEN
                IF NOT EXISTS (
                    SELECT 1 FROM account_gap_snapshot
                    WHERE operation_id = NEW.id AND source_key = 'sumble_organizations'
                ) THEN
                    RAISE EXCEPTION 'account-gap success requires organization identity snapshot';
                END IF;
                IF EXISTS (
                    SELECT 1 FROM account_gap_snapshot
                    WHERE operation_id = NEW.id
                      AND state NOT IN ('succeeded', 'not_applicable')
                ) OR NOT EXISTS (
                    SELECT 1 FROM account_gap_snapshot WHERE operation_id = NEW.id
                ) THEN
                    RAISE EXCEPTION 'account-gap success requires terminal snapshots';
                END IF;
                IF EXISTS (
                    SELECT 1 FROM account_gap_field_result
                    WHERE operation_id = NEW.id AND state IN ('pending', 'failed_terminal')
                ) THEN
                    RAISE EXCEPTION 'account-gap success requires terminal field outcomes';
                END IF;
                IF EXISTS (
                    SELECT 1 FROM account_gap_field_result result
                    WHERE result.operation_id = NEW.id
                      AND NOT EXISTS (
                          SELECT 1 FROM account_gap_snapshot snapshot
                          WHERE snapshot.operation_id = result.operation_id
                            AND snapshot.source_key = result.source_key
                      )
                ) THEN
                    RAISE EXCEPTION 'account-gap success requires every selected source snapshot';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER account_gap_success_barrier BEFORE UPDATE OF state "
        "ON account_gap_operation FOR EACH ROW EXECUTE FUNCTION account_gap_validate_success()"
    )
    op.execute(
        """
        CREATE FUNCTION account_gap_reject_operation_terminal_mutation() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'account-gap operations cannot be deleted';
            END IF;
            IF OLD.state IN ('succeeded', 'failed_terminal', 'spend_outcome_unknown', 'cancelled')
               AND NEW IS DISTINCT FROM OLD THEN
                RAISE EXCEPTION 'terminal account-gap operation is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER account_gap_operation_terminal_immutable BEFORE UPDATE OR DELETE "
        "ON account_gap_operation FOR EACH ROW "
        "EXECUTE FUNCTION account_gap_reject_operation_terminal_mutation()"
    )
    op.execute(
        """
        CREATE FUNCTION account_gap_reject_snapshot_terminal_mutation() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'account-gap snapshots cannot be deleted';
            END IF;
            IF OLD.state IN ('succeeded', 'not_applicable', 'failed_terminal',
                             'spend_outcome_unknown') AND NEW IS DISTINCT FROM OLD THEN
                RAISE EXCEPTION 'terminal account-gap snapshot is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER account_gap_snapshot_terminal_immutable BEFORE UPDATE OR DELETE "
        "ON account_gap_snapshot FOR EACH ROW "
        "EXECUTE FUNCTION account_gap_reject_snapshot_terminal_mutation()"
    )
    op.execute(
        """
        CREATE FUNCTION account_gap_reject_field_terminal_mutation() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'account-gap field outcomes cannot be deleted';
            END IF;
            IF OLD.state <> 'pending' AND NEW IS DISTINCT FROM OLD THEN
                RAISE EXCEPTION 'terminal account-gap field outcome is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER account_gap_field_terminal_immutable BEFORE UPDATE OR DELETE "
        "ON account_gap_field_result FOR EACH ROW "
        "EXECUTE FUNCTION account_gap_reject_field_terminal_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER account_gap_field_terminal_immutable ON account_gap_field_result")
    op.execute("DROP FUNCTION account_gap_reject_field_terminal_mutation()")
    op.execute("DROP TRIGGER account_gap_snapshot_terminal_immutable ON account_gap_snapshot")
    op.execute("DROP FUNCTION account_gap_reject_snapshot_terminal_mutation()")
    op.execute("DROP TRIGGER account_gap_operation_terminal_immutable ON account_gap_operation")
    op.execute("DROP FUNCTION account_gap_reject_operation_terminal_mutation()")
    op.execute("DROP TRIGGER account_gap_success_barrier ON account_gap_operation")
    op.execute("DROP FUNCTION account_gap_validate_success()")
    op.execute("DROP TRIGGER account_gap_field_no_overlap ON account_gap_field_result")
    op.execute("DROP FUNCTION account_gap_reject_overlapping_field()")
    op.execute("DROP TRIGGER account_gap_result_claim_lineage ON account_gap_field_result")
    op.execute("DROP FUNCTION account_gap_validate_result_claims()")
    op.execute("DROP TRIGGER account_gap_tier_claim_lineage ON account_gap_operation")
    op.execute("DROP FUNCTION account_gap_validate_tier_claim()")
    op.execute("DROP TABLE account_gap_field_result")
    op.execute("DROP TABLE account_gap_snapshot")
    op.execute("DROP TABLE account_gap_operation")
    op.execute("DROP TYPE account_gap_field_state")
    op.execute("DROP TYPE account_gap_spend_outcome")
    op.execute("DROP TYPE account_gap_snapshot_state")
    op.execute("DROP TYPE account_gap_operation_state")
