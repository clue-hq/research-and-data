"""phase c3 ingestion jobs and segments

Revision ID: 5ab2d13ca389
Revises: b366c985ca12
Create Date: 2026-07-24 11:55:26.766691+00:00

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
revision: str = "5ab2d13ca389"
down_revision: str | None = "b366c985ca12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TYPE ingestion_status AS ENUM
            ('queued', 'snapshotted', 'extracting', 'completed', 'failed', 'erased')
        """
    )
    op.execute(
        """
        CREATE TABLE ingestion_job (
            id                    uuid NOT NULL,
            workspace_id          text NOT NULL,
            brand_id              text NOT NULL,
            product_id            text,
            project_id            text,
            artifact_key          text NOT NULL,
            content_sha256        text NOT NULL,
            declared_context_json jsonb NOT NULL,
            declared_context_hash text NOT NULL,
            media_type            text NOT NULL,
            adapter_key           text NOT NULL,
            status                ingestion_status NOT NULL DEFAULT 'queued',
            failure_code          text,
            failure_detail        text,
            segment_count         integer NOT NULL DEFAULT 0,
            claim_refs_json       jsonb NOT NULL DEFAULT '{}'::jsonb,
            retry_count           integer NOT NULL DEFAULT 0,
            created_by_actor      text NOT NULL,
            created_at            timestamptz NOT NULL DEFAULT now(),
            updated_at            timestamptz NOT NULL DEFAULT now(),
            completed_at          timestamptz,
            erased_at             timestamptz,

            CONSTRAINT ingestion_job_pkey PRIMARY KEY (id),
            CONSTRAINT ingestion_job_artifact_fk FOREIGN KEY (artifact_key)
                REFERENCES artifact (storage_key),
            CONSTRAINT ingestion_job_brand_fk FOREIGN KEY (brand_id, workspace_id)
                REFERENCES brand (brand_id, workspace_id),
            CONSTRAINT ingestion_job_product_fk FOREIGN KEY (product_id, workspace_id)
                REFERENCES product (product_id, workspace_id),
            CONSTRAINT ingestion_job_project_fk FOREIGN KEY (project_id, workspace_id, brand_id)
                REFERENCES project (project_id, workspace_id, brand_id),
            CONSTRAINT ingestion_job_sha_shape
                CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ingestion_job_context_hash_shape
                CHECK (declared_context_hash ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ingestion_job_context_object
                CHECK (jsonb_typeof(declared_context_json) = 'object'),
            CONSTRAINT ingestion_job_refs_object
                CHECK (jsonb_typeof(claim_refs_json) = 'object'),
            CONSTRAINT ingestion_job_counts_nonnegative
                CHECK (segment_count >= 0 AND retry_count >= 0),
            CONSTRAINT ingestion_job_actor
                CHECK (created_by_actor IN ('human', 'agent')),
            CONSTRAINT ingestion_job_failure_shape
                CHECK (
                    (status = 'failed') =
                    (failure_code IS NOT NULL AND failure_detail IS NOT NULL)
                ),
            CONSTRAINT ingestion_job_completed_shape
                CHECK (status <> 'completed' OR completed_at IS NOT NULL),
            CONSTRAINT ingestion_job_erased_shape
                CHECK (status <> 'erased' OR erased_at IS NOT NULL)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE ingestion_job IS 'C3 durable upload ingestion cursor. Idempotent by "
        "(workspace, content hash, canonical declared-context hash); lifecycle is resumable and "
        "raw bodies remain in artifact storage.'"
    )
    op.execute(
        "CREATE INDEX ingestion_job_workspace_status "
        "ON ingestion_job (workspace_id, status, updated_at DESC)"
    )
    op.execute(
        "CREATE UNIQUE INDEX ingestion_job_dedupe "
        "ON ingestion_job (workspace_id, content_sha256, declared_context_hash) "
        "WHERE erased_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ingestion_job_project ON ingestion_job (project_id, updated_at DESC) "
        "WHERE project_id IS NOT NULL AND erased_at IS NULL"
    )

    op.execute(
        """
        CREATE TABLE ingestion_segment (
            id                     uuid NOT NULL,
            ingestion_job_id       uuid NOT NULL,
            ordinal                integer NOT NULL,
            locator_json           jsonb NOT NULL,
            text_sha256            text NOT NULL,
            canonical_artifact_key text NOT NULL,
            created_at             timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT ingestion_segment_pkey PRIMARY KEY (id),
            CONSTRAINT ingestion_segment_job_fk FOREIGN KEY (ingestion_job_id)
                REFERENCES ingestion_job (id) ON DELETE CASCADE,
            CONSTRAINT ingestion_segment_artifact_fk FOREIGN KEY (canonical_artifact_key)
                REFERENCES artifact (storage_key),
            CONSTRAINT ingestion_segment_ordinal_unique
                UNIQUE (ingestion_job_id, ordinal),
            CONSTRAINT ingestion_segment_ordinal_nonnegative CHECK (ordinal >= 0),
            CONSTRAINT ingestion_segment_locator_object
                CHECK (jsonb_typeof(locator_json) = 'object'),
            CONSTRAINT ingestion_segment_sha_shape
                CHECK (text_sha256 ~ '^[0-9a-f]{64}$')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE ingestion_segment IS 'Stable C3 locator into a canonical extracted "
        "artifact. Segment bodies are not duplicated in Postgres.'"
    )
    op.execute(
        "CREATE INDEX ingestion_segment_canonical_artifact "
        "ON ingestion_segment (canonical_artifact_key)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ingestion_segment_canonical_artifact")
    op.execute("DROP TABLE IF EXISTS ingestion_segment")
    op.execute("DROP INDEX IF EXISTS ingestion_job_project")
    op.execute("DROP INDEX IF EXISTS ingestion_job_dedupe")
    op.execute("DROP INDEX IF EXISTS ingestion_job_workspace_status")
    op.execute("DROP TABLE IF EXISTS ingestion_job")
    op.execute("DROP TYPE IF EXISTS ingestion_status")
