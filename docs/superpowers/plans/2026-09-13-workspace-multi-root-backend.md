# Multi-root agent workspace backend Implementation Plan (Lane 1, plan 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The deepagent's filesystem can present more than one anchored root under one virtual tree — a read-only library mount, a read-write persistent thread scratchpad, and the per-turn folders — with the same security model the single-root backend has today, and the on-disk layout mirrors the platform's hierarchy (`<ws>/projects/<project>/{library,threads,turns}`).

**Architecture:** `AnchoredAgentWorkspaceBackend` gains a mount table: a virtual first segment (`brand`, `project`, `thread`) resolves to its own open directory descriptor and mode; every existing path rule (normalization, `O_NOFOLLOW` walks, private-mode audits, atomic writes, quotas) runs unchanged against whichever root the segment resolves to. The factory creates the new layout and opens the mounts; the turn wiring asks for the `thread` mount only (the libraries arrive in plan 2, the versioned `project` writer in plan 3). Cleanup learns the new layout and purges archived threads' scratch.

**Tech Stack:** Python 3.12, `os.*` with `dir_fd`, `fcntl`, deepagents 0.6.12 `BackendProtocol`, pytest with `tmp_path`.

**Spec:** `docs/superpowers/specs/2026-09-13-agent-workspace-reorganization-design.md` — W1, W5, §4.1, §4.2, §4.3 (concurrency/replay), §4.7.

## Global Constraints

- **Security model unchanged:** directories 0700 and owned by the service user; every component opened with `O_NOFOLLOW | O_DIRECTORY`; files regular only; temp-file + `link` install; no host path in any model-visible string or error. Every existing test in `tests/agents/test_workspace_backend.py` and `test_workspace_policy.py` stays green.
- **Virtual paths:** `normalize_virtual_path` rules unchanged. Mount names are single segments and are reserved: a profile's `readable_prefixes` may list them, and `_LAYOUT` folders may not collide with them.
- **On-disk layout (host, never model-visible):**
  `<root>/<workspace_id>/library/brand/<brand_id>/<knowledge_version>/`,
  `<root>/<workspace_id>/projects/<project_id>/library/`,
  `<root>/<workspace_id>/projects/<project_id>/threads/<thread_id>/scratch/`,
  `<root>/<workspace_id>/projects/<project_id>/turns/<execution_id>/`.
  The literal segment names `library`, `projects`, `threads`, `turns`, `scratch` are constants in `workspace.py`.
- **Turn folders:** `_LAYOUT = (".deepagent", "inputs", "context", "work", "reads", "delegations", "outputs")`; `reads/` is new and is materialization-free (it is where plan 4 spills). `_MATERIALIZED_PREFIXES` unchanged.
- **Thread scratch quota:** its own envelope, `ThreadScratchQuota(max_file_count=50, max_file_bytes=262_144, max_total_bytes=2_097_152)`, enforced at write time by walking the scratch mount. The turn quota keeps counting the turn folders only.
- **Env flags:** `CLUE_AGENT_THREAD_SCRATCH_RETENTION_S=2592000` (30 days) added to `.env.example` and `.env` at parity, read by `Settings.agent_thread_scratch_retention_s`.
- **Tests:** offline only in this plan (no DB) except the cleanup job's DB test, which runs against the lane DB with `--ignore-glob='*_live.py' -p no:cacheprovider`.
- **Commits:** local only, no push, no AI attribution.

---

### Task 1: Mount table on the backend — resolve, read, list

**Files:**
- Modify: `platform/agents/clue_agents/workspace.py` (constants at 71–80; `AnchoredAgentWorkspaceBackend.__init__` 213–233; `_validate_path` 273–291; `_parent_fd` 293–316; `_open_file` 318–332; `_walk_files` 334–373; `list_entries_sync` 621; deepagents `ls` 739)
- Modify: `platform/agents/clue_agents/__init__.py` (export `WorkspaceMount`, `MountMode`)
- Test: `tests/agents/test_workspace_backend.py`

**Interfaces:**

