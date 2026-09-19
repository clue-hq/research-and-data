# Agent code execution and document attachments

Status: DRAFT for founder review, 2026-09-19. Branch `rebase-and-expand-attachment-types` (cut
from `origin/research-streaming` after PR #64 merged the chat-attachments feature).

## 1. What we are building

Head-of-ABM gets two new abilities so that a person can attach a PDF, Word file, PowerPoint,
spreadsheet or data file to a chat and the agent can genuinely work with it, not just skim it:

1. **Document attachments reach the agent as files.** The upload path accepts PDF, DOCX, PPTX,
   XLSX, CSV and JSON beside the markdown, text and image types it accepts today. Every attached
   document is installed, byte for byte, in a read-only `attachments/` folder of the agent's
   workspace that every thread of the project shares, and a markdown twin of it is written as a
   project document so the agent (and the Gallery) has an instantly readable copy.
2. **A governed `run_python@1` tool.** The agent can run a short Python script in a sandboxed
   container over its own workspace, with the document libraries preinstalled, no network, no
   secrets, and hard limits on time, CPU, memory, output and the number of runs per turn. The
   script's stdout, stderr, exit code and the files it wrote come back as a governed receipt.

The reading knowledge in the founder's reference material (the XLSX, DOCX and PDF skills under
`attachments/`) is what the new agent skill teaches: two-pass spreadsheet reads (formulas and
cached values), page-wise PDF text with table extraction and OCR for scanned pages, headings and
tables out of Word files, slide text and notes out of decks. That material assumes a Python
sandbox; item 2 is what gives Head-of-ABM one.

### Founder rulings (2026-09-19)

- Option 1 chosen: execution in a container on the worker host, over the thread's own workspace.
  A hosted sandbox (documents leaving the box) was rejected; converters-only was rejected as too
  limiting ("I don't want it restricted to just reading markdown files").
- The markdown converters stay as the fast path beside execution.
- Defaults proposed and accepted by proceeding: Docker, no network, 60 s wall clock, 1 CPU,
  1 GB RAM, 10 runs per turn, 1 MB captured output, PyMuPDF / pypdf / pdfplumber / python-docx /
  python-pptx / openpyxl / pandas / matplotlib / Tesseract in the image. Each is a setting, so
  the founder can amend any of them in `.env` without a code change.

## 2. What exists today (verified 2026-09-19)

