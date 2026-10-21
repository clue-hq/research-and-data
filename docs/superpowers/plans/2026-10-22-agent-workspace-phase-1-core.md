# Agent workspace Phase 1 (core) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Any worker can continue any chat with the files its agent left, every worker's disk is
only a cache in its own area, and no folder is shared by two chats.

**Architecture:** A chat's agent folders (`scratch/ reads/ work/ outputs/`) are saved at turn end
as a versioned snapshot: a file list plus content-addressed files in the artifact store (R2), with
one version record per chat in Postgres moved by compare-and-set under the fleet lease. At turn
start the worker brings its local copy up to that version, downloading only what differs. Each
fleet worker process claims its own area of the disk, and each chat folder in it holds its own
copy of the brand and project files. Every folder is written only where something changed.

**Tech Stack:** Python 3.12, asyncio, SQLAlchemy async (asyncpg), Alembic (hand-written),
`clue_storage` artifact store (FsStorage / S3), `clue_fleet` work leases, pytest.

**Spec:** `docs/superpowers/specs/agent-workspace/2026-10-21-agent-workspace-durability-design.md`
(Phase 1: WS-1–WS-22, WS-36, WS-37) and `docs/superpowers/specs/agent-workspace/rulings.md`
(AW-1–AW-17). Read §0, §7 and §10–§12 of the spec before Task 1.

## Decisions this plan makes (founder to confirm before execution)

The spec left these to the builder, or the code survey showed the spec's wording cannot hold
exactly. Each is a choice the founder should see.

1. **A failed save does not requeue the turn** (adjusts AW-15). By the time a save runs, the
   model's work is done and the runtime marks the turn abandoned on any exception
   (`agent_runtime_wiring.py:1639-1646`), so a fleet requeue would re-run the whole turn and spend
   again. Instead: the save is retried 3 times; if storage is still unreachable the turn fails, the
   worker keeps its local copy and marks it "unsaved", and the chat's next turn on that worker saves
   it. A **restore** that cannot reach storage, which happens before any model call, does requeue
   the turn (spec §10). The spec's claim that "this is what happens today" was wrong: today a
   failed outputs snapshot fails the turn without a retry.
2. **Worker areas are claimed, not named.** No worker has a stable name today (ids are random
   uuid4, compose sets none). Each fleet process claims the first free area
   `<root>/workers/area-<n>` by taking an exclusive `flock` on `<root>/workers/area-<n>.lock`,
   then wipes it. The kernel drops the lock when the process dies, so a restarted worker claims a
   free area and wipes it, and no configuration is needed. At start-up a worker also deletes every
   *other* area whose lock it can take, because a takeable lock proves no live process owns it.
   This replaces the spec's "deploy step deletes areas of removed workers".
3. **The project library stops being rendered on disk outside a turn.** Each chat syncs its own
   copy at turn start (WS-37), so the shared tree that `ProjectLibraryRefresher` keeps on disk has
   no reader. A privacy erasure that changes a library file without moving its digest currently
   relies on a forced disk rewrite, which never reaches another machine. It now bumps a new
   `project_library_epoch` row, which the digest includes, so every chat's copy resyncs on its next
   turn. The API process stops building a workspace factory.
4. **Measurement is structured log events** (`agent_workspace.restore`, `agent_workspace.save`)
   carrying warm/cold, files, bytes and milliseconds (WS-20). There is no new table.
5. **A save with no change touches the record but does not create a version.** It updates
   `last_activity_at` only.
6. **The idle job runs every 5 minutes** (`CLUE_AGENT_WORKSPACE_CACHE_SWEEP_INTERVAL_S=300`), so a
   folder idle for 30 minutes is gone within 35.

## Global Constraints

- Test database: `clue_dushanbe_test` only (AW-7). Never run DB tests against
  `clue_nashville_pm_clone`. DB test command prefix (from the repo root):
  `set -a; source .env; set +a; export CLUE_DATABASE_URL="${CLUE_DATABASE_URL%/*}/clue_dushanbe_test";`
- No live-key test suites. Run only the named test files; never `make check` with real keys.
- Migrations: hand-written, reversible, named constraints, generated with
  `uv run alembic revision -m "<slug>"`, `down_revision` = the current single head (`c87ba03cfc4e`
  unless `feat/crm-integration` has moved it; check `uv run alembic heads`). Exactly one head.
- Every new setting goes in `libs/clue-config/clue_config/settings.py` (comment ending
  ``Env: ``CLUE_X``.``), `.env.example` and the lane `.env`, with its default, in the same commit.
- Settings and defaults (spec WS-21, AW-11, AW-17):
  `CLUE_AGENT_WORKSPACE_SNAPSHOTS_ENABLED=true`, `CLUE_AGENT_WORKSPACE_CACHE_IDLE_S=1800`,
  `CLUE_AGENT_WORKSPACE_CACHE_MAX_BYTES=10737418240`, `CLUE_AGENT_WORKSPACE_TRANSFER_CONCURRENCY=16`,
  `CLUE_AGENT_WORKSPACE_CACHE_SWEEP_INTERVAL_S=300`. Retire `CLUE_AGENT_WORKSPACE_RETENTION_S` and
  `CLUE_AGENT_CLEANUP_INTERVAL_S` (Task 10).
- File modes inside every thread and chat folder: directories 0700 (0500 frozen), files 0600 (0400
  frozen), owned by the process uid, no links, no special files (`workspace.py:94-97,161-171`).
- Saved folders: `scratch/ reads/ work/ outputs/`, all of them, nothing emptied between turns
  (AW-14). Raw-input paths: `reads/`, `work/conversation_history/`, `work/large_tool_results/`.
  Everything else saved is a work product.
- Manifest media type: `application/vnd.clue.agent-workspace-manifest+json`, `schema_version` 1.
- Artifact reference kind for snapshot files: `"agent_workspace_snapshot"`, reference id
  `"<thread_id>"`.
- Commits: local only, never push, no AI attribution lines. Commit after each task's tests pass.
- Skill and manual text is not changed in Phase 1. The manual rewrite is WS-32, in Phase 2.

## Review Focus

1. **A manifest entry whose path escapes the agent folders** (`../x`, `/etc/x`, `outputs/../../x`)
   must be refused on restore, never written. Test: Task 8, `test_restore_refuses_escaping_path`.
2. **A file the agent deleted** must also disappear on another worker's restore, not linger from
   an older local copy. Test: Task 8, `test_restore_deletes_files_not_in_the_manifest`.
3. **Empty and binary files** (0-byte `.txt`, `.xlsx`) must round-trip byte-identical. Test:
   Task 8, `test_round_trip_keeps_empty_and_binary_files`.
4. **A restore cut off half-way** (disk full, a bad hash) must leave no local version note, so the
   next turn restores again. Test: Task 8, `test_failed_restore_leaves_no_note`.
5. **Two workers starting at the same moment** must claim different areas, and a dead worker's
   area must be wiped by the next worker that starts. Test: Task 6,
   `test_two_processes_claim_different_areas` and `test_dead_area_is_wiped_at_claim`.

---

## File map

