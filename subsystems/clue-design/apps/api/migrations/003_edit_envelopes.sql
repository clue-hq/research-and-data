-- Edit envelopes: the history unit around canonical operation batches.
-- Replay reads operation_log only; envelopes carry intent, checkpoint,
-- actor, touched targets, base revision, and the inverse batch computed
-- at apply time. Migrations run on every startup, so everything here is
-- idempotent. Backfill of pre-envelope operation rows happens in
-- database.run_migrations after operation_log.batch_id is ensured.
CREATE TABLE IF NOT EXISTS edit_envelopes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id TEXT NOT NULL UNIQUE,
  document_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  envelope_version INTEGER NOT NULL DEFAULT 1,
  base_revision INTEGER,
  actor_kind TEXT NOT NULL,
  actor_id TEXT,
  source TEXT NOT NULL,
  intent TEXT,
  checkpoint_label TEXT,
  touched_targets_json TEXT NOT NULL DEFAULT '[]',
  operations_json TEXT NOT NULL,
  inverse_operations_json TEXT,
  lineage_json TEXT,
  reverts_batch_id TEXT,
  reapplies_batch_id TEXT,
  created_at TEXT NOT NULL,
  UNIQUE (document_id, seq),
  FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_edit_envelopes_document
  ON edit_envelopes (document_id, seq DESC);