- **Attachments (PR #64).** `POST /frontend/v1/uploads` accepts `.md`/`.txt` and PNG/JPEG/WebP/GIF
  (`platform/api/clue_api/chat/uploads.py`, allow-lists at lines 37–48); a submission carries
  `attachment_refs`; text uploads become project documents at `attachments/<name>` at send time
  (`chat/attachments.py::materialize_text_attachments`); images ride the model message as image
  parts; the L7 context line names each attachment and, for text, its workspace path
  (`clue_agents/context.py::TurnLayerSource`, `clue_api/attachment_binding.py`).
- **The agent workspace is a real directory** per thread at
  `<CLUE_AGENT_WORKSPACE_ROOT>/<workspace>/projects/<project>/threads/<thread>/`
  (`clue_agents/workspace.py::AgentWorkspaceFactory`), reached through file-descriptor anchoring
  (`AnchoredAgentWorkspaceBackend`). Mounts are directories the backend opens beside the thread
  root (`MountRequest`: `brand` → `<ws>/library/brand/<brand>/<version>`, `project_library` →
  `<ws>/projects/<project>/library`), read-only, not charged against the workspace quota
  (`_quota_files` skips read-only and versioned mounts). Seeds and library files must be UTF-8
  text (`resources.py::WorkspaceSeedFile`, `library_tree.py::LibraryFile`). The profile's
  workspace policy (head-of-abm v57) is 20 MiB total, 1 MiB per file, 400 files, writable
  prefixes `scratch/ work/ outputs/ project/`, allowed write extensions `.json .md .txt .yaml`,
  readable prefixes `.deepagent inputs context scratch reads work outputs brand project`.
  Extension checks apply to writes only; a read is bounded by the readable prefixes and the
  1 MiB cap.
- **Governed tools** subclass `clue_toolbelt.Tool` (`name`, `version`, `input_model`,
  `output_model`, `effect_class`, `replay`, `parameter_policy`, `pin_requirements`, `invoke`) and
  are registered in `toolbelt_wiring.build_toolbelt`, granted per role in
  `agent_registry_wiring.py` (`"read_artifact": (AgentRole.HEAD_OF_ABM,)`), listed in the
  recipe contract (`recipe_contracts.py` RECIPE_0 addresses, `stage0_recipe.py`), pinned by the
  profile, and described in the generated manual through `catalog/manual/tool_notes.yaml`.
  `ToolContext` carries `workspace_id`, `execution_id`, `operation_id` and worker identity but
  no workspace handle; the oversized-result spill (`reads/<operation_id>.json`) is the one seam
  today where a tool output touches the workspace, bound in `head_of_abm_wiring.py` where the
  lease is in hand (`spill_sink=`). `C5AgentExecutionAdapter` holds the turn's tools and invoker.
- **Subprocess precedent.** The design leg runs `lumen-api-helper` as a blocking subprocess
  inside `asyncio.to_thread` (`design_leg_tools.py:651`). No container or sandbox code exists.
  Docker Desktop is installed on the founder's machine (the only backend host today); macOS
  also ships `sandbox-exec`.
- **Parsers.** The research lane has pypdf, PyMuPDF (`fitz`), Pillow and pytesseract installed
  and zip/XML readers for DOCX and PPTX (`clue_research/adapters/docx.py`, `pptx.py`). Not
  installed: openpyxl, pandas, python-docx, python-pptx, pdfplumber, pypdfium2, pdf2image.
  `pdftotext` and `tesseract` binaries exist on the founder's machine; LibreOffice does not.
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
| document (new) | `application/pdf`; DOCX and PPTX (OOXML types); XLSX; `text/csv`; `application/json` | `CLUE_CHAT_ATTACHMENT_DOCUMENT_MAX_BYTES` (25 MB) |

Legacy `.doc`/`.ppt`/`.xls` and macro workbooks are out of scope (they need LibreOffice).
Validation at upload: extension and declared type resolve as today; magic bytes (`%PDF-`, the
zip signature for OOXML, UTF-8 for CSV/JSON, a JSON parse for JSON). The message-level rules
(10 files, 150 MB) are unchanged.

**Convert at upload.** The route converts a document to markdown immediately (§3.3), stores the
markdown as a second content-addressed artifact, and records both on the upload row. A file
that cannot be opened (corrupt zip, password-protected PDF) is refused at upload with 422
`UPLOAD_UNREADABLE` and the reason, while the chip is still in the composer. Migration: two
nullable columns on `chat_upload`, `text_artifact_key` and `conversion_note`.

### 3.2 Where the bytes go: the `attachments` mount

At send time the submission path records nothing new on disk; the durable facts are the
upload row and the submission's attachment rows. The **fleet worker** installs the tree at the
start of every Head-of-ABM turn, before the workspace is mounted: an idempotent sync of the
project's document and text uploads (every `agent_turn_submission_attachment` row of the
project, joined to `chat_upload`) into `<ws>/projects/<project>/attachments/<filename>` on the
worker host, copying only files whose digest is not already installed, removing files whose
upload has been erased, and rewriting `attachments/index.json` beside them: one entry per file
with its name, media type, byte count, upload time, the message it arrived with, and the path
of its markdown twin under `project/`. The worker owns the workspace root, so this works when
the API and the worker are on different machines (they share one laptop today). A re-upload of
the same filename with different bytes replaces the file (the twin's version chain keeps the
history; the index notes the replacement). Images are not installed (ruling 3 of the
attachments feature keeps them out of the Gallery; they still ride the message as image parts).