```python
# clue_agents/workspace.py
MountMode = Literal["read_only", "read_write"]

@dataclass(frozen=True, slots=True)
class WorkspaceMount:
    """One extra anchored root under a reserved first segment of the virtual tree."""
    name: str                # a validated single segment: "brand" | "project" | "thread"
    directory_fd: int        # already open with _DIR_FLAGS, audited private
    mode: MountMode
    #: Only for a read_write mount: its own quota envelope (the turn's policy does not apply).
    quota: ThreadScratchQuota | None = None

@dataclass(frozen=True, slots=True)
class ThreadScratchQuota:
    max_file_count: int
    max_file_bytes: int
    max_total_bytes: int

class AnchoredAgentWorkspaceBackend(BackendProtocol):
    def __init__(self, *, execution_fd, identity, policy, artifact_sink,
                 mounts: Sequence[WorkspaceMount] = ()) -> None: ...
    def _resolve(self, logical: str) -> tuple[int, str, WorkspaceMount | None]:
        """(root fd, path relative to that root, the mount or None for the execution root)."""
```

- [ ] **Step 1: Write the failing tests**

```python
# tests/agents/test_workspace_backend.py — new helpers + tests
def _mounted_backend(tmp_path: Path, *, mode: str = "read_only"):
    """A backend over tmp root with one extra mount at ``library``."""
    root, factory, lease = make_lease(tmp_path)          # the file's existing helper
    mount_dir = tmp_path / "mount"
    mount_dir.mkdir(mode=0o700)
    (mount_dir / "plan.md").write_text("# Plan\n")
    os.chmod(mount_dir / "plan.md", 0o400)
    fd = os.open(mount_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    backend = AnchoredAgentWorkspaceBackend(
        execution_fd=os.open(root_of(lease), os.O_RDONLY | os.O_DIRECTORY),
        identity=lease.identity,
        policy=policy(readable=(".deepagent", "inputs", "context", "work", "outputs", "library")),
        artifact_sink=RecordingArtifactSink(),
        mounts=(WorkspaceMount(name="library", directory_fd=fd, mode=mode),),
    )
    return backend, mount_dir


def test_a_read_only_mount_is_readable_by_its_virtual_name_and_never_writable(tmp_path: Path) -> None:
    backend, _ = _mounted_backend(tmp_path)
    assert backend.read_text_sync("library/plan.md") == "# Plan\n"
    assert backend.read("library/plan.md").file_data["content"] == "# Plan\n"
    with pytest.raises(WorkspaceSecurityError):
        backend.write_text_sync("library/notes.md", "x")
    assert backend.write("library/notes.md", "x").error.startswith("permission_denied")


def test_root_listing_shows_mounts_as_directories(tmp_path: Path) -> None:
    backend, _ = _mounted_backend(tmp_path)
    listed = backend.ls("/")
    assert {"path": "library", "is_dir": True, "size": 0} in listed.entries
    assert [e["path"] for e in backend.ls("library").entries] == ["library/plan.md"]


def test_a_mount_cannot_be_escaped_or_shadowed(tmp_path: Path) -> None:
    backend, mount_dir = _mounted_backend(tmp_path)
    os.symlink("/etc/hosts", mount_dir / "hosts")
    with pytest.raises(WorkspaceSecurityError):
        backend.read_text_sync("library/hosts")
    with pytest.raises(WorkspaceSecurityError):
        backend.read_text_sync("library/../inputs/user-message.txt")
    # The execution root cannot grow a folder that shadows a mount.
    with pytest.raises(WorkspaceSecurityError):
        backend.write_text_sync("library.md", "x")  # allowed name...
    with pytest.raises(WorkspaceSecurityError):
        backend.materialize_bytes("library/x.md", b"x")
```

Adjust `policy(...)` in `workspace_helpers.py` to accept `readable=`/`writable=` overrides (keyword-only, defaults unchanged). The last two assertions pin two rules: a *file* named like a mount at the root is fine (drop that assertion if `library.md` is not a collision; keep the materialize one), and materialization may never target a mount.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/agents/test_workspace_backend.py -k "mount" -p no:cacheprovider -q`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'mounts'`.

- [ ] **Step 3: Implement the mount table**

