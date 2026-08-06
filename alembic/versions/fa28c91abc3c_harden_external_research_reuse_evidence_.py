"""harden external research reuse evidence and spend

Revision ID: fa28c91abc3c
Revises: 2e6920101a1b
Create Date: 2026-08-04 12:35:34.288436+00:00

Adds one semantic acquisition identity, immutable per-run snapshot adoption, append-only cost
reconciliation, and database-enforced claim-to-snapshot/result lineage.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fa28c91abc3c"
down_revision: str | None = "2e6920101a1b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _operation_guard(*, include_reuse_fingerprint: bool) -> str:
    reuse_guard = (
        "\n               OR NEW.reuse_fingerprint <> OLD.reuse_fingerprint"
        if include_reuse_fingerprint
        else ""
    )
    return f"""
        CREATE OR REPLACE FUNCTION external_research_reject_operation_mutation()
        RETURNS trigger AS $$
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
               OR NEW.request_fingerprint <> OLD.request_fingerprint{reuse_guard}
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


def upgrade() -> None:
    # A semantic identity deliberately excludes run/window labels. Historical rows retain their
    # exact fingerprint as a safe non-reusing backfill; new writers supply the real semantic hash.
    op.execute("ALTER TABLE external_research_operation ADD COLUMN reuse_fingerprint text")
    op.execute(
        "UPDATE external_research_operation SET reuse_fingerprint=request_fingerprint "
        "WHERE reuse_fingerprint IS NULL"
    )
    op.execute(
        "ALTER TABLE external_research_operation ALTER COLUMN reuse_fingerprint SET NOT NULL"
    )
    op.execute(
        "ALTER TABLE external_research_operation ADD CONSTRAINT "
        "external_research_operation_reuse_hash CHECK "
        "(reuse_fingerprint ~ '^[0-9a-f]{64}$')"
    )
    op.execute(
        "CREATE INDEX external_research_reuse_lookup ON external_research_operation "
        "(workspace_id, reuse_fingerprint, state, fresh_until DESC)"
    )
    op.execute(_operation_guard(include_reuse_fingerprint=True))

    # One ready provider snapshot can be consumed by several project runs without pretending that
    # the original paid operation belongs to each run. The adoption is immutable and records the
    # exact consumer request/window which selected it.
    op.execute(
        """
        CREATE TABLE external_research_snapshot_use (
            workspace_id                text NOT NULL,
            project_id                  text NOT NULL,
            project_run_id              uuid NOT NULL,
            account_id                  uuid NOT NULL,
            source_key                  text NOT NULL,
            snapshot_id                 uuid NOT NULL,
            reuse_fingerprint           text NOT NULL,
            consumer_request_fingerprint text NOT NULL,
            consumer_observation_window text NOT NULL,
            adopted_at                  timestamptz NOT NULL,

            CONSTRAINT external_research_snapshot_use_pkey
                PRIMARY KEY (workspace_id, project_run_id, snapshot_id),
            CONSTRAINT external_research_snapshot_use_run_fk
                FOREIGN KEY (project_run_id, workspace_id, project_id)
                REFERENCES project_run (id, workspace_id, project_id),
            CONSTRAINT external_research_snapshot_use_account_fk
                FOREIGN KEY (account_id, workspace_id)
                REFERENCES account_entity (id, workspace_id),
            CONSTRAINT external_research_snapshot_use_source_fk
                FOREIGN KEY (source_key) REFERENCES source_manifest (source_key),
            CONSTRAINT external_research_snapshot_use_snapshot_fk
                FOREIGN KEY (snapshot_id, workspace_id)
                REFERENCES external_research_snapshot (id, workspace_id),
            CONSTRAINT external_research_snapshot_use_hashes CHECK (
                reuse_fingerprint ~ '^[0-9a-f]{64}$'
                AND consumer_request_fingerprint ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT external_research_snapshot_use_window CHECK (
                length(btrim(consumer_observation_window)) > 0
            )
        )
        """
    )
    op.execute(
        """
        INSERT INTO external_research_snapshot_use (
            workspace_id, project_id, project_run_id, account_id, source_key, snapshot_id,
            reuse_fingerprint, consumer_request_fingerprint, consumer_observation_window,
            adopted_at
        )
        SELECT operation.workspace_id, operation.project_id, operation.project_run_id,
               operation.account_id, operation.source_key, snapshot.id,
               operation.reuse_fingerprint, operation.request_fingerprint,
               operation.observation_window, snapshot.created_at
        FROM external_research_snapshot snapshot
        JOIN external_research_operation operation
          ON operation.id=snapshot.operation_id
         AND operation.workspace_id=snapshot.workspace_id
        WHERE operation.state='ready'
        """
    )
    op.execute(
        "CREATE INDEX external_research_snapshot_use_lookup ON external_research_snapshot_use "
        "(workspace_id, project_run_id, account_id, source_key, adopted_at DESC)"
    )
    op.execute(
        """
        CREATE FUNCTION external_research_validate_snapshot_use() RETURNS trigger AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM external_research_snapshot snapshot
                JOIN external_research_operation operation
                  ON operation.id=snapshot.operation_id
                 AND operation.workspace_id=snapshot.workspace_id
                WHERE snapshot.id=NEW.snapshot_id
                  AND snapshot.workspace_id=NEW.workspace_id
                  AND snapshot.account_id=NEW.account_id
                  AND snapshot.source_key=NEW.source_key
                  AND snapshot.fresh_until > NEW.adopted_at
                  AND operation.project_id=NEW.project_id
                  AND operation.reuse_fingerprint=NEW.reuse_fingerprint
                  AND operation.state='ready'
            ) THEN
                RAISE EXCEPTION 'snapshot use must reference a matching fresh ready acquisition';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER external_research_snapshot_use_validate BEFORE INSERT "
        "ON external_research_snapshot_use FOR EACH ROW "
        "EXECUTE FUNCTION external_research_validate_snapshot_use()"
    )
    op.execute(
        """
        CREATE FUNCTION external_research_snapshot_use_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'external research snapshot use rows are immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER external_research_snapshot_use_immutable BEFORE UPDATE OR DELETE "
        "ON external_research_snapshot_use FOR EACH ROW "
        "EXECUTE FUNCTION external_research_snapshot_use_immutable()"
    )

    # The initial provider-reported receipt stays immutable. A later billing lookup/operator
    # decision is a separate append-only fact and adjusts project-run spend exactly once.
    op.execute("CREATE TYPE external_research_cost_disposition AS ENUM ('charged', 'not_charged')")
    op.execute(
        """
        CREATE TABLE external_research_cost_reconciliation (
            id                 uuid NOT NULL,
            operation_id       uuid NOT NULL,
            workspace_id       text NOT NULL,
            disposition        external_research_cost_disposition NOT NULL,
            settled_cost_cents numeric NOT NULL,
            evidence_artifact_key text NOT NULL,
            actor_ref          text NOT NULL,
            created_at         timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT external_research_cost_reconciliation_pkey PRIMARY KEY (id),
            CONSTRAINT external_research_cost_reconciliation_operation_unique UNIQUE (operation_id),
            CONSTRAINT external_research_cost_reconciliation_operation_fk
                FOREIGN KEY (operation_id, workspace_id)
                REFERENCES external_research_operation (id, workspace_id),
            CONSTRAINT external_research_cost_reconciliation_artifact_fk
                FOREIGN KEY (evidence_artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT external_research_cost_reconciliation_cost CHECK (
                settled_cost_cents >= 0
                AND (disposition <> 'not_charged' OR settled_cost_cents = 0)
            ),
            CONSTRAINT external_research_cost_reconciliation_actor CHECK (
                length(btrim(actor_ref)) > 0
            )
        )
        """
    )
    op.execute(
        """
        CREATE FUNCTION external_research_validate_cost_reconciliation() RETURNS trigger AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM external_research_operation operation
                WHERE operation.id=NEW.operation_id
                  AND operation.workspace_id=NEW.workspace_id
                  AND operation.state IN ('ready', 'spend_outcome_unknown')
            ) THEN
                RAISE EXCEPTION 'cost reconciliation requires ready or spend-unknown operation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER external_research_cost_reconciliation_validate BEFORE INSERT "
        "ON external_research_cost_reconciliation FOR EACH ROW "
        "EXECUTE FUNCTION external_research_validate_cost_reconciliation()"
    )
    op.execute(
        """
        CREATE FUNCTION external_research_cost_reconciliation_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'external research cost reconciliation rows are immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER external_research_cost_reconciliation_immutable BEFORE UPDATE OR DELETE "
        "ON external_research_cost_reconciliation FOR EACH ROW "
        "EXECUTE FUNCTION external_research_cost_reconciliation_immutable()"
    )

    # Shape checks alone are insufficient for immutable provenance. Prove that the claim's exact
    # operation/snapshot/request/result artifact tuple exists and belongs to its account/source.
    op.execute(
        """
        CREATE FUNCTION claim_validate_external_research_lineage() RETURNS trigger AS $$
        BEGIN
            IF NEW.source_key = 'exa_deep'
               AND NEW.source_operation_ref IS NOT NULL
               AND NOT EXISTS (
                SELECT 1
                FROM external_research_snapshot snapshot
                JOIN external_research_operation operation
                  ON operation.id=snapshot.operation_id
                 AND operation.workspace_id=snapshot.workspace_id
                JOIN external_research_result_artifact result
                  ON result.snapshot_id=snapshot.id
                 AND result.workspace_id=snapshot.workspace_id
                WHERE operation.id::text=NEW.source_operation_ref
                  AND snapshot.id::text=NEW.source_snapshot_ref
                  AND snapshot.provider_request_id=NEW.source_request_ref
                  AND snapshot.account_id=NEW.entity_id
                  AND snapshot.source_key=NEW.source_key
                  AND result.artifact_key=NEW.artifact_key
                  AND (NEW.workspace_id IS NULL OR snapshot.workspace_id=NEW.workspace_id)
            ) THEN
                RAISE EXCEPTION
                    'claim external research lineage does not match its snapshot/result evidence';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM claim candidate
                WHERE candidate.source_key = 'exa_deep'
                  AND candidate.source_operation_ref IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1
                    FROM external_research_snapshot snapshot
                    JOIN external_research_operation operation
                      ON operation.id=snapshot.operation_id
                     AND operation.workspace_id=snapshot.workspace_id
                    JOIN external_research_result_artifact result
                      ON result.snapshot_id=snapshot.id
                     AND result.workspace_id=snapshot.workspace_id
                    WHERE operation.id::text=candidate.source_operation_ref
                      AND snapshot.id::text=candidate.source_snapshot_ref
                      AND snapshot.provider_request_id=candidate.source_request_ref
                      AND snapshot.account_id=candidate.entity_id
                      AND snapshot.source_key=candidate.source_key
                      AND result.artifact_key=candidate.artifact_key
                      AND (candidate.workspace_id IS NULL
                           OR snapshot.workspace_id=candidate.workspace_id)
                  )
            ) THEN
                RAISE EXCEPTION 'existing claim has invalid external research lineage';
            END IF;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER claim_external_research_lineage_validate BEFORE INSERT OR UPDATE OF "
        "source_operation_ref, source_snapshot_ref, source_request_ref, artifact_key, source_key, "
        "entity_id, workspace_id ON claim FOR EACH ROW "
        "EXECUTE FUNCTION claim_validate_external_research_lineage()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER claim_external_research_lineage_validate ON claim")
    op.execute("DROP FUNCTION claim_validate_external_research_lineage()")

    op.execute(
        "DROP TRIGGER external_research_cost_reconciliation_immutable "
        "ON external_research_cost_reconciliation"
    )
    op.execute("DROP FUNCTION external_research_cost_reconciliation_immutable()")
    op.execute(
        "DROP TRIGGER external_research_cost_reconciliation_validate "
        "ON external_research_cost_reconciliation"
    )
    op.execute("DROP FUNCTION external_research_validate_cost_reconciliation()")
    op.execute("DROP TABLE external_research_cost_reconciliation")
    op.execute("DROP TYPE external_research_cost_disposition")

    op.execute(
        "DROP TRIGGER external_research_snapshot_use_immutable ON external_research_snapshot_use"
    )
    op.execute("DROP FUNCTION external_research_snapshot_use_immutable()")
    op.execute(
        "DROP TRIGGER external_research_snapshot_use_validate ON external_research_snapshot_use"
    )
    op.execute("DROP FUNCTION external_research_validate_snapshot_use()")
    op.execute("DROP INDEX external_research_snapshot_use_lookup")
    op.execute("DROP TABLE external_research_snapshot_use")

    op.execute(_operation_guard(include_reuse_fingerprint=False))
    op.execute("DROP INDEX external_research_reuse_lookup")
    op.execute(
        "ALTER TABLE external_research_operation DROP CONSTRAINT "
        "external_research_operation_reuse_hash"
    )
    op.execute("ALTER TABLE external_research_operation DROP COLUMN reuse_fingerprint")
