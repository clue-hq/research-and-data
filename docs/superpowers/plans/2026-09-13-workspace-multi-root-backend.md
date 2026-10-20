# Thread-rooted agent workspace with mounts Implementation Plan (Lane 1, plan 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The deepagent's filesystem is one persistent directory per chat thread plus read-only mounts. There are no per-turn directories. A turn rewrites `inputs/` from durable artifacts at its start and snapshots `outputs/` to artifact storage at its finalize; `scratch/` and `reads/` persist across the thread's turns under one quota.

**Architecture:** `AnchoredAgentWorkspaceBackend` gains a mount table (a reserved first segment resolves to its own anchored root and mode) and keeps every existing path rule. The factory roots the backend at `<ws>/projects/<project>/threads/<thread>/` and opens the mounts the caller asks for. `AgentResourceMaterializer` stops being one-shot: at each turn start it replaces `.deepagent/` and `inputs/` (verifying digests as today), and at each finalize `outputs/` is snapshotted then emptied. Crash resume rebuilds `inputs/` from the same artifacts and verifies the same digests, so the recovery guarantee is unchanged without a frozen copy. Cleanup purges threads, not executions.

**Tech Stack:** Python 3.12, `os.*` with `dir_fd`, `fcntl`, deepagents 0.6.12 `BackendProtocol`, pytest with `tmp_path`, one Alembic revision.

**Spec:** `docs/superpowers/specs/archive/2026-09-13-agent-workspace-reorganization-design.md` — W1, W5, §4.1, §4.2, §4.3 (as amended 2026-09-13: thread-rooted, no per-turn directory).

## Global Constraints

- **Security model unchanged:** 0700 directories owned by the service user; `O_NOFOLLOW | O_DIRECTORY` on every component; regular files only; temp-file + `link` install; no host path in any model-visible string. `tests/agents/test_workspace_backend.py` and `test_workspace_policy.py` stay green (paths updated where the layout moved).
- **On-disk layout (host, never model-visible):**
  `<root>/<workspace_id>/library/brand/<brand_id>/<knowledge_version>/` (plan 2),
  `<root>/<workspace_id>/projects/<project_id>/library/` (plan 2),
  `<root>/<workspace_id>/projects/<project_id>/threads/<thread_id>/` — **the backend root**.
  Segment names `library`, `projects`, `threads` are constants in `workspace.py`.
- **Thread folders:** `_LAYOUT = (".deepagent", "inputs", "scratch", "reads", "outputs")`. `work/` and `delegations/` are gone (delegation is withheld on this surface; `scratch/` is the notebook). `_MATERIALIZED_PREFIXES = (".deepagent", "inputs")` are rewritten by the platform at every turn start and read-only in between.
- **Per-turn state on disk: none.** The turn's identity is the lease's `execution_id` (in-process) and the DB rows; `workspace_root_id = sha256(workspace, project, thread)`.
- **One quota per thread:** the profile's `workspace` block applies to the whole thread directory; profile v51 raises it to `max_file_count: 400`, `max_total_bytes: 20971520` because scratch and reads persist.
- **Retention:** a thread directory is purged when its thread is archived, or when its newest turn is terminal and older than `CLUE_AGENT_WORKSPACE_RETENTION_S` (existing flag, now thread-scoped; `.env.example` comment updated). No new flag.
- **Tests:** offline suites without `.env`; DB suites only on the lane DB with `--ignore-glob='*_live.py' -p no:cacheprovider`. **Commits:** local only, no push, no AI attribution.

---

### Task 1: Mount table on the backend — resolve, read, list, write

**Files:**
- Modify: `platform/agents/clue_agents/workspace.py` (constants 71–80; `AnchoredAgentWorkspaceBackend.__init__` 213–233; `_validate_path` 273–291; `_parent_fd` 293–316; `_open_file` 318–332; `_walk_files` 334–373; `_quota_before_write` 375–391; `list_entries_sync` 621; deepagents `ls`/`glob` 739–802)
- Modify: `platform/agents/clue_agents/__init__.py` (export `WorkspaceMount`, `MountMode`)
- Test: `tests/agents/test_workspace_backend.py`, `tests/agents/workspace_helpers.py` (`policy(readable=…, writable=…)` overrides)

