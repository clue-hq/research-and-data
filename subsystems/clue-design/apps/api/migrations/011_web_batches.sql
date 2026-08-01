-- Website-mode personalization batches (P5 D5): one row per bulk derive(+publish)
-- run over a set of accounts against a template web document. Mirrors
-- instance_batches — the cursor column is the synchronous-chunked resume seam
-- (a real queue lands here later). manifest_json holds the per-account rows
-- ({account_id, account_name, document_id?, slug?, url?, status, unbound, error?});
-- counts are derived from the manifest on read (not stored). template_doc_version
-- pins the source version for provenance. No FK — a deleted template or account
-- leaves the batch row intact.
CREATE TABLE IF NOT EXISTS web_batches (
  batch_id TEXT PRIMARY KEY,
  template_document_id TEXT NOT NULL,
  template_doc_version INTEGER NOT NULL,
  status TEXT NOT NULL,
  account_ids_json TEXT NOT NULL,
  publish INTEGER NOT NULL DEFAULT 1,
  slug_base TEXT,
  cursor INTEGER NOT NULL DEFAULT 0,
  manifest_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_web_batches_template
  ON web_batches (template_document_id);
