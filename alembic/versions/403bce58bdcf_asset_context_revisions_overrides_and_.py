"""asset context revisions overrides and enrichment jobs

Revision ID: 403bce58bdcf
Revises: 5cac3234cfb3
Create Date: 2026-09-21 15:36:34.468460+00:00

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
revision: str = "403bce58bdcf"
down_revision: str | None = "5cac3234cfb3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE design_agent_run ADD COLUMN asset_context_snapshot jsonb")
    _ingestion_kind(("website", "pdf", "asset_upload", "ad_assets", "asset_enrichment"))
    op.execute("""
        ALTER TABLE design_asset_description
          ADD COLUMN analysis_json jsonb NOT NULL DEFAULT '{}',
          ADD COLUMN overrides_json jsonb NOT NULL DEFAULT '{}',
          ADD COLUMN analysis_input_json jsonb NOT NULL DEFAULT '{}',
          ADD COLUMN analyzed_input_json jsonb NOT NULL DEFAULT '{}',
          ADD COLUMN input_fingerprint text,
          ADD COLUMN revision integer NOT NULL DEFAULT 0,
          ADD COLUMN analysis_status text NOT NULL DEFAULT 'stale',
          ADD COLUMN analysis_diagnostic_json jsonb,
          ADD COLUMN analysis_job_id text,
          ADD COLUMN analysis_token text,
          ADD CONSTRAINT design_asset_description_revision_check CHECK (revision >= 0),
          ADD CONSTRAINT design_asset_description_status_check CHECK (
            analysis_status IN ('stale', 'queued', 'analyzing', 'ready', 'failed', 'unsupported')),
          ADD CONSTRAINT design_asset_description_analysis_object CHECK (
            jsonb_typeof(analysis_json) = 'object' AND
            jsonb_typeof(overrides_json) = 'object' AND
            jsonb_typeof(analysis_input_json) = 'object')
    """)
    # Legacy human rows protected all four fields; preserve that exact protection.
    op.execute("""
        UPDATE design_asset_description SET overrides_json = jsonb_build_object(
          'title', title, 'description', description, 'usage', usage, 'tags', tags_json)
        WHERE origin = 'human'
    """)
    op.execute("""
        CREATE INDEX design_asset_description_status_idx
        ON design_asset_description (workspace_id, analysis_status)
    """)
    op.execute("""
        CREATE TABLE design_asset_upload_request (
          workspace_id text NOT NULL REFERENCES workspace(workspace_id) ON DELETE CASCADE,
          idempotency_key text NOT NULL,
          request_digest text NOT NULL,
          asset_id text NOT NULL,
          job_id text NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT design_asset_upload_request_pk PRIMARY KEY (workspace_id, idempotency_key),
          CONSTRAINT design_asset_upload_request_asset_fk FOREIGN KEY (asset_id, workspace_id)
            REFERENCES design_asset (asset_id, workspace_id) ON DELETE CASCADE,
          CONSTRAINT design_asset_upload_request_job_fk FOREIGN KEY (job_id, workspace_id)
            REFERENCES design_ingestion_job (job_id, workspace_id) ON DELETE CASCADE,
          CONSTRAINT design_asset_upload_request_key_check CHECK (
            length(idempotency_key) BETWEEN 1 AND 200)
        )
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE design_agent_run DROP COLUMN asset_context_snapshot")
    # Live enrichment jobs must be resolved/removed before removing their enum value.
    _ingestion_kind(("website", "pdf", "asset_upload", "ad_assets"))
    op.execute("DROP TABLE design_asset_upload_request")
    op.execute("DROP INDEX design_asset_description_status_idx")
    op.execute("""
        ALTER TABLE design_asset_description
          DROP CONSTRAINT design_asset_description_revision_check,
          DROP CONSTRAINT design_asset_description_status_check,
          DROP CONSTRAINT design_asset_description_analysis_object,
          DROP COLUMN analysis_json, DROP COLUMN overrides_json,
          DROP COLUMN analysis_input_json, DROP COLUMN analyzed_input_json,
          DROP COLUMN input_fingerprint,
          DROP COLUMN revision, DROP COLUMN analysis_status,
          DROP COLUMN analysis_diagnostic_json, DROP COLUMN analysis_job_id,
          DROP COLUMN analysis_token
    """)


def _ingestion_kind(values: tuple[str, ...]) -> None:
    labels = ", ".join(f"'{value}'" for value in values)
    op.execute("ALTER TYPE design_ingestion_kind RENAME TO design_ingestion_kind_old")
    op.execute(f"CREATE TYPE design_ingestion_kind AS ENUM ({labels})")
    op.execute("""
        ALTER TABLE design_ingestion_job ALTER COLUMN kind TYPE design_ingestion_kind
        USING kind::text::design_ingestion_kind
    """)
    op.execute("DROP TYPE design_ingestion_kind_old")
