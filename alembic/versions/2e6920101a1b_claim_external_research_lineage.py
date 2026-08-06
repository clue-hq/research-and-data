"""claim external research lineage

Revision ID: 2e6920101a1b
Revises: bc0612c57713
Create Date: 2026-08-04 09:58:58.886799+00:00

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
revision: str = "2e6920101a1b"
down_revision: str | None = "bc0612c57713"
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
)
_NEW_IMMUTABLE = (
    *_PREVIOUS_IMMUTABLE,
    "source_operation_ref",
    "source_snapshot_ref",
    "source_request_ref",
)
_MUTABLE = ("superseded_by", "verification_status", "corroborations")


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


def upgrade() -> None:
    op.execute("ALTER TABLE claim ADD COLUMN source_operation_ref text")
    op.execute("ALTER TABLE claim ADD COLUMN source_snapshot_ref text")
    op.execute("ALTER TABLE claim ADD COLUMN source_request_ref text")
    op.execute(
        "ALTER TABLE claim ADD CONSTRAINT claim_external_research_lineage_shape CHECK ("
        "(source_operation_ref IS NULL AND source_snapshot_ref IS NULL "
        " AND source_request_ref IS NULL) OR "
        "(source_operation_ref IS NOT NULL AND source_snapshot_ref IS NOT NULL "
        " AND source_request_ref IS NOT NULL "
        " AND length(btrim(source_operation_ref)) > 0 "
        " AND length(btrim(source_snapshot_ref)) > 0 "
        " AND length(btrim(source_request_ref)) > 0 AND artifact_key IS NOT NULL))"
    )
    op.execute(
        "CREATE INDEX claim_source_operation_ref_idx ON claim (source_operation_ref) "
        "WHERE source_operation_ref IS NOT NULL"
    )
    op.execute(_claim_guard(_NEW_IMMUTABLE))


def downgrade() -> None:
    op.execute(_claim_guard(_PREVIOUS_IMMUTABLE))
    op.execute("DROP INDEX claim_source_operation_ref_idx")
    op.execute("ALTER TABLE claim DROP CONSTRAINT claim_external_research_lineage_shape")
    op.execute("ALTER TABLE claim DROP COLUMN source_request_ref")
    op.execute("ALTER TABLE claim DROP COLUMN source_snapshot_ref")
    op.execute("ALTER TABLE claim DROP COLUMN source_operation_ref")
