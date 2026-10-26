# Agent workspace footprint — findings (2026-10-21)

What every kind of agent job leaves behind — in Postgres, in object storage, and on the machine
that ran it — and how much of the agent's working state depends on that one machine. Written as
the input to the F3 spec (making the agent workspace machine-independent; rulings in
[`rulings.md`](rulings.md)).

**How this was gathered.** CRM trial 1 surfaced finding F3 (`outputs/` emptied every turn;
`docs/superpowers/specs/crm-integration/2026-10-21-trial-1-findings.md`). Four read-only
investigations then mapped the platform agent workspace, the chat and turn records, ARV2 research
jobs, and design jobs, and a web review compared how other agent products handle the same problem.
Every claim below names its source in code. **Verified** marks a claim checked first-hand against
the code or the lane's database; everything else is from the investigations and is to be confirmed
by the spec author before it is relied on.

---

## 1. The platform agent workspace (Head of ABM chats, research runs)

One directory per chat thread on a local disk, under `CLUE_AGENT_WORKSPACE_ROOT`:
`<root>/<workspace>/projects/<project>/threads/<thread>/`. Production: one VM,
`/srv/clue/workspaces`, bind-mounted at the same path into the chat, design, batch and ingestion
containers (`deploy/vm/compose.yaml`, `deploy/vm/deploy.sh`). Dev: `/private/tmp/clue-agent-workspaces*`
(macOS clears `/private/tmp` periodically).

| Folder | Each turn | Survives a move to another machine? |
|---|---|---|
| `.deepagent/`, `inputs/`, `context/` | emptied and rebuilt from database pins (`workspace.py` `reset_materialized_trees`; `resources.py`) | yes |
| `brand/` (`<ws>/library/brand/<brand>/<ver>/`), `project/` (`<ws>/projects/<p>/library/`), `attachments/` (`<ws>/projects/<p>/attachments/`) | rebuilt from DB/R2 pins; shared per brand / project, not per thread | yes |
| `outputs/` | saved as artifacts at finalize. Until 2026-10-21 it was then emptied (F3); since `f799a9830` the files are kept and the folder reopened (interim) | the saved copy yes; nobody reads it (no UI, no agent tool) |
| `scratch/` (agent's notebook), `reads/` (CRM reads, spilled large results), `work/` (compaction offloads `work/conversation_history/`, `work/large_tool_results/`, sandbox writes) | left as they are on local disk | **no** |

**Verified:** the trial chat's folder held 11 CRM read files in `reads/` (~390 KB, largest 208 KB);
`scratch/`, `work/` and `outputs/` were empty.

**How "persistence" works today:** nothing is copied anywhere. The thread directory simply stays on
the VM's disk and the next turn reopens it. The conversation itself is durable (LangGraph
checkpoints in Postgres), but a compaction summary in the checkpoint points at
`work/conversation_history/` files that exist only on the original machine, and earlier turns'
history names `reads/<op>.json` paths that would not exist elsewhere.

**Cleanup** (`platform/api/clue_api/agent_cleanup.py`): deletes a thread directory 24 h
(`CLUE_AGENT_WORKSPACE_RETENTION_S=86400`) after the thread's newest turn is terminal, or when the
thread is archived. Gaps:
- **Threads whose newest turn is `awaiting_input` are never purged**, archived or not (the status is
  excluded on purpose as "live resumable state"). **Verified:** 15 of 81 chat threads in this lane's
  DB. Design leg turns also end `awaiting_input` (reported).
- **A thread purged, resumed and aged out again crashes the job.** The receipt id is
  `uuid5(workspace:thread:thread_purge)`, the same for every purge of a thread, but the insert's
  `ON CONFLICT (turn_id, action)` does not cover the primary key, so the second purge raises and —
  rows being ordered oldest first — blocks every later row on every cycle. **Verified by reading**
  (`agent_cleanup.py` ~43–47, ~97–100); no test yet.
- **Library swap leftovers are never removed.** `LibraryTree` renames the old copy to
  `.old-<pid>` / `.next-<pid>`. **Verified:** three such folders on this lane's disk. Containerised
  workers can share PIDs.
- **Old brand-knowledge versions are never pruned**; project `library/` and `attachments/` outlive
  their threads (`_delete_thread` removes only empty parents).
- **Research thread folders are purged** (they create `agent_thread` rows via
  `ensure_platform_thread`). **Verified** in the lane DB. Delegated sub-agent (`delegation-<id>`) and
  Stage-0 trial (`stage0-trial-*`, `/tmp/clue-stage0-agent-<uid>`) workspaces are reported as never
  purged — not yet checked.
- A crash before `finally` can leave `pinned-<turn>` replay trees; attachment writes truncate in
  place (no rename), so a crash leaves a truncated file until the next sync (reported).

**Single-machine assumptions** (reported, with code references):
1. `flock` on the root and thread directories (`workspace.py`) — only meaningful on one kernel.
2. "One live lease per thread" is an in-memory map (`_active`); cross-process exclusion relies on
   the DB one-turn-per-thread queue.
