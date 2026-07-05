-- Asset description store (brandkit ingestion v1 slice 3). Persists AI- and
-- human-authored library metadata (title/description/usage/tags) per asset.
-- run_migrations re-runs this on every startup; IF NOT EXISTS keeps it
-- idempotent and preserves existing rows.
CREATE TABLE IF NOT EXISTS asset_descriptions (
    asset_id TEXT PRIMARY KEY,
    title TEXT,
    description TEXT,
    usage TEXT,
    tags_json TEXT NOT NULL DEFAULT '[]',
    origin TEXT NOT NULL CHECK (origin IN ('ai', 'human')),
    model TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
