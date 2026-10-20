# Agent Code Execution and Document Attachments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a person attach PDF, DOCX, PPTX, XLSX, CSV and JSON files to a project chat, put every attached file (all three families) byte for byte in a read-only `attachments/` folder of the agent's workspace, and give Head-of-ABM a governed `run_python@1` tool that runs a script in a Docker sandbox over that workspace so it can read the binaries with code.

**Architecture:** Nothing is converted. The upload route only validates a new `document` family; at the start of every Head-of-ABM turn the fleet worker syncs every upload attached to any turn of the project into `<ws>/projects/<project>/attachments/`, which the turn mounts read-only as `attachments/`. The PR #64 text route (text uploads written as project documents) is retired so one mechanism carries every family. `run_python@1` is a normal governed tool that finds its turn's host paths in a per-execution registry the conversation engine fills while it holds the workspace lease, runs one `docker run --rm --network none …` off the event loop, and re-applies the workspace policy afterwards. A new skill, a manual chapter, a prompt line, profile v58 and recipe v29 teach the agent.

**Tech Stack:** FastAPI + SQLAlchemy async; Pydantic v2 contracts; Docker CLI via `subprocess` for the sandbox; `node:test` + Zod for the frontend; pytest with a throwaway Postgres for `*_db.py` suites.

**Spec:** `docs/superpowers/specs/archive/2026-09-19-agent-code-execution-and-document-attachments-design.md` (revised 2026-09-19 afternoon: no markdown step anywhere)

## Global Constraints

- Document family media types: `application/pdf`, `application/vnd.openxmlformats-officedocument.wordprocessingml.document` (`.docx`), `application/vnd.openxmlformats-officedocument.presentationml.presentation` (`.pptx`), `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` (`.xlsx`), `text/csv`, `application/json`. No `.doc`/`.ppt`/`.xls`/`.xlsm`.
- Settings and defaults, every one added to `.env.example` AND the local `.env` in the task that introduces it: `CLUE_SANDBOX_ENABLED=false`, `CLUE_SANDBOX_IMAGE=clue-agent-sandbox:latest`, `CLUE_SANDBOX_TIMEOUT_S=60`, `CLUE_SANDBOX_CPUS=1`, `CLUE_SANDBOX_MEMORY_MB=1024`, `CLUE_SANDBOX_MAX_RUNS_PER_TURN=10`, `CLUE_SANDBOX_MAX_OUTPUT_BYTES=1048576`, `CLUE_CHAT_ATTACHMENT_DOCUMENT_MAX_BYTES=26214400`. There is no OCR switch, no sheet-row cap, no markdown cap: those existed only for the retired converter.
- Every attached file of a project, whatever its family, lives in the workspace at `attachments/<filename>` (host path `<root>/<ws>/projects/<project>/attachments/<filename>`). No markdown twin, no index file, no project-document write.
- Sandbox: `docker run --rm -i --network none --cpus … --memory …m --pids-limit 256 --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges --user 65534:65534 --workdir /workspace`; writable binds `scratch/ work/ outputs/`; read-only binds `inputs/ context/ reads/ brand/ project/ attachments/`; script on stdin to `python -I -`; no host environment variables.
- Files a script leaves under the writable prefixes must satisfy the profile's workspace policy plus the extra output extensions `.csv .xlsx .docx .pptx .pdf .png`; offending files are deleted and reported.
- Package boundary: `platform/agents/clue_agents` never imports `clue_api`; `make contracts` (import-linter) is the guard.
- No migration in this plan. `uv run alembic heads` must still print exactly `d659c2d2b537 (head)` at the end.
- DB suites run only on the throwaway DB: `set -a; source .env; set +a; export CLUE_DATABASE_URL="${CLUE_DATABASE_URL%/clue_damascus}/clue_damascus_test"`. Never run the broad pytest suite with real keys (`.env` holds them); run the named files.
- Gates: backend `uv run ruff check <files> && uv run ruff format --check <files> && uv run mypy <files>` and `make contracts`; frontend `cd apps/frontend && npm test && npm run lint` (two pre-existing warnings in `canvasOperations.ts` are not ours) and `npm run build` in the frontend task.
- Profile bump mechanics are the v56/v57 ones: a skill's `sha256` is the SHA-256 of its `SKILL.md` bytes; a tool grant's schema digests are `_schema_sha256(input_model)` / `_schema_sha256(output_model)` from `clue_toolbelt.envelope`; every pin of the profile version moves together (`agent_registry_wiring.py` `C6_ACTIVE_PROFILE_VERSIONS`, `composer_context.PROJECT_CONVERSATION_AGENT_PROFILE_ID`, `manual/build.py` `PROFILE_VERSION`, `tool_notes.yaml` header, the tests that assert them).
- Agent-facing text (skill, manual chapter, prompt, tool descriptions) is plain, simple language: fewer rules, never compressed prose.
- No `Co-Authored-By` trailers, no AI attribution, never push. Commit at the end of each task.

---

### Task 1: Settings for the sandbox and the document family

**Files:**
- Modify: `libs/clue-config/clue_config/settings.py` (after `chat_attachment_history_images_max`, ~line 689)
- Modify: `.env.example` (after `CLUE_CHAT_ATTACHMENT_HISTORY_IMAGES_MAX=20`, line 465); `.env` (same block, not committed)
- Test: `tests/test_sandbox_settings.py`

**Interfaces:**
- Produces on `Settings`: `sandbox_enabled: bool`, `sandbox_image: str`, `sandbox_timeout_s: float`, `sandbox_cpus: float`, `sandbox_memory_mb: int`, `sandbox_max_runs_per_turn: int`, `sandbox_max_output_bytes: int`, `chat_attachment_document_max_bytes: int`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sandbox_settings.py
from __future__ import annotations

from pathlib import Path

from clue_config import Settings

REPO = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = REPO / ".env.example"

DEFAULTS: dict[str, object] = {
    "sandbox_enabled": False,
    "sandbox_image": "clue-agent-sandbox:latest",
    "sandbox_timeout_s": 60.0,
    "sandbox_cpus": 1.0,
    "sandbox_memory_mb": 1024,
    "sandbox_max_runs_per_turn": 10,
    "sandbox_max_output_bytes": 1_048_576,
    "chat_attachment_document_max_bytes": 25 * 1024 * 1024,
}
ENV_LINES = {
    "CLUE_SANDBOX_ENABLED=false",
    "CLUE_SANDBOX_IMAGE=clue-agent-sandbox:latest",
    "CLUE_SANDBOX_TIMEOUT_S=60",
    "CLUE_SANDBOX_CPUS=1",
    "CLUE_SANDBOX_MEMORY_MB=1024",
    "CLUE_SANDBOX_MAX_RUNS_PER_TURN=10",
    "CLUE_SANDBOX_MAX_OUTPUT_BYTES=1048576",
    "CLUE_CHAT_ATTACHMENT_DOCUMENT_MAX_BYTES=26214400",
}


def test_sandbox_and_document_defaults(monkeypatch) -> None:
    for line in ENV_LINES:
        monkeypatch.delenv(line.split("=", 1)[0], raising=False)
    settings = Settings(_env_file=None)
    for name, value in DEFAULTS.items():
        assert getattr(settings, name) == value, name


def test_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("CLUE_SANDBOX_ENABLED", "true")
    monkeypatch.setenv("CLUE_SANDBOX_MAX_RUNS_PER_TURN", "3")
    settings = Settings(_env_file=None)
    assert settings.sandbox_enabled is True
    assert settings.sandbox_max_runs_per_turn == 3


def test_every_new_key_is_documented_with_its_default() -> None:
    body = ENV_EXAMPLE.read_text()
    missing = sorted(line for line in ENV_LINES if line not in body)
    assert not missing, f"absent from .env.example: {missing}"
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/test_sandbox_settings.py -q` → FAIL, `Settings` has no attribute `sandbox_enabled`.

- [ ] **Step 3: Add the fields and the env lines**

In `settings.py`, directly after `chat_attachment_history_images_max`:

```python
    # Document attachments (spec 2026-09-19 §3.1): the per-file cap of the document family
    # (PDF, DOCX, PPTX, XLSX, CSV, JSON). Env: ``CLUE_CHAT_ATTACHMENT_DOCUMENT_MAX_BYTES``.
    chat_attachment_document_max_bytes: int = Field(default=25 * 1024 * 1024, ge=1)
    # The code sandbox (spec 2026-09-19 §3.4): off until an operator builds the image and turns it
    # on; then one container per run with these bounds. Env: ``CLUE_SANDBOX_ENABLED`` /
    # ``_IMAGE`` / ``_TIMEOUT_S`` / ``_CPUS`` / ``_MEMORY_MB`` / ``_MAX_RUNS_PER_TURN`` /
    # ``_MAX_OUTPUT_BYTES``.
    sandbox_enabled: bool = False
    sandbox_image: str = "clue-agent-sandbox:latest"
    sandbox_timeout_s: float = Field(default=60.0, gt=0)
    sandbox_cpus: float = Field(default=1.0, gt=0)
    sandbox_memory_mb: int = Field(default=1024, ge=64)
    sandbox_max_runs_per_turn: int = Field(default=10, ge=1)
    sandbox_max_output_bytes: int = Field(default=1_048_576, ge=1024)
