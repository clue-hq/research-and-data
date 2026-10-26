# Agent Workspace Phase 2: Retention and Honesty — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A chat's rough work (raw inputs after 48 hours, working files after 7 days, old versions, erased chats) leaves R2 for real; the agent is told at every turn what it has, how old it is and what expired; nothing a person can see is ever touched.

**Architecture:** Snapshot files move to their own storage area (`<ws>/agent-workspace/<sha>`) so deleting a chat's file can never reach an upload, a Gallery artifact or a research output. The file list (schema 2) carries a receipt and an `expired_at` per entry. A daily fleet job expires due entries with the same compare-and-set a turn uses; a turn's save rebases over an expiry-only conflict. Each turn's context gains a `workspace_files` card built from the file list, never from disk. The manual and the staleness instruction are rewritten after founder review.

**Tech Stack:** Python 3.12, asyncpg/SQLAlchemy raw SQL, Alembic, `clue_storage`, pytest on `clue_dushanbe_test` only.

**Spec:** `docs/superpowers/specs/agent-workspace/2026-10-21-agent-workspace-durability-design.md` §8 (WS-23–WS-32), rulings AW-1–AW-26 in `docs/superpowers/specs/agent-workspace/rulings.md`. Phase 1 is on `feat/agent-workspace-durability`; this plan is built on `feat/agent-workspace-retention` (branched from it, AW-23).

## Global Constraints