Every Head-of-ABM turn mounts that tree read-only as `attachments/` (`MountRequest.attachments`),
the same mechanism as `brand/` and `project/`, so it is not charged against the workspace
quota and every thread of the project sees the same files. The profile's readable prefixes gain
`attachments`. `read_file` on a binary file fails as it does for any non-UTF-8 bytes; the agent
reads binaries through `run_python@1` and everything else through the markdown twin. The L7
attachment line becomes:

```
Attachment "q3-pipeline.xlsx" (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,
412,010 bytes) was attached to this message. The file is at attachments/q3-pipeline.xlsx; a
markdown reading of it is at project/attachments/q3-pipeline.xlsx.md. Use run_python to open
the file itself when the reading is not enough.
```

The earlier idea of a second per-turn copy under `inputs/attachments/` is dropped: one mount,
and the L7 line says which files came with this message.

### 3.3 The markdown twin (fast path)

Written as a project document at `attachments/<original name>.md` (so `report.pdf` reads at
`project/attachments/report.pdf.md`), kind `attachment`, versioned per original file, listed in
the Gallery under Documents. Front matter: `kind`, `title`, `source: user_upload`, `upload_id`,
`original_media_type`, `units` (pages / sheets / slides count) and `conversion_note` (truncation
or unreadable parts). Then a short contents list and one section per unit:

- **PDF** (PyMuPDF): `## Page N` with the page's text in reading order; tables PyMuPDF finds
  are rendered as markdown tables; a page with no extractable text is OCR'd with Tesseract when
  `CLUE_CHAT_ATTACHMENT_OCR_ENABLED` is on (default off), else marked "no extractable text".
- **DOCX** (own zip/XML converter): headings by Word style level, paragraphs, list items,
  tables as markdown tables, headers and footers appended.
- **PPTX** (own zip/XML converter): `## Slide N — <title>` with body text and speaker notes.
- **XLSX** (openpyxl): `## Sheet: <name>` as a markdown table of cached values, formula cells
  whose cached value is missing show the formula text, followed by a formula list for the sheet
  when it has any; row cap per sheet `CLUE_CHAT_ATTACHMENT_SHEET_MAX_ROWS` (2,000).
- **CSV** (stdlib): one markdown table with the same row cap. **JSON**: pretty-printed in a
  fenced block.
- Total cap `CLUE_CHAT_ATTACHMENT_MARKDOWN_MAX_BYTES` (1 MiB, the workspace's per-file read
  bound, which `read_file` refuses to exceed rather than truncate) with an explicit truncation
  note in the front matter; a truncated twin is what tells the agent to open the file itself
  with `run_python`.

