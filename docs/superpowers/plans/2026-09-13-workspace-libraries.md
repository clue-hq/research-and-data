# Workspace and project libraries Implementation Plan (Lane 1, plan 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Brand knowledge is materialized once per knowledge version and mounted read-only into every turn as `brand/`; the project's settled state (compiled status and decisions, the current version of each project document, an artifact index) lives in one persistent, row-derived project library mounted read-only as `project/`; a turn pins the library index it was mounted against so replay re-mounts exactly that set; the per-turn copies under `inputs/brand/…` and `inputs/project/…` stop.

**Architecture:** Two library materializers in `clue_api` write anchored, read-only trees under the workspace root (`library/brand/<brand>/<version>/` and `projects/<project>/library/`), refreshed lazily at turn start when a cheap staleness digest computed from rows differs from the on-disk index, and after any project write (plan 3). The turn wiring asks the factory (plan 1) to mount both. The existing per-turn pins (`agent_turn_knowledge_pin`, `agent_turn_project_files`) keep their insert-once role and now record the mounted library indexes; a retried or replayed turn mounts a per-turn snapshot rebuilt from the pinned artifacts instead of the live library. The index cards in `context/` keep their shapes with the new virtual paths.

**Tech Stack:** Python 3.12, SQLAlchemy async, `clue_storage` artifacts, the plan-1 mount table, pytest DB suites against the lane DB.

**Spec:** `docs/superpowers/specs/2026-09-13-agent-workspace-reorganization-design.md` — W2, W3, W4, W11, §4.1, §4.3.

## Global Constraints

- **Postgres is the truth.** A library file is a rendering of rows; nothing reads a library file to decide anything server-side. The DB pins, not the files, are what replay and DSAR consult.
- **Current version only in view (W3):** each project document appears once, at its plain path (`audience/icp-<key>.md`, `audience/persona-<key>.md`, `plan.md`), as the pinned version for the ICP the project is pinned to, else the highest servable version. No `.vN` siblings, no `.versions/` folder in the library.
- **Artifacts by reference (W4):** `project/artifacts/index.json` lists design documents (id, kind, title, status, current version id, updated_at, origin thread) from `project_design_documents`; never content.
- **Immutability on disk:** library files are 0400 in 0500 directories; a refresh writes a complete new tree beside the old one and swaps it with one `rename`, under the project's library lock, so a turn that already mounted the old tree keeps reading it (its fd stays open on the old directory inode) and a new turn sees the new one.
- **Pins:** `agent_turn_project_files` keeps its columns; `files` now carries the library index entries plus one row `{path: "index.json", …}`; `files_sha256` doubles as the library digest. `agent_turn_knowledge_pin` unchanged; the brand library version is `documents_sha256[:16]`.
- **Skill/profile bump:** virtual paths move (`inputs/brand/knowledge/…` → `brand/knowledge/…`, `inputs/project/…` → `project/…`) → skill `stage0-interview@v29`, profile `head-of-abm@v52` with `readable_prefixes` adding `brand` and `project`; the index cards' `workspace_path` values change accordingly. Recipe unchanged.
- **Tests:** DB suites on the lane DB with `--ignore-glob='*_live.py' -p no:cacheprovider`; offline suites without `.env`.
- **Commits:** local only, no push, no AI attribution.

---

### Task 1: An anchored library tree writer in `clue_agents`

**Files:**
- Create: `platform/agents/clue_agents/library_tree.py`
- Modify: `platform/agents/clue_agents/__init__.py` (export), `platform/agents/clue_agents/workspace.py` (factory: `open_library(kind, *segments) -> int` and `library_paths`)
- Test: `tests/agents/test_library_tree.py`

**Interfaces:**