3. The brand library is written under a thread lock only (the project library also takes a DB lock).
4. `run_python` runs a sibling container through the host Docker socket with bind mounts the host
   daemon resolves, so the worker's path must equal the host's (`sandbox/docker_runner.py`); it runs
   as the worker's UID/GID. No startup sweep of orphaned containers; only the timeout path kills by
   label.
5. Per-execution registries hold host paths in memory: `SandboxWorkspaces`, `CrmReadSinks`
   (registered in `conversation_turns.py`).
6. A research run's reconciliation step copies `work/`, `scratch/` and `reads/` from the source
   run's thread folder on local disk (`quality_research_wiring.py` ~1084–1111); on another machine,
   or after the 24 h purge, it silently gets nothing.
7. Every fleet process runs the cleanup loop; the first host to purge writes the global DB receipt,
   so other hosts' copies are orphaned.

## 2. Chat and turn records (Postgres, object storage, traces)

**Postgres** — almost everything is kept forever; many tables are append-only by trigger:
`agent_thread`, `agent_turn_submission` (+ refs, attachments), `onboarding_input` (per user
message), `fleet_task`, `execution*` (node, attempt, event, artifact refs), `agent_turn`,
`agent_turn_event`, scope / knowledge / project-file pins, `agent_context_bundle*`,
`agent_model_call` (one row per LLM call; the per-turn cost ledger), `agent_tool_result`,
`agent_plan*`, `agent_delegation*`, `agent_finalization*`, `agent_thread_message` (the canonical
transcript), artifact bindings and privacy events, `agent_workspace_usage`, `agent_runtime_route`,
`agent_workspace_cleanup_event`, turn controls, `tool_invocation` (idempotency; no sweep),
`chat_upload`.
- Retention exists only for: `agent_turn_event_stream` (live-stream outbox; terminal turns pruned
  after 24 h, `chat_turn_event_retention_s`), `stream_token` (hourly sweep), `work_lease` (30 days).
- `agent_turn.retention_class` exists but no job reads it.