The converters live in a new package `platform/api/clue_api/chat/converters/` (one module per
family) with one entry point `convert_document(data, media_type, filename, settings) ->
ConvertedDocument(markdown, units, note)`. They are pure functions over bytes with tests on
generated fixtures. New platform dependencies: `openpyxl`, `pymupdf` (already present via the
design subsystem's environment; declared explicitly).

### 3.4 `run_python@1`

**Contract.**

- Inputs: `code` (str, ≤ 65,536 bytes), `timeout_s` (optional, ≤ the setting), `note`
  (optional one-line purpose, journaled). No file arguments: the script reads and writes the
  workspace by relative path.
- Output references: `exit_code`, `duration_ms`, `stdout` (inline up to 16 KB, else spilled to
  `reads/<operation_id>.stdout.txt` and referenced), `stderr` (same rule), `files_written`
  (paths under the writable prefixes, with sizes), `truncated` flags, `runs_remaining` for the
  turn.
- `effect_class = WRITE` (it changes workspace files); `ReplayPolicy.OPERATION_IDEMPOTENT`
  keyed on the operation id: a replayed turn serves the journaled receipt and never re-runs the
  script. `parameter_policy` journals `code` and `note` verbatim (the script is the audit
  record). `pin_requirements = ("project",)`.
- Refusals (preconditions): `sandbox_unavailable` (feature off, Docker not reachable, image
  missing), `run_budget_exhausted` (per-turn cap), `code_too_large`, `workspace_unavailable`
  (no lease bound for this execution). A non-zero exit or a timeout is a normal result, not a
  refusal, so the model can read stderr and try again.

**Execution.** The tool runs, off the event loop (`asyncio.to_thread`, the design precedent),
one `docker run --rm` of the configured image with:

- `--network none`, `--cpus <CLUE_SANDBOX_CPUS>`, `--memory <CLUE_SANDBOX_MEMORY_MB>m`,
  `--pids-limit 256`, `--read-only` root filesystem, a `tmpfs` at `/tmp`, `--cap-drop ALL`,
  `--security-opt no-new-privileges`, an unprivileged user, no environment variables from the
  host;
- bind mounts: the thread's `scratch/`, `work/`, `outputs/` read-write; its `inputs/`,
  `context/`, `reads/` and the `brand/`, `project/`, `attachments/` mount directories read-only,
  all at `/workspace/<name>` so the paths the agent uses elsewhere hold inside the container
  (working directory `/workspace`);
- the script passed on stdin to `python -I -`; wall-clock enforced by the tool (kill and report
  `timed_out`), stdout and stderr captured up to `CLUE_SANDBOX_MAX_OUTPUT_BYTES` each with a
  truncation marker.

After the run the tool scans the writable prefixes, refuses and deletes files that break the
workspace policy (an extension outside the allow-list, a file over the per-file cap, the total
over quota), and reports what it removed in the receipt. The allow-list for sandbox-written
files is the profile's `allowed_extensions` plus `.csv .xlsx .docx .pptx .pdf .png`, so a
script can leave a derived spreadsheet or a chart under `outputs/` (nothing renders those for
the human yet; they are snapshotted to artifacts at finalize like any output).

**Finding the workspace.** `ToolContext` has no workspace handle, so the tool is given a
`SandboxWorkspaces` registry at composition: `head_of_abm_wiring` registers the turn's
execution id with the host paths derived from the lease (`PreparedWorkspaceRoot.path` plus
the lease's workspace, project and thread segments, and each mount's directory) at the same
point it binds the spill sink, and releases it when the turn ends. The registry also counts
runs per execution for the per-turn cap. A tool call whose execution id is unknown refuses
`workspace_unavailable`.

**Image.** `docker/agent-sandbox/Dockerfile` on `python:3.12-slim`, adding `tesseract-ocr`,
`pymupdf`, `pypdf`, `pdfplumber`, `python-docx`, `python-pptx`, `openpyxl`, `pandas`,
`matplotlib`, `pillow`, `pytesseract`. Built locally as `clue-agent-sandbox:<tag>` and named by
`CLUE_SANDBOX_IMAGE`; a `make sandbox-image` target builds it; the tool checks the image exists
at first use and refuses `sandbox_unavailable` with a one-line fix when it does not.

**Settings** (every one in `.env.example` with its default):

```
CLUE_SANDBOX_ENABLED=false
CLUE_SANDBOX_IMAGE=clue-agent-sandbox:latest
CLUE_SANDBOX_TIMEOUT_S=60
CLUE_SANDBOX_CPUS=1
CLUE_SANDBOX_MEMORY_MB=1024
CLUE_SANDBOX_MAX_RUNS_PER_TURN=10
CLUE_SANDBOX_MAX_OUTPUT_BYTES=1048576
CLUE_CHAT_ATTACHMENT_DOCUMENT_MAX_BYTES=26214400
CLUE_CHAT_ATTACHMENT_SHEET_MAX_ROWS=2000
CLUE_CHAT_ATTACHMENT_MARKDOWN_MAX_BYTES=1048576
CLUE_CHAT_ATTACHMENT_OCR_ENABLED=false
```

`CLUE_SANDBOX_ENABLED` ships off. The tool is granted regardless; with the flag off every call
refuses `sandbox_unavailable`, and the skill tells the agent to fall back to the markdown twin.

### 3.5 What the agent is taught

- **New skill `code-execution` v1** (hand-written): when to run code (compute, cross-tabulate,
  read a binary the twin does not capture, produce a derived file) and when not to (a question
  the twin answers); the workspace paths inside the container; the run budget; reading recipes
  adapted from the founder's reference material: XLSX two-pass load (formulas via
  `data_only=False`, values via `data_only=True`), `pandas.read_excel(sheet_name=None)` for bulk,
  PDF page text and `pdfplumber` tables, OCR of a scanned page with PyMuPDF rendering plus
  Tesseract, DOCX paragraphs with style names and tables, PPTX slide text and notes, CSV/JSON
  with pandas; the rule that every number the agent states comes from output it saw, with the
  page, sheet or row it came from; and how to read a spilled stdout.