```python
# constants
_MOUNT_SEGMENT = re.compile(r"^[a-z][a-z0-9-]{0,31}$")

class AnchoredAgentWorkspaceBackend(BackendProtocol):
    def __init__(self, *, execution_fd, identity, policy, artifact_sink, mounts=()):
        ...existing...
        by_name: dict[str, WorkspaceMount] = {}
        for mount in mounts:
            if not _MOUNT_SEGMENT.fullmatch(mount.name) or mount.name in _LAYOUT:
                raise WorkspaceConfigurationError("mount name is reserved or malformed")
            if mount.name in by_name:
                raise WorkspaceConfigurationError("duplicate mount name")
            _validate_private_directory(mount.directory_fd)
            if mount.mode == "read_write" and mount.quota is None:
                raise WorkspaceConfigurationError("a writable mount needs its own quota")
            by_name[mount.name] = mount
        self._mounts = by_name

    def _resolve(self, logical: str) -> tuple[int, str, WorkspaceMount | None]:
        head, _, rest = logical.partition("/")
        mount = self._mounts.get(head)
        if mount is None:
            return self._root_fd, logical, None
        if not rest:
            raise WorkspaceSecurityError("a mount root is a directory, not a file")
        return mount.directory_fd, rest, mount
```

Thread the resolution through every host-touching method: `_parent_fd(logical, *, create, root_fd=None)` and `_open_file` take the resolved root (change their first line from `os.dup(self._root_fd)` to `os.dup(root_fd)`); `_walk_files(prefix, *, root_fd=None)` likewise; `read_text_sync`, `write_text_sync`, `edit_text_sync`, `_create_file`, `_replace_file_unlocked`, `_entry`, `stat_entry_sync`, `list_entries_sync` call `self._resolve` first and pass the fd and the relative path down, then re-prefix returned paths with `f"{mount.name}/"` so model-visible paths stay virtual. `_validate_path(write=True)`: after the existing prefix checks, `if mount is not None and mount.mode == "read_only": raise WorkspaceSecurityError("path is inside a read-only mount")`; `materialize=True` with a mount → `WorkspaceSecurityError("materialization never targets a mount")`. `_filesystem_lock` keeps locking the execution root fd (one lock per backend is enough; mounts are per-thread/per-turn objects).

`ls`/`glob` at the root: append `{"path": name, "is_dir": True, "size": 0}` per mount. `usage_snapshot` and `materialized_trees_frozen` stay on the execution root only.

- [ ] **Step 4: Run the whole backend file**

Run: `.venv/bin/pytest tests/agents/test_workspace_backend.py tests/agents/test_workspace_policy.py -p no:cacheprovider -q`
Expected: PASS (all pre-existing tests, plus the three new ones).

- [ ] **Step 5: Commit**

```bash
git add platform/agents/clue_agents/workspace.py platform/agents/clue_agents/__init__.py tests/agents/test_workspace_backend.py tests/agents/workspace_helpers.py
git commit -m "feat(agent-workspace): a mount table — extra anchored roots under reserved virtual segments, read-only or read-write, same walk and audit rules"
```

---

### Task 2: A writable mount with its own quota (the thread scratchpad)

**Files:**
- Modify: `platform/agents/clue_agents/workspace.py` (`_quota_before_write` 375–391, `_validate_current_quota` 393–400, `write_text_sync`/`edit_text_sync`/`_create_file`/`_replace_file_unlocked`)
- Test: `tests/agents/test_workspace_backend.py`

**Interfaces:**
- Produces: writes under a `read_write` mount are quota-checked against `mount.quota` by walking that mount; file mode 0600, directory 0700, atomic install exactly as the turn folders.

- [ ] **Step 1: Failing tests**

```python
def test_a_writable_mount_takes_writes_and_edits_under_its_own_quota(tmp_path: Path) -> None:
    backend, mount_dir = _mounted_backend(tmp_path, mode="read_write",
                                          quota=ThreadScratchQuota(3, 64, 128))
    backend.write_text_sync("library/notes.md", "first\n")
    backend.edit_text_sync("library/notes.md", old="first", new="second")
    assert (mount_dir / "notes.md").read_text() == "second\n"
    assert stat.S_IMODE((mount_dir / "notes.md").stat().st_mode) == 0o600
    with pytest.raises(WorkspaceQuotaExceeded):
        backend.write_text_sync("library/big.md", "x" * 65)
    backend.write_text_sync("library/a.md", "a"); backend.write_text_sync("library/b.md", "b")
    with pytest.raises(WorkspaceQuotaExceeded):          # 4th file
        backend.write_text_sync("library/c.md", "c")
    # The turn's own usage does not count the mount.
    assert backend.usage_snapshot().file_count == 0


def test_mount_writes_never_touch_the_turn_quota_and_vice_versa(tmp_path: Path) -> None:
    backend, _ = _mounted_backend(tmp_path, mode="read_write",
                                  quota=ThreadScratchQuota(50, 4096, 8192))
    for i in range(20):                                   # policy() allows 20 files
        backend.write_text_sync(f"work/{i}.md", "x")
    with pytest.raises(WorkspaceQuotaExceeded):
        backend.write_text_sync("work/21.md", "x")
    backend.write_text_sync("library/still-fine.md", "x")  # the mount has its own room
```

