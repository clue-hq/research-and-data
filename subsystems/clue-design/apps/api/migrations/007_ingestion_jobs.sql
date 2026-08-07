CREATE TABLE IF NOT EXISTS ingestion_jobs (
    job_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('website', 'pdf', 'asset_upload')),
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    stage TEXT,
    progress REAL NOT NULL DEFAULT 0,
    request_json TEXT NOT NULL,
    evidence_json TEXT,
    brand_kit_id TEXT,
    brand_kit_version INTEGER,
    error_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_status ON ingestion_jobs(status, created_at);

-- Extend the brand_kits.source CHECK to admit ingestion-authored kits
-- ('website', 'pdf', 'asset_upload'). SQLite cannot ALTER a CHECK in place,
-- so we run the 12-step table rebuild. Foreign keys are toggled OFF for the
-- swap so brand_compatibility_reports rows are not cascaded away when the old
-- table is dropped; run_migrations re-runs this script on every startup, and
-- the INSERT ... SELECT preserves all existing rows each time (idempotent).
-- PRAGMA foreign_keys statements take effect here because run_migrations
-- executes each migration via executescript() in autocommit (no open
-- transaction), matching database.py conventions.
PRAGMA foreign_keys = OFF;

CREATE TABLE brand_kits_new (
  brand_kit_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  name TEXT NOT NULL,
  approval_status TEXT,
  product_ready INTEGER NOT NULL DEFAULT 0,
  source TEXT NOT NULL CHECK (
    source IN (
      'manual', 'uploaded', 'generated', 'styles', 'platform_default', 'api',
      'website', 'pdf', 'asset_upload'
    )
  ),
  brand_kit_json TEXT NOT NULL,
  brand_summary_json TEXT NOT NULL,
  diagnostics_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (brand_kit_id, version)
);

INSERT INTO brand_kits_new (
  brand_kit_id, version, name, approval_status, product_ready,
  source, brand_kit_json, brand_summary_json, diagnostics_json,
  created_at, updated_at
)
SELECT
  brand_kit_id, version, name, approval_status, product_ready,
  source, brand_kit_json, brand_summary_json, diagnostics_json,
  created_at, updated_at
FROM brand_kits;

DROP TABLE brand_kits;
ALTER TABLE brand_kits_new RENAME TO brand_kits;

PRAGMA foreign_keys = ON;