- **Manual chapter `manual-workspace` v5**: the `attachments/` mount, the twin path rule, what
  `run_python` may read and write. **`manual-tools`** is generated: a `run_python` entry in
  `tool_notes.yaml`. **`manual-limits`** is generated from the settings (the run budget, timeout,
  output cap).
- **Stage-0 skill v34**: one paragraph pointing at the code-execution skill when a turn names an
  attachment, and the "read the whole twin, in pages, before summarising" rule.
- **Prompt v11**: the sentence in v10 becomes "There is no shell, host filesystem, arbitrary
  network, secret, or provider SDK access. Code runs only through `run_python`, inside the
  sandbox it describes."
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
- Erasure: a document's bytes live in the artifact store (tombstone path as today) and in the
  project's attachments tree; the tree entry is deleted when the upload's artifact is erased,
  and the markdown twin follows the project-document erasure rules.

### 3.7 Frontend

Accept list and family detection gain the document types; chips show the file glyph and name
(no preview, per the founder). The composer's limit messages name the 25 MB document cap. An
`UPLOAD_UNREADABLE` refusal renders on the chip like other upload failures. Nothing renders
sandbox outputs to the human in this round.

## 4. Testing

- Converters: generated fixtures (a two-page PDF via pypdf, a DOCX and PPTX via zipfile, an XLSX
  via openpyxl with a formula and cached value, CSV, JSON), assertions on section structure,
  caps and notes; a password-protected PDF and a corrupt zip refuse.
- Upload route: each document type accepted with a twin artifact recorded; 422 on unreadable.
- Submission: the attachments tree gains the file and the index entry; re-upload replaces;
  the twin versions; the L7 line names both paths.
- Workspace: the `attachments` mount is read-only, not charged, listed by `ls`, refused by
  `write_file`.
- `run_python`: unit tests over the command builder (every flag, every mount, no host env),
  output capture and truncation, the post-run policy sweep, the per-turn cap, refusals when
  the feature is off or the execution is unknown; one integration test that runs a real
  container when Docker is present and the image exists (skipped otherwise, and the skip says
  why).
- Catalog: profile v58 digests, tool counts, authority audit, manual drift.
- Live walk (founder-triggered): attach a spreadsheet and ask for a total; attach a PDF and ask
  for the figure on page 3; attach a scanned PDF with OCR on; ask the agent to produce a CSV
  from a spreadsheet; a corrupt file refused at upload.

## 5. Out of scope

Rendering sandbox outputs or document previews to the human; package installation or network
inside the sandbox; LibreOffice-dependent formats (`.doc`, `.ppt`, `.xls`, `.xlsm`); the design
agent (its own runtime); GPU; a sandbox for delegated sub-agents (the tool is granted to
Head-of-ABM only).