| File | Responsibility |
|---|---|
| `alembic/versions/<rev>_agent_workspace_snapshot.py` (new) | `agent_workspace_snapshot` and `project_library_epoch` tables |
| `libs/clue-config/clue_config/settings.py`, `.env.example`, `.env` | new settings; retire two |
| `platform/agents/clue_agents/workspace_snapshot.py` (new) | manifest model, tiers, pointer, fence, errors (pure) |
| `platform/agents/clue_agents/ports.py` | `WorkspaceSnapshotStore` protocol |
| `platform/api/clue_api/agent_workspace_snapshots.py` (new) | `DbWorkspaceSnapshotStore`: DB + storage, compare-and-set, fence, references |
| `platform/agents/clue_agents/tree_sync.py` (new) | `sync_directory`: write only what changed |
| `platform/agents/clue_agents/worker_area.py` (new) | area claim, in-use registry, start-up wipe |
| `platform/agents/clue_agents/workspace.py` | chat layout, area root, per-chat mounts, `acquire_restored`, `release_saved`, `save_snapshot`, `remove_chat` |
| `platform/agents/clue_agents/resources.py` | recipe folders through `sync_directory` |
| `platform/agents/clue_agents/workspace_snapshotter.py` (new) | restore, save, local version note, legacy import |
| `platform/api/clue_api/brand_library.py`, `project_library.py`, `project_attachments.py`, `project_root_writer.py`, `project_library_refresh.py` | per-chat copies; epoch |
| `platform/api/clue_api/sandbox/workspaces.py`, `sandbox/docker_runner.py`, `run_python_tool.py` | chat host paths; area label; spill under quota |
| `platform/api/clue_api/agent_workspace_wiring.py` | build the factory with area and snapshot store |
| `platform/api/clue_api/agent_turn_fleet_wiring.py`, `conversation_turns.py`, `agent_runtime_wiring.py`, `quality_research_wiring.py`, `specialist_wiring.py`, `account_research_turn_wiring.py`, `onboarding_synthesis_wiring.py`, `stage0_trial.py` | use `acquire_restored` / `release_saved`; save in finalize; fence |
| `platform/api/clue_api/agent_workspace_cache.py` (new) | idle and size cleanup of the worker's area |
| `platform/api/clue_api/agent_cleanup.py` (deleted), `fleet_main.py`, `projections_main.py`, `agent_turn_wiring.py` | retire the old purge; schedule the new job; privacy erase |
| `scripts/remove_legacy_agent_workspaces.py` (new) | one-off removal of the old layout (dry run by default) |
| `tests/agents/test_workspace_snapshot.py`, `test_tree_sync.py`, `test_worker_area.py`, `test_workspace_snapshotter.py` (new) | unit tests |
| `tests/api/test_agent_workspace_snapshots_db.py`, `test_agent_workspace_cache.py`, `test_agent_workspace_scenarios_db.py` (new) | DB and scenario tests |

---

### Task 1: Settings and the migration

**Files:**
- Create: `alembic/versions/<rev>_agent_workspace_snapshot.py`
- Modify: `libs/clue-config/clue_config/settings.py:820-830`, `.env.example:565-590`, `.env`
- Test: `tests/db/test_agent_workspace_snapshot_migration.py`

**Interfaces:**
- Produces: tables `agent_workspace_snapshot`, `project_library_epoch`. Settings fields
  `agent_workspace_snapshots_enabled: bool = True`, `agent_workspace_cache_idle_s: float = 1800.0`,
  `agent_workspace_cache_max_bytes: int = 10737418240`,
  `agent_workspace_transfer_concurrency: int = 16`,
  `agent_workspace_cache_sweep_interval_s: float = 300.0`.

- [ ] **Step 1: Write the failing migration test**

```python
def test_agent_workspace_snapshot_table_shape():
    # after upgrade head: columns, PK and checks exist with these names
    cols = column_names("agent_workspace_snapshot")
    assert cols == {"workspace_id", "thread_id", "project_id", "version", "manifest_artifact_key",
                    "manifest_sha256", "last_activity_at", "updated_at"}
    assert constraint_names("agent_workspace_snapshot") >= {
        "agent_workspace_snapshot_pkey", "agent_workspace_snapshot_version_positive",
        "agent_workspace_snapshot_manifest_sha_shape"}

def test_project_library_epoch_table_shape():
    assert column_names("project_library_epoch") == {"workspace_id", "project_id", "epoch", "updated_at"}
    assert "project_library_epoch_pkey" in constraint_names("project_library_epoch")

def test_settings_defaults():
    s = Settings(_env_file=None)
    assert s.agent_workspace_snapshots_enabled is True
    assert s.agent_workspace_cache_idle_s == 1800.0
    assert s.agent_workspace_cache_max_bytes == 10737418240
    assert s.agent_workspace_transfer_concurrency == 16
    assert s.agent_workspace_cache_sweep_interval_s == 300.0
```

Use the `migrated_db` / `rollback_conn` fixtures from `tests/profiling/conftest.py` and query
`information_schema.columns` / `pg_constraint`.

- [ ] **Step 2: Run it to make sure it fails**

Run: `<DB prefix> uv run pytest tests/db/test_agent_workspace_snapshot_migration.py -v`
Expected: FAIL (tables and settings missing)

- [ ] **Step 3: Write the migration** (`uv run alembic revision -m "agent_workspace_snapshot"`)

```sql
CREATE TABLE agent_workspace_snapshot (
  workspace_id text NOT NULL, thread_id text NOT NULL, project_id text NOT NULL,
  version integer NOT NULL, manifest_artifact_key text NOT NULL, manifest_sha256 text NOT NULL,
  last_activity_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT agent_workspace_snapshot_pkey PRIMARY KEY (workspace_id, thread_id),
  CONSTRAINT agent_workspace_snapshot_version_positive CHECK (version >= 1),
  CONSTRAINT agent_workspace_snapshot_manifest_sha_shape CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$'));
CREATE TABLE project_library_epoch (
  workspace_id text NOT NULL, project_id text NOT NULL, epoch bigint NOT NULL DEFAULT 1,
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT project_library_epoch_pkey PRIMARY KEY (workspace_id, project_id),
  CONSTRAINT project_library_epoch_positive CHECK (epoch >= 1));
```

The downgrade drops both tables. The docstring states why there is no foreign key to
`agent_thread`: research, delegation and onboarding threads are also keyed here.

- [ ] **Step 4: Add the five settings, then `.env.example` and `.env` lines**

Each gets a comment above it, ending in its `Env:` line, in the agent-workspace block next to
`agent_workspace_root` (`settings.py:381-385`).

- [ ] **Step 5: Run the test, plus the migration round-trip**

Run: `<DB prefix> uv run pytest tests/db/test_agent_workspace_snapshot_migration.py tests/db/test_db_migrations.py -v`
and `uv run alembic heads`
Expected: PASS, one head

- [ ] **Step 6: Commit** — `git commit -m "F3 P1: agent_workspace_snapshot + project_library_epoch tables, settings"`

---

### Task 2: The snapshot model (pure)

**Files:**
- Create: `platform/agents/clue_agents/workspace_snapshot.py`
- Modify: `platform/agents/clue_agents/ports.py` (protocol), `platform/agents/clue_agents/__init__.py` (exports)
- Test: `tests/agents/test_workspace_snapshot.py`

