-- Agent runs + their event streams. An async agent turn (POST /agent/turns)
-- runs in a background thread and appends progress events here; the SSE
-- endpoint replays them from this store on (re)connect via Last-Event-ID,
-- then streams live. The store is the durable source of truth for a turn's
-- progress and final result, so a tab reload mid-run loses nothing.
--
-- Runs are NOT tied to a document via foreign key: a turn can start before
-- the canvas has been persisted (auto-create happens at Accept), so
-- document_id is a nullable, un-constrained hint only. Migrations run on
-- every startup, so everything here is idempotent.
CREATE TABLE IF NOT EXISTS agent_runs (
  run_id TEXT PRIMARY KEY,
  status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
  document_id TEXT,
  result_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- One row per progress event, ordered by a monotonic per-run seq (mirrors
-- the operation_log / edit_envelopes per-document sequencing). The seq is
-- the SSE event id used for Last-Event-ID replay. Only the run's own thread
-- ever writes a given run_id's events, so MAX(seq)+1 is race-free.
CREATE TABLE IF NOT EXISTS run_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  event_type TEXT NOT NULL,
  data_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  UNIQUE (run_id, seq),
  FOREIGN KEY (run_id) REFERENCES agent_runs(run_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_run_events_run
  ON run_events (run_id, seq ASC);