**Interfaces:**

```python
MountMode = Literal["read_only", "read_write"]

@dataclass(frozen=True, slots=True)
class WorkspaceMount:
    name: str            # single validated segment, e.g. "brand" | "project" | "manual"
    directory_fd: int    # open with _DIR_FLAGS, audited private
    mode: MountMode

class AnchoredAgentWorkspaceBackend(BackendProtocol):
    def __init__(self, *, execution_fd, identity, policy, artifact_sink,
                 mounts: Sequence[WorkspaceMount] = ()) -> None: ...
    def _resolve(self, logical: str) -> tuple[int, str, WorkspaceMount | None]:
        """(root fd, path relative to that root, the mount or None for the thread root)."""
```

(`execution_fd` keeps its parameter name for the diff's sake; it is the thread root's descriptor.)

- [ ] **Step 1: Failing tests**

```python
def _mounted_backend(tmp_path: Path, *, mode: MountMode = "read_only"):
    root, factory, lease = make_lease(tmp_path)          # existing helper
    mount_dir = tmp_path / "mount"; mount_dir.mkdir(mode=0o700)
    (mount_dir / "plan.md").write_text("# Plan\n"); os.chmod(mount_dir / "plan.md", 0o400)
    fd = os.open(mount_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    backend = AnchoredAgentWorkspaceBackend(
        execution_fd=os.open(root_of(lease), os.O_RDONLY | os.O_DIRECTORY),
        identity=lease.identity,
        policy=policy(readable=(".deepagent", "inputs", "scratch", "reads", "outputs", "library"),
                      writable=("scratch", "outputs", "library")),
        artifact_sink=RecordingArtifactSink(),
        mounts=(WorkspaceMount(name="library", directory_fd=fd, mode=mode),),
    )
    return backend, mount_dir

def test_a_read_only_mount_is_readable_by_its_virtual_name_and_never_writable(tmp_path): ...
    # read_text_sync("library/plan.md") == "# Plan\n"; write → WorkspaceSecurityError;
    # facade write → error startswith "permission_denied"

def test_root_listing_shows_mounts_as_directories(tmp_path): ...
    # {"path": "library", "is_dir": True, "size": 0} in backend.ls("/").entries

def test_a_mount_cannot_be_escaped_or_shadowed(tmp_path): ...
    # symlink inside the mount → WorkspaceSecurityError; "library/../inputs/x" → error;
    # materialize_bytes("library/x.md") → WorkspaceSecurityError

def test_a_read_write_mount_takes_writes_under_the_thread_quota(tmp_path): ...
    # mode="read_write": write + edit land in mount_dir with mode 0o600 and count toward the
    # same policy quota (policy() allows 20 files: 19 in scratch + 1 in the mount, the 21st refused)
```

- [ ] **Step 2: Run — FAIL** (`unexpected keyword argument 'mounts'`).

- [ ] **Step 3: Implement**

```python
_MOUNT_SEGMENT = re.compile(r"^[a-z][a-z0-9-]{0,31}$")

def __init__(..., mounts=()):
    ...existing...
    by_name: dict[str, WorkspaceMount] = {}
    for mount in mounts:
        if not _MOUNT_SEGMENT.fullmatch(mount.name) or mount.name in _LAYOUT:
            raise WorkspaceConfigurationError("mount name is reserved or malformed")
        if mount.name in by_name:
            raise WorkspaceConfigurationError("duplicate mount name")
        _validate_private_directory(mount.directory_fd)
        by_name[mount.name] = mount
    self._mounts = by_name

def _resolve(self, logical):
    head, _, rest = logical.partition("/")
    mount = self._mounts.get(head)
    if mount is None:
        return self._root_fd, logical, None
    if not rest:
        raise WorkspaceSecurityError("a mount root is a directory, not a file")
    return mount.directory_fd, rest, mount
```