**Interfaces:**
- Produces:
  - `SnapshotTier = Literal["work_product", "raw_input"]`
  - `SAVED_FOLDERS: Final = ("scratch", "reads", "work", "outputs")`
  - `RAW_INPUT_PREFIXES: Final = ("reads/", "work/conversation_history/", "work/large_tool_results/")`
  - `MANIFEST_MEDIA_TYPE: Final = "application/vnd.clue.agent-workspace-manifest+json"`
  - `def tier_for(path: str) -> SnapshotTier`
  - `def validate_snapshot_path(path: str) -> str` — a normalised relative path whose first segment
    is in `SAVED_FOLDERS`; raises `SnapshotCorrupt` otherwise.
  - `@dataclass(frozen=True, slots=True) class SnapshotEntry: path: str; sha256: str; size: int; media_type: str; tier: SnapshotTier; written_at: datetime`
  - `@dataclass(frozen=True, slots=True) class SnapshotManifest: entries: tuple[SnapshotEntry, ...]; schema_version: int = 1` with `def by_path(self) -> Mapping[str, SnapshotEntry]` and `def same_files(self, other: SnapshotManifest) -> bool` (equal `(path, sha256)` sets)
  - `def encode_manifest(manifest: SnapshotManifest) -> bytes` (canonical JSON: entries sorted by path, `sort_keys=True`, `separators=(",", ":")`, `written_at` ISO-8601 UTC)
  - `def decode_manifest(data: bytes) -> SnapshotManifest` (validates every path and sha; raises `SnapshotCorrupt`)
  - `@dataclass(frozen=True, slots=True) class SnapshotPointer: version: int; manifest_sha256: str; manifest_key: str`
  - `@dataclass(frozen=True, slots=True) class LeaseFence: work_id: UUID; worker_id: str; generation: int`
  - `SaveStatus = Literal["saved", "unchanged", "stale", "fenced"]`
  - `class SnapshotCorrupt(RuntimeError)`, `class WorkspaceRestoreUnavailable(RuntimeError)`, `class WorkspaceSaveUnavailable(RuntimeError)`
  - Protocol `WorkspaceSnapshotStore` in `ports.py`:
    - `async def current(self, *, workspace_id: str, thread_id: str) -> SnapshotPointer | None`
    - `async def read_manifest(self, *, workspace_id: str, pointer: SnapshotPointer) -> SnapshotManifest`
    - `async def read_file(self, *, workspace_id: str, entry: SnapshotEntry) -> bytes`
    - `async def store_files(self, *, workspace_id: str, files: Sequence[tuple[SnapshotEntry, bytes]]) -> int` (returns how many were uploaded)
    - `async def save(self, *, workspace_id: str, project_id: str, thread_id: str, expected_version: int | None, manifest: SnapshotManifest, fence: LeaseFence | None) -> tuple[SaveStatus, SnapshotPointer | None]`
    - `async def touch(self, *, workspace_id: str, thread_id: str) -> None`
    - `async def forget(self, *, workspace_id: str, thread_id: str) -> None`

- [ ] **Step 1: Write the failing tests**

```python
def test_tiers():
    assert tier_for("reads/op-1.json") == "raw_input"
    assert tier_for("work/conversation_history/e1.md") == "raw_input"
    assert tier_for("work/large_tool_results/x") == "raw_input"
    assert tier_for("work/deals_clean.csv") == "work_product"
    assert tier_for("scratch/notes.md") == "work_product"
    assert tier_for("outputs/table.csv") == "work_product"

@pytest.mark.parametrize("bad", ["../x", "/etc/passwd", "outputs/../../x", "inputs/a.md",
                                 ".deepagent/x", "brand/x", "", "scratch/"])
def test_validate_snapshot_path_refuses(bad):
    with pytest.raises(SnapshotCorrupt):
        validate_snapshot_path(bad)

def test_manifest_round_trip_is_canonical():
    m = SnapshotManifest(entries=(entry("scratch/b.md"), entry("outputs/a.csv")))
    data = encode_manifest(m)
    assert decode_manifest(data) == SnapshotManifest(entries=tuple(sorted(m.entries, key=lambda e: e.path)))
    assert encode_manifest(decode_manifest(data)) == data

def test_decode_refuses_bad_sha_and_paths():
    with pytest.raises(SnapshotCorrupt):
        decode_manifest(b'{"schema_version":1,"entries":[{"path":"../x","sha256":"' + b"a"*64 + b'"}]}')
```

- [ ] **Step 2: Run it to make sure it fails** — Run: `uv run pytest tests/agents/test_workspace_snapshot.py -v`. Expected: FAIL (module missing)
- [ ] **Step 3: Implement the module and the protocol** as above
- [ ] **Step 4: Run the tests** — Expected: PASS
- [ ] **Step 5: Commit** — `git commit -m "F3 P1: snapshot manifest model and store protocol"`

---

### Task 3: The snapshot store (Postgres + R2)

**Files:**
- Create: `platform/api/clue_api/agent_workspace_snapshots.py`
- Test: `tests/api/test_agent_workspace_snapshots_db.py`

**Interfaces:**
- Consumes: Task 2 types; `clue_storage.record_artifact`, `retain_artifact`, `release_artifacts`,
  `read_verified_artifact`, `artifact_key`, `content_address`; `clue_fleet.lease.hold_work_lease`.
- Produces: `class DbWorkspaceSnapshotStore(WorkspaceSnapshotStore)` with
  `__init__(self, *, storage: StorageBackend, conn_factory: ConnFactory = transaction, concurrency: int = 16)`.

Behaviour the implementer must follow:
- **`store_files`:** for each file whose `artifact_key(ws, sha)` row is not live,
  `record_artifact(...)` first (its docstring rule), then `storage.put`. Uploads run with an
  `asyncio.Semaphore(concurrency)`. The bytes' sha is checked against the entry before upload.
- **`save`:** one transaction does all of this, in order:
  1. If `fence` is set, `hold_work_lease(conn, work_id=WorkId(fence.work_id), worker_id=fence.worker_id, generation=LeaseGeneration(fence.generation))`; False → return `("fenced", None)`.
  2. The manifest bytes are already stored: the caller (and `save` itself, first thing, outside
     the transaction) passes them through `store_files`, so the record never names missing
     bytes.
  3. Compare-and-set: `expected_version is None` → `INSERT ... VALUES (..., 1, ...) ON CONFLICT
     (workspace_id, thread_id) DO NOTHING RETURNING version`; otherwise `UPDATE agent_workspace_snapshot
     SET version = version + 1, manifest_artifact_key = :key, manifest_sha256 = :sha,
     last_activity_at = now(), updated_at = now() WHERE workspace_id = :ws AND thread_id = :t AND
     version = :v RETURNING version`. No row → `("stale", None)`.
  4. `release_artifacts(kind="agent_workspace_snapshot", reference_id=thread_id)`, then
     `retain_artifact` for the manifest and every entry under the same kind and id, so the
     references always name exactly the current version.
