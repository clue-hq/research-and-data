-- Website-mode publish store: one row per public slug. The current html is
-- served at GET /p/{slug}; a republish moves the current html/doc_version into
-- previous_* (a single-step rollback buffer). status flips to 'unpublished' on
-- DELETE and back to 'active' on rollback/republish. slug is the primary key;
-- a slug is owned by exactly one document_id (the endpoint 409s a cross-doc
-- reuse).
CREATE TABLE IF NOT EXISTS web_publishes (
  slug TEXT PRIMARY KEY,
  document_id TEXT NOT NULL,
  doc_version INTEGER NOT NULL,
  html TEXT NOT NULL,
  previous_html TEXT,
  previous_doc_version INTEGER,
  runtime_version INTEGER,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT,
  updated_at TEXT
);
