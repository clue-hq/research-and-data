"""m8c c1 enforce sumble professional lineage

Revision ID: 26eaa6262063
Revises: 9e3afe93b8e1
Create Date: 2026-08-05 06:14:32.103404+00:00

Add typed assertion provenance to the claim substrate and prove every Sumble professional claim
against its exact ready operation, succeeded source snapshot, response artifact, project run,
workspace, account, and admitted contact. Opaque application strings are no longer authority.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "26eaa6262063"
down_revision: str | None = "9e3afe93b8e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PREVIOUS_IMMUTABLE = (
    "id",
    "entity_id",
    "entity_type",
    "field_key",
    "value_json",
    "source_url",
    "source_tier",
    "extraction_method",
    "evidence_span",
    "confidence",
    "observed_at",
    "collected_at",
    "cost_cents",
    "run_id",
    "research_mode",
    "identity_binding",
    "use_class",
    "discovery_provenance",
    "claim_flavor",
    "workspace_id",
    "reuse_scope",
    "source_key",
    "artifact_key",
    "product_id",
    "source_operation_ref",
    "source_snapshot_ref",
    "source_request_ref",
)
_NEW_IMMUTABLE = (*_PREVIOUS_IMMUTABLE, "provenance_kind")
_MUTABLE = ("superseded_by", "verification_status", "corroborations")

_SUMBLE_SOURCES_SQL = "('sumble_people', 'sumble_teams')"
_PROFESSIONAL_FIELDS_SQL = (
    "('contact.current_title', 'contact.job_function', 'contact.job_level', "
    "'contact.team_membership', 'contact.current_location', "
    "'contact.organization_relationship')"
)


def _claim_guard(columns: tuple[str, ...]) -> str:
    guard = " OR ".join(f"NEW.{column} IS DISTINCT FROM OLD.{column}" for column in columns)
    allowed = ", ".join(_MUTABLE)
    return f"""
        CREATE OR REPLACE FUNCTION claim_reject_immutable_update() RETURNS trigger AS $$
        BEGIN
            IF {guard} THEN
                RAISE EXCEPTION
                    'claim is append-only: only ({allowed}) may be updated; an immutable '
                    'provenance column was modified. Supersede by inserting a new claim.';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """


def _lineage_match(alias: str, *, require_live_evidence: bool = True) -> str:
    evidence_liveness = (
        "AND evidence.erased_at IS NULL AND subject_evidence.tombstoned_at IS NULL"
        if require_live_evidence
        else ""
    )
    return f"""
        EXISTS (
            SELECT 1
            FROM committee_acquisition_operation operation
            JOIN committee_acquisition_snapshot snapshot
              ON snapshot.operation_id=operation.id
             AND snapshot.workspace_id=operation.workspace_id
            JOIN contact_entity contact
              ON contact.id={alias}.entity_id
             AND contact.workspace_id=operation.workspace_id
             AND contact.account_entity_id=operation.account_id
            JOIN project_run run
              ON run.id=operation.project_run_id
             AND run.workspace_id=operation.workspace_id
             AND run.project_id=operation.project_id
            JOIN artifact evidence
              ON evidence.storage_key=snapshot.response_artifact_key
             AND evidence.workspace_id=snapshot.workspace_id
            JOIN discovery_artifact_subject subject_evidence
              ON subject_evidence.artifact_key=snapshot.response_artifact_key
             AND subject_evidence.workspace_id=snapshot.workspace_id
             AND subject_evidence.subject_kind='account'
             AND subject_evidence.subject_entity_id=operation.account_id
            WHERE operation.state='ready'
              AND snapshot.state='succeeded'
              AND snapshot.source_key={alias}.source_key
              AND snapshot.response_artifact_key={alias}.artifact_key
              AND {alias}.workspace_id=operation.workspace_id
              AND {alias}.run_id=operation.project_run_id
              AND ({alias}.product_id IS NULL OR {alias}.product_id=run.product_id)
              AND {alias}.source_operation_ref=
                  'committee-operation:' || operation.id::text
              AND {alias}.source_snapshot_ref=
                  'committee-snapshot:' || operation.id::text || ':' ||
                  snapshot.source_key || ':' || snapshot.request_fingerprint
              AND {alias}.source_request_ref=
                  'committee-request:' || snapshot.source_key || ':' ||
                  snapshot.request_fingerprint
              {evidence_liveness}
        )
    """


def _lineage_function() -> str:
    return f"""
        CREATE FUNCTION claim_validate_sumble_professional_lineage() RETURNS trigger AS $$
        BEGIN
            IF NEW.source_key IN {_SUMBLE_SOURCES_SQL}
               AND NEW.field_key IN {_PROFESSIONAL_FIELDS_SQL}
               AND NOT {_lineage_match("NEW")} THEN
                RAISE EXCEPTION
                    'Sumble professional claim lineage does not match its exact ready '
                    'operation, snapshot, artifact, run, account, and contact';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """


def upgrade() -> None:
    op.execute(
        "CREATE TYPE claim_provenance_kind AS ENUM ("
        "'provider_returned', 'provider_modeled', 'platform_inferred', 'human_asserted')"
    )
    op.execute("ALTER TABLE claim ADD COLUMN provenance_kind claim_provenance_kind")

    # Existing C1 rows were already immutable-snapshot-backed in application code. Give their
    # literal/modeled distinction a typed home before validating exact durable lineage.
    op.execute(
        "UPDATE claim SET provenance_kind=CASE "
        "WHEN field_key='contact.team_membership' "
        "THEN 'provider_modeled'::claim_provenance_kind "
        "ELSE 'provider_returned'::claim_provenance_kind END "
        f"WHERE source_key IN {_SUMBLE_SOURCES_SQL} "
        f"AND field_key IN {_PROFESSIONAL_FIELDS_SQL} AND provenance_kind IS NULL"
    )
    op.execute(
        "UPDATE claim SET provenance_kind='platform_inferred'::claim_provenance_kind "
        "WHERE research_mode='committee_discovery' "
        "AND field_key IN ('contact.role_on_committee', 'contact.persona') "
        "AND provenance_kind IS NULL"
    )

    op.execute(
        "ALTER TABLE claim ADD CONSTRAINT claim_sumble_professional_shape CHECK ("
        f"source_key NOT IN {_SUMBLE_SOURCES_SQL} "
        f"OR field_key NOT IN {_PROFESSIONAL_FIELDS_SQL} OR ("
        "entity_type='contact' AND claim_flavor='field_claim' "
        "AND source_tier=1 AND extraction_method='api' "
        "AND research_mode='committee_discovery' "
        "AND identity_binding='strong' AND use_class='professional-public' "
        "AND reuse_scope='tenant_private' AND workspace_id IS NOT NULL "
        "AND cost_cents=0 AND source_operation_ref IS NOT NULL "
        "AND source_snapshot_ref IS NOT NULL AND source_request_ref IS NOT NULL "
        "AND ((field_key='contact.team_membership' "
        "AND source_key='sumble_teams' AND provenance_kind='provider_modeled') "
        "OR (field_key<>'contact.team_membership' "
        "AND provenance_kind='provider_returned'))))"
    )

    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM claim candidate
                WHERE candidate.source_key IN {_SUMBLE_SOURCES_SQL}
                  AND candidate.field_key IN {_PROFESSIONAL_FIELDS_SQL}
                  AND NOT {_lineage_match("candidate", require_live_evidence=False)}
            ) THEN
                RAISE EXCEPTION 'existing Sumble professional claim has invalid lineage';
            END IF;
        END;
        $$
        """
    )
    op.execute(_lineage_function())
    op.execute(
        "CREATE TRIGGER claim_sumble_professional_lineage_validate BEFORE INSERT OR UPDATE OF "
        "entity_id, entity_type, field_key, source_key, artifact_key, source_operation_ref, "
        "source_snapshot_ref, source_request_ref, run_id, workspace_id, product_id ON claim "
        "FOR EACH ROW EXECUTE FUNCTION claim_validate_sumble_professional_lineage()"
    )
    op.execute(_claim_guard(_NEW_IMMUTABLE))


def downgrade() -> None:
    op.execute(_claim_guard(_PREVIOUS_IMMUTABLE))
    op.execute("DROP TRIGGER claim_sumble_professional_lineage_validate ON claim")
    op.execute("DROP FUNCTION claim_validate_sumble_professional_lineage()")
    op.execute("ALTER TABLE claim DROP CONSTRAINT claim_sumble_professional_shape")
    op.execute("ALTER TABLE claim DROP COLUMN provenance_kind")
    op.execute("DROP TYPE claim_provenance_kind")
