-- Website-mode personalization accounts (P5 D3): one row per target company.
-- An account IS the binding set — account_values() projects this row into the
-- flat account.* value namespace the web derive consumes. data_json holds the
-- string->string custom vars (each becomes account.<key>); notes is agent-only
-- context and is NEVER a substitution value. logo_asset_id references the
-- assets table (validated at write time; no FK — a DELETE keeps derived docs'
-- account_id string intact).
CREATE TABLE IF NOT EXISTS web_accounts (
  account_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  domain TEXT,
  logo_asset_id TEXT,
  data_json TEXT NOT NULL DEFAULT '{}',
  notes TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