- [ ] **Step 2: Run — expect FAIL** (`WorkspaceSecurityError: path is inside a read-only mount` or a quota error from the wrong envelope).

- [ ] **Step 3: Implement**

`_quota_before_write(*, byte_count, adds_file, mount=None)`: when `mount` is a writable mount, walk `mount.directory_fd` and check against `mount.quota` instead of the policy; `_validate_current_quota(files, *, quota=None)` takes the envelope to check. `_create_file`/`_replace_file_unlocked` receive the resolved `(root_fd, relative, mount)` and pass `mount` to the quota check. Writable-mount files are created with `_FILE_MODE` (never read-only).

- [ ] **Step 4: Run the backend file — PASS. Step 5: Commit**

```bash
git commit -am "feat(agent-workspace): a read-write mount writes and edits under its own quota envelope, apart from the turn's"
```

---

### Task 3: The factory creates the new layout and opens the thread mount

**Files:**
- Modify: `platform/agents/clue_agents/workspace.py` (`AgentWorkspaceFactory.create` 923–990, `acquire` 992–1044, `_reopen_backend` 1046–1103, `_delete_execution` 1129–1159, `erase_for_privacy`/`purge_terminal` 1173–1245, `_LAYOUT`)
- Modify: `platform/agents/clue_agents/workspace_policy.py` (nothing structural; the root audit already accepts directories only)
- Test: `tests/agents/test_workspace_backend.py` (`test_factory_securely_reopens_same_frozen_execution_after_process_restart`, `test_factory_rejects_unexpected_entries_between_scope_levels`, privacy erasure test), `tests/agents/workspace_helpers.py`

**Interfaces:**

```python
LIBRARY_DIR = "library"; PROJECTS_DIR = "projects"; THREADS_DIR = "threads"
TURNS_DIR = "turns"; SCRATCH_DIR = "scratch"
THREAD_SCRATCH_QUOTA = ThreadScratchQuota(max_file_count=50, max_file_bytes=262_144, max_total_bytes=2_097_152)

@dataclass(frozen=True, slots=True)
class MountRequest:
    """What the caller wants mounted; the factory turns it into open descriptors."""
    thread_id: str | None = None          # → "thread" mount, read_write, THREAD_SCRATCH_QUOTA
    # plan 2 adds: brand: tuple[str, str] | None (brand_id, knowledge_version) → "brand", read_only
    #              project_library: bool → "project", read_only (plan 3 makes it versioned)

class AgentWorkspaceFactory:
    def create(self, *, workspace_id, project_id, execution_id, policy,
               mounts: MountRequest = MountRequest()) -> AgentWorkspaceLease: ...
    def acquire(self, *, workspace_id, project_id, execution_id, policy,
                mounts: MountRequest = MountRequest()) -> AgentWorkspaceLease: ...
    def purge_thread_scratch(self, *, workspace_id, project_id, thread_id) -> bool: ...
```

- [ ] **Step 1: Failing tests**