```python
# clue_agents/library_tree.py
@dataclass(frozen=True, slots=True)
class LibraryFile:
    path: str          # virtual, relative to the library root, normalize_virtual_path-clean
    content: bytes     # UTF-8 text only (.md/.json/.txt/.yaml)

class LibraryTree:
    """One persistent read-only tree under an anchored parent directory, replaced atomically."""

    def __init__(self, *, parent_fd: int, name: str) -> None: ...
    def current_digest(self) -> str | None:
        """The ``library_sha256`` recorded in ``<name>/index.json``, or None when absent."""
    def replace(self, files: Sequence[LibraryFile], *, digest: str) -> None:
        """Write every file into ``<name>.next-<pid>`` (0700 dirs → 0500, files 0400), fsync,
        then ``rename`` over ``<name>`` (renaming the old tree to ``<name>.old-<pid>`` first and
        removing it after). ``files`` must include ``index.json``; ``digest`` must equal the
        ``library_sha256`` inside it."""
    def open_fd(self) -> int:
        """An O_DIRECTORY|O_NOFOLLOW descriptor on the current tree, audited private."""
```

- [ ] **Step 1: Failing tests**

```python
def test_replace_is_atomic_and_read_only(tmp_path: Path) -> None:
    parent = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    tree = LibraryTree(parent_fd=parent, name="library")
    assert tree.current_digest() is None
    tree.replace([LibraryFile("status.md", b"# s\n"), LibraryFile("index.json", b'{"library_sha256":"abc"}')], digest="abc")
    assert tree.current_digest() == "abc"
    assert stat.S_IMODE((tmp_path / "library" / "status.md").stat().st_mode) == 0o400
    assert stat.S_IMODE((tmp_path / "library").stat().st_mode) == 0o500
    assert not any(p.name.startswith("library.next") or p.name.startswith("library.old") for p in tmp_path.iterdir())


def test_an_open_reader_keeps_the_old_tree_across_a_replace(tmp_path: Path) -> None:
    ...replace once; fd = tree.open_fd(); replace again with different status.md;
    assert os.read(os.open("status.md", os.O_RDONLY, dir_fd=fd), 100) == b"# s\n"   # old bytes
    assert (tmp_path / "library" / "status.md").read_bytes() == b"# s2\n"           # new tree


def test_replace_refuses_a_digest_mismatch_and_a_hostile_path(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceSecurityError): tree.replace([LibraryFile("../x.md", b"")], digest="d")
    with pytest.raises(WorkspaceConflict): tree.replace([LibraryFile("index.json", b'{"library_sha256":"other"}')], digest="d")
```

- [ ] **Step 2: Run — FAIL (module missing). Step 3: Implement** with the same primitives `workspace.py` uses (`_write_temp`-style temp file + link, `_validate_private_directory`, `O_NOFOLLOW` walks); a swapped-in tree that fails its audit on `open_fd()` raises `WorkspaceSecurityError` rather than serving.

Factory additions (in `workspace.py`): `library_parent_fd(workspace_id) -> int` (opens/creates `<ws>/library`) and `project_parent_fd(workspace_id, project_id) -> int` (opens/creates `<ws>/projects/<project>`), both under `_root_lock`, both audited; `MountRequest` gains `brand: tuple[str, str] | None` and `project_library: bool`; `create/acquire` open `library/brand/<brand>/<version>` and `projects/<project>/library` through `LibraryTree(...).open_fd()` and mount them read-only as `brand` and `project`. A missing library at mount time is a `WorkspaceConflict("library not materialized")` — the wiring materializes before acquiring.

- [ ] **Step 4: Run** `tests/agents/test_library_tree.py tests/agents/test_workspace_backend.py`. PASS. **Step 5: Commit** — `feat(agent-workspace): LibraryTree — atomic, read-only, replaceable library trees; brand/project library mounts`.

---

### Task 2: The brand library, materialized once per knowledge version

**Files:**
- Create: `platform/api/clue_api/brand_library.py`
- Modify: `platform/api/clue_api/brand_knowledge_context.py` (`INPUT_PREFIX = "brand/knowledge/"`; `knowledge_seed_files` stays for the trial surface only — rename the production consumer), `platform/api/clue_api/agent_turn_fleet_wiring.py:596` (no brand seeds; call `ensure_brand_library`)
- Test: `tests/api/test_brand_library_db.py`

**Interfaces:**