```

In `.env.example` after line 465 (and the same block in `.env`):

```
# Document attachments (spec 2026-09-19): the per-file cap of a PDF / DOCX / PPTX / XLSX / CSV /
# JSON attachment. The file reaches the agent as-is; it reads it with run_python.
CLUE_CHAT_ATTACHMENT_DOCUMENT_MAX_BYTES=26214400
# The agent code sandbox (spec 2026-09-19 §3.4). Off until `make sandbox-image` has built the
# image on this host; then one `docker run` per run_python call with these bounds. Without it a
# binary attachment is unreadable to the agent (it says so; it does not guess).
CLUE_SANDBOX_ENABLED=false
CLUE_SANDBOX_IMAGE=clue-agent-sandbox:latest
CLUE_SANDBOX_TIMEOUT_S=60
CLUE_SANDBOX_CPUS=1
CLUE_SANDBOX_MEMORY_MB=1024
CLUE_SANDBOX_MAX_RUNS_PER_TURN=10
CLUE_SANDBOX_MAX_OUTPUT_BYTES=1048576
```

- [ ] **Step 4: Run the test and gates**

Run: `uv run pytest tests/test_sandbox_settings.py tests/test_chat_attachment_settings.py -q` → PASS. `uv run ruff check libs/clue-config/clue_config/settings.py tests/test_sandbox_settings.py && uv run mypy libs/clue-config/clue_config/settings.py` → clean.

- [ ] **Step 5: Commit**

```bash
git add libs/clue-config/clue_config/settings.py .env.example tests/test_sandbox_settings.py
git commit -m "feat(config): sandbox and document-attachment settings"
```

---

### Task 2: The `document` family in upload validation

**Files:**
- Modify: `platform/api/clue_api/chat/uploads.py:37-56` (allow-lists, extensions, magic) and `:64-70` (`attachment_family`), `:81-125` (`resolve_media_type`, `validate_upload_bytes`)
- Test: `tests/api/test_chat_uploads.py` (extend)

**Interfaces:**
- Produces in `uploads.py`: `DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"`, `PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"`, `XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"`, `ALLOWED_DOCUMENT_MEDIA_TYPES = frozenset({"application/pdf", DOCX, PPTX, XLSX, "text/csv", "application/json"})`; `attachment_family(media_type) -> Literal["text", "image", "document"] | None`; `validate_upload_bytes` enforces `settings.chat_attachment_document_max_bytes` and the magic bytes (`%PDF-` for PDF, `PK\x03\x04` for the three OOXML types, UTF-8 for CSV, `json.loads` for JSON), refusing `UPLOAD_NOT_A_DOCUMENT`. `resolve_media_type`'s refusal text becomes "attach a .md, .txt, .pdf, .docx, .pptx, .xlsx, .csv or .json file, or a PNG, JPEG, WebP or GIF image".
- Every downstream `family == "text"` / `"image"` check keeps its meaning; `"document"` is a third value that Tasks 3, 5 and 6 handle.

- [ ] **Step 1: Extend the pure tests**

Append to `tests/api/test_chat_uploads.py`:

```python
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_document_family_and_extensions() -> None:
    assert attachment_family("application/pdf") == "document"
    assert attachment_family(DOCX) == "document"
    assert attachment_family("text/csv") == "document"
    assert attachment_family("application/json") == "document"
    assert resolve_media_type(declared=None, filename="a.PDF") == "application/pdf"
    assert resolve_media_type(declared="application/octet-stream", filename="a.xlsx").endswith(
        "spreadsheetml.sheet"
    )
    assert resolve_media_type(declared=None, filename="a.csv") == "text/csv"


def test_document_bytes_rules() -> None:
    settings = Settings(_env_file=None, chat_attachment_document_max_bytes=64)
    validate_upload_bytes(
        data=b"%PDF-1.7\n" + b"\x00" * 10, media_type="application/pdf", settings=settings
    )
    validate_upload_bytes(data=b"PK\x03\x04" + b"\x00" * 10, media_type=DOCX, settings=settings)
    validate_upload_bytes(data=b'{"a": 1}', media_type="application/json", settings=settings)
    validate_upload_bytes(data=b"a,b\n1,2\n", media_type="text/csv", settings=settings)
    with pytest.raises(UploadRefused) as too_big:
        validate_upload_bytes(
            data=b"%PDF-" + b"x" * 100, media_type="application/pdf", settings=settings
        )
    assert too_big.value.code == "UPLOAD_TOO_LARGE"
    with pytest.raises(UploadRefused) as not_pdf:
        validate_upload_bytes(data=b"hello", media_type="application/pdf", settings=settings)
    assert not_pdf.value.code == "UPLOAD_NOT_A_DOCUMENT"
    with pytest.raises(UploadRefused) as not_json:
        validate_upload_bytes(data=b"{oops", media_type="application/json", settings=settings)
    assert not_json.value.code == "UPLOAD_NOT_A_DOCUMENT"
    with pytest.raises(UploadRefused) as not_utf8:
        validate_upload_bytes(data=b"\xff\xfe,x\n", media_type="text/csv", settings=settings)
    assert not_utf8.value.code == "UPLOAD_NOT_A_DOCUMENT"
```

- [ ] **Step 2: Run to see it fail**: `uv run pytest tests/api/test_chat_uploads.py -q` → FAIL.

- [ ] **Step 3: Implement**

In `uploads.py`: add the three OOXML constants and `ALLOWED_DOCUMENT_MEDIA_TYPES` beside the existing allow-lists; `_OOXML_TYPES = frozenset({DOCX, PPTX, XLSX})`; extend `_EXTENSION_MEDIA_TYPES` with `.pdf .docx .pptx .xlsx .csv .json`; `attachment_family` returns `"document"` for the new set (return type `Literal["text", "image", "document"] | None`); `import json`; in `validate_upload_bytes` choose the limit per family (`text` / `image` / `document`) and add, before the text branch:

```python
    if family == "document":
        if media_type == "application/pdf" and not data.startswith(b"%PDF-"):
            raise UploadRefused("UPLOAD_NOT_A_DOCUMENT", "the file is not a PDF")
        if media_type in _OOXML_TYPES and not data.startswith(b"PK\x03\x04"):
            raise UploadRefused("UPLOAD_NOT_A_DOCUMENT", "the file is not an Office document")
        if media_type in ("text/csv", "application/json"):
            try:
                text_body = data.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise UploadRefused("UPLOAD_NOT_A_DOCUMENT", "the file is not UTF-8") from exc
            if media_type == "application/json":
                try:
                    json.loads(text_body)
                except json.JSONDecodeError as exc:
                    raise UploadRefused(
                        "UPLOAD_NOT_A_DOCUMENT", "the file is not valid JSON"
                    ) from exc
        return
```

Update the `__all__` and the module docstring (it lists the accepted types).

- [ ] **Step 4: Run tests and gates**: `uv run pytest tests/api/test_chat_uploads.py tests/api/test_chat_uploads_db.py tests/api/test_chat_attachment_refs.py -q` (the DB one on the throwaway DB) → PASS; ruff + mypy on `uploads.py` → clean.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/chat/uploads.py tests/api/test_chat_uploads.py
git commit -m "feat(chat): document family (pdf, docx, pptx, xlsx, csv, json) in upload validation"
```

---

### Task 3: Retire the text-document route (one mechanism for every family)

**Files:**
- Modify: `platform/api/clue_api/chat/attachments.py` (delete `materialize_text_attachments`, `_attachment_document`, `ATTACHMENT_FOLDER`, and the now-unused imports `yaml`, `parse_front_matter`, and everything from `clue_api.arv2.project_documents`; `ValidatedAttachment.family: Literal["text", "image", "document"]`; update `__all__` and the module docstring)
- Modify: `platform/api/clue_api/chat/router.py` (delete `_wrote_attachment_documents` at 683–725, its import at line 75 and the `ProjectDocumentRefused` import at line 69 if nothing else uses it; delete the two `wrote_attachment_documents = False` initialisations at ~930 and ~2355 and the two call sites at ~1084 and ~2573; the refresh condition at ~1117 goes away entirely, the one at ~2843 becomes `if pinned_project_icp and project_library is not None:`)
- Delete: `tests/api/test_chat_attachment_documents_db.py`
- Modify: `tests/api/test_attachment_binding_db.py` (remove the `materialize_text_attachments` import and call; the assertions change in Task 6 — for this task make the file's two tests pass by deleting the call only and changing the two `workspace_path` expectations to the Task 6 values, `"attachments/brief.md"` and `"attachments/shot.png"`, marked `xfail(strict=True, reason="Task 6")` until Task 6 lands. Simpler alternative: delete the file here and let Task 6 recreate it. Choose the delete; Task 6's test is written from scratch.)
- Test: `tests/api/test_chat_attachment_refs.py` (add one assertion that `ValidatedAttachment` accepts `family="document"`)

**Interfaces:**
- Consumes: `attachment_family` three-valued (Task 2).
- Produces: `ValidatedAttachment(upload_id, ref, filename, family)` with the three-valued family; nothing in the API writes a project document for an attachment anymore.

- [ ] **Step 1: Write the failing test** — in `tests/api/test_chat_attachment_refs.py` add:

```python
def test_a_document_upload_validates_as_the_document_family(...):
    # seed one chat_upload row with media_type "application/pdf" the way the file's existing
    # tests seed text and image rows, call validated_attachment_refs, assert
    # validated[0].family == "document"