- **`touch`:** `UPDATE ... SET last_activity_at = now()`.
- **`forget`:** delete the row and `release_artifacts` for the thread (Phase 2 erases the bytes).
- **`read_file` / `read_manifest`:** `read_verified_artifact` (checks sha, size, workspace); any
  `StorageError` becomes `WorkspaceRestoreUnavailable`; a mismatch becomes `SnapshotCorrupt`.

- [ ] **Step 1: Write the failing DB tests** (each in `rollback_conn`-style isolation with committed rows cleaned up, `FsStorage(tmp_path / "store")`)

```python
def test_first_save_creates_version_1_and_reads_back()          # current() -> version 1; read_manifest == saved; read_file bytes equal
def test_second_save_with_expected_version_moves_to_2()
def test_stale_expected_version_is_refused()                     # save(expected=1) after another saved 2 -> ("stale", None); row still 2
def test_concurrent_first_saves_one_wins()                       # two expected=None saves -> one "saved", one "stale"
def test_save_with_lost_lease_is_fenced()                        # acquire_work_lease twice (takeover) -> old fence -> ("fenced", None)
def test_identical_bytes_are_uploaded_once()                     # counting storage wrapper: second store_files of same file -> 0 uploads
def test_references_name_only_the_current_version()              # artifact_reference rows for thread == entries of v2 + manifest
def test_tampered_blob_raises_corrupt()                          # overwrite blob in FsStorage -> read_file raises SnapshotCorrupt
def test_storage_down_raises_restore_unavailable()               # storage.get raises StorageError -> WorkspaceRestoreUnavailable
def test_forget_deletes_the_record()                             # current() -> None
```

- [ ] **Step 2: Run them to make sure they fail** — Run: `<DB prefix> uv run pytest tests/api/test_agent_workspace_snapshots_db.py -v`. Expected: FAIL
- [ ] **Step 3: Implement `DbWorkspaceSnapshotStore`**
- [ ] **Step 4: Run the tests** — Expected: PASS
- [ ] **Step 5: Commit** — `git commit -m "F3 P1: DbWorkspaceSnapshotStore — compare-and-set under the fleet lease"`

---

### Task 4: Write only what changed

**Files:**
- Create: `platform/agents/clue_agents/tree_sync.py`
- Test: `tests/agents/test_tree_sync.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True, slots=True) class TreeSyncReport: written: tuple[str, ...]; removed: tuple[str, ...]; unchanged: int`
  - `def sync_directory(parent_fd: int, name: str, files: Mapping[str, bytes], *, frozen: bool) -> TreeSyncReport`

Rules: open `name` under `parent_fd` with `O_NOFOLLOW` (create 0700 if missing). If `frozen`,
thaw it first (dirs 0700, files 0600). A file whose size and sha256 match is untouched. A new or
different file is written to a `.clue-tmp-*` temp and `os.replace`d in. A file not in `files` is
unlinked, and empty directories left behind are removed. If `frozen`, freeze it again at the end
(dirs 0500, files 0400). Links and special files raise `WorkspaceSecurityError`. Relative paths
are validated with the backend's existing path rules (no `..`, no absolute paths, no empty
segments).

- [ ] **Step 1: Write the failing tests**

```python
def test_second_sync_with_same_files_writes_nothing(tmp_path)    # report.written == (), unchanged == 3
def test_changed_file_is_replaced_only(tmp_path)                 # written == ("context/project/budget.json",) shape: one path
def test_missing_file_is_removed_and_empty_dirs_pruned(tmp_path)
def test_frozen_tree_ends_read_only(tmp_path)                    # dir mode 0o500, file mode 0o400
def test_symlink_in_tree_is_refused(tmp_path)
def test_binary_and_empty_files(tmp_path)                        # b"" and b"\x00\xff" round-trip
```

- [ ] **Step 2: Fail** — Run: `uv run pytest tests/agents/test_tree_sync.py -v`
- [ ] **Step 3: Implement**
- [ ] **Step 4: Pass**
- [ ] **Step 5: Commit** — `git commit -m "F3 P1: sync_directory — write only new or changed files"`

---

### Task 5: Recipe folders written only where changed (WS-36)

**Files:**
- Modify: `platform/agents/clue_agents/workspace.py:1011-1090` (replace `reset_materialized_trees` + `materialize_bytes` with `sync_materialized_trees`); `platform/agents/clue_agents/resources.py:330-366`
- Test: `tests/agents/test_resource_materialization.py` (extend), `tests/agents/test_workspace_backend.py` (update callers of the removed methods)

**Interfaces:**
- Consumes: `sync_directory` (Task 4).
- Produces: `AnchoredAgentWorkspaceBackend.sync_materialized_trees(self, trees: Mapping[str, Mapping[str, bytes]]) -> Mapping[str, TreeSyncReport]`.
  - Keys must be exactly the three `_MATERIALIZED_PREFIXES`.
  - The existing UTF-8 and trusted-path checks of `materialize_bytes` apply to every file.
  - Runs under the exclusive filesystem lock; the trees end frozen.
  - `reset_materialized_trees` and `materialize_bytes` are deleted.

- [ ] **Step 1: Write the failing tests**

```python
def test_second_materialize_with_same_snapshot_writes_only_new_input(tmp_path)
    # materialize snapshot S with inputs/user-message.txt "a"; again with "b" -> reports:
    # .deepagent written == (), context written == (), inputs written == ("inputs/user-message.txt",)
def test_changed_budget_rewrites_only_budget(tmp_path)
def test_new_skill_version_rewrites_only_deepagent_files_that_changed(tmp_path)
def test_agent_folders_untouched_by_materialize(tmp_path)        # scratch/notes.md mtime and bytes unchanged
```

- [ ] **Step 2: Fail**
- [ ] **Step 3: Implement**
  - `AgentResourceMaterializer._write_trees` builds the three file maps (the manifest file included) and calls `sync_materialized_trees`.
  - Verification (`:352-359`) and `mark_resources_frozen` / `mark_materialized` stay as they are.
- [ ] **Step 4: Pass** — Run: `uv run pytest tests/agents/test_resource_materialization.py tests/agents/test_workspace_backend.py -v`
- [ ] **Step 5: Commit** — `git commit -m "F3 P1: recipe folders written only where changed (WS-36)"`

---

### Task 6: Worker areas and the chat layout (WS-15, AW-9)

**Files:**
- Create: `platform/agents/clue_agents/worker_area.py`
- Modify: `platform/agents/clue_agents/workspace.py` (layout, root, path helpers, `purge_thread` → `remove_chat`, mounts from the chat folder); `platform/api/clue_api/sandbox/workspaces.py:144-196`; `platform/api/clue_api/sandbox/docker_runner.py:48,99-116,189`
- Test: `tests/agents/test_worker_area.py`, `tests/agents/test_workspace_backend.py` (layout tests), `tests/api/sandbox/test_workspaces.py`