```python
def test_the_factory_lays_out_projects_turns_and_threads(tmp_path: Path) -> None:
    root, factory = make_factory(tmp_path)
    lease = factory.create(workspace_id="ws_a", project_id="prj_a", execution_id=EXECUTION_ID,
                           policy=policy(readable=(*DEFAULT_READABLE, "thread"), writable=("work", "outputs", "thread")),
                           mounts=MountRequest(thread_id="thr_a"))
    turn = root / "ws_a" / "projects" / "prj_a" / "turns" / str(EXECUTION_ID)
    scratch = root / "ws_a" / "projects" / "prj_a" / "threads" / "thr_a" / "scratch"
    assert turn.is_dir() and scratch.is_dir()
    assert sorted(p.name for p in turn.iterdir()) == [".deepagent", "context", "delegations", "inputs", "outputs", "reads", "work"]
    lease.backend.write_text_sync("thread/notes.md", "remember\n")
    assert (scratch / "notes.md").read_text() == "remember\n"
    for path in (turn, scratch, scratch.parent, turn.parent):
        assert stat.S_IMODE(path.stat().st_mode) == 0o700


def test_the_scratchpad_survives_the_turn_and_is_shared_by_the_thread_s_next_turn(tmp_path: Path) -> None:
    root, factory = make_factory(tmp_path)
    first = factory.create(..., execution_id=EXECUTION_ID, mounts=MountRequest(thread_id="thr_a"))
    first.backend.write_text_sync("thread/notes.md", "from turn one\n")
    await_snapshot_and_cleanup(factory, first)     # helper: snapshot outputs, authorize, cleanup
    second = factory.create(..., execution_id=ExecutionId(uuid4()), mounts=MountRequest(thread_id="thr_a"))
    assert second.backend.read_text_sync("thread/notes.md") == "from turn one\n"
    assert factory.purge_thread_scratch(workspace_id="ws_a", project_id="prj_a", thread_id="thr_a") is True
    assert not (root / "ws_a" / "projects" / "prj_a" / "threads" / "thr_a").exists()


def test_a_thread_id_is_validated_like_every_other_segment(tmp_path: Path) -> None:
    _, factory = make_factory(tmp_path)
    with pytest.raises(WorkspaceConfigurationError):
        factory.create(..., mounts=MountRequest(thread_id="../thr"))
```

Update the two existing layout-dependent tests (reopen after restart; unexpected entries between scope levels) for the `projects/<project>/turns/<execution>` path.

- [ ] **Step 2: Run — expect FAIL** on `mounts=`.

- [ ] **Step 3: Implement**

In `create`: under `_root_lock`, `_ensure_directory` chain `workspace → projects → <project> → turns`, then the existing `mkdir(execution)` no-reuse rule and `_LAYOUT` creation under it. If `mounts.thread_id`: validate the segment, `_ensure_directory` chain `<project> → threads → <thread> → scratch`, open its fd with `_DIR_FLAGS`, validate private, build `WorkspaceMount(name="thread", directory_fd=fd, mode="read_write", quota=THREAD_SCRATCH_QUOTA)`. Pass `mounts=` to the backend. `_audit_scope_directories` runs on `workspace`, `projects`, `<project>`, `turns` and `threads` levels (they are all directories-only levels; `library` at the workspace level is a directory and passes the audit).

`acquire`: same `mounts` argument; `_reopen_backend` re-opens the mounts the same way (idempotent `_ensure_directory`). Store the mount request in `_active`'s value alongside the backend so a reopen with a *different* thread id is refused (`WorkspaceConflict("execution was created for another thread")`).

`_delete_execution`: remove `turns/<execution>`; rmdir `turns`, `<project>`, `projects`, `<workspace>` only when empty (extend the existing ENOTEMPTY tolerance). `purge_thread_scratch`: `_remove_tree` on `threads/<thread>` under the root lock; return whether anything existed. `erase_for_privacy` (DSAR): also purge every `threads/*` under the project when called with `thread_id=None`? No — keep DSAR's contract per execution; add `erase_thread_scratch` as an alias of `purge_thread_scratch` and note in the docstring that the DSAR sweep (plan 2) calls both.

Backend `close()` closes mount fds too.

- [ ] **Step 4: Run the two workspace files — PASS. Step 5: Commit**

```bash
git commit -am "feat(agent-workspace): projects/<project>/{turns,threads} layout, the persistent thread scratchpad mount, and its purge"
```

---

### Task 4: The turn mounts its thread scratchpad; profile grants `thread/`