Thread the resolved `(root_fd, relative, mount)` through `_parent_fd`, `_open_file`, `_walk_files`, `read_text_sync`, `write_text_sync`, `edit_text_sync`, `_create_file`, `_replace_file_unlocked`, `_entry`, `stat_entry_sync`, `list_entries_sync` (re-prefix returned paths with `f"{mount.name}/"`). `_validate_path(write=True)`: a `read_only` mount raises `WorkspaceSecurityError("path is inside a read-only mount")`; `materialize=True` into any mount raises. Quota: `_quota_before_write` walks the thread root **and** every `read_write` mount and checks the sum against the policy (one quota, W5). `ls`/`glob` at the root append one `is_dir: True` entry per mount. `close()` closes mount fds.

- [ ] **Step 4: Run** `tests/agents/test_workspace_backend.py tests/agents/test_workspace_policy.py` — PASS. **Step 5: Commit** — `feat(agent-workspace): a mount table — extra anchored roots under reserved virtual segments, read-only or read-write, one quota`.

---

### Task 2: The factory roots the workspace at the thread

**Files:**
- Modify: `platform/agents/clue_agents/workspace.py` (`_LAYOUT`, `WorkspaceIdentity` gains `thread_id`, `AgentWorkspaceFactory.create` 923–990, `acquire` 992–1044, `_reopen_backend` 1046–1103, `_delete_execution` → `_delete_thread` 1129–1159, `erase_for_privacy`/`purge_terminal` 1173–1245)
- Test: `tests/agents/test_workspace_backend.py` (the reopen-after-restart, scope-audit and privacy-erasure tests move to the new layout), `tests/agents/workspace_helpers.py`

**Interfaces:**

```python
LIBRARY_DIR = "library"; PROJECTS_DIR = "projects"; THREADS_DIR = "threads"

@dataclass(frozen=True, slots=True)
class MountRequest:
    """What the caller wants mounted; the factory turns it into open descriptors (plan 2 fills it)."""
    brand: tuple[str, str] | None = None      # (brand_id, knowledge_version) → "brand", read_only
    project_library: bool = False             # → "project", read_only (plan 3 makes it versioned)

class AgentWorkspaceFactory:
    def create(self, *, workspace_id, project_id, thread_id, execution_id, policy,
               mounts: MountRequest = MountRequest()) -> AgentWorkspaceLease: ...
    def acquire(self, *, workspace_id, project_id, thread_id, execution_id, policy,
                mounts: MountRequest = MountRequest()) -> AgentWorkspaceLease:
        """The thread directory is created if absent and reopened if present. The execution id
        keys the in-process lease (one live lease per thread at a time — a second acquire for a
        different execution while one is open is a WorkspaceConflict, matching the one-turn-per-
        thread queue) and stamps the snapshot idempotency."""
    def purge_thread(self, *, workspace_id, project_id, thread_id) -> bool: ...
```

`WorkspaceIdentity(workspace_id, project_id, thread_id, execution_id, workspace_root_id, retention_class)`; `workspace_root_id = "awr_" + sha256(f"{ws}\0{project}\0{thread}")`.

- [ ] **Step 1: Failing tests**

```python
def test_the_factory_roots_the_workspace_at_the_thread(tmp_path):
    root, factory = make_factory(tmp_path)
    lease = factory.create(workspace_id="ws_a", project_id="prj_a", thread_id="thr_a",
                           execution_id=EXECUTION_ID, policy=policy())
    thread = root / "ws_a" / "projects" / "prj_a" / "threads" / "thr_a"
    assert sorted(p.name for p in thread.iterdir()) == [".deepagent", "inputs", "outputs", "reads", "scratch"]
    for p in (thread, thread.parent, thread.parent.parent):
        assert stat.S_IMODE(p.stat().st_mode) == 0o700
    assert lease.identity.workspace_root_id == expected_root_id("ws_a", "prj_a", "thr_a")

def test_scratch_and_reads_survive_across_turns_of_the_thread(tmp_path):
    ...first = create(..., execution_id=E1); first.backend.write_text_sync("scratch/notes.md", "one\n")
    ...finish(first)                                      # snapshot outputs, authorize, release
    ...second = acquire(..., execution_id=E2); assert read "scratch/notes.md" == "one\n"

def test_one_live_lease_per_thread(tmp_path):
    ...first = create(E1); with pytest.raises(WorkspaceConflict): factory.acquire(..., execution_id=E2)

def test_purge_thread_removes_the_directory_and_reports_absence_the_second_time(tmp_path): ...

def test_a_thread_id_is_validated_like_every_other_segment(tmp_path):
    with pytest.raises(WorkspaceConfigurationError): factory.create(..., thread_id="../thr")
```

