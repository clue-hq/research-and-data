PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  status TEXT NOT NULL,
  current_scene_json TEXT NOT NULL,
  current_version INTEGER NOT NULL DEFAULT 0,
  effective_brand_kit_source TEXT,
  effective_brand_kit_id TEXT,
  effective_brand_kit_version INTEGER,
  brand_kit_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS operation_log (
  document_id TEXT NOT NULL,
  sequence INTEGER NOT NULL,
  operation_json TEXT NOT NULL,
  actor_kind TEXT NOT NULL,
  actor_id TEXT,
  source TEXT NOT NULL CHECK (source IN ('editor', 'agent', 'api', 'system')),
  diagnostics_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (document_id, sequence),
  FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS snapshots (
  snapshot_id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  scene_json TEXT NOT NULL,
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS template_revisions (
  template_revision_id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL,
  source_snapshot_id TEXT,
  version INTEGER NOT NULL,
  scene_json TEXT NOT NULL,
  export_profiles_json TEXT NOT NULL,
  slot_summary_json TEXT NOT NULL,
  brand_ref_json TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
  FOREIGN KEY (source_snapshot_id) REFERENCES snapshots(snapshot_id)
);

CREATE TABLE IF NOT EXISTS asset_metadata (
  asset_id TEXT PRIMARY KEY,
  document_id TEXT,
  kind TEXT NOT NULL,
  filename TEXT,
  source_uri TEXT,
  mime_type TEXT,
  width INTEGER,
  height INTEGER,
  dpi REAL,
  provenance_json TEXT NOT NULL,
  licensing_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS document_diagnostics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  document_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  diagnostics_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
);

