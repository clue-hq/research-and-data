-- P6.5 immutable publish packages. The mutable slug row remains the public
-- pointer; every payload it references is append-only and content identified.
CREATE TABLE IF NOT EXISTS web_publish_revisions (
  publish_id TEXT PRIMARY KEY,
  slug TEXT NOT NULL,
  document_id TEXT NOT NULL,
  doc_version INTEGER NOT NULL,
  html TEXT NOT NULL,
  html_digest TEXT NOT NULL,
  manifest_json TEXT NOT NULL,
  manifest_digest TEXT NOT NULL,
  package_digest TEXT NOT NULL,
  runtime_version INTEGER,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_web_publish_revisions_slug_created
  ON web_publish_revisions(slug, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_web_publish_revisions_document_created
  ON web_publish_revisions(document_id, created_at DESC);

CREATE TRIGGER IF NOT EXISTS web_publish_revisions_reject_update
BEFORE UPDATE ON web_publish_revisions
BEGIN
  SELECT RAISE(ABORT, 'web publish revisions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS web_publish_revisions_reject_delete
BEFORE DELETE ON web_publish_revisions
BEGIN
  SELECT RAISE(ABORT, 'web publish revisions are immutable');
END;