```

written in full against the file's existing seeding helper.

- [ ] **Step 2: Run to see it fail** → FAIL (`Literal["text", "image"]` rejects `"document"` at the dataclass, or the router import error once the deletion begins).

- [ ] **Step 3: Delete and widen** as listed in Files. Grep afterwards: `grep -rn "materialize_text_attachments\|_wrote_attachment_documents\|ATTACHMENT_FOLDER\|ATTACHMENT_DOCUMENT_REFUSED" platform tests apps/frontend/docs` must return nothing (the frontend contract note mentions the document route: update `apps/frontend/docs/api-contracts/projects.md` "Chat attachments" section to say a text attachment is a file in the agent's `attachments/` folder, not a project document; the Gallery no longer lists it).

- [ ] **Step 4: Run tests and gates**: `uv run pytest tests/api/test_chat_attachment_refs.py tests/api/test_chat_attachment_refs_db.py tests/api/test_chat_uploads.py -q` and `uv run pytest tests/api -k "router and attachment and not live" -q` on the throwaway DB → PASS; ruff + ruff format + mypy on the two modules → clean; `make contracts` → kept count unchanged.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/chat/attachments.py platform/api/clue_api/chat/router.py tests/api/test_chat_attachment_refs.py apps/frontend/docs/api-contracts/projects.md
git rm tests/api/test_chat_attachment_documents_db.py tests/api/test_attachment_binding_db.py
git commit -m "refactor(chat): retire the text-attachment project-document route; every attachment is a file"
```

---

### Task 4: The `attachments` mount in the workspace

**Files:**
- Modify: `platform/agents/clue_agents/workspace.py` (`MountRequest.attachments: bool = False`; `_open_mounts` opens `<ws>/projects/<project>/attachments` read-only as mount `attachments` when present; `AgentWorkspaceFactory` keeps `self._root_path = prepared_root.path` and exposes `root_path`, `project_host_path(workspace_id, project_id) -> Path` and `thread_host_path(workspace_id, project_id, thread_id) -> Path`; `AgentWorkspaceLease` exposes `workspace_segment`, `project_segment`, `thread_segment` properties)
- Add constant `ATTACHMENTS_DIR: Final = "attachments"` beside `LIBRARY_DIR`.
- Test: `tests/agents/test_workspace_attachments_mount.py`

**Interfaces:**
- `MountRequest(attachments=True)` mounts the directory if it exists; a missing directory is not an error (the mount is simply absent), so a project with no uploads mounts nothing.
- `AgentWorkspaceLease.workspace_segment/project_segment/thread_segment: str` (read-only properties over the private fields).
- `AgentWorkspaceFactory.root_path: Path`; `project_host_path(ws, project)` = `root_path / <validated ws segment> / "projects" / <validated project segment>`; `thread_host_path(ws, project, thread)` = `project_host_path(...) / "threads" / <validated thread segment>`. Use the same segment validation the factory uses to build fds (`validate_workspace_segment`).

- [ ] **Step 1: Write the failing test**

Model it on the existing workspace tests (find the factory fixture in `tests/agents/test_workspace*.py` that exercises `MountRequest(brand=…)` and reuse its `PreparedWorkspaceRoot`/policy builders):

```python
def test_attachments_mount_is_read_only_optional_and_readable(factory, identity_kwargs, policy) -> None:
    # 1. no directory → acquire with attachments=True succeeds and no mount named "attachments" exists
    lease = factory.acquire(**identity_kwargs, policy=policy, mounts=MountRequest(attachments=True))
    try:
        assert "attachments" not in {m.name for m in lease.backend.mounts}  # adapt to the backend's accessor
    finally:
        lease.release()
    # 2. create the directory with a text file and a pdf → listed; the .md reads; the .pdf refuses
    #    as non-UTF-8; a write is refused
    project_dir = factory.project_host_path(identity_kwargs["workspace_id"], identity_kwargs["project_id"])
    (project_dir / "attachments").mkdir(mode=0o700, parents=True)
    (project_dir / "attachments" / "brief.md").write_text("# brief\n")
    (project_dir / "attachments" / "r.pdf").write_bytes(b"%PDF-1.4\xff\xfe")
    lease = factory.acquire(**identity_kwargs, policy=policy_with_readable("attachments"), mounts=MountRequest(attachments=True))
    try:
        names = {e.path for e in run(lease.backend.list_entries("attachments"))}
        assert {"attachments/brief.md", "attachments/r.pdf"} <= names
        assert run(lease.backend.read_text("attachments/brief.md")) == "# brief\n"
        with pytest.raises(WorkspaceSecurityError):  # or the backend's non-UTF-8 error class
            run(lease.backend.read_text("attachments/r.pdf"))
        with pytest.raises(WorkspaceSecurityError):
            run(lease.backend.write_text("attachments/x.md", "no"))
        assert factory.thread_host_path(identity_kwargs["workspace_id"], identity_kwargs["project_id"], identity_kwargs["thread_id"]).is_dir()
    finally:
        lease.release()
```

Write it in full against the real fixtures; use the exact exception class `read_text` raises for non-UTF-8 (see `workspace.py:829`).

- [ ] **Step 2: Run to see it fail** → FAIL (`attachments` kwarg unknown).

- [ ] **Step 3: Implement** in `workspace.py`:

```python
ATTACHMENTS_DIR: Final = "attachments"
# MountRequest:
    #: ``<ws>/projects/<project>/attachments`` → the ``attachments`` mount, read-only, when the
    #: directory exists (spec 2026-09-19 §3.2). The fleet's sync creates it before the acquire.
    attachments: bool = False
# _open_mounts, after the project_library block:
            if request.attachments:
                try:
                    directory_fd = self._open_library(
                        (workspace_segment, PROJECTS_DIR, project_segment, ATTACHMENTS_DIR),
                        name="attachments",
                    )
                except WorkspaceConfigurationError:
                    directory_fd = -1
                if directory_fd >= 0:
                    opened.append(WorkspaceMount(name="attachments", directory_fd=directory_fd, mode="read_only"))
```

Factory: store `self._root_path = prepared_root.path` in `__init__`; add

```python
    @property
    def root_path(self) -> Path:
        return self._root_path

    def project_host_path(self, workspace_id: str, project_id: str) -> Path:
        return (
            self._root_path
            / validate_workspace_segment(workspace_id, label="workspace_id")
            / PROJECTS_DIR
            / validate_workspace_segment(project_id, label="project_id")
        )

    def thread_host_path(self, workspace_id: str, project_id: str, thread_id: str) -> Path:
        return self.project_host_path(workspace_id, project_id) / THREADS_DIR / validate_workspace_segment(thread_id, label="thread_id")
```

(`THREADS_DIR` exists or is the literal the factory already uses for `threads`; use the same constant.) Lease: three `@property` accessors.

- [ ] **Step 4: Run tests and gates**: `uv run pytest tests/agents/test_workspace_attachments_mount.py tests/agents -k "workspace" -q` → PASS; ruff + mypy on `workspace.py` → clean; `make contracts` → kept count unchanged.

- [ ] **Step 5: Commit**

```bash
git add platform/agents/clue_agents/workspace.py tests/agents/test_workspace_attachments_mount.py
git commit -m "feat(agents): read-only attachments mount and host-path accessors"
```

---

### Task 5: Sync the project's attachments on the worker, mount them every turn

**Files:**
- Create: `platform/api/clue_api/project_attachments.py`
- Modify: `platform/api/clue_api/agent_turn_fleet_wiring.py` (after the `mounts = replace(mounts, project_library=True, …)` at ~757 and before `self._engine.components.workspaces.acquire(...)` at ~812: call the sync and set `attachments=True` on the request)
- Test: `tests/api/test_project_attachments_sync_db.py`