- Raw inputs (`reads/`, `work/conversation_history/`, `work/large_tool_results/`) expire **172800 s** after the chat's last activity (`CLUE_AGENT_WORKSPACE_RAW_RETENTION_S`, AW-2).
- Working files (`scratch/`, and `work/` apart from the two compaction folders) expire **604800 s** after the chat's last activity (`CLUE_AGENT_WORKSPACE_WORKING_RETENTION_S`, AW-22/AW-24).
- `outputs/` never expires (AW-22).
- The expiry job checks every **86400 s** (daily; `CLUE_AGENT_WORKSPACE_RETENTION_SWEEP_INTERVAL_S`, AW-24), one runner at a time (`maintenance_run` + advisory lock, like the storage sweep).
- Last activity = the newest of `agent_workspace_snapshot.last_activity_at` and the chat's newest `agent_turn_submission.requested_at` (WS-24).
- Only keys of the shape `<ws>/agent-workspace/<sha256>` are ever marked erased by this work (AW-26). A key of any other shape is released, never erased.
- A deleted file keeps its file-list entry, marked `expired_at`, with its receipt, for the chat's life (WS-25, WS-26).
- Every entry has a receipt; one with no durable row has `source: "unknown"` and is never dropped (WS-25).
- Every env flag the code reads appears in `.env.example` and the lane `.env` at the moment it is introduced (CLAUDE.md parity rule). `CLUE_AGENT_WORKSPACE_RETENTION_S` is retired in Task 8 (its only reader was the manual sentence that task rewrites).
- Agent-facing text (the manual chapter, the staleness sentence, the receipt's "how to read again" wording) is presented to the founder and approved before it is written (AW-2, D-26; memory rule *skill content needs founder review*).
- Migrations: hash revision id, `down_revision` = current head `01baa2e73e84`, named constraints, reversible, one head.
- DB tests run on `clue_dushanbe_test` only; never with real API keys (`--ignore-glob='*_live.py'`).
- No Claude attribution in commits.

## Review Focus

1. A file written again at a path whose entry had expired must be live again (new `written_at`, no `expired_at`), not stay expired. Test in Task 3.
2. A turn that saves while the expiry job moved the version must not lose its files: the save rebases when the only change is expiry. Test in Task 4.
3. A Phase 1 file list (schema 1, bytes under `<ws>/<sha>`) must restore, re-store under the new area on its next save, and release its old-shape holds **without erasing them** (those bytes may be an upload's). Test in Task 2.
4. Two chats holding the same bytes: expiry in one must not delete the other's file. Test in Task 2.
5. A chat with more than 200 live files gets a per-folder summary, and the card says what was left out. Test in Task 6.

---

### Task 1: Own storage area and the Phase 2 settings

**Files:**
- Create: `alembic/versions/<hash>_agent_workspace_storage_area.py`
- Modify: `libs/clue-storage/clue_storage/protocol.py` (beside `artifact_key`), `libs/clue-storage/clue_storage/__init__.py`
- Modify: `libs/clue-config/clue_config/settings.py:819-840`, `.env.example:586-600`, `.env`
- Test: `tests/storage/test_protocol.py`, `tests/db/test_agent_workspace_storage_area_migration.py`, `tests/test_settings.py` (or the existing settings test file)

**Interfaces:**
- Produces: `agent_workspace_key(workspace_id: str, sha256: str) -> str` returning `f"{workspace_id}/agent-workspace/{sha256}"`; `is_agent_workspace_key(storage_key: str) -> bool`.
- Produces: `Settings.agent_workspace_raw_retention_s: float = 172800.0`, `Settings.agent_workspace_working_retention_s: float = 604800.0`, `Settings.agent_workspace_retention_sweep_interval_s: float = 86400.0` (all `gt=0`).

- [ ] **Step 1: Write the failing tests**

```python
def test_agent_workspace_key_has_its_own_area():
    assert agent_workspace_key("ws_a", "ab" * 32) == f"ws_a/agent-workspace/{'ab' * 32}"
    assert is_agent_workspace_key(f"ws_a/agent-workspace/{'ab' * 32}")
    assert not is_agent_workspace_key(f"ws_a/{'ab' * 32}")
    assert not is_agent_workspace_key(f"ws_a/design/{'ab' * 32}")

async def test_the_artifact_table_accepts_the_agent_workspace_shape(conn):
    # INSERT INTO artifact (storage_key, workspace_id, content_sha256, media_type, size_bytes)
    # with storage_key = 'ws_x/agent-workspace/<sha>' succeeds; 'ws_x/other/<sha>' still raises IntegrityError.

def test_phase_2_retention_settings_defaults(monkeypatch):
    s = Settings()  # with the env cleared of CLUE_AGENT_WORKSPACE_*
    assert (s.agent_workspace_raw_retention_s, s.agent_workspace_working_retention_s,
            s.agent_workspace_retention_sweep_interval_s) == (172800.0, 604800.0, 86400.0)
```

- [ ] **Step 2: Run them**

Run: `uv run pytest tests/storage/test_protocol.py tests/db/test_agent_workspace_storage_area_migration.py -q -p no:cacheprovider -k "agent_workspace"`
Expected: FAIL (`ImportError: agent_workspace_key`; `IntegrityError` on the new shape).

- [ ] **Step 3: Implement**

`protocol.py`: the two functions, exported from `clue_storage`. Migration: `ALTER TABLE artifact DROP CONSTRAINT artifact_key_encodes_scope` then re-add it with a third `OR storage_key = COALESCE(workspace_id,'public') || '/agent-workspace/' || content_sha256`; `downgrade()` refuses with `RuntimeError` if any row has the new shape (`SELECT 1 FROM artifact WHERE storage_key LIKE '%/agent-workspace/%' LIMIT 1`), else restores the two-shape constraint. Settings: the three fields with comments naming their env vars and rulings; `.env.example` lines after `CLUE_AGENT_WORKSPACE_CACHE_SWEEP_INTERVAL_S` with a two-line comment; the same three lines appended to `.env`.

- [ ] **Step 4: Run tests, migrate the test DB, check one head**

Run: `uv run alembic upgrade head && uv run alembic heads` (with `CLUE_DATABASE_URL` pointed at `clue_dushanbe_test`), then the Step 2 command.
Expected: one head; PASS.

- [ ] **Step 5: Commit** — `feat(workspace): agent-workspace storage area and Phase 2 retention settings`

---

### Task 2: Snapshot store — new area, legacy fallback, delete what no snapshot holds (WS-30)

**Files:**
- Modify: `platform/api/clue_api/agent_workspace_snapshots.py`
- Modify: `platform/agents/clue_agents/ports.py:221-254` (docstring only)
- Test: `tests/api/test_agent_workspace_snapshots_db.py`

**Interfaces:**
- Consumes: Task 1's `agent_workspace_key`, `is_agent_workspace_key`; `clue_storage.erase_if_unreferenced`, `purge_erased_artifacts`.
- Produces: `DbWorkspaceSnapshotStore.save(...)` and `.forget(...)` unchanged in signature; both now end by erasing released agent-workspace keys. New read rule: `read_file` tries `agent_workspace_key(ws, sha)` first, then `artifact_key(ws, sha)` (Phase 1 bytes). `store_files` and the manifest always store under `agent_workspace_key`.

- [ ] **Step 1: Write the failing tests** (all with the existing `_workspace()` fixture and `CountingStorage`)

```python
async def test_files_are_stored_under_the_agent_workspace_area():
    # after store_files + save, every artifact_reference row of kind agent_workspace_snapshot
    # for this thread has a storage_key that is_agent_workspace_key(...)

async def test_a_phase_1_file_is_read_from_the_old_key_and_restored_under_the_new_one():
    # record + put bytes under artifact_key(ws, sha) only; save a manifest naming them with
    # the Phase 1 path; read_file returns the bytes; after store_files+save of the same bytes the
    # new key exists and the OLD key's artifact row has erased_at IS NULL (released, not erased)

async def test_a_new_version_erases_the_files_only_the_old_version_used():
    # v1 = {a, b}; v2 = {a}; after save: b's agent-workspace key has erased_at set and its blob is
    # deleted from storage; a's is untouched; the v1 manifest key is erased too

async def test_a_file_two_chats_hold_survives_one_chat_dropping_it():
    # thread X and thread Y both save bytes B; X saves a version without B; B's key is still live

async def test_forget_erases_every_file_no_other_chat_holds():
    # after forget(): the chat's holds are gone; keys no other reference holds are erased + purged

async def test_erasure_never_touches_a_key_of_another_shape():
    # a hold on artifact_key(ws, sha) (Phase 1 shape) released by save/forget leaves that row live
```

- [ ] **Step 2: Run them**

Run: `uv run pytest tests/api/test_agent_workspace_snapshots_db.py -q -p no:cacheprovider`
Expected: the six new tests FAIL (keys under the old shape; nothing erased).

- [ ] **Step 3: Implement**

In `_store_one`, `save`, `_hold_current`: keys from `agent_workspace_key`. `_read_verified` takes the candidate keys in order and uses the first whose row is live. Add `async def _erase_released(self, conn, *, workspace_id, before: set[str], after: set[str]) -> tuple[str, ...]`: for each key in `before - after` with `is_agent_workspace_key(key)`, call `erase_if_unreferenced(conn, key)`; collect the marked keys. `save` computes `before` as this thread's current reference keys (one SELECT on `artifact_reference`) before `_hold_current`, calls `_erase_released` inside the same transaction, and after the transaction commits runs `purge_erased_artifacts(conn, self._storage, keys=marked)` in a fresh `self._conn_factory()` (phase 2 of erasure must be after commit — `artifacts.py:459` docstring). `forget` does the same with `after = set()`.

- [ ] **Step 4: Run tests**

Run: the Step 2 command, then `uv run pytest tests/agents/test_workspace_snapshotter.py -q -p no:cacheprovider`
Expected: PASS, 20/20 and the snapshotter suite unchanged.

- [ ] **Step 5: Commit** — `feat(workspace): snapshot files live in their own storage area and leave it when no snapshot holds them`

---

### Task 3: File list schema 2 — tiers, receipts, expired entries

**Files:**
- Modify: `platform/agents/clue_agents/workspace_snapshot.py`
- Modify: `platform/agents/clue_agents/workspace_snapshotter.py:_manifest_for, _restore_version, save`
- Modify: `platform/agents/clue_agents/ports.py` (new `ReceiptSource` protocol)
- Test: `tests/agents/test_workspace_snapshot.py`, `tests/agents/test_workspace_snapshotter.py`

**Interfaces:**
- Produces: `SnapshotTier = Literal["work_product", "working_file", "raw_input"]`; `tier_for(path)` → `raw_input` for `RAW_INPUT_PREFIXES`, `work_product` for `outputs/…`, else `working_file`.
- Produces: `@dataclass(frozen=True) Receipt(source: str, operation_id: str | None, produced_at: datetime | None, details: Mapping[str, JsonValue], read_again: str)`; `SnapshotEntry` gains `receipt: Receipt | None = None`, `expired_at: datetime | None = None`; `MANIFEST_SCHEMA_VERSION = 2`; `decode_manifest` accepts 1 and 2 (schema 1 entries get `tier_for(path)`, no receipt, not expired); `SnapshotManifest.live()` / `.expired()` views; `same_files` compares live `(path, sha256)` sets and the expired path set.
- Produces: `class ReceiptSource(Protocol): async def receipt_for(self, *, workspace_id: str, thread_id: str, path: str) -> Receipt`. `WorkspaceSnapshotter(..., receipts: ReceiptSource | None = None)`.
- Snapshotter rules: an expired entry has no bytes — restore never downloads it and deletes a local file at that path; `_manifest_for` carries expired entries forward unless a local file now exists at the path (then a fresh live entry replaces it); a new raw-input or working-file entry gets `receipt = await receipts.receipt_for(...)` at save time (a `None` source gives `Receipt(source="unknown", …, read_again="")`).

- [ ] **Step 1: Write the failing tests**

```python
def test_tier_for_three_tiers():
    assert tier_for("reads/x.json") == "raw_input"
    assert tier_for("work/conversation_history/e.md") == "raw_input"
    assert tier_for("work/notes.md") == "working_file"
    assert tier_for("scratch/a.txt") == "working_file"
    assert tier_for("outputs/report.csv") == "work_product"

def test_schema_1_file_list_still_decodes_with_tiers_from_the_path():
    # encode a v1 document by hand with tier "work_product" on "scratch/a"; decode → tier working_file

def test_round_trip_keeps_receipt_and_expired_at():
    # an entry with receipt + expired_at survives encode/decode byte-for-byte

def test_restore_never_downloads_an_expired_entry_and_removes_its_local_file(tmp_path):
    # manifest {reads/r.json expired, scratch/a live}; local has reads/r.json → after restore the
    # file is gone, downloaded == 1, lease.snapshot_base.manifest still lists reads/r.json expired

def test_save_carries_expired_entries_forward_and_revives_a_rewritten_path(tmp_path):
    # base has reads/r.json expired; local writes nothing → saved manifest keeps it expired;
    # local writes reads/r.json again → saved entry is live with a new written_at and no expired_at

def test_save_attaches_a_receipt_to_each_new_raw_input(tmp_path):
    # a fake ReceiptSource returns Receipt(source="run_crm_action", ...); after save the entry
    # for reads/<op>.json carries it; a scratch file carries one too (working_file); outputs none
```

- [ ] **Step 2: Run them**

Run: `uv run pytest tests/agents/test_workspace_snapshot.py tests/agents/test_workspace_snapshotter.py -q -p no:cacheprovider`
Expected: FAIL (`working_file` unknown; `Receipt` undefined; expired file restored).

- [ ] **Step 3: Implement** per the Interfaces block; `encode_manifest` writes `receipt` as a nested object and `expired_at` as ISO-8601 or omits both when `None`.

- [ ] **Step 4: Run tests** — the Step 2 command. Expected: PASS, every earlier test still green.

- [ ] **Step 5: Commit** — `feat(workspace): file list schema 2 — three tiers, receipts, expired entries`

---

### Task 4: Receipts from durable rows, and a save that rebases over expiry

**Files:**
- Create: `platform/api/clue_api/agent_workspace_receipts.py`
- Modify: `platform/api/clue_api/agent_workspace_wiring.py:47-55` (pass `receipts=`)
- Modify: `platform/agents/clue_agents/workspace_snapshotter.py:save`
- Test: `tests/api/test_agent_workspace_receipts_db.py`, `tests/agents/test_workspace_snapshotter.py`

**Interfaces:**
- Produces: `class DbReceiptSource(ReceiptSource)` with `__init__(self, *, conn_factory: ConnFactory = transaction, artifacts: DurableAgentArtifactStore)`. Rules by path:
  - `reads/<uuid>.json` → `execution_node` row with that `operation_id`: `source = tool_name`, `produced_at = created_at`, `details` = `display_params_json` plus, when an `agent_tool_result` row exists for the operation, `record_count`/`total`/`done` read from its result artifact's `references`; `read_again` = the approved sentence from Task 8 formatted with the tool name and parameters.
  - `reads/<uuid>.stdout.txt` / `.stderr.txt` → `source = "run_python"`, `details = {"stream": "stdout"|"stderr"}`.
  - `work/conversation_history/<execution>.md` and `work/conversation_history/media/**` → `source = "conversation_history"`, `details = {"execution_id": …}`.
  - `work/large_tool_results/<name>` → `source = "large_tool_results"`.
  - anything else, or no row → `source = "unknown"`, `details = {}`.
- Produces: `WorkspaceSnapshotter.save` on `"stale"`: re-read `current` + its manifest; if `base.manifest.live()` ⊇ `current.live()` with equal hashes and every path missing from `current.live()` is in `current.expired()` (an expiry-only move), rebuild the manifest from local files plus `current.expired()` entries (for paths with no local file) and retry once with `expected_version = current.version`; otherwise return `"stale"` as today.

- [ ] **Step 1: Write the failing tests**

```python
async def test_a_crm_read_receipt_names_the_action_and_its_count(conn):
    # seed execution_node (tool_name run_crm_action, display_params_json {"slug": "HUBSPOT_SEARCH_DEALS"})
    # + agent_tool_result whose artifact references {"record_count": 12, "total": 12, "done": true}
    # receipt_for("reads/<op>.json") == Receipt(source="run_crm_action", details ⊇ {slug, record_count: 12})

async def test_a_file_with_no_row_gets_an_unknown_receipt(conn):
    # receipt_for("reads/<random uuid>.json").source == "unknown"

def test_a_save_rebases_over_an_expiry_only_move(tmp_path):
    # restore v1 {reads/r.json, scratch/a}; the store moves to v2 with reads/r.json expired;
    # local wrote scratch/b → save returns "saved", version 3, manifest = {reads/r.json expired,
    # scratch/a, scratch/b}

def test_a_save_still_refuses_a_real_conflict(tmp_path):
    # the store moved to v2 with scratch/a CHANGED → save returns "stale"
```

- [ ] **Step 2: Run** — `uv run pytest tests/api/test_agent_workspace_receipts_db.py tests/agents/test_workspace_snapshotter.py -q -p no:cacheprovider`. Expected: FAIL.
- [ ] **Step 3: Implement** per Interfaces; wire `DbReceiptSource` in `build_agent_workspace_factory` (the factory already receives `conn_factory` and the artifact store's storage).
- [ ] **Step 4: Run** the Step 2 command. Expected: PASS.
- [ ] **Step 5: Commit** — `feat(workspace): receipts from durable rows; a save rebases over an expiry-only move`

---

### Task 5: The expiry job (WS-26)

**Files:**
- Create: `platform/api/clue_api/agent_workspace_retention.py`
- Modify: `platform/api/clue_api/fleet_main.py` (a loop beside `_orphan_sweep_loop`, started where `_start_workspace_cache_sweep` is)
- Test: `tests/api/test_agent_workspace_retention_db.py`

**Interfaces:**
- Consumes: Task 2's store (`save` with `fence=None`, `read_manifest`), Task 3's manifest, Task 1's settings.
- Produces: `RETENTION_SWEEP = "agent_workspace_retention"` (the `maintenance_run` name; lock key `"agent-workspace-retention"`); `@dataclass RetentionReport(chats_checked: int, chats_expired: int, files_expired: int, skipped_busy: int, stale: int)`; `class AgentWorkspaceRetentionJob` with `__init__(self, *, store: DbWorkspaceSnapshotStore, conn_factory: ConnFactory, raw_s: float, working_s: float)` and `async def run_once(self, *, now: datetime | None = None) -> RetentionReport`; `async def run_retention_if_due(conn, *, job, every: timedelta, now=None) -> RetentionReport | None` (the `maintenance_run` + `pg_try_advisory_xact_lock` pattern of `storage_wiring.run_orphan_blob_sweep_if_due`).
- `run_once` rules: candidates = `agent_workspace_snapshot` rows where `GREATEST(last_activity_at, COALESCE((SELECT max(requested_at) FROM agent_turn_submission s WHERE s.workspace_id = … AND s.thread_id = …), last_activity_at)) <= now - min(raw_s, working_s)`. A candidate is **busy** (skipped, counted) when a `fleet_task` of kind `agent_turn` for `thread_work_id(workspace_id, thread_id)` is `queued`/`claimed`, or a `work_lease` row for that work id has `expires_at > now`. For each other candidate: read the manifest; an entry expires when it is live and its tier's window has passed since last activity (`raw_input` → `raw_s`, `working_file` → `working_s`, `work_product` → never); if none, skip; else save the new manifest (expired entries keep their receipt, get `expired_at = now`) with `expected_version = current.version`, `fence=None`; a `"stale"` result is counted and left for the next hour. Released keys are erased by the store (Task 2).

- [ ] **Step 1: Write the failing tests** (scenario tests through the real store, `require_profiling_db`)

```python
async def test_raw_inputs_expire_after_their_window_and_keep_their_receipt():
    # a chat saved {reads/r.json (receipt R), scratch/a, outputs/o} with last activity 3 days ago,
    # raw_s=172800, working_s=604800 → files_expired == 1; the manifest lists reads/r.json with
    # expired_at and receipt R; its agent-workspace key is erased + purged; scratch/a and outputs/o untouched

async def test_working_files_expire_after_seven_days_outputs_never():
    # last activity 8 days ago → scratch/a expired, outputs/o live

async def test_a_busy_chat_is_skipped():
    # a queued fleet_task for the thread's work id → skipped_busy == 1, nothing changed

async def test_a_recent_submission_counts_as_activity():
    # snapshot last_activity 3 days ago but a submission requested_at 1 hour ago → not a candidate

async def test_one_runner_at_a_time_and_only_when_due():
    # run_retention_if_due twice within `every` → second returns None; maintenance_run row written

async def test_reading_identical_bytes_again_works_after_expiry():
    # after reads/r.json expired (bytes erased), a later save of the SAME bytes at reads/r2.json
    # succeeds: record_artifact resurrects the row (the key was erased, not privacy-erased), the
    # blob is put again, read_file returns the bytes   (spec WS-26 "required, and tested")
```

- [ ] **Step 2: Run** — `uv run pytest tests/api/test_agent_workspace_retention_db.py -q -p no:cacheprovider`. Expected: FAIL (`ImportError`).
- [ ] **Step 3: Implement** per Interfaces. In `fleet_main.py`: `_workspace_retention_loop(interval_s, job, every, conn_factory)` that every `interval_s` opens a transaction and calls `run_retention_if_due`; composed only when `settings.agent_workspace_snapshots_enabled`; log `fleet.workspace_retention.ran` with the report's fields.
- [ ] **Step 4: Run** the Step 2 command. Expected: PASS.
- [ ] **Step 5: Commit** — `feat(workspace): daily expiry of raw inputs and working files, one runner at a time`

---

### Task 6: The turn-start file list (WS-28) for chats and research runs

**Files:**
- Create: `platform/api/clue_api/agent_workspace_files_card.py`
- Modify: `platform/api/clue_api/agent_turn_fleet_wiring.py:866-900` (after `acquire_restored`) and `_compose_project_context` (new `workspace_files: WorkspaceFilesCard | None = None` argument; append a `ProjectContextArtifact(name="workspace_files", …)` like `since_last_turn` at :1147)
- Modify: `platform/api/clue_api/account_research_turn_wiring.py:541-575` (append to `project_context_artifacts`)
- Test: `tests/api/test_agent_workspace_files_card.py`, `tests/api/test_lane_d2_turn_submission_db.py` (one scenario), `tests/api/test_account_research_turn_wiring*.py` (one scenario)

**Interfaces:**
- Consumes: `lease.snapshot_base.manifest` (Task 3), `lease.restore_report`.
- Produces: `WORKSPACE_FILES_MEDIA_TYPE = "application/vnd.clue.agent-workspace-files+json"`; `WORKSPACE_FILES_MAX_LISTED = 200`; `def build_workspace_files_card(manifest: SnapshotManifest | None, *, now: datetime) -> dict[str, JsonValue]` returning `{"schema_version": "1", "generated_at": iso, "live": [{"path","folder","size","age_hours","tier"}…] (sorted by path, at most 200), "expired": [{"path","tier","expired_at","receipt": {source, operation_id, produced_at, details, read_again}}…] (all of them), "omitted": {"<folder>": count…} (live files beyond the first 200, by top folder), "note": <the approved one-line explanation from Task 8, or "" until then>}`. A `None` manifest gives empty lists.
- The card is an L3 context artifact at `context/workspace_files.json`, re-sent on continued turns like the others.

- [ ] **Step 1: Write the failing tests**

```python
def test_card_lists_live_files_with_age_and_expired_files_with_receipts():
    # manifest {scratch/a (written 2 days ago), reads/r.json expired with receipt} →
    # live == [{"path": "scratch/a", "folder": "scratch", "size": 3, "age_hours": 48, "tier": "working_file"}]
    # expired[0]["receipt"]["source"] == "run_crm_action"

def test_card_bounds_the_live_list_and_says_what_was_left_out():
    # 250 live files under work/ → len(live) == 200; omitted == {"work": 50}

def test_an_empty_or_missing_manifest_gives_an_empty_card():
    assert build_workspace_files_card(None, now=NOW)["live"] == []

async def test_a_chat_turn_materializes_context_workspace_files_json(...):
    # through _handle_next on the D2 harness: the second turn's context/ holds workspace_files.json
    # naming the first turn's outputs file

async def test_a_research_turn_materializes_the_card(...):
    # same through the account research runner
```

- [ ] **Step 2: Run** — `uv run pytest tests/api/test_agent_workspace_files_card.py tests/api/test_lane_d2_turn_submission_db.py -q -p no:cacheprovider -k "workspace_files"`. Expected: FAIL.
- [ ] **Step 3: Implement** per Interfaces (`age_hours` = whole hours from `written_at`; the chat runner builds the card right after `acquire_restored` and passes it to `_compose_project_context`; the research runner persists it with its `_artifact(...)` helper under `object_type="thread"`).
- [ ] **Step 4: Run** the Step 2 command plus `tests/api/test_account_research_turn_wiring*.py`. Expected: PASS.
- [ ] **Step 5: Commit** — `feat(workspace): every turn starts with a card of the chat's files, their age and what expired`

---

### Task 7: Scenario tests 5, 6 and 7 (§11)

**Files:**
- Modify: `tests/api/test_agent_workspace_scenarios_db.py`

**Interfaces:** consumes Tasks 2–6 through the real factory, store, job and card builder; no new production code (a failure here is a bug in an earlier task — fix it there, test-first).

- [ ] **Step 1: Write the three scenarios**

```python
def test_5_raw_expiry_removes_bytes_keeps_receipt_and_the_next_turn_sees_it(tmp_path):
    # turn on root A writes reads/r.json + scratch/a; last activity pushed 3 days back in SQL;
    # AgentWorkspaceRetentionJob(raw_s=0, working_s=604800).run_once() → files_expired == 1;
    # next turn on root B: reads/r.json absent on disk, scratch/a present, the card's expired[]
    # names reads/r.json with its receipt; saving the same bytes again at reads/r2.json works

def test_6_work_products_survive_the_expiry_job(tmp_path):
    # outputs/o and (within 7 days) scratch/a survive run_once with raw_s=0

def test_7_erasing_a_chat_leaves_nothing_in_storage_and_no_root_reuses_its_copy(tmp_path):
    # chat saved on A and restored on B; forget_chat on A → version record gone, every
    # agent-workspace key erased and purged (CountingStorage shows the deletes); B's next
    # acquire_restored empties its copy; B's cache sweep removes the folder
```

- [ ] **Step 2: Run** — `uv run pytest tests/api/test_agent_workspace_scenarios_db.py -q -p no:cacheprovider`. Expected: the three PASS on first run only if Tasks 2–6 are complete; any failure is fixed in the owning task.
- [ ] **Step 3: Commit** — `test(workspace): Phase 2 scenarios — raw expiry, work products survive, erasure leaves nothing`

---

### Task 8: Agent-facing text — manual chapter, staleness instruction, receipt wording (WS-29, WS-32) — FOUNDER GATE

**Files:**
- Modify: `platform/agents/clue_agents/manual/build.py` (the workspace chapter at the `"workspace"` builder and the limits chapter at :896-904), `MANUAL_VERSION = "v24"`
- Create (by re-mint): `platform/agents/catalog/skills/manual-*/v24/SKILL.md`, `stage0-interview/v51/SKILL.md` (v50 with manual paths repointed), `head-of-abm/v78/profile.yaml` (v77 with the v24 manual chapters and stage0-interview v51)
- Modify: `platform/api/clue_api/agent_registry_wiring.py` (the active profile), `platform/api/clue_api/chat/composer_context.py` if the disclosed-skills budget moves, `libs/clue-config/clue_config/settings.py:823` and `.env.example:588-590` / `.env` (retire `CLUE_AGENT_WORKSPACE_RETENTION_S`), `platform/api/clue_api/agent_workspace_receipts.py` and `agent_workspace_files_card.py` (the approved sentences)
- Test: `tests/agents/test_manual_builder.py`, `tests/agents/test_manual_drift.py`, `tests/api/test_agent_registry_wiring.py`, `tests/api/test_recipe_contracts.py`

**Interfaces:** consumes Task 4's `read_again` and Task 6's `note` placeholders; produces manual v24, profile v78.

- [ ] **Step 1: Draft and present — STOP for approval.** Before writing any file, post in chat: (a) the rewritten folder table rows for `scratch/`, `reads/`, `work/`, `outputs/` (what each keeps and for how long: `outputs/` for the chat; `scratch/`/`work/` 7 days after the chat's last activity; `reads/` and `work/conversation_history/`, `work/large_tool_results/` 48 hours, leaving a receipt); (b) one paragraph on `context/workspace_files.json` (what it lists, that an expired file's receipt says how to read it again); (c) the staleness instruction (after a gap, check how old your numbers and their source data are before relying on them; decide yourself whether to read again; you need not tell the person — AW-4); (d) the receipt's `read_again` sentence template per source, and the card's `note` line; (e) the new limits-chapter sentence replacing the `CLUE_AGENT_WORKSPACE_RETENTION_S` one. Wait for the founder's approval; apply their edits.
- [ ] **Step 2: Message the CRM session** (`SendMessage`, AW-7) that this lane is minting manual v24 / head-of-abm v78 / stage0-interview v51, so the lanes do not mint the same numbers.
- [ ] **Step 3: Write the approved text** into `build.py` and the two Python modules; retire the setting (field, example line, lane `.env` line); re-mint following commit `f6276a28d` as the template (`uv run python -m clue_agents.manual.build --catalog-root platform/agents/catalog` or the command that commit's `build.py` change documents; copy v77 → v78 and v50 → v51 repointing `manual-*/v23` → `v24`); make v78 the active profile.
- [ ] **Step 4: Run** — `uv run pytest tests/agents/test_manual_builder.py tests/agents/test_manual_drift.py tests/api/test_agent_registry_wiring.py tests/api/test_recipe_contracts.py tests/api/test_fleet_wiring.py -q -p no:cacheprovider` (without sourcing `.env`). Expected: PASS; the drift test proves the catalog matches the builder.
- [ ] **Step 5: Commit** — `feat(agents): manual v24 — what each folder keeps and for how long; staleness instruction; head-of-abm v78`

---

### Task 9: Docs, memory, CLAUDE.md, and the live check

**Files:**
- Modify: `docs/superpowers/specs/agent-workspace/2026-10-21-agent-workspace-durability-design.md` (§3 P2 row exit criteria met; §5 "Today" rows; change log), `CLAUDE.md` (the agent-workspace paragraph: Phase 2 built, windows, the storage area), `docs/runbooks/agent-runtime.md:100-112` (replace the retired cleanup job with the cache sweep + retention job; review minor M5), `_memory/2026-10-22-agent-workspace-f3-spec.md` (closing entry)

- [ ] **Step 1: Live check on the dushanbe stack** (pre-approved; report the cost). Migrate the stack DB (`alembic upgrade head`), restart API and workers via the runbook. In a new chat: ask the agent to write `scratch/note.md` and `outputs/table.csv` (≈ $0.20). Push the snapshot's `last_activity_at` 8 days back in SQL; run `AgentWorkspaceRetentionJob.run_once()` by hand with the production windows; confirm `scratch/note.md` is expired in the manifest, its key erased and purged from R2, `outputs/table.csv` live. Next turn (≈ $0.20): the agent's `context/workspace_files.json` lists `outputs/table.csv` live and `scratch/note.md` expired; ask it what files it has — it must name the table and say the note expired. Record versions, timings and cost.
- [ ] **Step 2: Write the docs** listed above; the spec's §11 table marks tests 5, 6, 7 as passing with the test names.
- [ ] **Step 3: Full relevant suite** — `uv run pytest tests/agents tests/api/test_agent_workspace_*.py tests/api/test_lane_d2_turn_submission_db.py tests/storage tests/db/test_agent_workspace_*.py -q -p no:cacheprovider --ignore-glob='*_live.py'`. Expected: PASS apart from the pre-existing failures recorded in the Phase 1 ledger (DSAR agent-copy test; `test_fleet_wiring` only when `.env` is sourced).
- [ ] **Step 4: Commit** — `F3 P2: docs, runbook, memory and the live check`

---

## Self-review

- **Spec coverage:** WS-23 (Task 3 tiers; Task 5 windows), WS-24 (Task 5 last-activity SQL), WS-25 (Tasks 3–4), WS-26 (Task 5; identical-bytes re-read test), WS-27 (builder's call: Task 4 stores large tool results like any raw input; rebuilding from `result_ref` is not done — recorded here), WS-28 (Task 6), WS-29 and WS-32 (Task 8, gated), WS-30 (Tasks 1–2), WS-31 (Task 2 `forget` + Task 7 test 7; the chat/project erasure callers are the existing `forget_chat` path), WS-31a dropped (AW-26). §11 tests 5, 6, 7: Task 7.
- **Type consistency:** `Receipt`, `SnapshotTier`, `agent_workspace_key`, `AgentWorkspaceRetentionJob.run_once`, `build_workspace_files_card` are named identically across tasks.
- **Proportion:** nine tasks, signatures and assertions only; no bodies.
