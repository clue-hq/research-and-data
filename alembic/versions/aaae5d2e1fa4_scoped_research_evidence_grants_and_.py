"""scoped research evidence grants and processing receipts

Revision ID: aaae5d2e1fa4
Revises: 68e3053b58f2
Create Date: 2026-09-22 17:44:38.819472+00:00

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
revision: str = "aaae5d2e1fa4"
down_revision: str | None = "68e3053b58f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE arv2_research_run ADD CONSTRAINT arv2_run_workspace "
        "UNIQUE(run_id,workspace_id)"
    )
    op.execute(
        "ALTER TABLE arv2_research_job ADD CONSTRAINT arv2_job_scope "
        "UNIQUE(job_id,workspace_id,run_id,account_entity_id)"
    )
    op.execute(
        "ALTER TABLE arv2_research_job ADD CONSTRAINT arv2_job_run_scope FOREIGN "
        "KEY(run_id,workspace_id) REFERENCES arv2_research_run(run_id,workspace_id)"
    )
    op.execute("""
      CREATE TABLE artifact_derivation (
        workspace_id text NOT NULL,
        parent_key text NOT NULL,
        child_key text NOT NULL,
        CONSTRAINT artifact_derivation_pk PRIMARY KEY(workspace_id,parent_key,child_key),
        CONSTRAINT artifact_derivation_not_self CHECK(parent_key<>child_key),
        CONSTRAINT artifact_derivation_parent_fk FOREIGN KEY(parent_key,workspace_id)
          REFERENCES artifact(storage_key,workspace_id),
        CONSTRAINT artifact_derivation_child_fk FOREIGN KEY(child_key,workspace_id)
          REFERENCES artifact(storage_key,workspace_id)
      )
    """)
    op.execute("CREATE INDEX artifact_derivation_child ON artifact_derivation(child_key)")
    op.execute("""
      CREATE FUNCTION erase_derived_artifacts() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF NEW.privacy_erased AND NOT OLD.privacy_erased THEN
          UPDATE artifact a SET privacy_erased=true,erased_at=COALESCE(a.erased_at,now()),
            erasure_reason=NEW.erasure_reason,source_url=NULL
          FROM artifact_derivation d WHERE d.parent_key=NEW.storage_key
            AND a.storage_key=d.child_key AND NOT a.privacy_erased;
        END IF;
        RETURN NEW;
      END $$
    """)
    op.execute(
        "CREATE TRIGGER artifact_erase_derivatives AFTER UPDATE OF privacy_erased ON "
        "artifact FOR EACH ROW EXECUTE FUNCTION erase_derived_artifacts()"
    )
    op.execute("""
      CREATE TABLE arv2_evidence_manifest (
        workspace_id text NOT NULL,
        run_id uuid NOT NULL,
        account_id uuid NOT NULL,
        revision bigint NOT NULL DEFAULT 0,
        CONSTRAINT arv2_evidence_manifest_pk PRIMARY KEY(workspace_id,run_id,account_id),
        CONSTRAINT arv2_evidence_manifest_run FOREIGN KEY(run_id,workspace_id)
          REFERENCES arv2_research_run(run_id,workspace_id),
        CONSTRAINT arv2_evidence_manifest_revision CHECK(revision>=0)
      )
    """)
    op.execute("""
      CREATE TABLE arv2_evidence_source (
        source_id uuid PRIMARY KEY,
        workspace_id text NOT NULL,
        run_id uuid NOT NULL,
        account_id uuid NOT NULL,
        job_id uuid NOT NULL,
        subject_id uuid NOT NULL,
        revision bigint NOT NULL,
        kind text NOT NULL,
        artifact_key text NOT NULL,
        artifact_sha256 text NOT NULL,
        byte_size bigint NOT NULL,
        media_type text NOT NULL,
        original_key text,
        source_url text,
        observed_at timestamptz NOT NULL,
        ledger_id uuid REFERENCES provider_call_ledger(ledger_id),
        operation_id uuid REFERENCES arv2_research_operation(operation_id),
        origin_locator text NOT NULL,
        normalizer_version text NOT NULL,
        metadata jsonb NOT NULL DEFAULT '{}',
        CONSTRAINT arv2_evidence_source_scope UNIQUE(source_id,workspace_id),
        CONSTRAINT arv2_evidence_source_sequence UNIQUE(workspace_id,run_id,account_id,revision),
        CONSTRAINT arv2_evidence_source_job FOREIGN KEY(job_id,workspace_id,run_id,account_id)
          REFERENCES arv2_research_job(job_id,workspace_id,run_id,account_entity_id),
        CONSTRAINT arv2_evidence_source_manifest FOREIGN KEY(workspace_id,run_id,account_id)
          REFERENCES arv2_evidence_manifest(workspace_id,run_id,account_id),
        CONSTRAINT arv2_evidence_source_artifact FOREIGN KEY(artifact_key,workspace_id)
          REFERENCES artifact(storage_key,workspace_id),
        CONSTRAINT arv2_evidence_source_original FOREIGN KEY(original_key,workspace_id)
          REFERENCES artifact(storage_key,workspace_id),
        CONSTRAINT arv2_evidence_source_kind CHECK(kind IN
          ('web_snapshot','provider_record','research_report','transcript','seller_document','acquisition_gap')),
        CONSTRAINT arv2_evidence_source_sha CHECK(artifact_sha256 ~ '^[0-9a-f]{64}$'),
        CONSTRAINT arv2_evidence_source_size CHECK(byte_size>=0),
        CONSTRAINT arv2_evidence_source_revision CHECK(revision>0)
      )
    """)
    op.execute(
        "CREATE INDEX arv2_evidence_source_job_index ON "
        "arv2_evidence_source(workspace_id,job_id,revision)"
    )
    op.execute("""
      CREATE TABLE arv2_evidence_grant (
        grant_id uuid PRIMARY KEY,
        workspace_id text NOT NULL,
        run_id uuid NOT NULL,
        account_id uuid NOT NULL,
        job_id uuid NOT NULL,
        consumer_id uuid NOT NULL,
        revision bigint NOT NULL,
        revoked_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT arv2_evidence_grant_scope UNIQUE(grant_id,workspace_id),
        CONSTRAINT arv2_evidence_grant_job FOREIGN KEY(job_id,workspace_id,run_id,account_id)
          REFERENCES arv2_research_job(job_id,workspace_id,run_id,account_entity_id),
        CONSTRAINT arv2_evidence_grant_revision CHECK(revision>=0)
      )
    """)
    op.execute("""
      CREATE TABLE arv2_evidence_disposition (
        disposition_id uuid PRIMARY KEY,
        grant_id uuid NOT NULL,
        workspace_id text NOT NULL,
        source_id uuid NOT NULL,
        unit_locator text NOT NULL,
        decision text NOT NULL,
        receipt_key text NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT arv2_disposition_grant FOREIGN KEY(grant_id,workspace_id)
          REFERENCES arv2_evidence_grant(grant_id,workspace_id),
        CONSTRAINT arv2_disposition_source FOREIGN KEY(source_id,workspace_id)
          REFERENCES arv2_evidence_source(source_id,workspace_id),
        CONSTRAINT arv2_disposition_artifact FOREIGN KEY(receipt_key,workspace_id)
          REFERENCES artifact(storage_key,workspace_id),
        CONSTRAINT arv2_disposition_decision CHECK(decision IN
          ('written','reused','conflict','excluded','gap','unprocessed'))
      )
    """)


def downgrade() -> None:
    for table in (
        "arv2_evidence_disposition",
        "arv2_evidence_grant",
        "arv2_evidence_source",
        "arv2_evidence_manifest",
    ):
        op.execute("DROP TABLE " + table)
    op.execute("DROP TRIGGER artifact_erase_derivatives ON artifact")
    op.execute("DROP FUNCTION erase_derived_artifacts()")
    op.execute("DROP TABLE artifact_derivation")
    op.execute("ALTER TABLE arv2_research_job DROP CONSTRAINT arv2_job_run_scope")
    op.execute("ALTER TABLE arv2_research_job DROP CONSTRAINT arv2_job_scope")
    op.execute("ALTER TABLE arv2_research_run DROP CONSTRAINT arv2_run_workspace")
