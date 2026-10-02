# Agent code execution and document attachments

Status: APPROVED 2026-09-19, revised the same day at the founder's ruling to drop every
markdown conversion step (see the second ruling block). Branch
`rebase-and-expand-attachment-types` (cut from `origin/research-streaming` after PR #64 merged the
chat-attachments feature).

## 1. What we are building

Head-of-ABM gets two new abilities so that a person can attach a PDF, Word file, PowerPoint,
spreadsheet or data file to a chat and the agent can genuinely work with it:

1. **Every attachment reaches the agent as the file it is.** The upload path accepts PDF, DOCX,
   PPTX, XLSX, CSV and JSON beside the markdown, text and image types it accepts today. At the
   start of every turn the worker installs every file ever attached in this project, byte for
   byte, in a read-only `attachments/` folder of the agent's workspace that all the project's
   threads share. Nothing is converted, summarised or rewritten on the way in. A text file is read
   with `read_file`; a binary is read with code; an image is also shown to the model as an image,
   as it is today.
2. **A governed `run_python@1` tool.** The agent can run a short Python script in a sandboxed
   container over its own workspace, with the document libraries preinstalled, no network, no
   secrets, and hard limits on time, CPU, memory, output and the number of runs per turn. The
   script's stdout, stderr, exit code and the files it wrote come back as a governed receipt.

This is the shape the founder's reference material (the XLSX, DOCX and PDF skills under
`attachments/`, written for a CRM platform's agent) assumes: the file is mounted at a path, the
sandbox has the libraries, the skill teaches the agent how to read each format with code. That
material is what the new agent skill is adapted from.

### Founder rulings (2026-09-19, morning)

- Option 1 chosen: execution in a container on the worker host, over the thread's own workspace.
  A hosted sandbox (documents leaving the box) was rejected; converters-only was rejected as too
  limiting ("I don't want it restricted to just reading markdown files").
- Defaults proposed and accepted by proceeding: Docker, no network, 60 s wall clock, 1 CPU,
  1 GB RAM, 10 runs per turn, 1 MB captured output, PyMuPDF / pypdf / pdfplumber / python-docx /
  python-pptx / openpyxl / pandas / matplotlib / Tesseract in the image. Each is a setting, so
  the founder can amend any of them in `.env` without a code change.

### Founder rulings (2026-09-19, afternoon) — one mechanism, no markdown step

- **No conversion at upload, no markdown twin, no "markdown first".** The earlier draft converted
  every document to markdown at upload and wrote it as a project document beside the original.
  Ruled out: it was a second mechanism serving a fast path the agent does not need, and it made
  the platform "markdown first" for no product reason. The sandbox is the one way to read a
  binary.
- **The text-file route from PR #64 is retired too.** A `.md`/`.txt` upload no longer becomes a
  versioned project document at `attachments/<name>` (and so no longer appears in the Gallery).
  It is synced into `attachments/` like every other file and read with `read_file`. The version
  chain on re-upload goes: the newest upload of a name wins in the folder; every upload row is
  still at rest.
- **Images are synced too**, so code can process them; they still ride the message as image
  parts (ruling 1 of the attachments feature) and still stay out of the Gallery (ruling 3).
- **Accepted trade-off:** a binary attachment is unreadable when the sandbox is unavailable. On
  any host running the fleet worker, Docker plus the built image is a requirement for document
  attachments; the tool's `sandbox_unavailable` refusal is what the agent tells the human.

## 2. What exists today (verified 2026-09-19)