**Interfaces:**
- Produces:
  - `ChatScope` — `@dataclass(frozen=True, slots=True) class ChatScope: workspace_id: str; project_id: str; thread_id: str` (in `workspace.py`), plus `AgentWorkspaceLease.chat -> ChatScope`.
  - `class WorkerArea` with `name: str`, `path: Path`, `def mark_in_use(self, chat: ChatScope) -> None`, `def mark_idle(self, chat: ChatScope) -> None`, `def in_use(self) -> frozenset[ChatScope]`, `def close(self) -> None` (thread-safe; counts nested uses).
  - `def claim_worker_area(root: Path, *, max_areas: int = 64) -> WorkerArea`. Claims the first `<root>/workers/area-<n>` whose `area-<n>.lock` takes `LOCK_EX|LOCK_NB`, then wipes its contents. It also wipes and removes every other `area-<m>` whose lock it can take, releasing each lock after. Raises `RuntimeError` when all `max_areas` are taken.
  - `def process_worker_area(root: Path) -> WorkerArea` — memoised for the process, so every factory in one fleet process shares one area.
  - Factory constructor gains `area: WorkerArea | None = None`; with an area, the factory's root
    is `area.path` (the prepared root is created there).
  - Chat layout under the factory root: `chats/<ws>/<project>/<thread>/`, holding `agent/` (the thread root: `_LAYOUT`, audited exactly as today), `brand/`, `project/`, `attachments/`, `snapshot-note.json`, `last-used`.
  - Factory: `def chat_host_path(self, chat: ChatScope) -> Path`; `def chat_dir_fd(self, chat: ChatScope) -> int` (creates 0700 dirs); `thread_host_path(chat)` → `<chat>/agent`; `def remove_chat(self, chat: ChatScope) -> bool`.
    - `purge_thread`, `erase_for_privacy` and `purge_terminal` collapse into `remove_chat`.
    - `create`/`acquire` call `area.mark_in_use(chat)` and touch `last-used`; `release` calls `area.mark_idle(chat)` and touches `last-used`.
  - Deleted: `project_host_path`, `library_parent_fd`, `project_parent_fd`, `remove_project_tree`, `MountRequest.project_library_name`.
  - `_open_mounts` opens `<chat>/brand`, `<chat>/project` and `<chat>/attachments`. `brand` stays a `(brand_id, version)` pair so `acquire`'s mount-equality check still works. The versioned project mount's `reopen` reopens `<chat>/project`.
  - `sandbox_mounts_for_lease(lease, workspaces, *, brand, project_library, attachments) -> SandboxMounts`: host paths `<chat>/agent/{scratch,work,outputs}` read-write, `<chat>/agent/{inputs,context,reads}` and `<chat>/{brand,project,attachments}` read-only.
  - `docker_runner.build_command(..., area: str | None)` adds `--label clue.worker-area=<area>`; `def kill_area_containers(area: str) -> int` runs `docker ps -q --filter label=clue.worker-area=<area>` and kills them.

- [ ] **Step 1: Write the failing tests**

```python
def test_claim_takes_first_free_area(tmp_path)                   # area-0 held by another process -> claims area-1
def test_two_processes_claim_different_areas(tmp_path)            # multiprocessing: two claims -> different names
def test_dead_area_is_wiped_at_claim(tmp_path)                    # area-0 with files, no lock holder -> claim wipes it
def test_live_area_is_never_touched(tmp_path)                     # child process holds area-0 lock with files -> files remain
def test_process_worker_area_is_memoised(tmp_path)
def test_thread_root_is_inside_chat_folder(tmp_path)              # factory.thread_host_path(chat) == root/chats/ws-1/project-1/thread-1/agent
def test_two_chats_of_one_project_get_separate_folders(tmp_path)
def test_remove_chat_removes_whole_folder(tmp_path)
def test_sandbox_mounts_point_into_the_chat_folder(tmp_path)      # brand -> <chat>/brand, project -> <chat>/project
def test_build_command_carries_area_label()
```

- [ ] **Step 2: Fail** — Run: `uv run pytest tests/agents/test_worker_area.py tests/agents/test_workspace_backend.py tests/api/sandbox/test_workspaces.py tests/api/sandbox/test_docker_runner.py -v`
- [ ] **Step 3: Implement**
  - Update every existing test that relied on the old layout.
  - `tests/agents/workspace_helpers.py:make_factory` keeps working without an area: the factory root is the prepared root, and the layout is the same.
- [ ] **Step 4: Pass**
- [ ] **Step 5: Commit** — `git commit -m "F3 P1: worker areas and per-chat folders (WS-15, AW-9)"`

---

### Task 7: Each chat's own brand and project files (WS-37) and the library epoch

**Files:**
- Modify: `platform/api/clue_api/brand_library.py:115-190`, `project_library.py:170-760`, `project_attachments.py:130-270`, `project_root_writer.py:200-300`, `project_library_refresh.py`, `agent_turn_fleet_wiring.py:600-800,1004-1012`, `projections_main.py:169-190`, `agent_turn_wiring.py:2295-2310`, `stage0_card_dsar.py:190-200`
- Test: `tests/api/test_brand_library_db.py`, `test_project_library_db.py`, `test_project_attachments_sync_db.py`, `test_project_root_writer_db.py` (update); new cases below

**Interfaces:**
- Consumes: `sync_directory` (Task 4), `ChatScope` and `chat_dir_fd` (Task 6).
- Produces:
  - `async def ensure_brand_library(workspaces: AgentWorkspaceFactory, *, chat: ChatScope, pin: KnowledgePinRow, documents: Sequence[PinnedDocument]) -> str` (returns the brand version, as today)
  - `async def ensure_project_library(conn, storage, artifacts, workspaces, *, chat: ChatScope, snapshot: ProjectLibrarySnapshot | None = None) -> ProjectLibrarySnapshot` (the `force` parameter is deleted). It reads the installed digest from `<chat>/project/index.json`; when the digest differs it compiles and calls `sync_directory(chat_fd, "project", files, frozen=True)`.
  - `async def sync_pinned_project_library(workspaces, *, chat: ChatScope, files: Sequence[PinnedProjectFile]) -> None` replaces `materialize_pinned_project_library`. The retry path syncs the pin's files into the chat's own `project/`, so there is no `pinned-*` tree.
  - `async def sync_project_attachments(workspaces, artifacts, conn, *, chat: ChatScope) -> int`
  - `ProjectRootWriter` gains `chat: ChatScope`; `_refresh` calls `ensure_project_library(..., chat=self.chat)`.
  - `async def bump_project_library_epoch(conn: AsyncConnection, *, workspace_id: str, project_id: str) -> int` (upsert `epoch = epoch + 1`) in `project_library.py`. `project_library_digest` adds `"epoch": <current epoch or 0>` to its facts.
  - `ProjectLibraryRefresher.__init__(self, *, conn_factory: ConnFactory = transaction)`. `refresh(*, workspace_id, project_id, force=False) -> None`: `force` → bump the epoch in its own transaction; otherwise do nothing. It never raises; a failure is logged as before.
  - `projections_main.py` stops building a workspace factory.

- [ ] **Step 1: Write the failing tests**

```python
def test_two_chats_of_one_project_hold_separate_copies()          # sync both; delete chat A's folder; chat B's project/ intact
def test_second_turn_with_unchanged_digest_writes_nothing()       # sync report empty
def test_epoch_bump_moves_the_digest()                            # digest before != after bump_project_library_epoch
def test_forced_refresh_bumps_epoch_and_touches_no_disk(tmp_path) # refresher.refresh(force=True) -> epoch 2; tmp root unchanged
def test_retry_turn_syncs_pinned_files_into_chat_copy()           # no pinned-* directory anywhere under the root
def test_versioned_write_refreshes_the_chats_own_copy()           # write via ProjectRootWriter -> <chat>/project/<doc>.md has new text
def test_attachments_land_in_the_chat_folder()
```

