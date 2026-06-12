CREATE TABLE IF NOT EXISTS brand_kits (
  brand_kit_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  name TEXT NOT NULL,
  approval_status TEXT,
  product_ready INTEGER NOT NULL DEFAULT 0,
  source TEXT NOT NULL CHECK (
    source IN ('manual', 'uploaded', 'generated', 'styles', 'platform_default', 'api')
  ),
  brand_kit_json TEXT NOT NULL,
  brand_summary_json TEXT NOT NULL,
  diagnostics_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (brand_kit_id, version)
);

CREATE TABLE IF NOT EXISTS brand_compatibility_reports (
  report_id TEXT PRIMARY KEY,
  from_brand_kit_id TEXT NOT NULL,
  from_version INTEGER NOT NULL,
  to_brand_kit_id TEXT NOT NULL,
  to_version INTEGER NOT NULL,
  report_json TEXT NOT NULL,
  diagnostics_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (from_brand_kit_id, from_version)
    REFERENCES brand_kits(brand_kit_id, version)
    ON DELETE CASCADE,
  FOREIGN KEY (to_brand_kit_id, to_version)
    REFERENCES brand_kits(brand_kit_id, version)
    ON DELETE CASCADE
);
