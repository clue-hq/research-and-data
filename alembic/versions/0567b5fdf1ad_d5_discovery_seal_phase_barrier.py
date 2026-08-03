"""d5 discovery seal phase barrier

Revision ID: 0567b5fdf1ad
Revises: 413e800f79b5
Create Date: 2026-08-03 05:31:10.806860+00:00

D5 makes a durable discovery generation structurally incapable of advancing a project run until
its exact current batch has one relationally verified immutable manifest bundle and seal.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0567b5fdf1ad"
down_revision: str | None = "413e800f79b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TERMINAL_CHILD_GUARD = r"""
CREATE OR REPLACE FUNCTION discovery_reject_sealed_batch_mutation() RETURNS trigger AS $$
DECLARE
    scoped_workspace text;
    scoped_batch uuid;
    scoped_operation uuid;
    scoped_resolution uuid;
    current_state text;
BEGIN
    IF TG_TABLE_NAME IN (
        'discovery_operation', 'discovery_candidate_link',
        'discovery_field_resolution', 'discovery_batch_manifest'
    ) THEN
        IF TG_OP = 'DELETE' THEN
            scoped_workspace := OLD.workspace_id;
            scoped_batch := OLD.batch_id;
        ELSE
            scoped_workspace := NEW.workspace_id;
            scoped_batch := NEW.batch_id;
        END IF;
    ELSIF TG_TABLE_NAME IN (
        'discovery_provider_event', 'discovery_page_receipt',
        'discovery_item_snapshot', 'discovery_page_item'
    ) THEN
        IF TG_OP = 'DELETE' THEN
            scoped_workspace := OLD.workspace_id;
            scoped_operation := OLD.operation_id;
        ELSE
            scoped_workspace := NEW.workspace_id;
            scoped_operation := NEW.operation_id;
        END IF;
        SELECT operation.batch_id INTO scoped_batch
        FROM discovery_operation operation
        WHERE operation.workspace_id = scoped_workspace
          AND operation.id = scoped_operation;
    ELSE
        IF TG_OP = 'DELETE' THEN
            scoped_workspace := OLD.workspace_id;
            scoped_resolution := OLD.resolution_id;
        ELSE
            scoped_workspace := NEW.workspace_id;
            scoped_resolution := NEW.resolution_id;
        END IF;
        SELECT resolution.batch_id INTO scoped_batch
        FROM discovery_field_resolution resolution
        WHERE resolution.workspace_id = scoped_workspace
          AND resolution.id = scoped_resolution;
    END IF;

    SELECT batch.state::text INTO current_state
    FROM discovery_batch batch
    WHERE batch.workspace_id = scoped_workspace AND batch.id = scoped_batch;

    IF current_state = 'sealed' THEN
        IF TG_TABLE_NAME = 'discovery_provider_event' AND TG_OP = 'INSERT'
           AND to_jsonb(NEW)->>'processing_disposition' = 'late_after_seal'
           AND to_jsonb(NEW)->>'processed_at' IS NOT NULL THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'discovery batch % is sealed', scoped_batch;
    END IF;
    IF current_state IN ('failed_terminal', 'cancelled_unsealed') THEN
        IF TG_TABLE_NAME = 'discovery_provider_event' AND TG_OP = 'INSERT'
           AND to_jsonb(NEW)->>'processing_disposition' = 'superseded'
           AND to_jsonb(NEW)->>'processed_at' IS NOT NULL THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'discovery batch % is terminal', scoped_batch;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""