- [ ] **Step 2: Fail** — Run: `<DB prefix> uv run pytest tests/api/test_brand_library_db.py tests/api/test_project_library_db.py tests/api/test_project_attachments_sync_db.py tests/api/test_project_root_writer_db.py -v`
- [ ] **Step 3: Implement**
  - In `ProjectConversationTurnRunner.run`, create the chat folder (`chat_dir_fd`) before syncing the libraries, then pass `chat=ChatScope(...)` everywhere.
  - Delete the `pinned_tree_name` branch and the `finally` block's `remove_project_tree` (`:736`, `:1004-1012`).
  - Update the two DSAR sites to keep calling `refresh(force=True)`, which now bumps the epoch.
- [ ] **Step 4: Pass**
- [ ] **Step 5: Commit** — `git commit -m "F3 P1: each chat syncs its own brand and project copy (WS-37); library epoch"`

---

### Task 8: Restore and save (WS-6, WS-7, WS-8, WS-10, WS-11, WS-22)

**Files:**
- Create: `platform/agents/clue_agents/workspace_snapshotter.py`
- Modify: `platform/agents/clue_agents/workspace.py` (factory and lease hooks)
- Test: `tests/agents/test_workspace_snapshotter.py` (uses an in-memory `WorkspaceSnapshotStore` fake defined in the test module)

**Interfaces:**
- Consumes: Tasks 2, 4, 6.
- Produces:
  - `@dataclass(frozen=True, slots=True) class RestoreReport: warm: bool; downloaded: int; deleted: int; bytes: int; duration_ms: int; imported_legacy: bool`
  - `@dataclass(frozen=True, slots=True) class SaveReport: status: SaveStatus; uploaded: int; bytes: int; version: int | None; duration_ms: int`
  - `class WorkspaceSnapshotter` with `__init__(self, *, store: WorkspaceSnapshotStore, concurrency: int, legacy_root: Path | None = None)`, `async def restore(self, lease: AgentWorkspaceLease) -> RestoreReport` and `async def save(self, lease: AgentWorkspaceLease) -> SaveReport`.
  - Factory constructor gains `snapshotter: WorkspaceSnapshotter | None = None` (the `area` came in Task 6).
  - Factory gains `async def acquire_restored(self, *, workspace_id, project_id, thread_id, execution_id, policy, mounts=_NO_MOUNTS, artifact_sink=None, fence: LeaseFence | None = None) -> AgentWorkspaceLease` (`acquire`, then `restore`; it releases the lease if restore raises).
  - Factory gains `async def release_saved(self, lease: AgentWorkspaceLease) -> None` (a best-effort `save` when the lease has unsaved writes, logged on failure, then `release`).
  - `AgentWorkspaceLease` gains `fence: LeaseFence | None` and `async def save_snapshot(self) -> SaveReport`. Without a snapshotter it returns `SaveReport(status="unchanged", ...)`.

Local version note, `<chat>/snapshot-note.json` (outside `agent/`):
`{"version": int, "manifest_sha256": str, "unsaved": bool}`.

**Restore rules:**
- Read the record.
- **No record:**
  - if no note exists and `legacy_root/<ws>/projects/<p>/threads/<t>/` exists, copy its `scratch reads work outputs` regular files in (validated, no links), with `imported_legacy=True`;
  - otherwise keep the local folders as they are.
- **Record equals the note** (unsaved or not): warm; nothing downloaded.
- **Otherwise:**
  - remove the note first;
  - download the file list;
  - keep files whose sha matches, download the missing or different entries (bounded by `concurrency`), delete local files that are not listed;
  - write the note last with `unsaved=false`.
- Any failure removes the note and raises (`WorkspaceRestoreUnavailable` for storage, `SnapshotCorrupt` for a hash or path problem).
- Restore never touches `.deepagent/ inputs/ context/`, `brand/`, `project/` or `attachments/` (WS-18).

**Save rules:**
- Walk the saved folders, build the file list, carry `written_at` forward for unchanged `(path, sha)`.
- **Same files as the base:** call `touch` and return `"unchanged"`.
- **Otherwise:**
  - `store_files` the new bytes;
  - call `save(expected_version=base version or None, fence=lease.fence)`;
  - on `"saved"`, write the note and, if the chat was imported, delete its legacy thread folder;
  - on `"stale"` or `"fenced"`, remove the note and log `agent_workspace.save_refused` with both versions.
- Storage errors are retried 3 times (0.5 s, 1 s, 2 s). After that, set the note's `unsaved=true` (keeping the base version) and raise `WorkspaceSaveUnavailable`.
- Emit the `agent_workspace.restore` and `agent_workspace.save` log events with every report field (WS-20).

- [ ] **Step 1: Write the failing tests**

```python
def test_new_chat_starts_empty_and_first_save_is_version_1(tmp_path)
def test_warm_restore_downloads_nothing(tmp_path)                 # fake store counts read_file calls == 0
def test_stale_copy_downloads_only_changed_files(tmp_path)        # 3 files, 1 changed elsewhere -> downloaded == 1
def test_restore_deletes_files_not_in_the_manifest(tmp_path)
def test_restore_refuses_escaping_path(tmp_path)                  # manifest with "../x" -> SnapshotCorrupt, nothing written outside
def test_round_trip_keeps_empty_and_binary_files(tmp_path)
def test_failed_restore_leaves_no_note(tmp_path)                  # fake read_file raises on 2nd file -> note absent
def test_restore_never_touches_recipe_folders_or_libraries(tmp_path)
def test_unchanged_save_only_touches(tmp_path)                    # status "unchanged", version unchanged, touch called
def test_stale_save_removes_note(tmp_path)
def test_save_storage_down_marks_unsaved_and_raises(tmp_path)     # note.unsaved True; WorkspaceSaveUnavailable
def test_unsaved_copy_is_kept_and_saved_next_turn(tmp_path)       # next restore warm (no download), next save -> "saved"
def test_legacy_folder_is_imported_then_removed_after_save(tmp_path)
def test_written_at_carries_forward_for_unchanged_files(tmp_path)
```

- [ ] **Step 2: Fail** — Run: `uv run pytest tests/agents/test_workspace_snapshotter.py -v`
- [ ] **Step 3: Implement**
- [ ] **Step 4: Pass**
- [ ] **Step 5: Commit** — `git commit -m "F3 P1: WorkspaceSnapshotter — restore and save with a local version note"`

---

### Task 9: Wire it into every agent (WS-8, WS-9, WS-14, WS-20)