**Files:**
- Modify: `platform/api/clue_api/agent_turn_fleet_wiring.py:723-728` (the `acquire` call), `platform/api/clue_api/onboarding_synthesis_wiring.py:1542` region (its own factory use is unchanged; confirm it passes no mounts)
- Create: `platform/agents/catalog/profiles/head-of-abm/v51/profile.yaml` (copy of v50 from the hotfix; `readable_prefixes` adds `"reads"` and `"thread"`, `writable_prefixes` adds `"thread"`)
- Modify: `platform/api/clue_api/agent_registry_wiring.py` (`C6_ACTIVE_PROFILE_VERSIONS[HEAD_OF_ABM] = "v51"`), `PROJECT_CONVERSATION_AGENT_PROFILE_ID`, `tests/agents/test_catalog.py`, `tests/api/test_agent_registry_wiring.py` (digest re-measured)
- Modify: `platform/agents/catalog/skills/stage0-interview/v28/SKILL.md` (copy of v27; §1 gains one bullet) — see the text below
- Test: `tests/api/test_o6_conversation_composition_db.py` (a DB test that a production turn's lease has the `thread` mount and a write there lands under `threads/<thread>/scratch`)

Skill v28 §1 addition (founder-reviewed with this plan; appended after the `inputs/project/` bullet):

```markdown
- `thread/` is your notebook for this conversation. It keeps what you write there across the turns of this thread and nobody else reads it. Use it for what you have read and decided so far in a long conversation (`thread/notes.md`); never for anything the project should remember — that goes in the project's files (section 6).
```

- [ ] **Step 1: Failing DB test** — in the composition test file, submit one turn on a project thread through the fleet wiring test harness the file already uses; assert `lease.backend._mounts["thread"]` exists (or, black-box: after the turn, the host path `<root>/<ws>/projects/<project>/threads/<thread>/scratch` exists; the test knows the root from `Settings`).
- [ ] **Step 2: Run — FAIL** (no `threads/` directory).
- [ ] **Step 3: Implement** — `acquire(..., mounts=MountRequest(thread_id=submission.thread_id))`. Profile v51 and skill v28 as above; registry pins; re-measure the manifest digest.
- [ ] **Step 4: Run** the composition DB test, the catalog and registry tests, and the workspace tests. PASS.
- [ ] **Step 5: Commit**

```bash
git commit -am "feat(head-of-abm): v51 mounts the thread scratchpad — readable/writable thread/, readable reads/; skill v28 §1 names the notebook"
```

---

### Task 5: Cleanup learns the layout; archived threads' scratch is purged

**Files:**
- Modify: `platform/api/clue_api/agent_cleanup.py` (`run_once`: a second query), `libs/clue-config/clue_config/settings.py` (`agent_thread_scratch_retention_s: int = 2_592_000`), `.env.example`, `.env`
- Test: `tests/api/test_agent_cleanup_db.py` (find the existing cleanup DB test file by `grep -rl AgentWorkspaceCleanupJob tests`)

**Interfaces:**
- Produces: `AgentCleanupResult` gains `threads_purged: int`.

- [ ] **Step 1: Failing test** — seed an `agent_thread` row with `status='archived'` and `updated_at` older than the retention, create its scratch directory through the factory, run `run_once`, assert the directory is gone and `threads_purged == 1`; a second run reports `0`. An active thread older than the window is untouched.
- [ ] **Step 2: Run — FAIL. Step 3: Implement**

```python
            archived = await conn.execute(text(
                "SELECT id, workspace_id, project_id FROM agent_thread "
                "WHERE status = 'archived' AND updated_at <= :cutoff "
                "AND NOT EXISTS (SELECT 1 FROM agent_workspace_cleanup_event c "
                " WHERE c.thread_id = agent_thread.id AND c.action = 'thread_scratch_purge')"
            ), {"cutoff": current - timedelta(seconds=self._settings.agent_thread_scratch_retention_s)})
```

`agent_workspace_cleanup_event` needs a nullable `thread_id` column and an `action` value `thread_scratch_purge` — one migration `alembic revision -m "agent_workspace_cleanup_event thread scratch purge"` (add the column, extend the CHECK if the action is CHECK-constrained; reversible). Record one event per purged thread, keyed `uuid5(_CLEANUP_NAMESPACE, f"{workspace}:{thread}:thread_scratch_purge")`.

- [ ] **Step 4: Run** the cleanup DB test and `alembic heads` (one head). **Step 5: Commit** with the env parity change.

---

## Self-review

- **Spec coverage:** W1 layout (Task 3), W5 scratchpad + quota + retention (Tasks 2–5), §4.2 mount mechanics (Task 1), `reads/` folder for W9 (Task 3), security model preserved (every task's gate). Libraries and the versioned root are plans 2 and 3 by design. ✔
- **Placeholders:** the `make_factory`/`await_snapshot_and_cleanup` helpers are named here and must be added to `workspace_helpers.py` by Task 3's implementer, mirroring the existing `make_lease`; the file's existing helpers are the pattern. ✔
- **Type consistency:** `WorkspaceMount`, `ThreadScratchQuota`, `MountRequest` and the five directory constants are defined in Task 1/3 and used unchanged after. ✔