```python
# clue_api/brand_library.py
def brand_library_version(pin: KnowledgePinRow) -> str:   # pin.documents_sha256[:16]

async def ensure_brand_library(
    storage: StorageBackend, workspaces: AgentWorkspaceFactory, *,
    pin: KnowledgePinRow, documents: Sequence[PinnedDocument],
) -> str:
    """Materialize ``library/brand/<brand>/<version>/`` from the pinned documents if absent
    (content-addressed by the pin digest, so a present tree is never rewritten); returns the
    version segment. Files: ``knowledge/<folder>/<file>.md`` (the same bytes ``knowledge_seed_files``
    produced, minus the ``inputs/brand/`` prefix) and ``index.json`` (the BrandKnowledgeIndexCard
    with ``workspace_path`` values under ``brand/knowledge/…`` and ``library_sha256``)."""
```

- [ ] **Step 1: Failing DB test** — seed a brand with three knowledge documents (the fixture `tests/arv2/icp_fixture.py` already builds one), create a pin through `load_or_create_knowledge_pin`, call `ensure_brand_library` twice; assert the tree exists once with the expected files, the second call did not rewrite (mtime unchanged), and `index.json`'s `library_sha256 == pin.documents_sha256`.
- [ ] **Step 2: Run — FAIL. Step 3: Implement**, then in the fleet wiring replace `input_seeds = knowledge_seed_files(...)` with `brand_version = await ensure_brand_library(...)` and pass `MountRequest(brand=(scope.brand_id, brand_version), …)` to `acquire`. The brand index card composed into `context/project/brand_knowledge_index.json` is the same card, produced by `compile_brand_knowledge_index_card` with the new prefix.
- [ ] **Step 4: Run** the new DB test and `tests/api/test_brand_knowledge_context_db.py` (update the expected paths). **Step 5: Commit** — `feat(brand-library): brand knowledge materialized once per pinned version and mounted read-only as brand/`.

---

### Task 3: The project library — compile, digest, refresh

**Files:**
- Create: `platform/api/clue_api/project_library.py`
- Modify: `platform/api/clue_api/project_context_files.py` (`PROJECT_INPUT_PREFIX = "project/"`; `project_workspace_path` returns `project/<row_path minus the "project/" folder>`; `ProjectFilesIndexCard` becomes `ProjectLibraryIndexCard` with `card_kind: "project_library_index"`, `schema_version "1"`, plus `library_sha256: str` and `artifacts: int`), `platform/api/clue_api/arv2/project_documents.py` (`PLAN_WORKSPACE_PATH = "project/plan.md"`)
- Test: `tests/api/test_project_library_db.py`, updates to `tests/api/test_project_context_files_db.py`, `tests/api/test_project_status.py`

**Interfaces:**

```python
# clue_api/project_library.py
@dataclass(frozen=True, slots=True)
class ProjectLibrarySnapshot:
    files: tuple[CompiledProjectFile, ...]      # status.md, decisions.md, each current document, artifacts/index.json
    index: ProjectLibraryIndexCard              # includes library_sha256
    digest: str

async def project_library_digest(conn, *, workspace_id, project_id) -> str:
    """sha256 over the sorted tuple of contributing facts, ONE round trip per source:
    (document_id, version) of every servable project document; the ICP pin's document id;
    max(updated_at) of project_state rows; (run_id, status, finished_at) of the latest discovery
    run; (job_id, status) of every account research job in the latest run; (kind, status) of the
    latest personas onboarding run; (id, current_version, updated_at) of every design document.
    Cheap enough to run at every turn start."""

async def compile_project_library(conn, storage, artifacts, *, workspace_id, project_id) -> ProjectLibrarySnapshot:
    """The plan-1 compilers (status, decisions) + current_project_documents at plain paths
    (W3: the pinned ICP version at ``audience/icp-<key>.md``, else the highest servable) +
    ``artifacts/index.json`` from project_design_documents + ``index.json``."""

async def ensure_project_library(conn, storage, artifacts, workspaces, *, workspace_id, project_id) -> ProjectLibrarySnapshot:
    """Compute the digest; if it equals the on-disk index digest, read the index back and return;
    else compile and ``LibraryTree.replace`` under ``_lock_project``. Always returns what is on
    disk afterwards."""
```

- [ ] **Step 1: Failing DB tests**

