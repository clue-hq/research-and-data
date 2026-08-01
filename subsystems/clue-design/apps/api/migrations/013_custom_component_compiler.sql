-- P6.2 durable source revisions and compile-attempt ledger.
--
-- The migration runner is intentionally replayable, so schema additions to
-- existing P6.1 tables are installed through database.ensure_column. The new
-- tables and indexes below are idempotent. Existing component families remain
-- at source_version=0 with no invented source snapshot.

CREATE TABLE IF NOT EXISTS custom_component_source_revisions (
  revision_id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL,
  slug TEXT NOT NULL,
  source_version INTEGER NOT NULL CHECK (source_version > 0),
  entry_path TEXT NOT NULL,
  snapshot_digest_algorithm TEXT NOT NULL,
  snapshot_digest_value TEXT NOT NULL,
  snapshot_opaque_ref TEXT NOT NULL,
  snapshot_byte_length INTEGER NOT NULL CHECK (snapshot_byte_length > 0),
  files_manifest_json TEXT NOT NULL,
  provenance_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (account_id, slug, source_version),
  FOREIGN KEY (account_id, slug)
    REFERENCES custom_components(account_id, slug)
);

CREATE INDEX IF NOT EXISTS idx_custom_component_sources_account_slug_version
  ON custom_component_source_revisions(account_id, slug, source_version DESC);
CREATE INDEX IF NOT EXISTS idx_custom_component_sources_snapshot_digest
  ON custom_component_source_revisions(snapshot_digest_value);

CREATE TABLE IF NOT EXISTS custom_component_compilations (
  compilation_id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL,
  slug TEXT NOT NULL,
  source_revision_id TEXT NOT NULL,
  source_version INTEGER NOT NULL CHECK (source_version > 0),
  status TEXT NOT NULL CHECK (
    status IN ('succeeded', 'failed', 'transient_error')
  ),
  compiler_protocol_version INTEGER NOT NULL,
  compiler_version TEXT NOT NULL,
  diagnostics_json TEXT NOT NULL,
  artifact_id TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (source_revision_id)
    REFERENCES custom_component_source_revisions(revision_id)
);

CREATE INDEX IF NOT EXISTS idx_custom_component_compiles_account_slug_created
  ON custom_component_compilations(account_id, slug, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_custom_component_compiles_source_revision
  ON custom_component_compilations(source_revision_id, created_at DESC);

CREATE TRIGGER IF NOT EXISTS custom_component_sources_reject_update
BEFORE UPDATE ON custom_component_source_revisions
BEGIN
  SELECT RAISE(ABORT, 'custom component source revisions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS custom_component_compilations_reject_update
BEFORE UPDATE ON custom_component_compilations
BEGIN
  SELECT RAISE(ABORT, 'custom component compilations are immutable');
END;
