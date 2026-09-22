"""arv2 committee discovery references and provider identities

Revision ID: 0ab01fe27c1e
Revises: 7c4fe6965720
Create Date: 2026-09-22 10:35:23.904278+00:00

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
revision: str = "0ab01fe27c1e"
down_revision: str | None = "7c4fe6965720"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE arv2_research_run ADD COLUMN persona_pin jsonb")
    op.execute("ALTER TABLE arv2_research_job ADD COLUMN profile_ref text")
    op.execute(
        "ALTER TABLE arv2_research_job ADD COLUMN input_refs jsonb NOT NULL DEFAULT '{}'::jsonb"
    )
    op.execute("ALTER TABLE arv2_research_job ADD COLUMN selection_claim_ids uuid[]")
    op.execute("ALTER TABLE artifact ADD COLUMN privacy_erased boolean NOT NULL DEFAULT false")
    op.execute("ALTER TABLE artifact ADD COLUMN expires_at timestamptz")
    op.execute("""
        CREATE TABLE arv2_research_operation (
            operation_id uuid PRIMARY KEY,
            workspace_id text NOT NULL,
            run_id uuid NOT NULL REFERENCES arv2_research_run(run_id),
            job_id uuid NOT NULL REFERENCES arv2_research_job(job_id),
            account_id uuid NOT NULL REFERENCES account_entity(id),
            kind text NOT NULL,
            request_sha256 text NOT NULL,
            state text NOT NULL DEFAULT 'running',
            owner_token uuid NOT NULL,
            lease_until timestamptz NOT NULL,
            ledger_id uuid REFERENCES provider_call_ledger(ledger_id),
            artifact_key text REFERENCES artifact(storage_key),
            error_code text,
            created_at timestamptz NOT NULL DEFAULT now(),
            finished_at timestamptz,
            CONSTRAINT arv2_research_operation_state CHECK
              (state IN ('running','succeeded','empty','failed','unknown')),
            CONSTRAINT arv2_research_operation_once UNIQUE (workspace_id,job_id,kind,request_sha256)
        )
    """)
    op.execute("""
        CREATE TABLE provider_identity (
            workspace_id text NOT NULL,
            provider text NOT NULL,
            subject_id text NOT NULL,
            contact_id uuid REFERENCES contact_entity(id),
            evidence_artifact_key text REFERENCES artifact(storage_key),
            erased_at timestamptz,
            CONSTRAINT provider_identity_pk PRIMARY KEY(workspace_id,provider,subject_id)
        )
    """)
    op.execute(
        "CREATE INDEX provider_identity_contact ON provider_identity(workspace_id,contact_id)"
    )
    op.execute("""
        CREATE TABLE provider_artifact_subject (
            workspace_id text NOT NULL,
            provider text NOT NULL,
            subject_id text NOT NULL,
            artifact_key text NOT NULL REFERENCES artifact(storage_key),
            linkedin_url text,
            expires_at timestamptz NOT NULL DEFAULT (now() + interval '30 days'),
            CONSTRAINT provider_artifact_subject_pk PRIMARY KEY
              (workspace_id,provider,subject_id,artifact_key)
        )
    """)
    op.execute(
        "CREATE INDEX provider_artifact_subject_linkedin ON "
        "provider_artifact_subject(workspace_id,linkedin_url)"
    )

    # Keep the account-side selection evidence separate from operational receipts and erasable.
    op.execute("""
        CREATE TABLE provider_selection_claim (
            workspace_id text NOT NULL,
            provider text NOT NULL,
            subject_id text NOT NULL,
            claim_id uuid NOT NULL REFERENCES claim(id),
            CONSTRAINT provider_selection_claim_pk PRIMARY KEY (claim_id)
        )
    """)


def downgrade() -> None:
    op.drop_table("provider_selection_claim")
    op.drop_table("provider_artifact_subject")
    op.drop_table("provider_identity")
    op.drop_table("arv2_research_operation")
    op.drop_column("artifact", "expires_at")
    op.drop_column("artifact", "privacy_erased")
    op.drop_column("arv2_research_job", "selection_claim_ids")
    op.drop_column("arv2_research_job", "input_refs")
    op.drop_column("arv2_research_job", "profile_ref")
    op.drop_column("arv2_research_run", "persona_pin")
