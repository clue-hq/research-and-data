"""claim quality assessments corrections and invalidation

Revision ID: 8822efd6ceae
Revises: aaae5d2e1fa4
Create Date: 2026-09-22 17:54:01.708553+00:00

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
revision: str = "8822efd6ceae"
down_revision: str | None = "aaae5d2e1fa4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
      CREATE TABLE arv2_quality_proposal (
        operation_id uuid PRIMARY KEY,
        workspace_id text NOT NULL,
        job_id uuid NOT NULL REFERENCES arv2_research_job(job_id),
        subject_id uuid NOT NULL,
        proposal_key text NOT NULL,
        request_sha256 text NOT NULL,
        claim_id uuid REFERENCES claim(id),
        status text NOT NULL,
        error_code text,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT arv2_quality_proposal_artifact FOREIGN KEY(proposal_key,workspace_id)
          REFERENCES artifact(storage_key,workspace_id),
        CONSTRAINT arv2_quality_proposal_status CHECK(status IN
          ('supported','qualified','unresolved','invalid','refused')),
        CONSTRAINT arv2_quality_proposal_sha CHECK(request_sha256 ~ '^[0-9a-f]{64}$')
      )
    """)
    op.execute("ALTER TABLE claim ADD CONSTRAINT claim_quality_scope UNIQUE(id,workspace_id)")
    op.execute("""
      CREATE TABLE claim_quality_assessment (
        assessment_id uuid PRIMARY KEY,
        claim_id uuid NOT NULL,
        workspace_id text NOT NULL,
        revision integer NOT NULL,
        conclusion text NOT NULL,
        rationale_key text NOT NULL,
        actor_ref text NOT NULL,
        policy_version text NOT NULL,
        context_id uuid,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT claim_quality_assessment_scope UNIQUE(assessment_id,workspace_id),
        CONSTRAINT claim_quality_assessment_sequence UNIQUE(claim_id,revision),
        CONSTRAINT claim_quality_assessment_claim FOREIGN KEY(claim_id,workspace_id)
          REFERENCES claim(id,workspace_id),
        CONSTRAINT claim_quality_assessment_rationale FOREIGN KEY(rationale_key,workspace_id)
          REFERENCES artifact(storage_key,workspace_id),
        CONSTRAINT claim_quality_assessment_revision CHECK(revision>0),
        CONSTRAINT claim_quality_assessment_conclusion CHECK(conclusion IN
          ('supported','qualified','unresolved','invalid'))
      )
    """)
    op.execute("""
      CREATE VIEW claim_quality_current AS
      SELECT DISTINCT ON (claim_id) * FROM claim_quality_assessment ORDER BY claim_id,revision DESC
    """)
    op.execute("""
      CREATE TABLE claim_quality_support (
        assessment_id uuid NOT NULL,
        workspace_id text NOT NULL,
        ordinal integer NOT NULL,
        artifact_key text NOT NULL,
        CONSTRAINT claim_quality_support_pk PRIMARY KEY(assessment_id,ordinal),
        CONSTRAINT claim_quality_support_assessment FOREIGN KEY(assessment_id,workspace_id)
          REFERENCES claim_quality_assessment(assessment_id,workspace_id),
        CONSTRAINT claim_quality_support_artifact FOREIGN KEY(artifact_key,workspace_id)
          REFERENCES artifact(storage_key,workspace_id)
      )
    """)
    op.execute(
        "CREATE INDEX claim_quality_support_artifact_index ON claim_quality_support(artifact_key)"
    )
    op.execute("""
      CREATE TABLE claim_quality_operation (
        operation_id uuid PRIMARY KEY,
        workspace_id text NOT NULL,
        claim_id uuid NOT NULL,
        replacement_id uuid,
        assessment_id uuid NOT NULL,
        request_sha256 text NOT NULL,
        kind text NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT claim_quality_operation_claim FOREIGN KEY(claim_id,workspace_id)
          REFERENCES claim(id,workspace_id),
        CONSTRAINT claim_quality_operation_replacement FOREIGN KEY(replacement_id,workspace_id)
          REFERENCES claim(id,workspace_id),
        CONSTRAINT claim_quality_operation_assessment FOREIGN KEY(assessment_id,workspace_id)
          REFERENCES claim_quality_assessment(assessment_id,workspace_id),
        CONSTRAINT claim_quality_operation_digest CHECK(request_sha256 ~ '^[0-9a-f]{64}$'),
        CONSTRAINT claim_quality_operation_kind
          CHECK(kind IN ('assessment','withdrawal','correction','conflict'))
      )
    """)
    op.execute("""
      CREATE TABLE claim_dependency_revision (
        workspace_id text NOT NULL REFERENCES workspace(workspace_id),
        entity_id uuid NOT NULL,
        revision bigint NOT NULL DEFAULT 0,
        CONSTRAINT claim_dependency_revision_pk PRIMARY KEY(workspace_id,entity_id),
        CONSTRAINT claim_dependency_revision_nonnegative CHECK(revision>=0)
      )
    """)
    op.execute("""
      CREATE TABLE claim_quality_event (
        event_id uuid PRIMARY KEY,
        workspace_id text NOT NULL,
        entity_id uuid NOT NULL,
        claim_id uuid NOT NULL,
        revision bigint NOT NULL,
        delivered_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT claim_quality_event_claim FOREIGN KEY(claim_id,workspace_id)
          REFERENCES claim(id,workspace_id),
        CONSTRAINT claim_quality_event_revision UNIQUE(workspace_id,entity_id,revision)
      )
    """)
    op.execute(
        "CREATE INDEX claim_quality_event_pending ON claim_quality_event(created_at,event_id) "
        "WHERE delivered_at IS NULL"
    )
    op.execute("""
      CREATE FUNCTION reject_claim_quality_history_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN RAISE EXCEPTION 'claim quality history is append-only'; END $$
    """)
    for table in (
        "claim_quality_assessment",
        "claim_quality_support",
        "claim_quality_operation",
        "arv2_quality_proposal",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_claim_quality_history_mutation()"
        )


def downgrade() -> None:
    op.execute("DROP TABLE arv2_quality_proposal")
    for table in ("claim_quality_operation", "claim_quality_support"):
        op.execute("DROP TABLE " + table)
    op.execute("DROP VIEW claim_quality_current")
    op.execute("DROP TABLE claim_quality_assessment")
    op.execute("DROP FUNCTION reject_claim_quality_history_mutation()")
    op.execute("DROP TABLE claim_quality_event")
    op.execute("DROP TABLE claim_dependency_revision")
    op.execute("ALTER TABLE claim DROP CONSTRAINT claim_quality_scope")
