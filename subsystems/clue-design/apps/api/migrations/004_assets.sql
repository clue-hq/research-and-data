-- Phase E: workspace asset library rows. record_json is the canonical
-- AssetRecord (round-trips the Rust contract); the other columns are
-- query projections. Bytes live in the content-addressed store on disk,
-- never in the database.

CREATE TABLE IF NOT EXISTS assets (
  asset_id TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  kind TEXT NOT NULL,
  status TEXT NOT NULL,
  mime_type TEXT,
  digest_algorithm TEXT,
  digest_value TEXT,
  byte_length INTEGER,
  filename TEXT,
  tags_json TEXT NOT NULL,
  record_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_assets_digest ON assets(digest_value);
CREATE INDEX IF NOT EXISTS idx_assets_kind_status ON assets(kind, status);
