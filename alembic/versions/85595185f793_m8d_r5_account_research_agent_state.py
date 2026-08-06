"""m8d r5 account research agent state

Revision ID: 85595185f793
Revises: 5764311c620d
Create Date: 2026-08-06 01:47:33.994072+00:00

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
revision: str = "85595185f793"
down_revision: str | None = "5764311c620d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE entity_research_result "
        "ADD COLUMN provider_reported_cost_cents numeric(18, 6) NOT NULL DEFAULT 0, "
        "ADD COLUMN settled_cost_cents numeric(18, 6) NOT NULL DEFAULT 0, "
        "ADD COLUMN confirmed_empty_discovery boolean NOT NULL DEFAULT false, "
        "ADD CONSTRAINT entity_research_result_cost_nonnegative CHECK ("
        "provider_reported_cost_cents >= 0 AND settled_cost_cents >= 0)"
    )
    op.execute(
        """
        CREATE TABLE entity_research_provider_settlement_fold (
            provider_operation_ref text PRIMARY KEY REFERENCES
                entity_research_provider_operation(operation_ref),
            research_run_id       uuid NOT NULL REFERENCES entity_research_run(research_run_id),
            job_id                uuid NOT NULL REFERENCES entity_research_job(job_id),
            settled_cost_cents    numeric(18, 6) NOT NULL,
            folded_at             timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT entity_research_provider_settlement_fold_cost
                CHECK (settled_cost_cents >= 0)
        )
        """
    )
    op.execute(
        """
        CREATE FUNCTION validate_entity_research_provider_settlement_fold()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM entity_research_job job
                WHERE job.job_id=NEW.job_id
                  AND job.research_run_id=NEW.research_run_id
            ) THEN
                RAISE EXCEPTION
                    'entity research provider settlement fold is outside the exact job/run';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER entity_research_provider_settlement_fold_scope "
        "BEFORE INSERT ON entity_research_provider_settlement_fold FOR EACH ROW "
        "EXECUTE FUNCTION validate_entity_research_provider_settlement_fold()"
    )
    # R4 indexed a provider result by field alone.  A committee result legitimately projects the
    # same contact field (for example title) for several identity-admitted people, so field-key
    # uniqueness must include the exact projected subject.
    op.execute(
        "ALTER TABLE entity_research_result_field "
        "DROP CONSTRAINT entity_research_result_field_result_id_field_key_key, "
        "ADD CONSTRAINT entity_research_result_field_subject_field_key "
        "UNIQUE (result_id, subject_type, target_entity_id, field_key)"
    )
    op.execute(
        """
        CREATE TABLE entity_research_sumble_projection (
            provider_operation_ref        text PRIMARY KEY REFERENCES
                                          entity_research_provider_operation (operation_ref)
                                          ON DELETE RESTRICT,
            workspace_id                  text NOT NULL,
            provider_snapshot_ref         text NOT NULL,
            normalized_result_artifact_key text NOT NULL,
            raw_response_artifact_refs    text[] NOT NULL,
            retained_result_artifact_refs text[] NOT NULL,
            provider_receipt_ref          text NOT NULL,
            cost_settlement_ref           text NOT NULL,
            provider_request_id           text NOT NULL,
            provider_reported_cost_cents  numeric(18, 6) NOT NULL,
            settled_cost_cents            numeric(18, 6) NOT NULL,
            metadata_json                 jsonb NOT NULL,
            created_at                    timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT entity_research_sumble_projection_artifact_fk
                FOREIGN KEY (normalized_result_artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id) ON DELETE RESTRICT,
            CONSTRAINT entity_research_sumble_projection_nonempty CHECK (
                length(btrim(provider_snapshot_ref)) > 0
                AND cardinality(raw_response_artifact_refs) > 0
                AND cardinality(retained_result_artifact_refs) > 0
                AND length(btrim(provider_receipt_ref)) > 0
                AND length(btrim(cost_settlement_ref)) > 0
                AND length(btrim(provider_request_id)) > 0
            ),
            CONSTRAINT entity_research_sumble_projection_cost CHECK (
                provider_reported_cost_cents >= 0 AND settled_cost_cents >= 0
            ),
            CONSTRAINT entity_research_sumble_projection_metadata
                CHECK (jsonb_typeof(metadata_json)='object')
        )
        """
    )
    op.execute(
        """
        CREATE TABLE entity_research_account_committee_scope (
            scope_id             uuid PRIMARY KEY,
            tool_request_id      uuid NOT NULL UNIQUE REFERENCES entity_research_tool_request
                                     (tool_request_id) ON DELETE RESTRICT,
            research_run_id      uuid NOT NULL REFERENCES entity_research_run
                                     (research_run_id) ON DELETE RESTRICT,
            job_id               uuid NOT NULL REFERENCES entity_research_job
                                     (job_id) ON DELETE RESTRICT,
            workspace_id         text NOT NULL,
            account_entity_id    uuid NOT NULL,
            scope_json           jsonb NOT NULL,
            scope_sha256         text NOT NULL,
            created_at           timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT entity_research_account_committee_scope_object
                CHECK (jsonb_typeof(scope_json)='object'),
            CONSTRAINT entity_research_account_committee_scope_sha
                CHECK (scope_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT entity_research_account_committee_scope_exact CHECK ((
                scope_json->>'scope_id' = scope_id::text AND
                scope_json->>'account_entity_id' = account_entity_id::text
            ) IS TRUE)
        )
        """
    )
    op.execute(
        "CREATE INDEX entity_research_account_committee_scope_job "
        "ON entity_research_account_committee_scope (job_id, created_at)"
    )
    op.execute(
        """
        CREATE FUNCTION entity_research_all_account_fields(keys text[])
        RETURNS boolean LANGUAGE sql IMMUTABLE STRICT AS $$
            SELECT COALESCE(bool_and(field_key LIKE 'account.%'), TRUE)
            FROM unnest(keys) field_key
        $$
        """
    )
    op.execute(
        """
        CREATE TABLE entity_research_account_coverage (
            coverage_id              uuid PRIMARY KEY,
            research_run_id          uuid NOT NULL REFERENCES entity_research_run
                                         (research_run_id) ON DELETE RESTRICT,
            job_id                   uuid NOT NULL REFERENCES entity_research_job
                                         (job_id) ON DELETE RESTRICT,
            workspace_id             text NOT NULL,
            account_entity_id        uuid NOT NULL,
            result_refs              text[] NOT NULL,
            completed_field_keys     text[] NOT NULL,
            unresolved_field_keys    text[] NOT NULL,
            unresolved_reasons       text[] NOT NULL,
            committee_result_refs    text[] NOT NULL,
            committee_member_ids     uuid[] NOT NULL,
            committee_status         text NOT NULL,
            review_flags             text[] NOT NULL,
            claim_refs               text[] NOT NULL,
            evidence_refs            text[] NOT NULL,
            coverage_json            jsonb NOT NULL,
            coverage_sha256          text NOT NULL,
            created_at               timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT entity_research_account_coverage_object
                CHECK (jsonb_typeof(coverage_json)='object'),
            CONSTRAINT entity_research_account_coverage_sha
                CHECK (coverage_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT entity_research_account_coverage_committee_status CHECK (
                committee_status IN ('complete', 'partial', 'needs_review')
            ),
            CONSTRAINT entity_research_account_coverage_field_axis CHECK (
                entity_research_all_account_fields(
                    completed_field_keys || unresolved_field_keys
                )
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX entity_research_account_coverage_job "
        "ON entity_research_account_coverage (job_id, created_at DESC, coverage_id DESC)"
    )
    op.execute(
        """
        CREATE TABLE entity_research_account_review_item (
            review_item_id       uuid PRIMARY KEY,
            coverage_id          uuid NOT NULL REFERENCES entity_research_account_coverage
                                     (coverage_id) ON DELETE RESTRICT,
            research_run_id      uuid NOT NULL REFERENCES entity_research_run
                                     (research_run_id) ON DELETE RESTRICT,
            job_id               uuid NOT NULL REFERENCES entity_research_job
                                     (job_id) ON DELETE RESTRICT,
            workspace_id         text NOT NULL,
            account_entity_id    uuid NOT NULL,
            reason_code          text NOT NULL,
            details_json         jsonb NOT NULL,
            state                text NOT NULL DEFAULT 'open',
            created_at           timestamptz NOT NULL DEFAULT now(),
            resolved_at          timestamptz,
            resolved_by          text,
            resolution_ref       text,
            CONSTRAINT entity_research_account_review_reason_nonempty
                CHECK (length(btrim(reason_code)) > 0),
            CONSTRAINT entity_research_account_review_details_object
                CHECK (jsonb_typeof(details_json)='object'),
            CONSTRAINT entity_research_account_review_state
                CHECK (state IN ('open', 'resolved')),
            CONSTRAINT entity_research_account_review_resolution CHECK (
                (state='open' AND resolved_at IS NULL AND resolved_by IS NULL
                    AND resolution_ref IS NULL) OR
                (state='resolved' AND resolved_at IS NOT NULL
                    AND length(btrim(resolved_by)) > 0 AND length(btrim(resolution_ref)) > 0)
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX entity_research_account_review_queue "
        "ON entity_research_account_review_item (workspace_id, state, created_at)"
    )
    op.execute(
        """
        CREATE TABLE entity_research_account_finalization_intent (
            proposal_id          uuid PRIMARY KEY,
            coverage_id          uuid NOT NULL REFERENCES entity_research_account_coverage
                                     (coverage_id) ON DELETE RESTRICT,
            research_run_id      uuid NOT NULL REFERENCES entity_research_run
                                     (research_run_id) ON DELETE RESTRICT,
            job_id               uuid NOT NULL REFERENCES entity_research_job
                                     (job_id) ON DELETE RESTRICT,
            workspace_id         text NOT NULL,
            account_entity_id    uuid NOT NULL,
            current_state_sha256 text NOT NULL,
            proposal_json        jsonb NOT NULL,
            proposal_sha256      text NOT NULL,
            created_at           timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT entity_research_account_finalization_state_sha
                CHECK (current_state_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT entity_research_account_finalization_object
                CHECK (jsonb_typeof(proposal_json)='object'),
            CONSTRAINT entity_research_account_finalization_sha
                CHECK (proposal_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT entity_research_account_finalization_exact CHECK ((
                proposal_json->>'proposal_id' = proposal_id::text AND
                proposal_json->>'target_entity_id' = account_entity_id::text AND
                proposal_json->>'subject_type' = 'account'
            ) IS TRUE)
        )
        """
    )
    op.execute(
        "CREATE INDEX entity_research_account_finalization_job "
        "ON entity_research_account_finalization_intent (job_id, created_at DESC)"
    )
    op.execute(
        """
        CREATE FUNCTION reject_entity_research_account_history_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION
                'entity research account scope, coverage, and finalization are append-only';
        END
        $$
        """
    )
    for table in (
        "entity_research_provider_settlement_fold",
        "entity_research_sumble_projection",
        "entity_research_account_committee_scope",
        "entity_research_account_coverage",
        "entity_research_account_finalization_intent",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_entity_research_account_history_mutation()"
        )


def downgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
          IF to_regclass('entity_research_provider_settlement_fold') IS NOT NULL THEN
            DROP TRIGGER IF EXISTS entity_research_provider_settlement_fold_scope
              ON entity_research_provider_settlement_fold;
            DROP TRIGGER IF EXISTS entity_research_provider_settlement_fold_append_only
              ON entity_research_provider_settlement_fold;
          END IF;
        END $$
        """
    )
    op.execute("DROP FUNCTION IF EXISTS validate_entity_research_provider_settlement_fold")
    for table in (
        "entity_research_sumble_projection",
        "entity_research_account_committee_scope",
        "entity_research_account_coverage",
        "entity_research_account_finalization_intent",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
    op.execute("DROP FUNCTION reject_entity_research_account_history_mutation")
    op.execute("DROP TABLE entity_research_account_finalization_intent")
    op.execute("DROP TABLE entity_research_account_review_item")
    op.execute("DROP TABLE entity_research_account_coverage")
    op.execute("DROP FUNCTION entity_research_all_account_fields(text[])")
    op.execute("DROP TABLE entity_research_account_committee_scope")
    op.execute("DROP TABLE IF EXISTS entity_research_provider_settlement_fold")
    op.execute("DROP TABLE entity_research_sumble_projection")
    op.execute(
        "ALTER TABLE entity_research_result_field "
        "DROP CONSTRAINT IF EXISTS entity_research_result_field_subject_field_key"
    )
    op.execute(
        """
        DO $$ BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conrelid='entity_research_result_field'::regclass
              AND conname='entity_research_result_field_result_id_field_key_key'
          ) THEN
            ALTER TABLE entity_research_result_field
              ADD CONSTRAINT entity_research_result_field_result_id_field_key_key
              UNIQUE (result_id, field_key);
          END IF;
        END $$
        """
    )
    op.execute(
        "ALTER TABLE entity_research_result "
        "DROP CONSTRAINT entity_research_result_cost_nonnegative, "
        "DROP COLUMN IF EXISTS confirmed_empty_discovery, DROP COLUMN settled_cost_cents, "
        "DROP COLUMN provider_reported_cost_cents"
    )