**Interfaces:**
- ```python
  @dataclass(frozen=True)
  class ProjectAttachmentEntry:
      filename: str
      ref: ArtifactRef            # workspace_id, artifact_key, sha256, media_type, byte_count
      attached_at: datetime

  async def project_attachment_entries(conn, *, workspace_id: str, project_id: str) -> tuple[ProjectAttachmentEntry, ...]
      # SELECT DISTINCT ON (a.filename) a.filename, a.artifact_key, a.sha256, a.media_type, a.byte_count, a.created_at
      # FROM agent_turn_submission_attachment a
      # JOIN agent_turn_submission s ON s.turn_id = a.turn_id AND s.workspace_id = a.workspace_id
      # JOIN artifact art ON art.storage_key = a.artifact_key
      # WHERE s.workspace_id = :ws AND s.project_id = :project
      #   AND art.erased_at IS NULL AND art.purged_at IS NULL
      # ORDER BY a.filename, a.created_at DESC        -- newest attached upload of a name wins

  async def sync_project_attachments(workspaces: AgentWorkspaceFactory, artifacts: AgentArtifactReader, conn, *, workspace_id: str, project_id: str) -> int
      # ensures <project>/attachments exists (0o700), writes each entry whose file is missing or
      # whose sha256 on disk differs, removes files not in the entry set, returns the number written.
  ```
- All three families are synced (no `media_type NOT LIKE 'image/%'` filter).
- File writes go through the factory's fd (`project_parent_fd` → `ensure_child_directory(parent, ATTACHMENTS_DIR)` → `os.open(name, O_WRONLY|O_CREAT|O_TRUNC|O_NOFOLLOW, 0o600, dir_fd=…)`), never through a path string, matching the brand-library writer's discipline. Confirm the column names on `agent_turn_submission_attachment` in migration `d659c2d2b537` before writing the query.

- [ ] **Step 1: Write the failing DB test**

Seed as in `tests/api/test_chat_attachment_refs_db.py` (one PDF upload, one `.md` upload and one PNG upload inserted on one submission), build a real `AgentWorkspaceFactory` over a `tmp_path` root the way `tests/agents` fixtures do, then:

```python
            written = await sync_project_attachments(factory, artifacts, conn, workspace_id=ws, project_id=project_id)
            assert written == 3
            root = factory.project_host_path(ws, project_id) / "attachments"
            assert (root / "r.pdf").read_bytes() == b"%PDF-1.4 x"
            assert (root / "brief.md").read_text() == "# Brief\n"
            assert (root / "shot.png").exists()
            # idempotent: nothing rewritten the second time
            assert await sync_project_attachments(factory, artifacts, conn, workspace_id=ws, project_id=project_id) == 0
            # re-upload of the same name on a later submission → the newest bytes win
            #   (insert a second submission carrying a new "brief.md" upload with b"# Brief v2\n")
            assert await sync_project_attachments(...) == 1
            assert (root / "brief.md").read_text() == "# Brief v2\n"
            # erasure: mark the pdf's artifact erased → the file is removed on the next sync
            await conn.execute(text("UPDATE artifact SET erased_at = now() WHERE storage_key = :k"), {"k": pdf_key})
            await sync_project_attachments(...)
            assert not (root / "r.pdf").exists()
```

- [ ] **Step 2: Run to see it fail** → FAIL (module missing).

- [ ] **Step 3: Implement** the module per the interface, then in the fleet wiring, just before `acquire(...)`:

```python
        # Spec 2026-09-19 §3.2: every file attached in this project, byte for byte, beside the
        # threads. Synced here — on the worker that owns the workspace root — never by the API.
        async with self._conn_factory() as conn:
            await sync_project_attachments(
                self._engine.components.workspaces,
                self._engine.components.artifacts,
                conn,
                workspace_id=workspace_id,
                project_id=scope.project_id,
            )
        mounts = replace(mounts, attachments=True)
```

(`replace` is already imported at the ~757 site.) Use the same connection factory the surrounding code uses for its pre-acquire reads.

- [ ] **Step 4: Run tests and gates**: `uv run pytest tests/api/test_project_attachments_sync_db.py tests/api -k "fleet_wiring and not live" -q` → PASS; ruff + mypy on the two files → clean; `make contracts` → kept count unchanged.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/project_attachments.py platform/api/clue_api/agent_turn_fleet_wiring.py tests/api/test_project_attachments_sync_db.py
git commit -m "feat(fleet): sync the project's attachments on the worker and mount them every turn"
```

---

### Task 6: L7 names the file's one path; the describer needs no store lookup

**Files:**
- Modify: `platform/agents/clue_agents/context.py:585-660` (`AttachmentDescription` gains `family: str`; `TurnLayerSource.load` wording)
- Modify: `platform/api/clue_api/attachment_binding.py` (`DescribedAttachment(filename, workspace_path, family)`; `workspace_path = f"attachments/{filename}"` for every family; delete the `brand_knowledge_document` query and the `sqlalchemy.text` import; keep the module docstring honest: the path is where the worker's sync puts every attached file)
- Test: `tests/agents/test_turn_layer_attachments.py` (rewrite the assertions), `tests/api/test_attachment_binding_db.py` (recreate: one test, three families)

**Interfaces:**
- L7 lines (one sentence per file; `{size}` is `f"{byte_count:,} bytes"`):
  - text: `Attachment "brief.md" (text/markdown, 120 bytes) was attached to this message. It is at attachments/brief.md; open it with read_file.`
  - document: `Attachment "q3.xlsx" (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet, 412,010 bytes) was attached to this message. It is at attachments/q3.xlsx; open it with run_python.`
  - image: `Attachment "shot.png" (image/png, 4,096 bytes) was attached to this message. It is at attachments/shot.png; it is also shown to you as an image in this message.`
  - undescribed (no describer, or unknown key): unchanged pointer line.
- `AttachmentDescription` protocol: `filename: str`, `workspace_path: str | None`, `family: str` (`"text" | "image" | "document"`). The wording branches on `family`; `workspace_path is None` keeps producing the old image sentence only as a fallback for a describer that names no path.

- [ ] **Step 1: Update the tests** (RED): in `tests/agents/test_turn_layer_attachments.py` give `_Desc` a `family` argument, add a document ref, and assert the three exact sentences above; recreate `tests/api/test_attachment_binding_db.py` with one test that records a `.md`, a `.pdf` and a `.png` upload on one submission and asserts each `DescribedAttachment` has `workspace_path == f"attachments/{filename}"` and the right family (no `materialize_text_attachments`, no document store involved).

- [ ] **Step 2: Run to see it fail** → FAIL.

- [ ] **Step 3: Implement** the wording in `context.py` and the describer fields.

- [ ] **Step 4: Run tests and gates**: `uv run pytest tests/agents/test_turn_layer_attachments.py tests/api/test_attachment_binding_db.py tests/agents -k context -q` → PASS; ruff + mypy; `make contracts`.

- [ ] **Step 5: Commit**

```bash
git add platform/agents/clue_agents/context.py platform/api/clue_api/attachment_binding.py tests/agents/test_turn_layer_attachments.py tests/api/test_attachment_binding_db.py
git commit -m "feat(agents): L7 names every attachment's one workspace path and how to open it"
```

---

### Task 7: `SandboxWorkspaces` — the per-execution registry

**Files:**
- Create: `platform/api/clue_api/sandbox/__init__.py` (empty docstring), `platform/api/clue_api/sandbox/workspaces.py`
- Test: `tests/api/sandbox/__init__.py`, `tests/api/sandbox/test_workspaces.py`

**Interfaces:**
```python
@dataclass(frozen=True)
class SandboxMounts:
    thread_root: Path                      # <root>/<ws>/projects/<p>/threads/<t>
    read_only: Mapping[str, Path]          # name → host dir: inputs, context, reads, brand?, project?, attachments?
    read_write: Mapping[str, Path]         # scratch, work, outputs (created if missing)
    policy: WorkspacePolicy                # the profile's contract (max_file_bytes, max_total_bytes, allowed_extensions, …)

class SandboxWorkspaces:
    def __init__(self, *, max_runs_per_turn: int) -> None
    def register(self, execution_id: ExecutionId, mounts: SandboxMounts) -> None      # ValueError if already registered
    def release(self, execution_id: ExecutionId) -> None                              # idempotent
    def mounts_for(self, execution_id: ExecutionId) -> SandboxMounts | None
    def take_run(self, execution_id: ExecutionId) -> int                              # decrements; returns runs remaining; raises RunBudgetExhausted
    def runs_remaining(self, execution_id: ExecutionId) -> int