**LangGraph checkpoints** (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`): one thread id
per turn (the execution id). **Verified:** each new turn starts by copying every message of the
previous turn's checkpoint into its own (`platform/agents/clue_agents/runtime.py` ~787), so a chat's
stored history grows roughly with the square of its turn count. Only privacy erasure deletes
checkpoints. Continuation raises if the previous turn's saved state is missing, so they are
load-bearing.

**Object storage** (`CLUE_STORAGE_BACKEND`; prod R2 bucket, dev may be local `.artifacts`):
content-addressed keys `workspace/sha256`. Per turn: the user message, cards and manifests, every
distinct LangChain message plus a model-input manifest **per LLM call**, model outputs, the
finalization envelope, final message / assumptions / next actions, the `outputs/` snapshot, plan /
parameter / tool-result artifacts. Agent artifacts have no expiry; the 48 h sweep deletes only
erased, expired or orphan (row-less) blobs; purged `artifact` rows are kept.

**Observability:** Langfuse traces per turn (prompts and outputs truncated to 8,000 chars, secrets
masked); the privacy-erasure path does not delete from Langfuse.

**Duplication:** one user message lives in the message artifact (twice, as text and as a
serialized LangChain message), `onboarding_input`, the submission, `agent_thread_message`,
checkpoints, stream deltas, Langfuse and the finalization envelope.

## 3. ARV2 research jobs

- Results reach the Head of ABM chat **by database reference only** (`list_project_accounts`,
  `read_account_research`, `read_claims`, `read_discovery_run`); no chat tool reads research files.
- Job, run, discovery, quality, evidence, media and pin rows: no deletes found — grow forever.
  `display_block` keeps superseded rows. `provider_call_ledger` rows kept forever.
- Step-audit artifacts expire after 90 days (`CLUE_ARV2_RESEARCH_STEP_RETENTION_DAYS`); personal raw
  pages after 30 days; evidence, dossiers, claims and pages never. LangGraph checkpoints (full
  conversation) outlive the 90-day step-audit expiry.
- Uses the **same thread workspace mechanism** as chats (`research-quality-<execution>` threads),
  with the same machine-bound `scratch/`, `work/`, `reads/`. A crashed job resumed elsewhere gets its
  conversation and outcomes back from Postgres/R2 but not its notes or spill files (see §1 item 6).
- No browser scraping in ARV2 (provider APIs). Media downloads use a `/tmp/arv2-media-*` temp folder,
  leaked if the worker is killed; transcription needs `ffmpeg`/`ffprobe` on the worker.
- Fleet leases are Postgres-fenced (30 s TTL, 10 s heartbeat) — machine-independent.

## 4. Design jobs (ad / scene, web, site) — for the follow-up spec

- Postgres: legs, documents, edit envelopes, operation logs, snapshots, design runs (full
  `result_json`), brand kits and publish revisions grow forever; `run_event` has a pruner that is
  **off by default** (`design_run_event_prune_interval_s=0`). Site-turn checkpoints are reaped after
  96 h; scene and web checkpoints (`dsess_*`) never.
- Host: `LUMEN_AGENT_WORKSPACE_ROOT` (VM `/srv/clue/lumen-agent`; dev default
  `<repo>/.deepagent-workspace`) — a separate workspace the 24 h thread cleanup never touches.
  `sessions/dsess_<id>/workspace/` (brand card, state, rounds — "never deleted"), per-turn
  `turns/<run>/` logs and iterations, `conversation_history/` and its shared `media/`, and
  document-less `run_<id>/` folders: never cleaned except by privacy erasure. Engine asset cache
  `/srv/clue/engine-cache` ("wipeable mirror") has no eviction. The only guard is the VM's 80 % disk
  alert. **Verified:** on this machine `subsystems/clue-design/.deepagent-workspace` is 42 MB and
  `.engine-cache` 75 MB, mostly old dev runs.
- Machine independence: **site turns are fully versioned** (CAS pointer plus a stale-copy check) and
  move between machines cleanly — the model to copy. **Scene/web session folders are uploaded to R2
  every turn but restored only when missing**, so a machine holding an older copy reuses stale memory;
  session snapshots carry the history `.md` but not `conversation_history/media/`.
- Reported risks: privacy erasure of design files refuses when the container hostname differs from
  the recorded one (compose sets no `hostname:`); session-turn run dirs may fail erasure's path check;
  a long-lived web-substrate Chromium can leave Playwright profiles in `/tmp` on a crash; the
  `lumen-api-helper` subprocess has no timeout.
- A design leg turn uses no platform workspace lease (`workspace_root_id="design-leg:<leg>"` is a
  label only).

## 5. How other agent products handle it (checked against vendor docs, 2026-10-21)

No production agent keeps a chat's working state on a particular machine. Three patterns:

1. **Rebuild the machine from a recipe; durable work lives outside it.**
   - Claude Code cloud sessions start from a fresh clone and a saved environment (setup script,
     variables, network rules); the VM pauses when idle and is "restored or rebuilt"; the record is
     the git branch and the transcript ([docs](https://code.claude.com/docs/en/cloud-environments)).
   - Codex cloud builds containers from a setup script and caches them up to 12 h, only for speed
     ([docs](https://learn.chatgpt.com/docs/environments/cloud-environment)).
   - Cursor cloud agents use a saved snapshot or Dockerfile (`.cursor/environment.json`); work lands
     on a branch ([docs](https://cursor.com/docs/cloud-agent)).
   - Devin: every session boots a fresh copy of a golden snapshot; session changes do not persist
     back ([docs](https://docs.devin.ai/onboard-devin/environment)).
2. **Freeze the whole machine and resume it anywhere.** E2B pause/resume keeps filesystem (and
   optionally memory) indefinitely and resumes from an id stored in your DB
   ([docs](https://docs.e2b.dev/sandbox/persistence)); Modal, Daytona and Fly are similar. Worth it
   for long-running processes, not for a few megabytes of files.
3. **Disposable sandbox, durable files elsewhere.** OpenAI code-interpreter containers expire after
   ~20 min idle and lose their files — the well-known "session expired, re-upload" complaint
   ([forum](https://community.openai.com/t/code-interpreter-session-expires-after-an-hour-what-next/711186)).
   Anthropic's code-execution containers are reusable up to 30 days, with lasting files in the Files
   API ([docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool)).

Practices that bear on the design:
- **Results and progress are written somewhere durable**, never left only in the conversation
  (Anthropic's long-running harness: commit to git and keep a progress file; each session re-orients
  and verifies before new work —
  [post](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)).
- **Raw inputs may be dropped if the way to re-fetch them is kept** — Manus: compression is always
  "restorable" (drop a page, keep its URL —
  [post](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus));
  Anthropic: keep "lightweight identifiers" and load just in time
  ([post](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)).
- **Files are referenced by content hash**, so a different file under the same name is never
  mistaken for the original (general practice: Bazel, DVC).
- **deepagents itself** (our agent framework) advises against its local-disk `FilesystemBackend` in
  web servers and recommends its state, store or sandbox backends
  ([docs](https://docs.langchain.com/oss/python/deepagents/backends)).

## 6. Open points for the spec

- Which folder belongs to which retention tier (e.g. `work/conversation_history/` offloads,
  sandbox scratch in `work/`).
- What the turn-start summary shows the agent: files, their ages, what expired and how to re-read.
- The lease (DB lease replacing `flock` and `_active`), the local cache's idle eviction and boot
  wipe, and the restore check (version comparison, not "folder exists").
- Whether `run_python` stays on each VM's own Docker after a restore or moves to a hosted sandbox
  later.
- Retention policy for chats themselves (none exists; work products will follow it).
- Checkpoint growth (each turn copies the whole history) — in or out of scope.
- The cleanup-job crash and the `awaiting_input` gap — replaced by the cache model rather than
  patched, unless the spec lands late.
