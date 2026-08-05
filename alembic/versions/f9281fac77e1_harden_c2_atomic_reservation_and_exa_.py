"""harden c2 atomic reservation and exa lineage

Revision ID: f9281fac77e1
Revises: 26eaa6262063
Create Date: 2026-08-05 06:56:37.836623+00:00

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
revision: str = "f9281fac77e1"
down_revision: str | None = "26eaa6262063"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _claim_lineage_validator(*, require_complete: bool) -> str:
    lineage_missing = (
        """
            IF NEW.source_operation_ref IS NULL
               OR NEW.source_snapshot_ref IS NULL
               OR NEW.source_request_ref IS NULL
               OR NEW.artifact_key IS NULL THEN
                RAISE EXCEPTION
                    'exa_deep claims require complete operation, snapshot, request, and result '
                    'artifact lineage';
            END IF;
"""
        if require_complete
        else ""
    )
    lineage_guard = "TRUE" if require_complete else "NEW.source_operation_ref IS NOT NULL"
    return f"""
        CREATE OR REPLACE FUNCTION claim_validate_external_research_lineage() RETURNS trigger AS $$
        BEGIN
            IF NEW.source_key = 'exa_deep' THEN
                {lineage_missing}
                IF {lineage_guard}
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
                      AND (
                          (snapshot.subject_kind='account' AND snapshot.account_id=NEW.entity_id)
                          OR
                          (snapshot.subject_kind='contact' AND snapshot.contact_id=NEW.entity_id)
                      )
                      AND snapshot.source_key=NEW.source_key
                      AND result.artifact_key=NEW.artifact_key
                      AND (NEW.workspace_id IS NULL OR snapshot.workspace_id=NEW.workspace_id)
                ) THEN
                    RAISE EXCEPTION
                        'claim external research lineage does not match snapshot/result evidence';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """


def upgrade() -> None:
    # Invalid legacy rows cannot be repaired without inventing provider lineage. Fail the migration
    # explicitly instead of preserving an Exa claim that bypasses the exact-subject ledger.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM claim
                WHERE source_key='exa_deep'
                  AND (source_operation_ref IS NULL
                       OR source_snapshot_ref IS NULL
                       OR source_request_ref IS NULL
                       OR artifact_key IS NULL)
            ) THEN
                RAISE EXCEPTION
                    'existing exa_deep claim lacks complete external-research lineage';
            END IF;
        END;
        $$
        """
    )
    op.execute(
        "ALTER TABLE claim ADD CONSTRAINT claim_exa_deep_lineage_required CHECK ("
        "source_key IS DISTINCT FROM 'exa_deep' OR ("
        "source_operation_ref IS NOT NULL AND source_snapshot_ref IS NOT NULL "
        "AND source_request_ref IS NOT NULL AND artifact_key IS NOT NULL))"
    )
    op.execute(_claim_lineage_validator(require_complete=True))


def downgrade() -> None:
    # Restore C2's exact account/contact validator while returning to its former optional-lineage
    # behavior. The existing trigger resolves this replaced function automatically.
    op.execute(_claim_lineage_validator(require_complete=False))
    op.execute("ALTER TABLE claim DROP CONSTRAINT claim_exa_deep_lineage_required")