def sandbox_mounts_for_lease(lease: AgentWorkspaceLease, workspaces: AgentWorkspaceFactory, *, brand: tuple[str, str] | None, project_library: bool, attachments: bool) -> SandboxMounts
```
- `sandbox_mounts_for_lease` derives paths with the Task 4 accessors: thread root from `thread_host_path`; `brand` → `root_path/<ws>/library/brand/<brand>/<version>`; `project` → `project_host_path/library`; `attachments` → `project_host_path/attachments` (only when the directory exists). The policy is `lease.backend.policy` (confirm the backend exposes its policy; if it is `_policy`, add a read-only `policy` property in this task).
- Thread-safe (a `threading.Lock`): registration happens on the worker loop, `take_run` from the tool's thread.

- [ ] **Step 1: Write the failing test**

```python
# tests/api/sandbox/test_workspaces.py
from pathlib import Path
import pytest
from clue_api.sandbox.workspaces import RunBudgetExhausted, SandboxMounts, SandboxWorkspaces
from clue_agents.contracts import WorkspacePolicy  # adapt to where WorkspacePolicy (the contract) lives

def _mounts(tmp_path: Path) -> SandboxMounts:
    policy = WorkspacePolicy(virtual_mode=True, max_total_bytes=20_971_520, max_file_bytes=1_048_576, max_file_count=400,
                             allowed_extensions=(".md",), readable_prefixes=("scratch",), writable_prefixes=("scratch",), retention_class="agent-ephemeral-v1")
    return SandboxMounts(thread_root=tmp_path, read_only={"inputs": tmp_path / "inputs"}, read_write={"scratch": tmp_path / "scratch"}, policy=policy)

def test_register_take_release(tmp_path: Path) -> None:
    reg = SandboxWorkspaces(max_runs_per_turn=2)
    ex = "exec-1"
    assert reg.mounts_for(ex) is None
    reg.register(ex, _mounts(tmp_path))
    with pytest.raises(ValueError):
        reg.register(ex, _mounts(tmp_path))
    assert reg.runs_remaining(ex) == 2
    assert reg.take_run(ex) == 1 and reg.take_run(ex) == 0
    with pytest.raises(RunBudgetExhausted):
        reg.take_run(ex)
    reg.release(ex); reg.release(ex)
    assert reg.mounts_for(ex) is None
```

(`ExecutionId` is a `str` NewType in `clue_core`; pass strings.)

- [ ] **Step 2: Run to see it fail** → FAIL. **Step 3: Implement** per the interface. **Step 4:** `uv run pytest tests/api/sandbox -q` → PASS; ruff + mypy.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/sandbox tests/api/sandbox
git commit -m "feat(sandbox): per-execution workspace registry and run budget"
```

---

### Task 8: The Docker runner — command builder, execution, output capture

**Files:**
- Create: `platform/api/clue_api/sandbox/docker_runner.py`
- Test: `tests/api/sandbox/test_docker_runner.py`

**Interfaces:**
```python
@dataclass(frozen=True) class SandboxLimits: image: str; timeout_s: float; cpus: float; memory_mb: int; max_output_bytes: int
@dataclass(frozen=True) class SandboxRun: exit_code: int | None; timed_out: bool; duration_ms: int; stdout: bytes; stderr: bytes; stdout_truncated: bool; stderr_truncated: bool
def build_command(mounts: SandboxMounts, limits: SandboxLimits, *, label: str | None = None) -> list[str]
def docker_available(image: str) -> tuple[bool, str]     # (ok, reason) — `docker image inspect <image>` exit 0
def run_script(code: str, *, mounts: SandboxMounts, limits: SandboxLimits, timeout_s: float, label: str | None = None) -> SandboxRun   # BLOCKING; call in a thread
```
- `build_command` returns exactly:
  `["docker", "run", "--rm", "-i", "--network", "none", "--cpus", str(cpus), "--memory", f"{memory_mb}m", "--pids-limit", "256", "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=256m", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", "65534:65534", "--workdir", "/workspace", "--env", "PYTHONDONTWRITEBYTECODE=1", "--env", "MPLCONFIGDIR=/tmp", *label_flags, *mount_flags, image, "python", "-I", "-"]` where `mount_flags` is `-v <host>:/workspace/<name>:ro` for each read-only mount (sorted by name) and `-v <host>:/workspace/<name>:rw` for each read-write one, and `label_flags` is `["--label", f"clue.execution={label}"]` when a label is given (sanitised to `[A-Za-z0-9_.-]`).
- `run_script` creates the read-write dirs if missing (mode 0o700), runs `subprocess.run(cmd, input=code.encode(), capture_output=True, timeout=timeout_s, env={"PATH": "/usr/bin:/bin:/usr/local/bin"})`; on `subprocess.TimeoutExpired` it runs `docker kill` by label when a label was set and returns `timed_out=True, exit_code=None`; stdout/stderr are cut at `max_output_bytes` with the truncated flags.

- [ ] **Step 1: Tests**

```python
# tests/api/sandbox/test_docker_runner.py
import shutil, subprocess
from pathlib import Path
import pytest
from clue_api.sandbox.docker_runner import SandboxLimits, build_command, docker_available, run_script
from tests.api.sandbox.test_workspaces import _mounts

LIMITS = SandboxLimits(image="clue-agent-sandbox:latest", timeout_s=60, cpus=1.0, memory_mb=1024, max_output_bytes=4096)

def test_command_is_locked_down(tmp_path: Path) -> None:
    cmd = build_command(_mounts(tmp_path), LIMITS)
    for flag in ("--network", "none", "--read-only", "--cap-drop", "ALL", "--pids-limit", "256", "--user", "65534:65534"):
        assert flag in cmd
    assert cmd[-3:] == ["python", "-I", "-"]
    assert f"{tmp_path / 'inputs'}:/workspace/inputs:ro" in cmd
    assert f"{tmp_path / 'scratch'}:/workspace/scratch:rw" in cmd
    assert not any(part.startswith("CLUE_") or part.startswith("OPENROUTER") for part in cmd)

def test_output_truncation_flags(monkeypatch, tmp_path: Path) -> None:
    class Done:  # stands in for subprocess.CompletedProcess
        returncode = 0; stdout = b"x" * 10_000; stderr = b""
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Done())
    run = run_script("print('hi')", mounts=_mounts(tmp_path), limits=LIMITS, timeout_s=5)
    assert run.exit_code == 0 and run.stdout_truncated and len(run.stdout) == 4096

def test_timeout_is_reported(monkeypatch, tmp_path: Path) -> None:
    def boom(*a, **k): raise subprocess.TimeoutExpired(cmd="docker", timeout=1)
    monkeypatch.setattr(subprocess, "run", boom)
    run = run_script("while True: pass", mounts=_mounts(tmp_path), limits=LIMITS, timeout_s=1)
    assert run.timed_out and run.exit_code is None

@pytest.mark.skipif(shutil.which("docker") is None or not docker_available("clue-agent-sandbox:latest")[0],
                    reason="Docker or the clue-agent-sandbox image is not available on this host")
def test_real_container_runs_and_writes_scratch(tmp_path: Path) -> None:
    mounts = _mounts(tmp_path)
    run = run_script("import pathlib; pathlib.Path('scratch/hello.md').write_text('hi'); print('ok')", mounts=mounts, limits=LIMITS, timeout_s=60)
    assert run.exit_code == 0 and run.stdout.strip() == b"ok"
    assert (tmp_path / "scratch" / "hello.md").read_text() == "hi"
```