_SEALED_ONLY_CHILD_GUARD = r"""
CREATE OR REPLACE FUNCTION discovery_reject_sealed_batch_mutation() RETURNS trigger AS $$
DECLARE
    scoped_workspace text;
    scoped_batch uuid;
    scoped_operation uuid;
    scoped_resolution uuid;
    current_state text;
BEGIN
    IF TG_TABLE_NAME IN (
        'discovery_operation', 'discovery_candidate_link',
        'discovery_field_resolution'
    ) THEN
        IF TG_OP = 'DELETE' THEN
            scoped_workspace := OLD.workspace_id;
            scoped_batch := OLD.batch_id;
        ELSE
            scoped_workspace := NEW.workspace_id;
            scoped_batch := NEW.batch_id;
        END IF;
    ELSIF TG_TABLE_NAME IN (
        'discovery_provider_event', 'discovery_page_receipt',
        'discovery_item_snapshot', 'discovery_page_item'
    ) THEN
        IF TG_OP = 'DELETE' THEN
            scoped_workspace := OLD.workspace_id;
            scoped_operation := OLD.operation_id;
        ELSE
            scoped_workspace := NEW.workspace_id;
            scoped_operation := NEW.operation_id;
        END IF;
        SELECT operation.batch_id INTO scoped_batch
        FROM discovery_operation operation
        WHERE operation.workspace_id = scoped_workspace
          AND operation.id = scoped_operation;
    ELSE
        IF TG_OP = 'DELETE' THEN
            scoped_workspace := OLD.workspace_id;
            scoped_resolution := OLD.resolution_id;
        ELSE
            scoped_workspace := NEW.workspace_id;
            scoped_resolution := NEW.resolution_id;
        END IF;
        SELECT resolution.batch_id INTO scoped_batch
        FROM discovery_field_resolution resolution
        WHERE resolution.workspace_id = scoped_workspace
          AND resolution.id = scoped_resolution;
    END IF;

    SELECT batch.state::text INTO current_state
    FROM discovery_batch batch
    WHERE batch.workspace_id = scoped_workspace AND batch.id = scoped_batch;

    IF current_state = 'sealed' THEN
        IF TG_TABLE_NAME = 'discovery_provider_event' AND TG_OP = 'INSERT' THEN
            IF to_jsonb(NEW)->>'processing_disposition' = 'late_after_seal'
               AND to_jsonb(NEW)->>'processed_at' IS NOT NULL THEN
                RETURN NEW;
            END IF;
        END IF;
        RAISE EXCEPTION 'discovery batch % is sealed', scoped_batch;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""


_PROJECT_RUN_SEAL_GUARD = r"""
CREATE OR REPLACE FUNCTION discovery_require_current_seal_for_scoring() RETURNS trigger AS $$
DECLARE
    current_batch record;
    current_seal record;
    current_manifest record;
    discovery_checkpoint record;
BEGIN
    IF OLD.phase = 'discovery' AND NEW.phase = 'scoring' THEN
        SELECT batch.* INTO current_batch
        FROM discovery_batch batch
        WHERE batch.workspace_id = NEW.workspace_id
          AND batch.project_run_id = NEW.id
        ORDER BY batch.generation DESC
        LIMIT 1;

        IF FOUND THEN
            IF current_batch.project_id <> NEW.project_id
               OR current_batch.icp_key <> NEW.icp_key
               OR current_batch.icp_version <> NEW.icp_version
               OR current_batch.state <> 'sealed'
               OR current_batch.replacement_batch_id IS NOT NULL THEN
                RAISE EXCEPTION
                    'project run % requires exact current discovery batch seal', NEW.id;
            END IF;

            SELECT seal.* INTO current_seal
            FROM discovery_batch_seal seal
            WHERE seal.workspace_id = NEW.workspace_id
              AND seal.batch_id = current_batch.id
              AND seal.project_run_id = NEW.id
              AND seal.icp_key = NEW.icp_key
              AND seal.icp_version = NEW.icp_version;
            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'project run % requires exact current discovery batch seal', NEW.id;
            END IF;

            SELECT manifest.* INTO current_manifest
            FROM discovery_batch_manifest manifest
            WHERE manifest.workspace_id = NEW.workspace_id
              AND manifest.batch_id = current_batch.id;
            IF NOT FOUND
               OR current_manifest.account_manifest_artifact_key
                    <> current_seal.account_manifest_artifact_key
               OR current_manifest.account_manifest_sha256
                    <> current_seal.account_manifest_sha256
               OR current_manifest.raw_manifest_artifact_key
                    <> current_seal.raw_artifact_manifest_key
               OR current_manifest.claim_manifest_artifact_key
                    <> current_seal.claim_id_manifest_key
               OR current_manifest.coverage_report_artifact_key
                    <> current_seal.coverage_report_ref THEN
                RAISE EXCEPTION
                    'project run % requires exact current discovery manifest', NEW.id;
            END IF;
            IF EXISTS (
                SELECT 1 FROM (VALUES
                    (current_manifest.account_manifest_artifact_key,
                     current_manifest.account_manifest_sha256),
                    (current_manifest.claim_manifest_artifact_key,
                     current_manifest.claim_manifest_sha256),
                    (current_manifest.raw_manifest_artifact_key,
                     current_manifest.raw_manifest_sha256),
                    (current_manifest.coverage_report_artifact_key,
                     current_manifest.coverage_report_sha256)
                ) required(key, sha256)
                WHERE NOT EXISTS (
                    SELECT 1 FROM artifact
                    WHERE artifact.workspace_id = NEW.workspace_id
                      AND artifact.storage_key = required.key
                      AND artifact.content_sha256 = required.sha256
                      AND artifact.erased_at IS NULL
                      AND artifact.purged_at IS NULL
                )
            ) THEN
                RAISE EXCEPTION
                    'project run % requires live discovery manifest artifacts', NEW.id;
            END IF;

            SELECT checkpoint.* INTO discovery_checkpoint
            FROM project_phase_checkpoint checkpoint
            WHERE checkpoint.project_run_id = NEW.id
              AND checkpoint.phase = 'discovery'
              AND checkpoint.status = 'committed';
            IF NOT FOUND
               OR discovery_checkpoint.payload_json ->> 'discovery_batch_id'
                    <> current_batch.id::text
               OR discovery_checkpoint.payload_json ->> 'discovery_batch_seal_ref'
                    <> current_seal.seal_sha256 THEN
                RAISE EXCEPTION
                    'project run % requires exact committed discovery seal checkpoint',
                    NEW.id;
            END IF;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""