```python
def test_the_library_is_rebuilt_only_when_a_contributing_row_changes(): ...
    # seed project + ICP pin; ensure twice → one replace (assert via LibraryTree.current_digest and mtime);
    # record a project_state statement → digest differs → ensure → status/decisions rewritten.

def test_the_library_shows_one_version_per_document_and_the_pinned_icp_wins(): ...
    # author icp v1 (confirmed, pinned) and v2 (proposed) under the project → library has
    # audience/icp-<key>.md == v1 bytes; index entry says version 1, status confirmed.

def test_the_artifact_index_lists_design_documents_by_reference(): ...
    # seed one design document through the design-leg fixture used by the router tests → artifacts/index.json
    # carries id/kind/title/status/current_version_id/updated_at/origin_thread_id and no page json.
```

- [ ] **Step 2: Run — FAIL. Step 3: Implement.** `CompiledProjectFile` gains nothing; the artifact index is a `CompiledProjectFile(path="artifacts/index.json", kind="artifact-index", status="compiled", summary="Design artifacts of this project, by reference.")`. The `_lock_project` in `arv2/project_documents.py` is imported (promote it to `lock_project`, public).
- [ ] **Step 4: Run** the three DB files. **Step 5: Commit** — `feat(project-library): the project's settled state compiled into one persistent, digest-refreshed, read-only library`.

---

### Task 4: The turn mounts both libraries, pins the library index, replays from the pin

**Files:**
- Modify: `platform/api/clue_api/agent_turn_fleet_wiring.py:596-680` (replace the seeding block), `platform/api/clue_api/project_context_files.py` (`load_or_create_project_files_pin` takes the snapshot's index entries; `read_pinned_project_files` unchanged), `platform/api/clue_api/head_of_abm_wiring.py:218-240` (the seed collision check no longer sees brand/project seeds), `platform/api/clue_api/agent_runtime_wiring.py` (context card path `context/project/project_library_index.json`)
- Test: `tests/api/test_o6_conversation_composition_db.py`, `tests/api/test_project_context_files_db.py`

**Behaviour:**

1. `ensure_brand_library` → brand version; `ensure_project_library` → snapshot.
2. `load_or_create_project_files_pin(..., compile=lambda: snapshot.files)` pins the library's files (same insert-once rule; the pin's `files_sha256` equals `snapshot.digest` by construction because the index entries carry the same artifact shas).
3. **First attempt** (`project_pin_created`): `acquire(..., mounts=MountRequest(thread_id, brand=(brand_id, version), project_library=True))`.
4. **Retry/replay** (pin existed): if `LibraryTree.current_digest() == pin.files_sha256` mount the live library; else materialize the pinned files into a per-turn `LibraryTree` under the thread root's `.deepagent/project-pinned/` (built from `read_pinned_project_files`, replaced at the next turn start like the other materialized trees) and mount *that* as `project`. The brand mount is already content-addressed by version, so it is always exact.
5. `context/project/project_library_index.json` is the pinned index (replaces `project_files_index.json`); the brand index card is read from the brand library's `index.json`.

- [ ] **Step 1: Failing DB tests** — (a) a production turn's lease lists `brand/knowledge/company/overview.md` and `project/status.md` through `backend.ls`, and `inputs/` holds only the user message and the current-context refs; (b) after a `project_state` write between two attempts of the same turn (simulate by calling the pin loader twice with a changed compile), the second attempt's `project/status.md` bytes equal the first's (the pinned set), not the live library's.
- [ ] **Step 2: Run — FAIL. Step 3: Implement. Step 4: Run** the composition file, project-context files, `tests/api/test_c8_trial_surface.py` (the trial surface keeps seeds). **Step 5: Commit** — `feat(agent-turn): turns mount the brand and project libraries; the project pin records the library index; replay mounts the pinned set`.

---

### Task 5: Skill v29 and profile v52 — the new paths

**Files:**
- Create: `platform/agents/catalog/skills/stage0-interview/v29/SKILL.md` (copy of v28), `platform/agents/catalog/profiles/head-of-abm/v52/profile.yaml` (copy of v51; `readable_prefixes: [".deepagent", "inputs", "scratch", "reads", "outputs", "brand", "project"]`)
- Modify: registry pins, catalog/registry tests, `apps/frontend/src/features/projects/model/chat-tool-presentation.ts` (no change), `platform/api/clue_api/arv2/README.md` (paths)