- [ ] **Step 2: Run — FAIL. Step 3: Implement.** `create`: under `_root_lock`, `_ensure_directory` chain `workspace → projects → <project> → threads → <thread>`; `_LAYOUT` folders created if absent (idempotent — the thread persists). `_active` is keyed by `(ws, project, thread)`; `acquire` reopens the same backend for the same execution (crash resume) and refuses a different execution while one is live. `_delete_thread` replaces `_delete_execution` (removes `threads/<thread>`, rmdir-if-empty upward). `purge_terminal(workspace_id, project_id, thread_id)` and `erase_for_privacy(...)` take the thread. `AgentWorkspaceLease.release()` (new) drops the lease from `_active` without deleting anything; `cleanup()` becomes `release()` plus nothing on disk.

- [ ] **Step 4: Run the two workspace files — PASS. Step 5: Commit** — `feat(agent-workspace): the workspace is rooted at the thread; scratch/ and reads/ persist; one live lease per thread`.

---

### Task 3: Materialize per turn into a persistent directory; snapshot and empty outputs

**Files:**
- Modify: `platform/agents/clue_agents/resources.py` (`AgentResourceMaterializer.materialize` 149–194, `verify_materialized` 196–220), `platform/agents/clue_agents/workspace.py` (`freeze_materialized_trees` 583, `_freeze_tree` 588, a new `reset_materialized_trees()`, `snapshot_outputs` 687–730 gains `empty_after=True`)
- Test: `tests/agents/test_resource_materializer.py` (find the existing materializer tests by `grep -rl AgentResourceMaterializer tests/agents`), `tests/agents/test_workspace_backend.py`

**Behaviour:**

1. `materialize(lease, snapshot, seed_files)` at turn start: `reset_materialized_trees()` makes `.deepagent/` and `inputs/` writable and empties them; write the resource bodies, the seed files (user message, `inputs/current-context/*`; brand and project seeds until plan 2 moves them to mounts) and the manifest; freeze both trees; verify digests exactly as today. The one-shot guard (`resources_frozen or materialization_failed → conflict`) becomes "a live turn already materialized" (guard on the lease, not the directory).
2. `verify_materialized(...)` on crash resume: if the trees are present and frozen, verify digests as today; if absent or partial (the crash hit mid-write), `materialize` again — same artifacts, same bytes.
3. `snapshot_outputs(empty_after=True)`: snapshot exactly as today, then unfreeze and empty `outputs/`, leaving the directory. The finalize envelope names the snapshot refs, as today.
4. `usage_snapshot()` reports the whole thread directory (scratch + reads + inputs + outputs + `.deepagent`); `output_file_count`/`output_bytes` still count `outputs/` at snapshot time.

- [ ] **Step 1: Failing tests** — a second `materialize` on the same lease directory after a finished turn replaces `inputs/` (old file gone, new file present, both trees frozen again); a partial `.deepagent/` (delete the manifest by hand) is rebuilt by `verify_materialized`; `snapshot_outputs(empty_after=True)` persists the refs and leaves `outputs/` empty and writable; `scratch/` is untouched by all of the above.
- [ ] **Steps 2–5:** implement, run, commit — `feat(agent-workspace): inputs and resources are rewritten per turn in the thread directory; outputs are snapshotted then emptied`.

---

### Task 4: The turn wiring uses the thread root; profile v51; skill v28

