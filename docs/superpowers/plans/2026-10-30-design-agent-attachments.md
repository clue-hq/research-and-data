# Design Agents Read What Was Attached — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A file attached to a chat message reaches whichever agent handles that message — the Head of ABM or a design agent (ad, site, web) — and stays on the saved message, on every route.

**Architecture:** The attachment rows already stored per message are carried by every route (design-session turns, a session's first turn, the hand-back), written onto the saved message, and listed in the design run's envelope. A new read on the existing platform→design pipe (`DesignPlatformReads`) serves the thread's files; design agents get them as a read-only `attachments/` folder, attached images become library images and references, and design agents get the shared `run_python` sandbox. The exit judgement sees the files and reasons about them.

**Tech Stack:** Python 3.12, SQLAlchemy async + Postgres, LangChain/deepagents, Pillow 11.3 (+ new `pillow-heif`), Docker sandbox, Next.js/TypeScript (frontend).

**Spec:** `docs/superpowers/specs/2026-10-30-design-agent-attachments-design.md`

## Global Constraints

- Branch `fix/leg-turn-attachments` (from `main` at `6a1ff081`); local commits only, never push; no AI attribution in commits.
- Python tests run one file at a time through `.superpowers/review/2026-10-13-wave2/pytest-keyless.sh <repo-relative file>` with `timeout 600`; never `*_live.py`; never the whole `subsystems/clue-design/apps/api/tests` folder.
- Frontend gate: `npm test` in `apps/frontend`, eslint on changed files, `npx tsc --noEmit -p .` (60 errors pre-exist).
- Seam: nothing under `subsystems/clue-design/` imports `clue_api`; design may import `clue_agents`, `clue_core`, `clue_config`.
- AW-8: no state that lives only on a worker's disk; `attachments/` is rebuilt every turn from durable storage.
- A person's attached file is never modified by any agent (spec §3.7).
- Design agents run solo (`LUMEN_AGENT_SCENE_SOLO=1`, `LUMEN_AGENT_WEB_SOLO=1`); all prompt work targets the solo prompts.
- Every new env setting goes into `.env.example` (and the subsystem's `.env.example` when design-owned) with its default, when introduced.
- Agent-facing wording (exit judgement v5, the attachments paragraph, the `run_python` tool description) is shown to the founder and approved **before** it is written into a prompt, skill or tool description.
- Accepted chat attachment image types after this plan: `image/png`, `image/jpeg`, `image/webp`, `image/gif`, `image/svg+xml`, `image/heic`, `image/heif`, `image/avif`, `image/tiff`, `image/bmp`, `image/x-icon` (spec §3.6). Model-native: png, jpeg, webp, gif. SVG is never sent to a model as a picture.
- Scope of a design agent's files: the files attached in **this chat thread**; duplicate filenames → the newest wins.

## Review Focus

1. Two messages in one thread attach different files with the same filename → the folder holds the newest; the turn prompt names the current one.
2. A design turn is retried or taken over → the same attached image maps to the same library asset (no duplicates), keyed by its sha256.
3. An attached file's bytes were erased (DSAR) or are missing → the design turn still runs; the file is left out and the agent is told it is unavailable.
4. A 25 MB PDF and nine other files in one message → the design workspace stays within its quota; nothing is silently dropped without a note.
5. A filename with spaces, unicode or path characters (`../x.png`) → it lands inside `attachments/` under a safe name, never outside it.

---

### Task 1: Thread attachments and derived submissions (platform)

**Files:**
- Modify: `platform/api/clue_api/agent_turn_submission.py`
- Modify: `platform/api/clue_api/design_leg_tools.py:921` (`_queue_first_turn`), `:1677` (out-of-scope redelivery)
- Test: `tests/api/test_design_leg_attachments_db.py` (new)

**Interfaces:**
- Produces:
  - `def as_validated_attachment(row: SubmissionAttachmentRow) -> ValidatedAttachment` (family from `attachment_family(row.ref.media_type)`).
  - `async def thread_attachment_refs(conn, *, workspace_id: str, thread_id: str) -> tuple[SubmissionAttachmentRow, ...]` — every attachment of every submission in the thread, oldest message first, ordinal order within a message; derived submissions excluded (their rows copy their source's).

- [ ] **Step 1: Write the failing tests**
  - `test_a_sessions_first_turn_carries_the_opening_messages_files`: insert a submission with one attachment, open a leg through `OpenDesignLegTool` (as `tests/api/test_design_comment_routing_db.py::_worker_stage` does), assert `submission_attachment_refs(first_turn_id)` has the same upload_id and filename.
  - `test_an_out_of_scope_hand_back_carries_the_messages_files`: close a leg `out_of_scope` on a turn with two attachments; the redelivered submission has both, in order.
  - `test_thread_attachments_list_every_message_in_order_without_derived_copies`.
- [ ] **Step 2: Run** `timeout 600 .superpowers/review/2026-10-13-wave2/pytest-keyless.sh tests/api/test_design_leg_attachments_db.py` — Expected: FAIL (first turn and hand-back carry 0 attachments; `thread_attachment_refs` undefined).
- [ ] **Step 3: Implement** the two functions; pass `attachment_refs=tuple(as_validated_attachment(r) for r in await submission_attachment_refs(...))` at both `insert_submission` call sites in `design_leg_tools.py`.
- [ ] **Step 4: Run** the file — Expected: PASS. Also run `tests/api/test_design_comment_routing_db.py` — Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "Design sessions: a first turn and a hand-back carry the message's attachments"`

### Task 2: Design-session turns carry the files and keep the chips

**Files:**
- Modify: `platform/api/clue_api/agent_turn_fleet_wiring.py:553` (pass `attachments=submission_attachments`)
- Modify: `platform/api/clue_api/design_leg_wiring.py:1224` (`run_leg_turn`), `:1372` (`AgentTurnRequest`), `_envelope` (`:2688`)
- Test: `tests/api/test_design_leg_attachments_db.py`

**Interfaces:**
- Consumes: Task 1 `thread_attachment_refs`.
- Produces:
  - `run_leg_turn(..., attachments: tuple[SubmissionAttachmentRow, ...] = ())`.
  - Envelope `config["attachments"]`: a list of `{"filename": str, "media_type": str, "artifact_key": str, "sha256": str, "byte_count": int, "current": bool}` — the thread's files, newest per filename, `current` true for this message's own files. Absent key when the thread has none (keeps the frozen request bytes of attachment-free turns unchanged).

- [ ] **Step 1: Write the failing tests**
  - `test_a_design_session_turn_keeps_its_attachment_chips`: drive a leg turn with one attachment through the real worker (genweb `_FakeLane`); assert an `agent_artifact_ref` row with `ref_role='attachment'` exists for the turn.
  - `test_the_design_run_envelope_lists_the_threads_files`: two messages, the second re-sends `logo.png` with new bytes plus `brief.md`; the envelope lists `logo.png` once (newest sha) and `brief.md`, both `current: true`, and the first message's other file `current: false`.
  - `test_a_turn_without_files_sends_no_attachments_key`.
- [ ] **Step 2: Run** the file — Expected: FAIL.
- [ ] **Step 3: Implement**: forward `submission_attachments`; set `AgentTurnRequest.attachment_refs=tuple(a.ref for a in attachments)`; build `config["attachments"]` in `_envelope` from `thread_attachment_refs`.
- [ ] **Step 4: Run** the file and `tests/api/test_design_comment_routing_db.py`, `tests/api/test_p37_*` files touching legs — Expected: PASS (pre-existing failures listed in the spec's evidence stay as they were).
- [ ] **Step 5: Commit** `git commit -m "Design sessions: turns carry the message's files and keep their chips"`

### Task 3: The exit judgement sees the files

**Files:**
- Modify: `subsystems/design/clue_design/exit_judgment.py` (`render_exit_judgment_prompt`, `EXIT_JUDGMENT_PROMPT_VERSION = "v5"`)
- Modify: `platform/api/clue_api/design_leg_wiring.py:2002` (`_judge_exit`), `:236` (`DesignLegExitJudge`)
- Modify: `platform/api/clue_api/agent_turn_fleet_wiring.py:1869` (judge closure)
- Modify: `subsystems/design/clue_design/evals/golden.py`
- Test: `tests/design/test_exit_judgment_prompt.py` (new or existing file for this module)

**Interfaces:**
- Produces: `render_exit_judgment_prompt(..., files: Sequence[str] = ())` adding a fenced `<<<FILES` block, one line per file: `"<filename>" (<kind>)`, kind ∈ text, image, SVG image, PDF, Word document, PowerPoint deck, spreadsheet, CSV, JSON.

- [ ] **Step 1: Show the founder** the v5 wording (the FILES block and the one paragraph: files do not decide where a message belongs; what the person asks of them does). Wait for approval.
- [ ] **Step 2: Write the failing tests**: `test_the_prompt_lists_the_messages_files` (block present, kinds right, version `v5`); `test_a_message_without_files_has_no_files_block`; goldens added: Excel + "make an ad from this analysis" → stays; Excel + "calculate the ROI" → `out_of_scope`; PDF only + "here is the brief" → stays.
- [ ] **Step 3: Run** — Expected: FAIL.
- [ ] **Step 4: Implement**; `_judge_exit` passes the current message's files.
- [ ] **Step 5: Run** the test file and the existing exit-judgment tests — Expected: PASS. Commit `git commit -m "Exit judgement v5 reasons over the message's files"`

### Task 4: More image formats, one viewable-image rule

**Files:**
- Create: `platform/agents/clue_agents/attachment_images.py`
- Modify: `platform/api/clue_api/chat/uploads.py` (types, extensions, magic checks)
- Modify: `platform/agents/clue_agents/context.py:541,771,795` (image parts), `:684` (L7 opener for SVG)
- Modify: root `pyproject.toml` (add `pillow-heif`), `uv.lock`
- Modify: `apps/frontend/src/features/projects/model/chat-attachments.ts` (accepted types/extensions)
- Test: `tests/agents/test_attachment_images.py` (new), `tests/api/test_chat_uploads*.py` (existing), frontend `chat-attachments.test.ts`

**Interfaces:**
- Produces:
  - `MODEL_NATIVE_IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})`
  - `CONVERTIBLE_IMAGE_TYPES = frozenset({"image/heic", "image/heif", "image/avif", "image/tiff", "image/bmp", "image/x-icon"})`
  - `def viewable_image(data: bytes, media_type: str) -> tuple[bytes, str] | None` — native: unchanged; convertible: a PNG (first frame, RGBA kept); `image/svg+xml` and anything else: `None`.
  - `def is_shown_as_picture(media_type: str) -> bool`

- [ ] **Step 1: Write the failing tests**: each convertible type (fixtures made with Pillow in the test; HEIC from a tiny committed fixture `tests/agents/fixtures/one-pixel.heic`) → PNG bytes that `Image.open` reads at the original size; SVG → `None`; an upload of each new type passes `validate_upload_bytes`, and a PNG renamed `.heic` is refused `UPLOAD_NOT_AN_IMAGE`; L6/L7 build an `image/png` data URL for a TIFF attachment and no image part for an SVG, whose L7 line says "open it with read_file".
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement**; magic checks: HEIC/HEIF/AVIF by the `ftyp` brand at bytes 4–12, TIFF `II*\0`/`MM\0*`, BMP `BM`, ICO `\0\0\1\0`, SVG a UTF-8 document containing `<svg`; SVG family "image" but `is_shown_as_picture` false.
- [ ] **Step 4: Run** the three test files and the frontend gate — Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "Chat attachments: SVG, HEIC, AVIF, TIFF, BMP and ICO, with a PNG copy for what a model sees"`

### Task 5: Design runs read the thread's files

**Files:**
- Modify: `platform/api/clue_api/design_platform_reads.py` (new method)
- Test: `tests/api/test_design_platform_reads_attachments_db.py` (new)

**Interfaces:**
- Consumes: Task 2 envelope `config["attachments"]`; Task 4 `viewable_image`.
- Produces: `DesignPlatformReads.thread_attachments() -> tuple[AttachedFile, ...]` (sync, `_guarded`, cached for the run), where
  `@dataclass(frozen=True) class AttachedFile: filename: str; media_type: str; sha256: str; data: bytes; current: bool; viewable: tuple[bytes, str] | None; unavailable: str | None` — `unavailable` names why bytes could not be read (erased, missing), with `data=b""`.

- [ ] **Step 1: Write the failing tests**: reads every listed file from platform storage; a TIFF gets a PNG `viewable`, an SVG keeps its own bytes as `viewable` with `image/svg+xml` (the design library takes SVG); an erased artifact (`erased_at` set) → `unavailable="erased"`; a filename `../x.png` comes back as `x.png`.
- [ ] **Step 2: Run** — Expected: FAIL. **Step 3: Implement** (reads via `self._storage.get`, checks the `artifact` row like `design_leg_wiring._bundle_ref`). **Step 4: Run** — Expected: PASS. **Step 5: Commit** `git commit -m "Design platform reads serve the thread's attached files"`

### Task 6: `attachments/` in every design agent's workspace

**Files:**
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/platform_reads.py` (new writer)
- Modify: `lumen_agent/workspace.py:279` (`scaffold_workspace`), `lumen_agent/fs_backend.py:100` (`readonly_subdirs`), `lumen_agent/harness_web.py:215`, `lumen_agent/site/workspace.py:37,903` (`REGENERATED`, `materialize_workspace`), `lumen_agent/site/harness.py:51` (`READ_ONLY`), `lumen_agent/site/inputs.py` (field)
- Test: `subsystems/clue-design/apps/agent_runtime/tests/test_attachments_folder.py` (new)

**Interfaces:**
- Consumes: Task 5 `AttachedFile`.
- Produces: `def write_thread_attachments(workspace: Path, files: Sequence[AttachedFile]) -> str` — empties and rewrites `<workspace>/attachments/`, returns the turn-prompt block ("Attached with this message: …", plus "also in this chat: …" and "not available: … (why)"), `""` when there are none. `SiteTurnInputs.attachments: tuple[AttachedFile, ...] = ()`.

- [ ] **Step 1: Write the failing tests**: the folder holds exactly the files given (stale files from the last turn removed); the block names current files first; write/edit tools refuse `attachments/` for the scene agent (`AgentWorkspaceBackend`) and the site agent (`READ_ONLY`); an unavailable file is named with its reason and not written; a scene session folder kept from the previous turn gets the new set; with `DESIGN_ATTACHMENTS_MAX_BYTES = 157_286_400` (the per-message total, a module constant), the current message's files are written first and older files past the budget are named "not included: this chat's files pass 150 MB", never dropped silently.
- [ ] **Step 2: Run** `timeout 600 .superpowers/review/2026-10-13-wave2/pytest-keyless.sh subsystems/clue-design/apps/agent_runtime/tests/test_attachments_folder.py` — Expected: FAIL.
- [ ] **Step 3: Implement**; call the writer from the scene scaffold, site `materialize_workspace` and the web scaffold, and add the returned block to each turn's user prompt (the wording of that block is part of the Task 10 approval; until then use the plain listing).
- [ ] **Step 4: Run** the new file plus `test_site_workspace.py`, `test_site_harness.py`, `test_site_working_copy.py` — Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "Design agents get the chat thread's files in a read-only attachments folder"`

### Task 7: Attached images become library images and references

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_api/main.py` (`execute_agent_turn_job` ~10882/10996, `execute_site_turn_job` ~12401, `execute_web_turn_job` ~11616)
- Create: `subsystems/clue-design/apps/api/lumen_api/attached_images.py`
- Modify: `lumen_agent/site/inputs.py`, `lumen_agent/site/tools.py:610` (`view_asset` accepts them)
- Test: `subsystems/clue-design/apps/api/tests/test_attached_images.py` (new)

**Interfaces:**
- Consumes: Task 5 `thread_attachments()`; existing `core.ingest_asset` → `register_engine_write` → `design_register_asset_record` (as `site_turn_ports.register_generated`).
- Produces: `def register_attached_images(*, core, blobs, cache_dir, invocations, run_id: str, files: Sequence[AttachedFile]) -> dict[str, str]` — sha256 of the original → library `asset_id`; an image already in the library with the same digest is reused; label = filename; tags include `"attached-in-chat"`; provenance source `{"kind": "chat_attachment"}`.

- [ ] **Step 1: Write the failing tests**: a PNG and an SVG register once each (a second call returns the same ids, no new rows); the scene request's references become `tagged design_asset refs + this message's attached images`, capped at `REFERENCE_ASSETS_MAX`; an older-message image is registered but not a reference; the site turn's `view_asset` accepts an attached image's file and the site agent can place it.
- [ ] **Step 2: Run** the file — Expected: FAIL. **Step 3: Implement.** **Step 4: Run** the file plus `test_site_tools.py`, `test_site_render_tool.py` (agent runtime) — Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "Attached images become library images and design references"`

### Task 8: Move the sandbox to a shared package

**Files:**
- Move: `platform/api/clue_api/sandbox/{docker_runner,workspaces,policy_sweep}.py` → `platform/agents/clue_agents/sandbox/`
- Modify: `platform/api/clue_api/run_python_tool.py` and every importer (`git grep "clue_api.sandbox"`)
- Test: the existing sandbox and `run_python` test files (`git grep -l "clue_api.sandbox" tests`)

**Interfaces:** Produces `clue_agents.sandbox.{run_script, SandboxLimits, SandboxRun, SandboxMounts, snapshot, sweep, SweepResult, docker_available}` — unchanged signatures.

- [ ] **Step 1: Move** with `git mv`; update imports; no behaviour change.
- [ ] **Step 2: Run** each existing sandbox/run_python test file — Expected: PASS, same counts as before the move.
- [ ] **Step 3: Commit** `git commit -m "Move the code sandbox into clue_agents so design agents can share it"`

### Task 9: `run_python` for the design agents

**Files:**
- Create: `subsystems/clue-design/apps/agent_runtime/lumen_agent/sandbox_tool.py`
- Modify: `lumen_agent/harness.py:~841` (scene tools), `lumen_agent/site/harness.py` + `site/tools.py` (`TOOL_DESCRIPTIONS`), `lumen_agent/harness_web.py`
- Test: `subsystems/clue-design/apps/agent_runtime/tests/test_design_run_python.py` (new)

**Interfaces:**
- Consumes: Task 8 `clue_agents.sandbox`; `clue_config` settings `sandbox_enabled`, `sandbox_image`, `sandbox_timeout_s`, `sandbox_cpus`, `sandbox_memory_mb`, `sandbox_max_runs_per_turn`, `sandbox_max_output_bytes`.
- Produces: `def build_design_run_python_tool(*, workspace: Path, run_id: str) -> BaseTool | None` — `None` when the sandbox is off or Docker/image unavailable (the agent then gets no tool, and the prompt's file listing says documents cannot be opened). Mounts: `attachments/` read-only, `outputs/` read-write (created), the rest of the workspace not mounted. Policy: the Head of ABM's output extensions and a 50 MB quota on `outputs/`.

- [ ] **Step 1: Show the founder** the tool description wording (with Task 10). Wait for approval.
- [ ] **Step 2: Write the failing tests**: unit — mounts are exactly `attachments` (ro) and `outputs` (rw); `None` when `sandbox_enabled=False`. Docker-gated (`skipif` no image) — a script reads `attachments/report.xlsx` with openpyxl and writes `outputs/chart.png`; a write into `attachments/` fails; the per-turn run budget is enforced.
- [ ] **Step 3: Run** with `timeout 600` — Expected: FAIL. **Step 4: Implement** and register for scene, site and web when not `None`. **Step 5: Run** — Expected: PASS. **Step 6: Commit** `git commit -m "Design agents get run_python over their attachments and outputs"`

### Task 10: The agents are told, and stay honest

**Files:**
- Modify: the scene solo prompt (`build_scene_solo_prompt`), the site system prompt (`site/harness.py::site_system_prompt`), the web solo prompt
- Test: prompt snapshot tests for each (existing files that assert prompt content)

- [ ] **Step 1: Show the founder** one attachments paragraph (what is in `attachments/`, how each kind is read, use the exact file a message names, say so when a file cannot be opened, never use a similar library image instead) and the turn-prompt block from Task 6. Wait for approval.
- [ ] **Step 2: Write the failing tests** asserting the approved paragraph is present in each of the three prompts.
- [ ] **Step 3: Run** — FAIL. **Step 4: Implement.** **Step 5: Run** — PASS. **Step 6: Commit** `git commit -m "Design prompts: attachments, and never a lookalike for an attached file"`

### Task 11: The composer sends every file as an attachment

**Files:**
- Modify: `apps/frontend/src/features/chat-shell/components/chat-surface.tsx` (~459–496, 809–887, 1159–1214)
- Delete: `apps/frontend/src/features/chat-shell/model/attachment-routing.ts` (+ test), `apps/frontend/src/features/projects/hooks/use-design-reference-attachments.ts`; keep `model/design-reference-attachments.ts` only for what past-message chips still use
- Test: a `chat-surface` composer test (new or existing) proving an image dropped while an ad session is open is uploaded through `uploadChatFile` and sent as an attachment ref

- [ ] **Step 1: Write the failing test.** **Step 2: Run `npm test`** — FAIL. **Step 3: Implement**: one intake (`useChatAttachments`), the design-reference hook and routing removed; `design_asset` chips on past messages still render. **Step 4: Run the frontend gate** — PASS. **Step 5: Commit** `git commit -m "Composer: every file is a chat attachment, whatever the panel shows"`

### Task 12: Prove it live, record it

**Files:**
- Modify: `CLAUDE.md` (`[chat×attachments]` bullet: the design-leg residual is closed; new types; design sandbox)
- Create: `_memory/2026-10-30-design-agent-attachments.md`

- [ ] **Step 1:** Restart the trenton lane (`dev_stack_trenton.sh`, detached); `make sandbox-image` present.
- [ ] **Step 2:** In the in-app browser, the cofounder's flow: an ad session open, a different item in the panel, attach two PNGs and ask to use them → the ad run's references include both; the chips stay after the turn.
- [ ] **Step 3:** A site session: attach `brief.md` and a one-page PDF with "build the hero from this brief" → the site agent reads both (the PDF via `run_python`) and the hero reflects them.
- [ ] **Step 4:** A HEIC photo into an ad session → shown and placeable.
- [ ] **Step 5:** "Calculate the ROI from this Excel" in an open session → handed back to the Head of ABM with the Excel attached.
- [ ] **Step 6:** Record runs, costs and results in the memory note; update `CLAUDE.md`; commit `git commit -m "Record the design-agent attachments work and its live proof"`