**Files:**
- Modify: `platform/api/clue_api/agent_workspace_wiring.py:55-90`; `agent_platform_wiring.py:428-510`; `agent_turn_fleet_wiring.py:416, 842-850, 1004-1010, 1524-1570`; `conversation_turns.py:463-531`; `agent_runtime_wiring.py:829-903`; `quality_research_wiring.py:993-1001, 1086-1111, 1307-1318, 1393`; `specialist_wiring.py:334-340, 493`; `account_research_turn_wiring.py:541-547, 728-729`; `onboarding_synthesis_wiring.py:973-979, 1109-1110`; `stage0_trial.py:757-763, 846-847`; `run_python_tool.py:132-160, 262-266`; `crm/read_sinks.py`; `sandbox/workspaces.py:85`
- Test: `tests/api/test_agent_workspace_wiring.py`, `tests/api/test_agent_runtime_wiring_db.py`, `tests/api/test_sandbox_registration.py` (extend)

**Interfaces:**
- Consumes: Tasks 3, 6, 8.
- Produces:
  - **`build_agent_workspace_factory(*, storage, settings=None, source_root=None, home_root=None) -> AgentWorkspaceFactory`:**
    - snapshots enabled → root = `process_worker_area(Path(settings.agent_workspace_root))`, with a `WorkspaceSnapshotter(store=DbWorkspaceSnapshotStore(storage=storage), concurrency=settings.agent_workspace_transfer_concurrency, legacy_root=Path(settings.agent_workspace_root))`;
    - disabled → root = `<root>/local`, no area, no snapshotter (the emergency switch, WS-21).
  - **`AgentTurnWorkHandler.handle`:**
    - builds `LeaseFence(work_id=context.work_id, worker_id=context.worker_id, generation=int(context.lease_generation))` and passes it as `ProjectConversationTurnRunner.run(*, turn_id, workspace_id, fence: LeaseFence | None = None)`;
    - `WorkspaceRestoreUnavailable` → `WorkResult(outcome="workspace_unavailable", requeue=True, requeue_after=timedelta(seconds=30))`.
  - **Every acquire site** listed under Files uses `await workspaces.acquire_restored(...)` and `await workspaces.release_saved(lease)` in its `finally`. The research reconciliation copy (`:1086-1111`) keeps reading its source thread through `acquire_restored`, so it reads the snapshot on any worker. (The Phase 3 checks of WS-33 stay in Phase 3.)
  - **`AgentFinalizationAuthority.finalize`:** after `snapshot_outputs` (`:855`) and before `commit_finalization_authority` (`:890`), call `report = await self._lease.save_snapshot()`. `"stale"` or `"fenced"` raises `WorkspaceConflict` (a zombie must not commit). A replayed finalization (`_existing`) does not save.
  - **Per-turn registries:**
    - `AgentWorkspaceFactory` takes `turn_bindings: Sequence[TurnBinding] = ()`.
    - `TurnBinding` is a protocol in `ports.py` with `def bind(self, execution_id: ExecutionId, lease: AgentWorkspaceLease) -> None` and `def unbind(self, execution_id: ExecutionId) -> None`.
    - `CrmReadSinks` and `SandboxWorkspaces` implement it; the sandbox builds its mounts from `lease.mounts`.
    - `acquire_restored` binds; `release_saved` unbinds. The explicit register/release in `conversation_turns.py:463-531` is deleted.
  - **`run_python`:** output spills go through `lease.backend.write_spill_file(name: str, data: bytes) -> str`, a new backend method (`reads/<name>`, quota-checked, trusted write), reached through the sandbox binding. `_spill`'s raw `os.open` is deleted (spec §12).
  - **Area label:** `run_python` passes `area=<factory area name or None>` to `build_command`.

- [ ] **Step 1: Write the failing tests**

```python
def test_factory_uses_process_area_when_snapshots_enabled(tmp_path)
def test_factory_uses_local_root_when_snapshots_disabled(tmp_path)
def test_finalize_saves_before_commit()                            # fake lease.save_snapshot records call order: snapshot_outputs, save, commit
def test_finalize_refuses_commit_when_save_is_fenced()
def test_restore_unavailable_requeues_the_turn()                   # handler returns requeue=True, outcome "workspace_unavailable"
def test_acquire_restored_binds_and_release_unbinds_registries()
def test_run_python_spill_counts_against_quota(tmp_path)           # quota 10 bytes -> spill refused
def test_every_acquire_site_uses_acquire_restored()                # grep-style test over platform/api/clue_api: no bare ".acquire(" on workspaces outside workspace.py
```

- [ ] **Step 2: Fail**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Pass**
  - Run: `<DB prefix> uv run pytest tests/api/test_agent_workspace_wiring.py tests/api/test_agent_runtime_wiring_db.py tests/api/test_sandbox_registration.py tests/api/test_agent_turn_wiring_db.py tests/api/test_specialist_wiring_db.py -v`
  - Then the research and onboarding DB suites that construct factories: `tests/arv2/test_quality_runtime_db.py tests/arv2/test_research_receipt_spill_db.py`.
- [ ] **Step 5: Commit** — `git commit -m "F3 P1: every agent restores at start and saves at finalize (WS-8, WS-9, WS-14)"`

---

### Task 10: The cache cleanup and the end of the old purge (WS-16, WS-17)

**Files:**
- Create: `platform/api/clue_api/agent_workspace_cache.py`, `scripts/remove_legacy_agent_workspaces.py`
- Delete: `platform/api/clue_api/agent_cleanup.py`, `tests/api/test_agent_cleanup.py`, `tests/api/test_agent_cleanup_db.py`
- Modify: `fleet_main.py:376-409, 1071-1075, 1474-1537`; `agent_turn_wiring.py:2264-2275` (privacy erase); `platform/agents/clue_agents/workspace.py` (dead code: `cleanup`, `discard_failed_materialization`, `purge_terminal`, `authorize_cleanup`/`cleanup_authorized` and its two calls in `agent_runtime_wiring.py:850,902`); `settings.py`, `.env.example`, `.env` (retire `agent_workspace_retention_s`, `agent_cleanup_interval_s`); `platform/agents/clue_agents/manual/build.py:902` (the retention text it renders)
- Test: `tests/api/test_agent_workspace_cache.py`

**Interfaces:**
- Consumes: `WorkerArea` (Task 6), `AgentWorkspaceFactory.remove_chat`.
- Produces:
  - `@dataclass(frozen=True, slots=True) class CacheSweepResult: removed: tuple[str, ...]; bytes_freed: int`
  - `class AgentWorkspaceCacheJob` with `__init__(self, *, area: WorkerArea, idle_s: float, max_bytes: int)` and `def run_once(self, *, now: float | None = None) -> CacheSweepResult`:
    - skips `area.in_use()`;
    - removes chats whose `last-used` mtime is older than `idle_s`, then the oldest idle chats while the area is over `max_bytes`;
    - deletes `snapshot-note.json` first, then the folder.
  - `fleet_main._start_workspace_cache_sweep(settings, job)` runs every `agent_workspace_cache_sweep_interval_s` when snapshots are on. With snapshots off, it runs with `idle_s = 86400`.
  - **At process start, right after the area is claimed:**
    - `kill_area_containers(area.name)` when the sandbox is enabled;
    - delete `/tmp/arv2-media-*` directories older than 6 hours that this uid owns.
  - **Privacy erase:** `AgentPrivacyService` calls `workspaces.remove_chat(chat)` and `await snapshot_store.forget(workspace_id=..., thread_id=...)`. A cached copy elsewhere can never match a missing record and is removed by its own worker's sweep.
  - **`scripts/remove_legacy_agent_workspaces.py --root <path> [--older-than-hours 48] [--apply]`:** lists, then (with `--apply`) removes, entries of the old layout under the root (`<root>/<ws>/library`, `<root>/<ws>/projects/*/{library,attachments,pinned-*,threads}`) not modified within the window. Dry run is the default. It never touches `<root>/workers` or `<root>/local`.