- [ ] **Step 2: Run to see it fail** → FAIL. **Step 3: Implement.** **Step 4:** `uv run pytest tests/api/sandbox -q` → PASS (the real-container test skips until Task 12's image exists); ruff + mypy.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/sandbox/docker_runner.py tests/api/sandbox/test_docker_runner.py
git commit -m "feat(sandbox): locked-down docker runner with output capture and timeout"
```

---

### Task 9: Post-run policy sweep

**Files:**
- Create: `platform/api/clue_api/sandbox/policy_sweep.py`
- Test: `tests/api/sandbox/test_policy_sweep.py`

**Interfaces:**
```python
SANDBOX_OUTPUT_EXTENSIONS: Final = (".csv", ".xlsx", ".docx", ".pptx", ".pdf", ".png")
@dataclass(frozen=True) class SweepResult: kept: tuple[tuple[str, int], ...]; removed: tuple[tuple[str, str], ...]   # (path, bytes) / (path, reason)
def snapshot(mounts: SandboxMounts) -> dict[str, tuple[int, float]]       # path → (size, mtime) over the read-write dirs
def sweep(mounts: SandboxMounts, *, before: Mapping[str, tuple[int, float]]) -> SweepResult
```
- `sweep` walks the read-write dirs (never following symlinks; a symlink or non-regular file is removed with reason `not_a_regular_file`), removes files whose suffix is not in `policy.allowed_extensions + SANDBOX_OUTPUT_EXTENSIONS` (`extension_not_allowed`), files over `policy.max_file_bytes` (`file_too_large`), and, if the total over the writable dirs exceeds `policy.max_total_bytes` or the count exceeds `policy.max_file_count`, removes the newest-written files (by comparison with `before`) until within quota (`quota_exceeded`). `kept` lists files new or changed since `before`, with sizes.

- [ ] **Step 1: Tests** — one test per reason (`extension_not_allowed`, `file_too_large`, `quota_exceeded`, `not_a_regular_file`) plus "unchanged files are not listed as kept", each building a `tmp_path` workspace with `_mounts` from Task 7's test and a policy tuned to trip that one rule. **Step 2:** RED. **Step 3:** implement. **Step 4:** `uv run pytest tests/api/sandbox -q` → PASS + ruff + mypy.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/sandbox/policy_sweep.py tests/api/sandbox/test_policy_sweep.py
git commit -m "feat(sandbox): post-run workspace policy sweep"
```

---

### Task 10: `run_python@1` — the governed tool

**Files:**
- Create: `platform/api/clue_api/run_python_tool.py`
- Modify: `platform/api/clue_api/toolbelt_wiring.py` (`build_toolbelt` gains `sandbox_workspaces: SandboxWorkspaces | None = None`; registers `build_run_python_tools(...)` after the artifact reads at ~2849, `make_default=True`)
- Modify: `platform/api/clue_api/agent_registry_wiring.py` (grants dict: `"run_python": (),` — registered ungranted; Task 14 grants it)
- Test: `tests/api/test_run_python_tool.py`

**Interfaces:**
```python
class RunPythonInput(ToolInput): code: str = Field(min_length=1, max_length=65_536); timeout_s: float | None = Field(default=None, gt=0); note: str | None = Field(default=None, max_length=200)
class RunPythonOutput(ToolOutput): exit_code: int | None; timed_out: bool; duration_ms: int; stdout: str; stdout_spilled_to: str | None; stdout_truncated: bool; stderr: str; stderr_spilled_to: str | None; stderr_truncated: bool; files_written: tuple[dict[str, object], ...]; files_removed: tuple[dict[str, str], ...]; runs_remaining: int
class RunPythonTool(Tool):
    name = "run_python"; version = "1"; effect_class = ToolEffectClass.WRITE
    replay = ReplaySafety(policy=ReplayPolicy.OPERATION_IDEMPOTENT, durable_identity="this operation's journaled receipt", external_boundary=ExternalReplayBoundary.NONE)
    parameter_policy = JournalParameterPolicy(safe_display_fields=("code", "note", "timeout_s"))
    pin_requirements = ("project",)
    def __init__(self, *, settings: Settings, workspaces: SandboxWorkspaces | None)
def build_run_python_tools(*, settings: Settings, workspaces: SandboxWorkspaces | None) -> tuple[Tool, ...]
```
- `invoke`: refuse `PreconditionFailed([PreconditionFailure("sandbox_unavailable", reason)])` when `not settings.sandbox_enabled`, when `workspaces is None`, or when `docker_available(settings.sandbox_image)` is false (reason names the fix: `make sandbox-image`); `workspace_unavailable` when `ctx.execution_id` is `None` or unregistered; `run_budget_exhausted` from `take_run`; clamp `timeout_s` to `settings.sandbox_timeout_s`. Then `before = snapshot(mounts)`, `run = await asyncio.to_thread(run_script, …, label=ctx.execution_id)`, `swept = sweep(mounts, before=before)`. Stdout/stderr over 16 KB are written by the tool to `<thread_root>/reads/<operation_id>.stdout.txt` (and `.stderr.txt`) with mode 0o600 and referenced as `reads/<operation_id>.stdout.txt`; the inline field then holds the first 16 KB. `model_description` (plain language): the container's paths, that `attachments/` holds every file attached in this project, the run budget, and "Manual: .deepagent/skills/manual-tools/v5/SKILL.md#run_python".
- Copy the refusal, replay and journal mechanics from an existing WRITE tool in `clue_api` (find one with `ReplayPolicy.OPERATION_IDEMPOTENT`) rather than inventing them.

- [ ] **Step 1: Tests** (pure, with `SandboxWorkspaces` and `monkeypatch`ed `run_script`/`docker_available`): refusal codes for each precondition; a happy run returning `exit_code 0`, `files_written` from the sweep, `runs_remaining` decrement; spill when stdout > 16 KB; the tool appears in `build_toolbelt(...)` with address `run_python@1` and is granted to nobody (`authority` dict).

- [ ] **Step 2:** RED. **Step 3:** implement. **Step 4:** `uv run pytest tests/api/test_run_python_tool.py tests/api/test_toolbelt_wiring.py -q` → PASS after updating the two registry counts in `test_toolbelt_wiring.py` (`names 136 → 137`, `addresses 156 → 157`, at both assertion sites, with a one-line comment in the file's existing style); ruff + mypy; `make contracts`.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/run_python_tool.py platform/api/clue_api/toolbelt_wiring.py platform/api/clue_api/agent_registry_wiring.py tests/api/test_run_python_tool.py tests/api/test_toolbelt_wiring.py
git commit -m "feat(toolbelt): run_python@1 — sandboxed script execution, registered ungranted"
```

---

### Task 11: Wire the registry through the worker and the conversation engine

**Files:**
- Modify: `platform/api/clue_api/agent_platform_wiring.py` (`AgentPlatformComponents.sandbox_workspaces: SandboxWorkspaces | None = None` after `history_images_max`; `build_agent_platform_components` builds `SandboxWorkspaces(max_runs_per_turn=settings.sandbox_max_runs_per_turn)` when `settings.sandbox_enabled`)
- Modify: `platform/api/clue_api/fleet_main.py` (~1006: pass `sandbox_workspaces=` to `build_toolbelt`; the same instance must be the one on the components — build it once before both calls)
- Modify: `platform/api/clue_api/conversation_turns.py` (~410–440): register before `build_head_of_abm_stage0_execution`, release in a `finally`
- Modify: `platform/api/clue_api/agent_turn_fleet_wiring.py`: the engine needs the mount facts (`brand`, `project_library`, `attachments`) to derive host paths — pass the `MountRequest` used at `acquire` into `engine.run(...)` (add a `mounts: MountRequest | None = None` kwarg on the engine's run method and thread it)
- Test: `tests/api/test_sandbox_registration_db.py` (or extend `tests/api/test_o6_conversation_composition_db.py`)

**Interfaces:**
- In `conversation_turns.py`:
```python
            sandbox = self.components.sandbox_workspaces
            if sandbox is not None and mounts is not None:
                sandbox.register(
                    request.constitution.execution_id,
                    sandbox_mounts_for_lease(lease, self.components.workspaces, brand=mounts.brand, project_library=mounts.project_library, attachments=mounts.attachments),
                )
            try:
                execution = build_head_of_abm_stage0_execution(...)
                outcome = await self._runtime.run(...)
            finally:
                if sandbox is not None:
                    sandbox.release(request.constitution.execution_id)
```

- [ ] **Step 1: Test**: compose the engine with a `SandboxWorkspaces` and a fake runtime whose `run` asserts `sandbox.mounts_for(execution_id)` is set during the turn and `None` after; assert the thread root equals `workspaces.thread_host_path(...)`.

- [ ] **Step 2:** RED. **Step 3:** implement. **Step 4:** `uv run pytest tests/api/test_o6_conversation_composition_db.py tests/api/test_sandbox_registration_db.py tests/api -k "fleet_wiring and not live" -q` → PASS; ruff + mypy on the four files; `make contracts`.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/agent_platform_wiring.py platform/api/clue_api/fleet_main.py platform/api/clue_api/conversation_turns.py platform/api/clue_api/agent_turn_fleet_wiring.py tests/api/test_sandbox_registration_db.py
git commit -m "feat(fleet): the conversation engine registers the turn's sandbox mounts while it holds the lease"
```

---

### Task 12: The sandbox image and `make sandbox-image`

**Files:**
- Create: `docker/agent-sandbox/Dockerfile`, `docker/agent-sandbox/README.md`
- Modify: `Makefile` (target after `langfuse-check`)
- Test: `tests/api/sandbox/test_docker_runner.py::test_real_container_runs_and_writes_scratch` now runs (not skipped) on a host with Docker

- [ ] **Step 1: Dockerfile**

```dockerfile
# The Head-of-ABM code sandbox (spec 2026-09-19 §3.4). One container per run_python call:
# no network, no secrets, read-only root, an unprivileged user. Rebuild with `make sandbox-image`.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir \
    pymupdf==1.24.* pypdf==5.* pdfplumber==0.11.* python-docx==1.1.* python-pptx==1.0.* \
    openpyxl==3.1.* pandas==2.2.* matplotlib==3.9.* pillow==11.* pytesseract==0.3.*
RUN mkdir -p /workspace && chown 65534:65534 /workspace
USER 65534:65534
WORKDIR /workspace
ENV PYTHONDONTWRITEBYTECODE=1 MPLCONFIGDIR=/tmp
```

Makefile:

```make
# --- agent code sandbox (spec 2026-09-19) ------------------------------------
sandbox-image: ## Build the Head-of-ABM code sandbox image named by CLUE_SANDBOX_IMAGE (default clue-agent-sandbox:latest)
	docker build -t $${CLUE_SANDBOX_IMAGE:-clue-agent-sandbox:latest} docker/agent-sandbox
```

README: what is in the image, how to rebuild, that `CLUE_SANDBOX_ENABLED=true` is the switch, that without the image a binary attachment is unreadable to the agent, and that the tool refuses `sandbox_unavailable` naming `make sandbox-image` when the image is absent.

- [ ] **Step 2:** `make sandbox-image` on this host (a few hundred MB download; the founder has agreed), then `uv run pytest tests/api/sandbox/test_docker_runner.py -q -rs` → the real-container test PASSES (not skipped). Record the image size in the README.

- [ ] **Step 3: Commit**

```bash
git add docker/agent-sandbox Makefile
git commit -m "feat(sandbox): the clue-agent-sandbox image and make sandbox-image"
```

---

### Task 13: What the agent is taught — skill, manual chapter, Stage-0 pointer, prompt v11

**Files:**
- Create: `platform/agents/catalog/skills/code-execution/v1/SKILL.md`
- Create: `platform/agents/catalog/skills/manual-workspace/v5/SKILL.md` (copy of v4 with the `attachments/` mount row, a new "## `attachments/` — every file attached in this project" section stating: text files open with `read_file`; PDFs, Office files, images and any text file over 1 MiB open with `run_python`; nothing here is a summary, it is the file itself; and `run_python`'s read/write rules in the writes paragraph)
- Create: `platform/agents/catalog/skills/stage0-interview/v34/SKILL.md` (copy of v33; §1 gains "When a message names an attachment, read `.deepagent/skills/code-execution/v1/SKILL.md` first"; §7c gains one bullet "**What an attached file says:** open it — `read_file` for a text file, `run_python` for anything else — and read the whole thing, in pages or sheets, before you summarise it (asked of you)"; the frontmatter `tools:` list is unchanged)
- Create: `platform/agents/catalog/prompts/head-of-abm/v11/SYSTEM.md` (copy of v10; the sentence "There is no shell, code execution, host filesystem, arbitrary network, secret, or provider SDK access." becomes "There is no shell, host filesystem, arbitrary network, secret, or provider SDK access. Code runs only through `run_python`, inside the sandbox its manual entry describes.")
- Modify: `platform/agents/catalog/manual/tool_notes.yaml` (a `run_python:` entry with `afterwards`, `skill_section`, `see_also: [workspace, limits]`, `refusals` for `sandbox_unavailable`, `workspace_unavailable`, `run_budget_exhausted`, `code_too_large`, `project_not_found`)
- Test: `tests/agents/test_catalog.py` (lexical lists gain `skill:code-execution@v1`, `skill:manual-workspace@v5`, `skill:stage0-interview@v34`, `prompt:head-of-abm@v11`), `tests/agents/test_manual_drift.py` (the rule-sentence audit runs over the new skill; every rule line carries `(enforced)` or `(asked of you)`)

**The `code-execution` skill** (frontmatter `schema_version: "1"`, `kind: skill`, `name: code-execution`, `version: v1`, `summary: "Run a short Python script in the sandbox over your workspace to read an attached PDF, Word, PowerPoint, spreadsheet, CSV or JSON file, compute over it, or produce a derived file."`, `roles: [head_of_abm]`, `tools:` listing `run_python` `"1"` with its two schema digests computed by `python -c "from clue_toolbelt.envelope import _schema_sha256; from clue_api.run_python_tool import RunPythonInput, RunPythonOutput; print(_schema_sha256(RunPythonInput)); print(_schema_sha256(RunPythonOutput))"`). Body sections, plain language, adapted from `attachments/XLSX/skill.md`, `attachments/DOCX/skill.md`, `attachments/PDF/skill.md` (their reading parts; their delivery, styling and `displayFileV2` parts do not apply here):

1. **When to run code, when not to** — every file attached in this project is at `attachments/<name>`. A text file (`.md`, `.txt`, small `.csv`/`.json`) opens with `read_file`; anything else opens only with `run_python`: a PDF, a Word file, a deck, a spreadsheet, an image you want to measure, or a text file too big for `read_file`. Also run code when you need a number computed rather than read, a table joined or filtered, or a file produced. Do not run code for a question the transcript already answers. The budget is N runs per turn (`(enforced)`); a run is not a launch and spends nothing outside the container.
2. **Where things are inside the container** — `/workspace` is your workspace: `attachments/` (every attached file, read only), `project/`, `brand/`, `inputs/`, `context/`, `reads/` read only; `scratch/`, `work/`, `outputs/` writable; only files with the allowed extensions survive a run (`(enforced)`); nothing on the network, no secrets, no `pip install` (`(enforced)`).
3. **Reading recipes** — XLSX two passes (`load_workbook(path, data_only=False)` for formulas, `data_only=True` for cached values; `None` for a never-recalculated formula; `pandas.read_excel(path, sheet_name=None)` for bulk); PDF (`fitz.open(path)`, `page.get_text("text")`, `page.find_tables()`, `pdfplumber` for tables; a page with no text → render with `page.get_pixmap(dpi=200)` and `pytesseract.image_to_string`); DOCX (`docx.Document(path)`, paragraphs with `p.style.name`, `doc.tables`); PPTX (`pptx.Presentation(path)`, slide shapes' `text_frame`, `slide.notes_slide`); CSV/JSON with pandas / `json`; images with `PIL.Image`. Print what you found; keep output under the cap; write big results to `work/` and read them back with `read_file`.
4. **Reporting** — every number you state comes from output you saw, with its page, sheet or row (`(asked of you)`); when a run fails, read stderr, fix, and try again within the budget; when the sandbox is unavailable, tell the human you cannot open the file right now — never guess at its contents (`(asked of you)`).
5. **Producing files** — write under `outputs/` with an allowed extension; say what you wrote and where; nothing you write is shown to the human yet.

- [ ] **Step 1:** Write the four resources and the notes entry. **Step 2:** `uv run pytest tests/agents/test_catalog.py tests/agents/test_manual_drift.py -q` → FAIL on the lexical lists → add the four addresses (keep the lists sorted the way the file sorts them) → PASS. If `test_manual_drift`'s `SKILLS_BLOCK_MAX_BYTES` (4608) trips because the disclosed skills block grew, raise it with a dated comment in the file's existing style stating the new measured size.

- [ ] **Step 3: Commit**

```bash
git add platform/agents/catalog/skills/code-execution platform/agents/catalog/skills/manual-workspace/v5 platform/agents/catalog/skills/stage0-interview/v34 platform/agents/catalog/prompts/head-of-abm/v11 platform/agents/catalog/manual/tool_notes.yaml tests/agents/test_catalog.py tests/agents/test_manual_drift.py
git commit -m "feat(head-of-abm): code-execution skill, workspace chapter v5, stage0 v34, prompt v11"
```

---

### Task 14: Profile v58, recipe v29, the pins, the generated manual

**Files:**
- Create: `platform/agents/catalog/profiles/head-of-abm/v58/profile.yaml` (copy v57; `version: v58`; header comment; `prompt.version: v11` + its sha256; skills: `stage0-interview v34`, `manual-workspace v5`, every `manual-*` chapter at `v5`, plus `code-execution v1`, each with the SHA-256 of its `SKILL.md`; tools: add `run_python "1"` with the two schema digests; `workspace.allowed_extensions` unchanged (the sandbox's extra output extensions are enforced by the sweep, not by `write_file`); `workspace.readable_prefixes` gains `"attachments"`)
- Create: `platform/execution/recipes/recipe0-stage0-v29.json` (copy v28; `"version": 29`; `run_python@1` appended to `graph.tool_allowlist`, `nodes[1].dynamic_tool_allowlist`, `nodes[1].requirements` (`{"kind": "tool", "key": "run_python", "version": "1"}`) and `compatibility.nodes.stage0_interactions`)
- Modify: `platform/api/clue_api/recipe_wiring.py` (add `"recipe0-stage0-v29.json"` with a comment), `platform/api/clue_api/recipe_contracts.py` (RECIPE_0 addresses gain `"run_python@1"`), `platform/api/clue_api/stage0_recipe.py` (the tool name list gains `"run_python"`), `platform/api/clue_api/conversation_turns.py` (`CONVERSATION_RECIPE_VERSION = 29`), `platform/api/clue_api/agent_registry_wiring.py` (`AgentRole.HEAD_OF_ABM: "v58"`; grants `"run_python": (AgentRole.HEAD_OF_ABM,)`), `platform/api/clue_api/chat/composer_context.py` (`PROJECT_CONVERSATION_AGENT_PROFILE_ID = "head-of-abm@v58"`), `platform/agents/clue_agents/manual/build.py` (`MANUAL_VERSION = "v5"`, `PROFILE_VERSION = "v58"`), `platform/agents/catalog/manual/tool_notes.yaml` header
- Generated: `make manual` writes `manual-tools/v5`, `manual-fields/v5`, `manual-errors/v5`, `manual-limits/v5`; copy the other hand-written chapters (`index`, `turn`, `claims`, `accounts-research`, `discovery`, `documents-decisions`, `gates-authority`, `humans-screens`, `siblings`, `glossary`) to `v5` unchanged except their `version:` line and cross-reference paths (`make manual-link`), because the profile pins one manual version for every chapter
- Tests to update: `tests/agents/test_catalog.py` (`profile:head-of-abm@v58`, every `skill:manual-*@v5`), `tests/api/test_comprehensive_research_contract.py:469-470`, `tests/api/test_agent_registry_wiring.py:545`, `tests/api/test_client_knowledge_privacy_s4e.py:161`, `tests/api/test_toolbelt_wiring.py` (the authority dict now grants `run_python` to `HEAD_OF_ABM`), `tests/agents/test_tool_authority_audit.py` (if it enumerates grants)

- [ ] **Step 1:** Make every edit above; compute digests with `shasum -a 256 <SKILL.md>` and the schema snippet from Task 13. **Step 2:** `make manual && make manual-check` clean. **Step 3:** Run `uv run pytest tests/agents tests/api/test_toolbelt_wiring.py tests/api/test_agent_registry_wiring.py tests/api/test_comprehensive_research_contract.py tests/api/test_client_knowledge_privacy_s4e.py tests/api/test_o6_conversation_composition_db.py -q --ignore-glob='*_live.py'` (DB ones on the test DB) → PASS; `make lint typecheck contracts` clean.

- [ ] **Step 4: Commit**

```bash
git add platform/agents/catalog platform/execution/recipes/recipe0-stage0-v29.json platform/api/clue_api/recipe_wiring.py platform/api/clue_api/recipe_contracts.py platform/api/clue_api/stage0_recipe.py platform/api/clue_api/conversation_turns.py platform/api/clue_api/agent_registry_wiring.py platform/api/clue_api/chat/composer_context.py platform/agents/clue_agents/manual/build.py tests
git commit -m "feat(head-of-abm): v58 grants run_python@1 and pins the attachments-aware skills; recipe 29; manual v5"
```

---

### Task 15: Frontend — document types in the composer

**Files:**
- Modify: `apps/frontend/src/features/projects/model/chat-attachments.ts` (`CHAT_ATTACHMENT_ACCEPT` gains `.pdf,.docx,.pptx,.xlsx,.csv,.json,application/pdf,text/csv,application/json` and the three OOXML types; `CHAT_ATTACHMENT_LIMITS.documentMaxBytes: 26_214_400`; `AttachmentFamily` gains `"document"`; `DOCUMENT` set and `BY_EXT` entries; `attachmentLimitError` message `"${file.name} is over 25 MB."`)
- Modify: `apps/frontend/src/features/projects/hooks/use-chat-attachments.ts` (`UNSUPPORTED` message: "Use a .md, .txt, .pdf, .docx, .pptx, .xlsx, .csv or .json file, or a PNG, JPEG, WebP or GIF image.")
- Modify: `apps/frontend/src/features/chat-shell/model/attachment-routing.ts` — unchanged behaviour (documents are not images, so they go the chat route); add a test line for a `.pdf`
- Test: `chat-attachments.test.ts` (family, accept list, document limit), `attachment-routing.test.ts`

No upload-receipt change: the response shape is the same as PR #64's (no conversion note exists).

- [ ] **Step 1:** Tests RED. **Step 2:** implement. **Step 3:** `cd apps/frontend && npm test && npm run lint && npm run build` → PASS, 0 errors.

- [ ] **Step 4: Commit**

```bash
git add apps/frontend/src/features/projects/model/chat-attachments.ts apps/frontend/src/features/projects/model/chat-attachments.test.ts apps/frontend/src/features/projects/hooks/use-chat-attachments.ts apps/frontend/src/features/chat-shell/model/attachment-routing.test.ts
git commit -m "feat(frontend): document attachments (pdf, docx, pptx, xlsx, csv, json) in the composers"
```

---

### Task 16: Contract notes, memory, backlog, and the owed live walk

**Files:**
- Modify: `apps/frontend/docs/api-contracts/projects.md` ("Chat attachments" section: the document family, the 25 MB cap, `UPLOAD_NOT_A_DOCUMENT`; every attached file is a file in the agent's workspace, no family becomes a project document; Task 3 already removed the document-route wording — finish the section here)
- Modify: `_memory/2026-09-18-chat-attachments-and-target-accounts-card-exploration.md` (execution record: per-task commits, gates with counts, both ruling blocks, the retirement of the text route, deferred minors, the image build, the owed walk; strike the "re-upload edited copy → v2" step of the earlier owed walk)
- Modify: `CLAUDE.md` (amend the `[chat×attachments]` backlog bullet: the text-document route is retired; add one `[chat×sandbox]` bullet — what shipped, `CLUE_SANDBOX_ENABLED` off by default, `make sandbox-image` per host, a binary attachment is unreadable without it, residuals: outputs not rendered to the human, the sandbox is Head-of-ABM only)

- [ ] **Step 1:** Write the three documents. **Step 2:** Live walk (founder-triggered; do not run unattended): build the image, set `CLUE_SANDBOX_ENABLED=true` in the lane `.env`, restart the workers, then in a project chat: attach a spreadsheet and ask for a column total (expect a `run_python` receipt in the inspector and a number with the sheet named); attach a PDF and ask for a figure on page 3; attach a scanned PDF and ask what it says (expect OCR inside the run); attach a `.md` and ask about it (expect a `read_file`, no sandbox run); ask for a CSV derived from the spreadsheet (expect `outputs/<name>.csv` in `files_written`); upload a file with the wrong magic bytes (expect the chip to fail with the reason). Record outcomes in the memory note.

- [ ] **Step 3: Commit**

```bash
git add apps/frontend/docs/api-contracts/projects.md _memory/2026-09-18-chat-attachments-and-target-accounts-card-exploration.md CLAUDE.md
git commit -m "docs(chat): document attachments and the code sandbox — contract notes, execution record, backlog"
```

---

## Self-review

**Spec coverage.** §3.1 (family, caps, magic, `UPLOAD_NOT_A_DOCUMENT`, no migration) → Tasks 1, 2. §3.2 (worker-side sync of every family, `attachments/` mount, newest-name-wins, erasure, the one-sentence L7 line, the describer without a store lookup) → Tasks 4, 5, 6. §3.3 (retirement of the text route and its tests) → Task 3. §3.4 (contract, refusals, execution flags, sweep, registry, image, settings, off by default, OCR is the agent's call) → Tasks 1, 7–12. §3.5 (skill, manual v5, stage0 v34, prompt v11, profile v58, recipe 29, pins) → Tasks 13, 14. §3.6 security → Tasks 8 (flags), 9 (sweep), 10 (journaled code, refusals), 5 (erasure at sync). §3.7 frontend → Task 15. §4 testing → each task; live walk in Task 16. §5 out of scope respected (no rendering, no network, no LibreOffice formats, no markdown rendering).

**Placeholder scan.** Tasks 3, 4, 5, 9, 11, 13 describe tests by contract where the fixture setup is forty lines already present in a named neighbouring file; the assertions are stated exactly. No TBDs. Task 3 names the one choice (delete `test_attachment_binding_db.py` and let Task 6 recreate it) and makes it.

**Type consistency.** `attachment_family` returns the three-valued literal from Task 2 onward; Task 3 widens `ValidatedAttachment.family` to match; Task 6's `DescribedAttachment.family` and the `AttachmentDescription` protocol carry the same three strings. `SandboxMounts`/`SandboxWorkspaces` (Task 7) are consumed by Tasks 8–11 with the same field names. `AgentWorkspaceFactory.thread_host_path/project_host_path/root_path` and the lease segment properties (Task 4) are what Task 7's `sandbox_mounts_for_lease` uses and what Task 5's sync writes under. `RunPythonInput`/`RunPythonOutput` (Task 10) are what Task 13's digest snippet and Task 14's profile pin name. `MountRequest.attachments` (Task 4) is set in Task 5 and read in Task 11.