**Files:**
- Modify: `platform/api/clue_api/agent_turn_fleet_wiring.py:723-728` (`acquire(..., thread_id=submission.thread_id, ...)`), `platform/api/clue_api/head_of_abm_wiring.py:229-240` (the resume branch calls the new `verify_materialized` semantics), `platform/api/clue_api/agent_runtime_wiring.py:541` (`snapshot_outputs(empty_after=True)`), `platform/api/clue_api/onboarding_synthesis_wiring.py:1542` region and `account_research_turn_wiring.py` (their factory calls pass `thread_id=` — the onboarding run's thread id, the research job's synthetic thread id `f"arv2-{job_id}"`), `platform/api/clue_api/agent_workspace_wiring.py` (unchanged)
- Create: `platform/agents/catalog/profiles/head-of-abm/v51/profile.yaml` (copy of v50: `readable_prefixes: [".deepagent", "inputs", "scratch", "reads", "outputs"]`, `writable_prefixes: ["scratch", "outputs"]`, `max_file_count: 400`, `max_total_bytes: 20971520`), `platform/agents/catalog/skills/stage0-interview/v28/SKILL.md` (copy of v27; §1 gains the bullet below; every `work/` mention becomes `scratch/`)
- Modify: `agent_registry_wiring.py` pins, `PROJECT_CONVERSATION_AGENT_PROFILE_ID`, `tests/agents/test_catalog.py`, `tests/api/test_agent_registry_wiring.py` (digest re-measured), `tests/api/test_o6_conversation_composition_db.py`

Skill v28 §1 bullet (founder-reviewed with this plan):

```markdown
- `scratch/` is your notebook for this conversation. What you write there stays across the turns of this chat and nobody else reads it. Use it for what you have read and decided so far in a long conversation (`scratch/notes.md`); never for anything the project should remember — that goes in the project's files (section 6). `inputs/` is this turn's message and cards and is rewritten every turn.
```

- [ ] **Step 1: Failing DB test** — in the composition test, run two turns on one thread through the harness; after the first, write a marker into `scratch/` through the lease; assert the second turn's lease reads it, that `inputs/user-message.txt` holds the second message, and that the host path `<root>/<ws>/projects/<project>/threads/<thread>` is the only directory under `threads/`.
- [ ] **Steps 2–5:** implement, pin, re-measure, run the composition DB test + catalog/registry/onboarding-synthesis/account-research turn tests, commit — `feat(agent-turn): turns run in the thread's workspace; profile v51 grants scratch/ and reads/; skill v28 names the notebook`.

---

### Task 5: Cleanup purges threads

**Files:**
- Modify: `platform/api/clue_api/agent_cleanup.py` (`run_once`), `.env.example` (comment on `CLUE_AGENT_WORKSPACE_RETENTION_S`: now "seconds after a thread's newest turn went terminal"), one Alembic revision adding nullable `thread_id` to `agent_workspace_cleanup_event` and the action `thread_purge` (reversible)
- Test: the existing cleanup DB test file (`grep -rl AgentWorkspaceCleanupJob tests`)

**Behaviour:** one query selects threads whose `status='archived'`, plus threads whose newest `agent_turn_event` is terminal (`completed/failed/cancelled/abandoned/privacy_tombstoned`) and older than the retention window, excluding threads with an in-flight turn and threads already purged; `purge_thread` each; one cleanup event per thread keyed `uuid5(_CLEANUP_NAMESPACE, f"{workspace}:{thread}:thread_purge")`. `AgentCleanupResult` gains `threads_purged`. DSAR (`erase_for_privacy`) purges the thread directory.

- [ ] **Steps:** failing test → implement → `alembic heads` shows one head → commit — `feat(agent-cleanup): thread directories are purged on archive and after retention`.

---

## Self-review

- **Spec coverage (as amended):** W1 thread root + mounts (Tasks 1–2), W5 persistent scratchpad under one quota (Tasks 1–2, 4), `reads/` for W9 (Task 2), per-turn rewrite of inputs and snapshot-then-empty of outputs (Task 3), retention per thread (Task 5), security model preserved (every task's gate). ✔
- **Simplicity check:** no per-turn directory, no second quota envelope, no new env flag, no hidden record; the only new on-disk concept is "a thread has a folder". ✔
- **Type consistency:** `WorkspaceMount`, `MountRequest(brand=, project_library=)`, `WorkspaceIdentity.thread_id`, `purge_thread`, `snapshot_outputs(empty_after=)`, `reset_materialized_trees` are named identically across tasks and match plans 2–4 (which only use the mounts and `reads/`). ✔
