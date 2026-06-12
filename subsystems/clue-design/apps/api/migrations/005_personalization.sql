-- Phase G personalization runtime (slice G8).
--
-- Instances are derived artifacts: pure functions of (revision snapshot,
-- binding set, asset store). Rows cache the derived scene for readback and
-- export, but re-derivation always reproduces them — never op-log replay.
-- instance_batches is the synchronous-chunked job seam: the cursor column
-- is where a real queue lands later.

CREATE TABLE IF NOT EXISTS binding_sets (
  binding_set_id TEXT PRIMARY KEY,
  template_revision_id TEXT NOT NULL,
  binding_json TEXT NOT NULL,
  status TEXT NOT NULL,
  diagnostics_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_binding_sets_revision
  ON binding_sets (template_revision_id);

CREATE TABLE IF NOT EXISTS instances (
  instance_id TEXT PRIMARY KEY,
  template_revision_id TEXT NOT NULL,
  binding_set_id TEXT NOT NULL,
  batch_id TEXT,
  status TEXT NOT NULL,
  fit_status TEXT NOT NULL,
  derived_scene_json TEXT NOT NULL,
  diagnostics_json TEXT NOT NULL,
  audit_json TEXT NOT NULL,
  fit_report_json TEXT NOT NULL,
  artifacts_json TEXT NOT NULL,
  generated_assets_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_instances_revision
  ON instances (template_revision_id);
CREATE INDEX IF NOT EXISTS idx_instances_binding
  ON instances (binding_set_id);
CREATE INDEX IF NOT EXISTS idx_instances_batch
  ON instances (batch_id);

CREATE TABLE IF NOT EXISTS instance_batches (
  batch_id TEXT PRIMARY KEY,
  template_revision_id TEXT NOT NULL,
  status TEXT NOT NULL,
  binding_set_ids_json TEXT NOT NULL,
  export_formats_json TEXT NOT NULL,
  chunk_size INTEGER NOT NULL,
  cursor INTEGER NOT NULL,
  counts_json TEXT NOT NULL,
  manifest_json TEXT NOT NULL,
  diagnostics_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_instance_batches_revision
  ON instance_batches (template_revision_id);

CREATE TABLE IF NOT EXISTS repair_queue (
  repair_id TEXT PRIMARY KEY,
  template_revision_id TEXT NOT NULL,
  slot_key TEXT NOT NULL,
  node_id TEXT NOT NULL,
  binding_set_id TEXT NOT NULL,
  instance_id TEXT,
  reason TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_repair_queue_revision
  ON repair_queue (template_revision_id);