- **Attachments (PR #64).** `POST /frontend/v1/uploads` accepts `.md`/`.txt` and PNG/JPEG/WebP/GIF
  (`platform/api/clue_api/chat/uploads.py`, allow-lists at lines 37–48); a submission carries
  `attachment_refs` (`agent_turn_submission_attachment`); text uploads become project documents
  at `attachments/<name>` at send time (`chat/attachments.py::materialize_text_attachments`,
  called from `chat/router.py::_wrote_attachment_documents` at two call sites — **retired by this
  spec**); images ride the model message as image parts; the L7 context line names each
  attachment and, for text, its workspace path (`clue_agents/context.py::TurnLayerSource`,
  `clue_api/attachment_binding.py`, which looks the path up in the project-document store —
  **simplified by this spec**).
- **The agent workspace is a real directory** per thread at
  `<CLUE_AGENT_WORKSPACE_ROOT>/<workspace>/projects/<project>/threads/<thread>/`
  (`clue_agents/workspace.py::AgentWorkspaceFactory`), reached through file-descriptor anchoring
  (`AnchoredAgentWorkspaceBackend`). Mounts are directories the backend opens beside the thread
  root (`MountRequest`: `brand` → `<ws>/library/brand/<brand>/<version>`, `project_library` →
  `<ws>/projects/<project>/library`), read-only, not charged against the workspace quota
  (`_quota_files` skips read-only and versioned mounts). The profile's workspace policy
  (head-of-abm v57) is 20 MiB total, 1 MiB per file, 400 files, writable prefixes
  `scratch/ work/ outputs/ project/`, allowed write extensions `.json .md .txt .yaml`, readable
  prefixes `.deepagent inputs context scratch reads work outputs brand project`. Extension checks
  apply to writes only; `read_file` is bounded by the readable prefixes, the 1 MiB cap and UTF-8.
- **Governed tools** subclass `clue_toolbelt.Tool` (`name`, `version`, `input_model`,
  `output_model`, `effect_class`, `replay`, `parameter_policy`, `pin_requirements`, `invoke`) and
  are registered in `toolbelt_wiring.build_toolbelt`, granted per role in
  `agent_registry_wiring.py`, listed in the recipe contract (`recipe_contracts.py` RECIPE_0
  addresses, `stage0_recipe.py`), pinned by the profile, and described in the generated manual
  through `catalog/manual/tool_notes.yaml`. `ToolContext` carries `workspace_id`, `execution_id`,
  `operation_id` and worker identity but no workspace handle; the oversized-result spill
  (`reads/<operation_id>.json`) is the one seam today where a tool output touches the workspace,
  bound in `head_of_abm_wiring.py` where the lease is in hand (`spill_sink=`).
- **Subprocess precedent.** The design leg runs `lumen-api-helper` as a blocking subprocess
  inside `asyncio.to_thread` (`design_leg_tools.py:651`). No container or sandbox code exists.
  Docker Desktop is installed on the founder's machine (the only backend host today).
- **The Head-of-ABM prompt (v10) says** "There is no shell, code execution, host filesystem,
  arbitrary network, secret, or provider SDK access." Nothing in `docs/architecture/` rules on
  code execution either way; the sentence is a v1 statement of what the workspace offered.

## 3. Design

### 3.1 Document uploads

The upload route gains a third family, `document`:

| Family | Media types | Per-file cap (setting) |
|---|---|---|
| text (exists) | `text/markdown`, `text/plain` | `CLUE_CHAT_ATTACHMENT_TEXT_MAX_BYTES` (5 MB) |
| image (exists) | PNG, JPEG, WebP, GIF | `CLUE_CHAT_ATTACHMENT_IMAGE_MAX_BYTES` (10 MB) |
| document (new) | `application/pdf`; DOCX, PPTX, XLSX (their OOXML types); `text/csv`; `application/json` | `CLUE_CHAT_ATTACHMENT_DOCUMENT_MAX_BYTES` (25 MB) |

Legacy `.doc`/`.ppt`/`.xls` and macro workbooks are out of scope (they need LibreOffice).
Validation at upload: extension and declared type resolve as today; magic bytes (`%PDF-`, the zip
signature for the three OOXML types, UTF-8 for CSV and JSON, a JSON parse for JSON); a mismatch
refuses `UPLOAD_NOT_A_DOCUMENT`, the sibling of today's `UPLOAD_NOT_AN_IMAGE`. The message-level
rules (10 files, 150 MB) are unchanged. The upload row is unchanged: no new columns, no migration.

### 3.2 Where the bytes go: the `attachments` mount

At send time the submission path records nothing new on disk; the durable facts are the upload
row and the submission's attachment rows, exactly as today. The **fleet worker** installs the
tree at the start of every Head-of-ABM turn, before the workspace is acquired: an idempotent
sync of every upload attached to any turn of the project (every
`agent_turn_submission_attachment` row of the project, joined to `chat_upload` and the artifact
row) into `<ws>/projects/<project>/attachments/<filename>` on the worker host. It writes only
files that are missing or whose bytes differ, removes files whose upload has been erased or
purged, and when two uploads share a filename the one attached most recently wins. All three
families are synced. The worker owns the workspace root, so this works when the API and the
worker are on different machines (they share one laptop today). There is no index file: the
folder listing is the index, and the transcript says which message each file came with.

Every Head-of-ABM turn mounts that tree read-only as `attachments/` (`MountRequest.attachments`),
the same mechanism as `brand/` and `project/`, so it is not charged against the workspace quota
and every thread of the project sees the same files. The profile's readable prefixes gain
`attachments`. `read_file` reads a UTF-8 file up to 1 MiB (so `.md`, `.txt`, `.csv`, `.json` of
ordinary size); a binary, or a text file over 1 MiB, is read through `run_python@1`. The L7
attachment line becomes one sentence per file:

```
Attachment "q3-pipeline.xlsx" (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,
412,010 bytes) was attached to this message. It is at attachments/q3-pipeline.xlsx; open it with
run_python.
```

with `open it with read_file` for a text file, and `; it is also shown to you as an image in this
message` for an image. The describer no longer consults the project-document store; the path is
`attachments/<filename>` for every family, and the filename is the one the submission row holds.

### 3.3 What is retired

- `chat/attachments.py::materialize_text_attachments`, `_attachment_document`,
  `ATTACHMENT_FOLDER`; `chat/router.py::_wrote_attachment_documents` and its two call sites; the
  attachment-triggered `project_library.refresh`; the store lookup in
  `attachment_binding.DbAttachmentDescriber`; `tests/api/test_chat_attachment_documents_db.py`.
- Project documents already written at `attachments/<name>` in development databases stay as
  ordinary documents; nothing reads them specially and no data migration is run (dev data only).
- The "re-upload an edited copy makes version 2" step of the owed PR #64 live walk.

### 3.4 `run_python@1`

**Contract.**

- Inputs: `code` (str, ≤ 65,536 bytes), `timeout_s` (optional, ≤ the setting), `note`
  (optional one-line purpose, journaled). No file arguments: the script reads and writes the
  workspace by relative path.
- Output references: `exit_code`, `duration_ms`, `stdout` (inline up to 16 KB, else spilled to
  `reads/<operation_id>.stdout.txt` and referenced), `stderr` (same rule), `files_written`
  (paths under the writable prefixes, with sizes), `files_removed` (what the sweep deleted, with
  the reason), `truncated` flags, `runs_remaining` for the turn.
- `effect_class = WRITE` (it changes workspace files); `ReplayPolicy.OPERATION_IDEMPOTENT`
  keyed on the operation id: a replayed turn serves the journaled receipt and never re-runs the
  script. `parameter_policy` journals `code` and `note` verbatim (the script is the audit
  record). `pin_requirements = ("project",)`.
- Refusals (preconditions): `sandbox_unavailable` (feature off, Docker not reachable, image
  missing, worker running as root), `run_budget_exhausted` (per-turn cap), `code_too_large`,
  `workspace_unavailable` (no lease bound for this execution). A non-zero exit or a timeout is a normal result, not a
  refusal, so the model can read stderr and try again.

**Execution.** The tool runs, off the event loop (`asyncio.to_thread`, the design precedent),
one `docker run --rm` of the configured image with:

- `--network none`, `--cpus <CLUE_SANDBOX_CPUS>`, `--memory <CLUE_SANDBOX_MEMORY_MB>m`,
  `--pids-limit 256`, `--read-only` root filesystem, a `tmpfs` at `/tmp`, `--cap-drop ALL`,
  `--security-opt no-new-privileges`, the worker's non-root UID/GID (`--user`), no environment
  variables from the host;
- bind mounts: the thread's `scratch/`, `work/`, `outputs/` read-write; its `inputs/`,
  `context/`, `reads/` and the `brand/`, `project/`, `attachments/` mount directories read-only,
  all at `/workspace/<name>` so the paths the agent uses elsewhere hold inside the container
  (working directory `/workspace`);
- a fixed startup command sets `umask 077` inside the container, then execs `python -I -`;
  the script is passed on stdin, never inserted into shell text. Files are private (`0600`)
  and directories private (`0700`) at creation, with ownership matching the worker. The
  worker process's umask is never changed;
- wall-clock enforced by the tool (kill and report
  `timed_out`), stdout and stderr captured up to `CLUE_SANDBOX_MAX_OUTPUT_BYTES` each with a
  truncation marker.

After the run the tool scans the writable prefixes, refuses and deletes files that break the
workspace policy (an extension outside the allow-list, a file over the per-file cap, the total
over quota), and reports what it removed in the receipt. The allow-list for sandbox-written
files is the profile's `allowed_extensions` plus `.csv .xlsx .docx .pptx .pdf .png`, so a
script can leave a derived spreadsheet or a chart under `outputs/` (nothing renders those for
the human yet; they are snapshotted to artifacts at finalize like any output).
The sweep also removes disallowed links and repairs modes explicitly changed or copied by a
script; ordinary outputs require no chmod. This supersedes the initial fixed `nobody` UID and
post-run permission repair as the normal path (founder ruling, 2026-09-20).

**Finding the workspace.** `ToolContext` has no workspace handle, so the tool is given a
`SandboxWorkspaces` registry at composition: the conversation engine registers the turn's
execution id with the host paths derived from the lease (`PreparedWorkspaceRoot.path` plus the
lease's workspace, project and thread segments, and each mount's directory) at the same point
it binds the spill sink, and releases it when the turn ends. The registry also counts runs per
execution for the per-turn cap. A tool call whose execution id is unknown refuses
`workspace_unavailable`.

**Image.** `docker/agent-sandbox/Dockerfile` on `python:3.12-slim`, adding `tesseract-ocr`,
`pymupdf`, `pypdf`, `pdfplumber`, `python-docx`, `python-pptx`, `openpyxl`, `pandas`,
`matplotlib`, `pillow`, `pytesseract`. Built locally as `clue-agent-sandbox:<tag>` and named by
`CLUE_SANDBOX_IMAGE`; a `make sandbox-image` target builds it; the tool checks the image exists
at first use and refuses `sandbox_unavailable` with a one-line fix when it does not. OCR of a
scanned page is the agent's decision inside a run (Tesseract is in the image); there is no
platform OCR switch.

**Settings** (every one in `.env.example` with its default):

```
CLUE_SANDBOX_ENABLED=true
CLUE_SANDBOX_IMAGE=clue-agent-sandbox:latest
CLUE_SANDBOX_TIMEOUT_S=60
CLUE_SANDBOX_CPUS=1
CLUE_SANDBOX_MEMORY_MB=1024
CLUE_SANDBOX_MAX_RUNS_PER_TURN=10
CLUE_SANDBOX_MAX_OUTPUT_BYTES=1048576
CLUE_CHAT_ATTACHMENT_DOCUMENT_MAX_BYTES=26214400
```

`CLUE_SANDBOX_ENABLED` ships on (founder ruling 2026-09-20; the draft said off). The tool is
granted regardless; with the flag off, or with no image on the host, every call
refuses `sandbox_unavailable`, and the skill tells the agent to say so to the human rather than
guess at the file's contents.

### 3.5 What the agent is taught

- **New skill `code-execution` v1** (hand-written, adapted from the reference material): when
  to run code (any binary attachment; a text file too big for `read_file`; a number to compute
  rather than read; a table to join or filter; a derived file to produce) and when not to (a
  text file `read_file` opens; a question the transcript already answers); the workspace paths
  inside the container; the run budget; reading recipes: XLSX two-pass load (formulas via
  `data_only=False`, values via `data_only=True`), `pandas.read_excel(sheet_name=None)` for
  bulk, PDF page text and `pdfplumber` tables, OCR of a scanned page with PyMuPDF rendering plus
  Tesseract, DOCX paragraphs with style names and tables, PPTX slide text and notes, CSV/JSON
  with pandas; the rule that every number the agent states comes from output it saw, with the
  page, sheet or row it came from; and how to read a spilled stdout.
- **Manual chapter `manual-workspace` v5**: the `attachments/` mount, which read path each kind
  of file takes, what `run_python` may read and write. **`manual-tools`** is generated: a
  `run_python` entry in `tool_notes.yaml`. **`manual-limits`** is generated from the settings
  (the run budget, timeout, output cap).
- **Stage-0 skill v34**: one paragraph pointing at the code-execution skill when a turn names an
  attachment, and the "read the whole file, in pages, before summarising" rule.
- **Prompt v11**: the sentence in v10 becomes "There is no shell, host filesystem, arbitrary
  network, secret, or provider SDK access. Code runs only through `run_python`, inside the
  sandbox its manual entry describes."
- **Profile v58**, recipe 29, the registry pin, the catalog and toolbelt tests, following the
  v56/v57 mechanics exactly (skill digests are the SKILL.md sha256).

### 3.6 Security posture

- No network, no host environment, no secrets, unprivileged user, read-only root, dropped
  capabilities, CPU / memory / pid / time limits, output caps, per-turn run cap.
- The container sees only the thread's own workspace and the project's read-only mounts; the
  fd-anchored backend is unchanged, and the host paths handed to Docker are derived from the
  lease, never from model input.
- Prompt injection through an attached document can make the model write hostile code; the
  code cannot reach anything but the workspace it already has, and the script is journaled
  verbatim on the receipt, so an incident is auditable.
- Workspace policy is re-applied after every run; the sandbox cannot leave the workspace in a
  state `write_file` could not have produced, except for the extra output extensions above.
- Erasure: a file's bytes live in the artifact store (tombstone path as today) and in the
  project's attachments tree; the tree entry is deleted at the next sync after the upload's
  artifact is erased or purged. Because the sync runs at the start of every turn, no turn ever
  sees an erased file.

### 3.7 Frontend

Accept list and family detection gain the document types; chips show the file glyph and name
(no preview, per the founder). The composer's limit messages name the 25 MB document cap. An
`UPLOAD_NOT_A_DOCUMENT` refusal renders on the chip like every other upload failure. Nothing
renders sandbox outputs to the human in this round.

## 4. Testing

- Upload route: each document type accepted (a generated PDF, DOCX, PPTX, XLSX, CSV, JSON);
  `UPLOAD_NOT_A_DOCUMENT` on wrong magic bytes or invalid JSON; `UPLOAD_TOO_LARGE` at the cap.
- Retirement: the text-materialisation tests are deleted; a submission with a text attachment
  writes no project document and triggers no library refresh.
- Sync: the tree gains every attached file of the project (all three families), is idempotent,
  replaces a re-uploaded name with the newest bytes, removes an erased upload's file.
- Workspace: the `attachments` mount is read-only, not charged, listed by `ls`, refused by
  `write_file`; `read_file` opens a synced `.md` and refuses a synced `.pdf` as non-UTF-8.
- L7: the one-sentence line for each family; the pointer line when no describer is bound.
- `run_python`: unit tests over the command builder (every flag, every mount, no host env),
  output capture and truncation, the post-run policy sweep, the per-turn cap, refusals when
  the feature is off or the execution is unknown; one integration test that runs a real
  container when Docker is present and the image exists (skipped otherwise, and the skip says
  why).
- Catalog: profile v58 digests, tool counts, authority audit, manual drift.
- Live walk (founder-triggered): attach a spreadsheet and ask for a total; attach a PDF and ask
  for the figure on page 3; attach a scanned PDF and ask what it says (the agent OCRs it); attach
  a `.md` and ask about it (`read_file`, no sandbox run); ask the agent to produce a CSV from a
  spreadsheet; a file with the wrong magic bytes refused at upload.

## 5. Out of scope

Rendering sandbox outputs or document previews to the human; package installation or network
inside the sandbox; LibreOffice-dependent formats (`.doc`, `.ppt`, `.xls`, `.xlsm`); the design
agent (its own runtime); GPU; a sandbox for delegated sub-agents (the tool is granted to
Head-of-ABM only); any markdown rendering of an attachment.