_BATCH_MUTATION_GUARD = r"""
CREATE OR REPLACE FUNCTION discovery_reject_sealed_batch_reopen() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'durable discovery batch % cannot be deleted', OLD.id;
    END IF;
    IF TG_OP = 'UPDATE' AND OLD.state IN (
        'sealed', 'failed_terminal', 'cancelled_unsealed'
    ) AND NEW IS DISTINCT FROM OLD THEN
        IF OLD.state IN ('failed_terminal', 'cancelled_unsealed')
           AND OLD.replacement_batch_id IS NULL
           AND NEW.replacement_batch_id IS NOT NULL
           AND (to_jsonb(NEW) - ARRAY['replacement_batch_id', 'updated_at'])
               = (to_jsonb(OLD) - ARRAY['replacement_batch_id', 'updated_at']) THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'discovery batch % is terminal', OLD.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""


def upgrade() -> None:
    op.execute("ALTER TABLE discovery_wake_outbox DROP CONSTRAINT discovery_wake_outbox_reason")
    op.execute(
        "ALTER TABLE discovery_wake_outbox ADD CONSTRAINT discovery_wake_outbox_reason "
        "CHECK (reason IN ('scheduled_poll', 'provider_event', 'manual_reconcile', "
        "'crash_recovery', 'field_materialization', 'batch_seal'))"
    )
    op.execute(
        """
        CREATE TABLE discovery_batch_manifest (
            batch_id                         uuid NOT NULL,
            workspace_id                     text NOT NULL,
            project_id                       text NOT NULL,
            project_run_id                   uuid NOT NULL,
            icp_key                          text NOT NULL,
            icp_version                      integer NOT NULL,
            discovery_plan_id                uuid NOT NULL,
            plan_sha256                      text NOT NULL,
            generation                       integer NOT NULL,
            contract_version                 text NOT NULL,
            account_ids                      jsonb NOT NULL,
            claim_ids                        jsonb NOT NULL,
            raw_artifact_keys                jsonb NOT NULL,
            coverage_payload                 jsonb NOT NULL,
            account_manifest_artifact_key    text NOT NULL,
            account_manifest_sha256          text NOT NULL,
            claim_manifest_artifact_key      text NOT NULL,
            claim_manifest_sha256            text NOT NULL,
            raw_manifest_artifact_key        text NOT NULL,
            raw_manifest_sha256              text NOT NULL,
            coverage_report_artifact_key     text NOT NULL,
            coverage_report_sha256           text NOT NULL,
            created_at                       timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT discovery_batch_manifest_pkey PRIMARY KEY (batch_id),
            CONSTRAINT discovery_batch_manifest_batch_fk
                FOREIGN KEY (batch_id, workspace_id)
                REFERENCES discovery_batch (id, workspace_id),
            CONSTRAINT discovery_batch_manifest_plan_fk
                FOREIGN KEY (discovery_plan_id, workspace_id)
                REFERENCES discovery_plan (id, workspace_id),
            CONSTRAINT discovery_batch_manifest_run_fk
                FOREIGN KEY (project_run_id, workspace_id, project_id)
                REFERENCES project_run (id, workspace_id, project_id),
            CONSTRAINT discovery_batch_manifest_workspace_anchor
                UNIQUE (batch_id, workspace_id),
            CONSTRAINT discovery_batch_manifest_contract
                CHECK (contract_version = 'discovery-batch-manifest-v1'),
            CONSTRAINT discovery_batch_manifest_generation_positive CHECK (generation >= 1),
            CONSTRAINT discovery_batch_manifest_icp_version_positive CHECK (icp_version >= 1),
            CONSTRAINT discovery_batch_manifest_plan_sha_shape
                CHECK (plan_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT discovery_batch_manifest_json_shapes CHECK (
                jsonb_typeof(account_ids) = 'array'
                AND jsonb_typeof(claim_ids) = 'array'
                AND jsonb_typeof(raw_artifact_keys) = 'array'
                AND jsonb_typeof(coverage_payload) = 'object'
            ),
            CONSTRAINT discovery_batch_manifest_hash_shapes CHECK (
                account_manifest_sha256 ~ '^[0-9a-f]{64}$'
                AND claim_manifest_sha256 ~ '^[0-9a-f]{64}$'
                AND raw_manifest_sha256 ~ '^[0-9a-f]{64}$'
                AND coverage_report_sha256 ~ '^[0-9a-f]{64}$'
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX discovery_batch_manifest_run ON discovery_batch_manifest "
        "(workspace_id, project_run_id, generation DESC)"
    )
    op.execute(
        "CREATE TRIGGER discovery_batch_manifest_immutable BEFORE UPDATE OR DELETE "
        "ON discovery_batch_manifest FOR EACH ROW "
        "EXECUTE FUNCTION discovery_reject_immutable_mutation()"
    )
    op.execute(_TERMINAL_CHILD_GUARD)
    op.execute(
        "CREATE TRIGGER discovery_batch_manifest_sealed_guard "
        "BEFORE INSERT OR UPDATE OR DELETE ON discovery_batch_manifest FOR EACH ROW "
        "EXECUTE FUNCTION discovery_reject_sealed_batch_mutation()"
    )

    # A terminal unsuccessful generation freezes in place. A one-time replacement edge is the
    # only permitted later annotation and does not rewrite any execution fact.
    op.execute(_BATCH_MUTATION_GUARD)
    op.execute("DROP TRIGGER discovery_batch_sealed_guard ON discovery_batch")
    op.execute(
        "CREATE TRIGGER discovery_batch_sealed_guard BEFORE UPDATE OR DELETE ON discovery_batch "
        "FOR EACH ROW EXECUTE FUNCTION discovery_reject_sealed_batch_reopen()"
    )

    # The project transition is a database invariant, not a convention of one state-machine
    # caller. Legacy runs with no durable batch remain valid; the first batch activates the guard.
    op.execute(_PROJECT_RUN_SEAL_GUARD)
    op.execute(
        "CREATE TRIGGER project_run_discovery_seal_guard BEFORE UPDATE OF phase ON project_run "
        "FOR EACH ROW WHEN (OLD.phase IS DISTINCT FROM NEW.phase) "
        "EXECUTE FUNCTION discovery_require_current_seal_for_scoring()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS project_run_discovery_seal_guard ON project_run")
    op.execute("DROP FUNCTION IF EXISTS discovery_require_current_seal_for_scoring()")
    op.execute(
        "DROP TRIGGER IF EXISTS discovery_batch_manifest_sealed_guard ON discovery_batch_manifest"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS discovery_batch_manifest_immutable ON discovery_batch_manifest"
    )
    op.execute("DROP TABLE IF EXISTS discovery_batch_manifest")
    op.execute(_SEALED_ONLY_CHILD_GUARD)
    op.execute("DROP TRIGGER discovery_batch_sealed_guard ON discovery_batch")
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION discovery_reject_sealed_batch_reopen() RETURNS trigger AS $$
        BEGIN
            IF OLD.state = 'sealed' AND NEW IS DISTINCT FROM OLD THEN
                RAISE EXCEPTION 'discovery batch % is sealed', OLD.id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER discovery_batch_sealed_guard BEFORE UPDATE ON discovery_batch "
        "FOR EACH ROW EXECUTE FUNCTION discovery_reject_sealed_batch_reopen()"
    )
    op.execute("ALTER TABLE discovery_wake_outbox DROP CONSTRAINT discovery_wake_outbox_reason")
    op.execute(
        "UPDATE discovery_wake_outbox SET reason = 'field_materialization' "
        "WHERE reason = 'batch_seal'"
    )
    op.execute(
        "ALTER TABLE discovery_wake_outbox ADD CONSTRAINT discovery_wake_outbox_reason "
        "CHECK (reason IN ('scheduled_poll', 'provider_event', 'manual_reconcile', "
        "'crash_recovery', 'field_materialization'))"
    )