- [ ] **Step 1: Write the failing tests**

```python
def test_idle_chat_is_removed_after_idle_window(tmp_path)          # last-used 31 min ago -> removed; note gone
def test_chat_in_use_is_kept_even_when_old(tmp_path)
def test_size_cap_removes_oldest_idle_first(tmp_path)
def test_sweep_never_leaves_area(tmp_path)                        # a sibling area's files untouched
def test_privacy_erase_forgets_the_version_record()                # DB: row gone, local chat folder gone
def test_legacy_script_dry_run_lists_and_keeps(tmp_path)
def test_legacy_script_apply_removes_only_old_layout(tmp_path)
```

- [ ] **Step 2: Fail**
- [ ] **Step 3: Implement**, deleting the old job, its loop, its two settings and its tests in the same change
- [ ] **Step 4: Pass**
  - Run: `<DB prefix> uv run pytest tests/api/test_agent_workspace_cache.py tests/api/test_fleet_wiring.py -v`
  - Then `uv run ruff check platform tests && uv run mypy platform/agents platform/api/clue_api/agent_workspace_cache.py`.
- [ ] **Step 5: Commit** — `git commit -m "F3 P1: worker-area cache sweep replaces the 24-hour purge (WS-16, WS-17)"`

---

### Task 11: The Phase 1 proofs (AW-16)

**Files:**
- Create: `tests/api/test_agent_workspace_scenarios_db.py`
- Test helpers: one in-module helper that runs a "turn" against a factory. It calls `acquire_restored` with a `LeaseFence` from a real `acquire_work_lease`, writes the given files through `lease.backend`, calls `save_snapshot`, then `release_saved`.

Each scenario uses one database (`clue_dushanbe_test`), one `FsStorage`, and two or three factories built on **separate areas** claimed from one temporary root. This is the spec's "two machines".

- [ ] **Step 1: Write the scenarios** (spec §11 tests 1–4, 8, 10, 13, 14, plus WS-18)

```python
def test_1_two_machines_one_chat()          # A writes scratch/notes.md, outputs/t.csv, reads/op.json; B sees exactly those bytes;
                                            # third turn on A detects stale copy, restores B's version (downloaded >= 1)
def test_2_warm_second_turn_downloads_nothing()
def test_3_kill_before_save_and_after_save()  # before: B sees previous version; after save, before commit: B sees new version;
                                              # the retried finalize commits once
def test_4_zombie_save_is_refused()           # takeover bumps generation; old turn's save_snapshot -> "fenced"; record unchanged
def test_8_cleanup_stays_in_its_own_area()    # area A sweep + a fresh claim never touch area B while B runs a turn
def test_10_sandbox_after_restore()           # restored files 0600/0700, owned by uid; sandbox_mounts_for_lease paths exist;
                                              # policy_sweep over the restored tree removes nothing
def test_13_recipe_folders_update_in_place()  # second turn: only inputs/user-message.txt written
def test_14_two_chats_never_share_a_folder()  # same project, same area: separate brand/project copies; removing chat A leaves B's turn intact;
                                              # a project document written in A appears in B's next turn
def test_ws18_resume_on_a_newer_profile()     # chat saved under profile v1 continues under v2 with its agent files intact
```

- [ ] **Step 2: Run them** — Run: `<DB prefix> uv run pytest tests/api/test_agent_workspace_scenarios_db.py -v`. Expected: PASS (they exercise Tasks 1–10; a failure is a bug in those tasks, fixed there).
- [ ] **Step 3: Commit** — `git commit -m "F3 P1: scenario proofs — two machines, kill, zombie, areas, chats (AW-16)"`

---

### Task 12: First live check on the dushanbe stack, and the records

This needs no go: live checks are pre-approved. Report the cost.

- [ ] **Step 1: Migrate the lane's own stack database in place**
  - Run `set -a; source .env; set +a; uv run alembic upgrade head` against `clue_nashville_pm_clone`.
  - Start the stack only as `DEV_STACK.md` says for this lane.
- [ ] **Step 2: Run a real chat turn**
  - In the in-app browser, in a Head of ABM chat, ask for a small CRM-free analysis that writes a note to `scratch/` and a table to `outputs/`.
  - Confirm one `agent_workspace.save` event with `status="saved"`, version 1.
- [ ] **Step 3: Delete the whole area folder on disk** (`<root>/workers/area-*`), then send a follow-up that asks the agent to read back its note and table.
  - Confirm one `agent_workspace.restore` event with `warm=false`, and that the agent quotes the note's contents.
- [ ] **Step 4: Send one more message**
  - Confirm `warm=true`, and an `inputs/`-only write in the recipe folders.
- [ ] **Step 5: Check the compaction path** (spec §12)
  - In a chat long enough to compact, confirm that the summary names a path the agent can read, under `work/conversation_history/`.
  - If not, record it and fix it in a follow-up commit within this task.
- [ ] **Step 6: Write it all down**
  - Record the warm and cold timings, files and bytes, and the turn costs.
  - Add a status line to the spec's §3 table ("P1 built; live check passed <date>"), add the change-log entry, and add a closing note in `_memory/2026-10-22-agent-workspace-f3-spec.md`.
  - Update the CLAUDE.md "Agent workspace is being made machine-independent" paragraph: Phase 1 is built on this branch and is not in production until Phase 2 (Q7).
  - Commit: `git commit -m "F3 P1: live check on the dushanbe stack; records"`

---

## Self-review notes

- **Spec coverage:**

  | Requirement | Task(s) |
  |---|---|
  | WS-1 | T1 |
  | WS-2, WS-3, WS-5 | T2, T3 |
  | WS-4 | T2 (paths), T8 |
  | WS-6, WS-7 | T8 |
  | WS-8 | T3 (compare-and-set and fence), T8 (save) |
  | WS-9 | T9 |
  | WS-10 | T3, T8 |
  | WS-11 | T8, T11 |
  | WS-12 | T9 |
  | WS-13 | T3, T6 |
  | WS-14 | T9 |
  | WS-15 | T6 |
  | WS-16 | T6 (start-up), T10 |
  | WS-17 | T10 |
  | WS-18 | T8, T11 |
  | WS-19, WS-20 | T8 (events), T12 (numbers) |
  | WS-21 | T1, T9, T10 |
  | WS-22 | T8 (import), T10 (script) |
  | WS-36 | T4, T5 |
  | WS-37 | T6, T7 |
  | §12 notes | T9 (spill quota), T10 (dead code), T12 (compaction path) |
  | Settings parity | T1, T10 |

- **Not in Phase 1, by design:** tiers taking effect, receipts, expiry, the agent's file list, the
  staleness instruction, the manual rewrite, and erasure of R2 bytes (Phase 2). The Phase 3
  checks (WS-33–35).