Skill v29 §1 (founder-reviewed with this plan; replaces the section's path bullets):

```markdown
## 1. Read the brand's knowledge and the project's library before you speak

Two read-only folders are mounted for you on every turn. `brand/knowledge/` holds what the platform researched about the brand; `brand/knowledge/index.json` lists every file with its kind, version, status and a one-line summary. `project/` is this project's library: `project/status.md` (compiled from the rows: ICP, products, plan, accounts, discovery, research, personas), `project/decisions.md` (what the human told this project, in their words), the project's own documents (`project/audience/icp-<key>.md`, `project/audience/persona-<key>.md`, `project/plan.md`), and `project/artifacts/index.json` (the gallery's artifacts, by reference). `project/index.json` lists them. Every thread of this project sees the same library, so what another thread settled is here.

- Before your first reply on a thread, read `project/status.md` and `project/decisions.md`; before your first reply on a project, also read `brand/knowledge/company/overview.md` and every `brand/knowledge/audience/icp-*.md`, all in one step.
- Read `brand/knowledge/product/catalog.md` when products come up and the product file before you say anything specific about a product; `brand/knowledge/proof/customer-reviews.md` when the conversation turns to what customers say.
- Re-read `project/status.md` before answering where the project stands. When you need a detail, re-read the file rather than recalling it. Never state a fact a file does not contain; if a file says a thing was not found, say that.
- `scratch/` is your notebook for this conversation (see the previous version's rule; unchanged).
- If `brand/knowledge/index.json` lists no documents, onboarding has not run for this brand. Say so and point the human to the Knowledge page; do not research the company yourself.
```

Also replace every other `inputs/brand/knowledge/` and `inputs/project/` occurrence in the skill with `brand/knowledge/` and `project/` (sections 5b, 5c, 6, 6b, 7).

- [ ] **Steps:** create, pin, re-measure the manifest digest, run the catalog/registry/trial-surface tests, commit — `feat(head-of-abm): v52/v29 — the brand and project libraries by their mounted paths`.

---

### Task 6: Refresh after the writers, and DSAR

**Files:**
- Modify: `platform/api/clue_api/arv2/project_documents.py` (`write_project_plan`, `save_project_document`), `platform/api/clue_api/arv2/icp_authoring.py` (`author_icp_document`), `platform/api/clue_api/icp_confirmation` pin path, `platform/api/clue_api/dynamic_client_kb_erasure.py` (or wherever DSAR erasure of `project_state` quotes runs)
- Test: `tests/api/test_project_library_db.py`

**Behaviour:** each writer, after commit, calls `ensure_project_library` (cheap when the digest is unchanged; a rebuild when it moved). DSAR erasure of a statement re-runs `ensure_project_library` for the project so the quote leaves `decisions.md` in the same transaction boundary as the tombstone. Because the digest is lazy, a writer that forgets is *not* a correctness bug (the next turn rebuilds); the calls exist so the library is fresh for the frontend's future reads and for the human PUT round-trip.

- [ ] **Step 1: Failing DB test** — write a plan through `write_project_plan`; assert the library's `plan.md` bytes updated without a turn. Erase a `project_state` statement through the DSAR path; assert `decisions.md` no longer contains the quote.
- [ ] **Steps 2–5: implement, run, commit** — `feat(project-library): writers and DSAR refresh the library`.

---

## Self-review

- **Spec coverage:** W11 (Task 2), W2 + §4.3 refresh/pin/replay (Tasks 3–4, 6), W3 (Task 3), W4 (Task 3), the new virtual paths and grant (Task 5). ✔
- **Placeholders:** the design-document fixture in Task 3's third test is "the one the router tests use" — the implementer finds it by `grep -rl project_design_documents tests`. Stated explicitly rather than invented. ✔
- **Type consistency:** `ProjectLibrarySnapshot`, `ProjectLibraryIndexCard`, `MountRequest(brand=, project_library=)`, `LibraryTree` are named identically across Tasks 1–4. ✔
