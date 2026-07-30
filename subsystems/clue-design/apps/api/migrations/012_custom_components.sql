-- P6.1 custom-component registry.
--
-- Existing documents are deliberately NOT backfilled: no trustworthy
-- component artifact can be invented from a page node. The tables begin empty
-- and successful compiler output is the only future write source. Re-running
-- the migration is idempotent and leaves development documents byte-identical.

CREATE TABLE IF NOT EXISTS custom_components (
  account_id TEXT NOT NULL,
  slug TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (account_id, slug)
);

CREATE TABLE IF NOT EXISTS custom_component_artifacts (
  artifact_id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL,
  slug TEXT NOT NULL,
  source_digest_algorithm TEXT NOT NULL,
  source_digest_value TEXT NOT NULL,
  source_opaque_ref TEXT NOT NULL,
  source_byte_length INTEGER NOT NULL,
  bundle_digest_algorithm TEXT NOT NULL,
  bundle_digest_value TEXT NOT NULL,
  bundle_opaque_ref TEXT NOT NULL,
  bundle_byte_length INTEGER NOT NULL,
  manifest_json TEXT NOT NULL,
  provenance_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (account_id, slug)
    REFERENCES custom_components(account_id, slug)
);

CREATE INDEX IF NOT EXISTS idx_custom_component_artifacts_account_slug_created
  ON custom_component_artifacts(account_id, slug, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_custom_component_artifacts_source_digest
  ON custom_component_artifacts(source_digest_value);
CREATE INDEX IF NOT EXISTS idx_custom_component_artifacts_bundle_digest
  ON custom_component_artifacts(bundle_digest_value);

-- Artifact rows are immutable. Deletion remains possible for explicit
-- retirement/GC; documents keep their pin and render a safe missing placeholder.
CREATE TRIGGER IF NOT EXISTS custom_component_artifacts_reject_update
BEFORE UPDATE ON custom_component_artifacts
BEGIN
  SELECT RAISE(ABORT, 'custom component artifacts are immutable');
END;
