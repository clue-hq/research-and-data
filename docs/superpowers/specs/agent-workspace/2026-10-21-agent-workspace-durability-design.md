# Machine-independent agent workspace — design (F3)

**Status:** draft for founder review, 2026-10-21. Branch `feat/agent-workspace-durability`
(dushanbe), stacked on `feat/crm-integration`.
**Authority:** rulings AW-1–AW-8 in [`rulings.md`](rulings.md). Evidence:
[`2026-10-21-workspace-footprint-findings.md`](2026-10-21-workspace-footprint-findings.md).
**Scope:** every agent that runs in a platform thread workspace — Head of ABM chats, ARV2 research
runs (and their reconciliation step), delegated specialists, account-research turns and onboarding
synthesis. Design ad/web sessions get a separate, shorter follow-up spec (AW-5).

Requirement ids (`WS-n`) are stable so plans, tests and reviews can cite them. Where this document
says *builder's call*, any sensible choice that meets the stated requirement is fine. Decisions
made by Claude rather than the founder are marked **(Claude's call)** so they can be checked.

---

## 1. Why

Every chat thread's agent has a folder on one machine's disk. Four of its subfolders hold what the
agent made or read for itself — `scratch/` (its notebook), `outputs/` (deliverables), `reads/` (CRM
reads and large tool results), `work/` (compaction history and in-turn files). Nothing copies them
anywhere: the next turn simply reopens the folder on the same disk. So:

- A turn that runs on another machine (a second worker, autoscaling, a VM replacement) loses the
  agent's notes, drafts and reads, while its conversation — durable in Postgres — still refers to
  them (CRM trial 1, F3; findings §1).
- The folders are deleted 24 hours after a chat goes quiet, so a chat resumed the next day has
  lost them too; and the cleanup has gaps and a crash bug, leaving residue on disk (findings §1).
- Locks and registries assume one machine (`flock`, in-memory maps).

The founder wants (2026-10-21): any chat — new or a year old — to find the same workspace when it
is continued, on whichever machine picks it up; the copy on the machine to stay only while it is
useful and then disappear without residue; and none of this to make the product feel slower.

## 2. Goals, non-goals, anti-goals

**Goals**
1. **Any machine can continue any chat** with the same files the agent left (within the retention
   tiers), with no dependency on which machine ran the previous turn.
2. **A worker's disk holds only a cache**: deleting it at any time loses nothing; idle copies are
   removed automatically; a fresh machine starts empty and fills itself on demand.
3. **Honest memory**: the agent always knows what files it has from earlier, how old they are, and
   what has expired and how to read it again (AW-2, AW-4).
4. **No user-visible slowdown**: a turn on the machine that holds the current copy costs one
   database read; a cold restore of a typical chat costs well under a second.
5. **One place to erase**: deleting a chat or a privacy erasure removes its rows and blobs; no
   machine has to be visited.

**Non-goals (this spec)**
- Design ad/web/site sessions (`LUMEN_AGENT_WORKSPACE_ROOT`) — follow-up spec.
- The checkpoint growth (each turn copies the whole conversation into its own checkpoint, findings
  §2) — a separate item; nothing here makes it worse.
- A retention policy for chats themselves (there is none; work products follow whatever is adopted
  later — AW-2).
- Moving `run_python` to a hosted sandbox; routing a chat to the machine that last ran it.
- F11 (`.py` files refused in the sandbox) — owned by the CRM lane.

**Anti-goals** (failure even if it "works")
- A turn silently runs with an empty or stale workspace when its real files exist.
- The agent tells the person something is done, or quotes numbers, from files that are gone, without
  knowing they are gone.
- Two workers' saves interleave and corrupt a chat's files.
- A noticeably slower first reply, or a turn that fails because a cache was cleaned.
- Erased personal data survives in a snapshot, a cache folder or a forgotten blob.

## 3. Current state (what this changes)

Facts below are from the code on this branch; file references are for the builder.

| Piece | Today | Reference |
|---|---|---|
| Thread folder | `<root>/<ws>/projects/<p>/threads/<t>/` with exactly `.deepagent inputs context scratch reads work outputs`; top level audited | `platform/agents/clue_agents/workspace.py:105,1808-1846` |
| Recipe folders | `.deepagent/ inputs/ context/` rebuilt and frozen every turn from pins; brand/project/attachments mounted from shared libraries | `workspace.py:1021-1037`, `resources.py:251-330`, `agent_turn_fleet_wiring.py:657-798` |
| Agent folders | `scratch/ reads/ work/ outputs/` left on disk between turns; `outputs/` snapshotted to artifacts and (since `f799a9830`) kept | `workspace.py:1209-1262` |
| Lease | `AgentWorkspaceFactory.acquire/create/release`; in-memory `_active` per factory; `flock` on root and thread descriptors | `workspace.py:1434-1806,1482-1491,515-524` |
| One turn per thread | enforced in Postgres: advisory lock + one queued/claimed task; fleet `work_lease` per thread with a generation that increases on every takeover | `agent_turn_submission.py:693-794`, `platform/fleet/clue_fleet/lease.py` |
| Cleanup | hourly job purges a thread folder 24 h after its newest turn ended; skips `awaiting_input`; receipt id collides on a second purge | `platform/api/clue_api/agent_cleanup.py` |
| Artifact store | content-addressed `ws/sha256` blobs in R2 with an `artifact` row; `retain_artifact`/`release_artifacts` per owner; 48 h sweep purges expired/erased/orphan blobs | `libs/clue-storage/clue_storage/artifacts.py` |
| Versioned-folder precedent | design site turns: pointer row `(workspace, document) → (version, manifest_sha256)`, compare-and-set update, local marker, restore-if-stale | `clue_design/sessions.py:122-157`, `lumen_api/main.py:12093-12340`, `lumen_agent/session_sync.py` |

What lands in the agent folders today (findings, and the second code survey):
- `reads/<plan-op>.json` — oversized tool-result spills; the full result is also durable as the
  `result_ref` artifact (`agent_execution_wiring.py:1910-1992`), so a spill can be rebuilt.
- `reads/<exec-op>.json` — CRM reads, always written; the raw payload is **not** durable anywhere;
  the action, parameters, time and record count are (parameter snapshot + `agent_tool_result`).
- `reads/<op>.stdout.txt|.stderr.txt` — `run_python` output over 16 KB, written outside the quota.
- `work/conversation_history/<execution>.md` (+ `media/`) — compaction renderings; the history
  itself stays in the checkpoint, so these can be rebuilt. `work/large_tool_results/<id>` — the
  summariser's overflow clips (only the checkpoint holds them otherwise).
- `scratch/`, `outputs/` and other `work/` files — written by the agent and its sandbox runs,
  including binary formats (`.csv .xlsx .docx .pptx .pdf .png`).

## 4. The design in one picture

```
            ┌──────────── Postgres ────────────┐        ┌──────── R2 (artifact store) ────────┐
            │ agent_workspace_snapshot          │        │ manifest  ws/<sha>  (JSON)           │
 turn start │  (workspace, thread) → version,   │──────▶ │ file blobs ws/<sha> (content-addr.)  │
 ──────────▶│   manifest key/sha, activity time │        └──────────────────────────────────────┘
            │ fleet work_lease (generation)     │                     ▲ upload changed files,
            └───────────────────────────────────┘                     │ then manifest, then CAS
                    │ version matches local marker?                    │ the pointer (turn end)
                    ▼ yes: use cache   no: wipe + restore              │
            ┌──────────── worker disk (cache) ───────────────────────────────────────┐
            │ thread folder: recipe folders (rebuilt from pins, as today)             │
            │               agent folders  (= snapshot version N, marker file aside)  │
            │ evicted when idle; wiped when the pointer is gone; never the only copy  │
            └──────────────────────────────────────────────────────────────────────────┘
```

## 5. Requirements

### 5.1 The snapshot (what is durable)

- **WS-1 Pointer row.** A new table (name builder's call; `agent_workspace_snapshot` below) holds one
  row per thread workspace: `workspace_id`, `thread_id`, `project_id`, `version` (int ≥ 1),
  `manifest_artifact_key`, `manifest_sha256`, `last_activity_at`, `updated_at`. Primary key
  `(workspace_id, thread_id)`. Hand-written, reversible Alembic migration with named constraints
  (repo conventions).
- **WS-2 Manifest.** Each version is one JSON manifest stored as an artifact (its own media type,
  e.g. `application/vnd.clue.agent-workspace-manifest+json`). It lists every snapshotted file:
  logical path, `sha256`, size, media type, **tier** (WS-9), `written_at` (when this content first
  appeared in the workspace), and for raw inputs a **receipt** (WS-11). It also carries the receipts
  of raw inputs that have expired (WS-12), so receipts live as long as the chat. `schema_version` field
  from the start.
- **WS-3 File blobs.** Each file's bytes are stored once as a content-addressed artifact in the
  workspace's namespace, reusing the platform artifact store (`DurableAgentArtifactStore` /
  `clue_storage`). Unchanged files are not uploaded again (their address is already recorded).
  Binary files are supported.
- **WS-4 Retention references.** The snapshot owns its blobs and manifest through the artifact
  store's reference mechanism (`retain_artifact` / `release_artifacts` or an equivalent owner table),
  so a blob is deleted only when no live snapshot version references it. Expiry is a property of a
  **manifest entry**, never of `artifact.expires_at` — that field is per content address (a raw read
  and a draft with identical bytes would share it) and an expired-and-erased row can never be
  recorded again (`record_artifact` refuses it). **Required:** re-reading identical bytes after a raw
  entry expired must work (tested).
- **WS-5 Which folders are snapshotted.**
  - `scratch/` and `outputs/`: everything, tier *work product*.
  - `reads/`: everything, tier *raw input*.
  - `work/conversation_history/` (incl. `media/`) and `work/large_tool_results/`: tier *raw input*.
  - Any other path under `work/`: **not snapshotted** — `work/` is the turn's own scratch space, as
    the agent's manual already says ("Nothing is persisted from it"); it is emptied at turn start.
    **(Claude's call — see open question Q1.)**
  - Recipe folders (`.deepagent inputs context`) and mounts (`brand project attachments`) are never
    snapshotted; they are rebuilt from pins as today.

### 5.2 Turn start: getting the right files onto this machine

- **WS-6 Hydrate.** Before the agent or any tool touches the agent folders (and before
  `run_python` registers its mounts — `conversation_turns.py:464`), the workspace layer:
  1. reads the pointer row (one indexed read);
  2. compares `(version, manifest_sha256)` with the thread's **local marker**;
  3. if equal, uses the local copy as is — no download;
  4. if different or the marker is missing, empties the four agent folders, downloads the
     manifest and every live entry in parallel (bounded concurrency), checks each blob's sha256,
     writes files with the workspace's normal ownership and modes (owner uid, 0600 files / 0700
     dirs, no links), then writes the marker last;
  5. if there is no pointer row: a brand-new thread starts empty; a thread that predates this change
     keeps whatever is on this machine's disk, and its first save becomes version 1 (AW-5, no
     migration). `work/` is emptied in every case except its two raw sub-folders.
- **WS-7 Where the marker lives.** Outside the agent-visible thread folder (the top-level audit
  refuses unknown entries there and the agent must not read or forge it) — e.g. a sibling cache-state
  folder under the root. Builder's call on the exact place.
- **WS-8 One hook for every agent.** Hydrate and save live in the workspace layer (the factory /
  lease), not in each caller, so chats, research runs, delegations, account-research turns and
  onboarding synthesis all get them. A factory built without a snapshot store (unit tests, the dev
  Stage-0 trial CLI) keeps today's local-only behaviour. Production composition roots always inject
  it.

### 5.3 Tiers, receipts and expiry

- **WS-9 Tiers** (AW-2).
  - *Work product* (`scratch/`, `outputs/`): kept for the chat's lifetime.
  - *Raw input* (`reads/`, `work/conversation_history/`, `work/large_tool_results/`): its bytes are
    removed **48 hours after the thread's last activity** (`CLUE_AGENT_WORKSPACE_RAW_RETENTION_S`,
    default 172800). Its receipt stays for the chat's lifetime.
  - Outcomes (published documents, designs, research claims) are untouched — already durable.
- **WS-10 Last activity** = the newest of: a turn submission, a turn reaching a terminal or
  awaiting-input state, a save. Kept in `last_activity_at` on the pointer row.
- **WS-11 Receipts.** Every raw-input entry carries a receipt built at save time from durable rows
  already written by the turn:
  - what produced it: tool address and operation id (the file name is the operation id: CRM reads
    use the executor operation id, spills the plan operation id — both resolvable through
    `execution_node` / `agent_tool_result`);
  - for CRM reads: provider, action slug, a reference to the parameter snapshot artifact, record
    count, total, whether more pages exist;
  - when it was produced, its size and sha256;
  - **how to read it again**, in plain words (e.g. "run_crm_action HUBSPOT_SEARCH_DEALS with the same
    parameters", or "rebuilt from this conversation's history" for compaction files);
  - a file with no matching durable row still gets a receipt with source "unknown" — never dropped
    silently.
- **WS-12 Expiry sweep.** A periodic fleet job (interval `CLUE_AGENT_WORKSPACE_RETENTION_SWEEP_INTERVAL_S`,
  default 3600, single-runner like the storage sweep) finds threads whose raw entries are past their
  window and **no turn is queued or running**, writes a new snapshot version without those entries'
  bytes (receipts kept, marked `expired_at`), using the same compare-and-set as a turn's save, and
  releases the blob references. A thread with a live turn is skipped and retried next cycle.
- **WS-13 Spills can be rebuilt.** Governed spills whose full result is durable (`result_ref`) may be
  restored from that artifact instead of being stored twice — builder's call; either way the agent
  sees the same file while it is within its window.

### 5.4 Turn end: saving

- **WS-14 Save.** At the end of every turn that ran (completed, awaiting input, failed after the
  agent wrote files, or stopped), the workspace layer:
  1. walks the four agent folders (WS-5 paths only);
  2. uploads blobs not already stored (content addressed, parallel, bounded);
  3. builds the manifest (tiers, `written_at` carried forward for unchanged content, receipts for new
     raw entries) and stores it;
  4. moves the pointer with a **compare-and-set**: `version = version + 1 WHERE version = <the version
     this turn hydrated>` (insert for version 1), **and only while this worker still holds the
     thread's fleet `work_lease` generation** (`hold_work_lease`, as design saves do — the turn
     runner must receive `WorkContext.lease_generation`, which it does not today);
  5. writes the local marker.
  The pointer moves only after every blob and the manifest are durable, so a pointer never names
  missing bytes.
- **WS-15 Save inside finalize.** For a turn that finalizes, the save happens inside the
  finalization authority, after the outputs snapshot and before the finalization commit
  (`agent_runtime_wiring.py:829-903`), so a finalized turn always has its files saved. Transient
  storage errors are retried; if the save still fails, finalization fails and the turn is retried by
  the fleet — the same behaviour as today when the outputs snapshot cannot reach storage. **(Claude's
  call — open question Q3.)** Turns that end without finalizing save best-effort when the lease is
  released.
- **WS-16 Stale save.** If the compare-and-set finds a newer version (a takeover already saved) or
  the lease generation is gone, nothing is written, the event is logged loudly with both versions,
  and the local marker is cleared so the next turn on this machine restores the winner. This should
  never happen under the one-turn-per-thread rule; it exists so a zombie worker cannot overwrite.
- **WS-17 Retries and crashes.** A re-claimed turn hydrates again: if its earlier attempt saved, it
  sees that version; if not, it sees the previous one. A crash between the save and the finalization
  commit leaves a newer version with the turn's files — the retry starts from it and saves again
  with the new expected version. Saves are idempotent for identical content.

### 5.5 What the agent is told

- **WS-18 Turn-start workspace card.** Each turn's context includes a bounded card listing the
  agent's earlier files from the snapshot: path, folder, size, age (from `written_at`), tier; and for
  expired raw inputs their receipt (what it was, when it was read, how many records, how to read it
  again). Composed from the pointer row and manifest (not from the disk), added with the other
  project-context artifacts (`agent_turn_fleet_wiring.py:_compose_project_context`, L3 — re-sent on
  continued turns) and the research equivalent (`account_research_turn_wiring.py:555-684`). Large
  workspaces are summarised by folder beyond a bound (builder's call; it must say what was left out).
- **WS-19 Staleness (AW-4).** The skills tell the agent to check the age of its numbers and their
  source data before relying on them after a gap, and to decide itself whether to read again,
  without having to tell the person. This is skill text (founder review), not a code check.
- **WS-20 Manual.** The workspace chapter of the manual is rewritten to match: what each folder keeps
  and for how long, that `outputs/` and `scratch/` persist for the chat, that `work/` is per turn
  apart from compaction history, that `reads/` expire with receipts, and where the card is. Skill and
  manual text is presented to the founder before it is written (standing rule).

### 5.6 The local cache: present only while useful, never residue

- **WS-21 Idle eviction.** A periodic job on each worker removes cached thread folders (and their
  markers) not used for `CLUE_AGENT_WORKSPACE_CACHE_IDLE_S` (default 1800) whose thread has no queued
  or running turn (checked in Postgres, so it is safe with several processes sharing one disk), and
  removes the oldest idle folders first when the cache root exceeds `CLUE_AGENT_WORKSPACE_CACHE_MAX_BYTES`
  (default 10 GiB). The marker is removed before the files, so a racing turn re-hydrates rather than
  trusting a half-deleted folder. "In use" is decided from the fleet's own state — a queued or claimed
  task for the thread, or a live work lease — not from `agent_turn` rows: today's cleanup reads the
  newest turn row, but a worker opens the folder before that row exists
  (`agent_turn_fleet_wiring.py:842` vs `conversation_turns.py:435`), so a thread idle for a day could
  lose its folder to the cleanup in that gap.
- **WS-22 Orphans.** The same job removes cached folders whose pointer row no longer exists (erased
  or deleted chats), stale library swap folders (`.old-*`, `.next-*`), replay trees (`pinned-*`) and
  brand/project library versions not used for the idle window. At worker start it runs once
  immediately and also clears leftovers of earlier crashes in its own temp areas (e.g.
  `/tmp/arv2-media-*`) and sandbox containers carrying the platform's execution label with no live
  turn.
- **WS-23 Retire the old cleanup.** The 24-hour thread purge (`agent_cleanup.py`) is replaced by
  WS-21/22; its crash bug and its `awaiting_input` gap go with it. `CLUE_AGENT_WORKSPACE_RETENTION_S`
  is retired (removed from settings and `.env.example`, with a note in the change log).
- **WS-24 Locks.** Correctness across machines rests only on Postgres: one turn per thread, the work
  lease generation and the pointer's compare-and-set. `flock` and the in-memory `_active` map may stay
  as same-host guards; nothing may depend on them for cross-machine safety. Several factories per
  process (findings) are acceptable for the same reason.

### 5.7 Research runs and other workspaces

- **WS-25 Research reconciliation.** The reconciliation step stops copying the source run's
  `work/ scratch/ reads/` from local disk (`quality_research_wiring.py:1084-1111`). It hydrates the
  source thread's snapshot (or reads its manifest and blobs directly) and copies from that. If the
  source has no snapshot, it says so in its log and in the reconciliation input instead of silently
  copying nothing.
- **WS-26 Delegations, account-research turns, onboarding synthesis.** Same mechanism through the
  shared factory (WS-8), with their own thread ids. Short-lived threads expire like any other by the
  rules above.

### 5.8 Erasure

- **WS-27 Privacy and project erasure.** Erasing a thread, a project or a person's data deletes the
  pointer rows and manifests involved and releases their blobs (which the existing purge then deletes,
  respecting other live references); cached copies on any machine are removed by WS-22 within one
  eviction interval, and are never used again in the meantime because their marker cannot match a
  missing pointer. The erasure tests prove no erased content remains in R2 after the purge.

### 5.9 Performance and limits

- **WS-28 Targets.** Warm turn (marker matches): one indexed DB read, no storage calls. Cold restore of
  a typical chat (≈10–50 files, < 2 MB): p95 under 1 s; the quota maximum (400 files / 20 MB): p95
  under 5 s. Save: only changed files uploaded, in parallel; p95 under 1 s for a typical turn.
  Concurrency for transfers: `CLUE_AGENT_WORKSPACE_TRANSFER_CONCURRENCY` (default 16).
- **WS-29 Measured.** Every hydrate and save logs and records (in the existing usage record or a
  sibling) whether the cache was warm, files and bytes moved, and duration; a live check reports
  these numbers on the dev stack.
- **WS-30 Quotas unchanged.** The profile quotas still bound the workspace (they bound the snapshot
  too). `run_python`'s stdout spills move under the quota accounting (they bypass it today).

### 5.10 Settings and rollout

- **WS-31 Settings** (all in `libs/clue-config`, `.env.example` and the lane `.env` with defaults, per
  the parity rule): `CLUE_AGENT_WORKSPACE_SNAPSHOTS_ENABLED` (default `true` once landed — built
  features stay on), `CLUE_AGENT_WORKSPACE_RAW_RETENTION_S=172800`,
  `CLUE_AGENT_WORKSPACE_RETENTION_SWEEP_INTERVAL_S=3600`, `CLUE_AGENT_WORKSPACE_CACHE_IDLE_S=1800`,
  `CLUE_AGENT_WORKSPACE_CACHE_MAX_BYTES=10737418240`, `CLUE_AGENT_WORKSPACE_TRANSFER_CONCURRENCY=16`.
  With snapshots disabled the system behaves as on `feat/crm-integration` (local folders only) apart
  from the new cache eviction, which then uses today's 24-hour rule — **builder must keep this
  fallback honest or drop it; it exists only as an emergency switch.**
- **WS-32 Rollout.** No backfill or migration of existing chats (AW-5): the first turn on an old
  thread saves its current folder as version 1.

## 6. Failure behaviour (what a person experiences)

| Situation | Behaviour |
|---|---|
| R2 unreachable, local copy current | turn runs normally (no storage needed to start) |
| R2 unreachable, local copy stale or missing | turn fails with a retryable error and is retried by the fleet; it never runs on a stale or empty workspace when a snapshot exists |
| R2 unreachable at save | retried; then the turn fails and is retried (as outputs do today) |
| Worker dies mid-turn | the turn is re-claimed (possibly elsewhere), hydrates the last saved version, resumes its checkpoint |
| Zombie worker saves late | refused by lease generation / compare-and-set; logged |
| Cache deleted by hand or evicted | next turn restores; nothing lost |
| Raw input expired | the file is gone, the card lists its receipt, the agent reads again if it needs to |
| Disk full during restore | turn fails retryably; the half-written cache folder and its marker are removed |
| Manifest or blob digest mismatch | turn fails loudly; never restores mismatched bytes |

## 7. Verification

Following the founder's standing rule (business-logic scenario tests through real code paths, plus
live checks), the plan must include at least:

1. **Two machines, one chat:** two factories with different cache roots, one database and one
   storage; a turn on A writes `scratch/`, `outputs/` and a CRM read; the next turn on B sees exactly
   those files; a third turn back on A detects its stale copy and restores B's version.
2. **Warm path:** a second turn on the same root makes no storage calls.
3. **Kill mid-turn:** a turn dies before and after the save; the retry on another root sees the right
   version and finalizes once.
4. **Zombie save** is refused (stale version; lost lease generation).
5. **Raw expiry:** with a 0-second window, the sweep removes `reads/` bytes, keeps the receipt, the
   next turn's card lists it, and re-reading identical bytes works.
6. **Work products survive** the sweep and a cache wipe.
7. **Erasure:** pointer, manifests and blobs gone after the purge; a cached folder on another root is
   never used and is removed by the next eviction.
8. **Eviction safety:** an idle folder is evicted; a folder whose thread has a running turn in another
   process is not; boot clean-up never touches a leased thread.
9. **Research reconciliation** across two roots reads the source run's snapshot.
10. **Sandbox after restore:** `run_python` reads and writes restored files (ownership, modes, sweep).
11. **Migration** round trip, single Alembic head.
12. **Live check on the dushanbe stack:** a real chat turn; delete the cache; continue the chat —
    the agent finds its files; record warm/cold timings (WS-29).

## 8. Found while surveying (for the builder)

- **Compaction file path (unverified).** deepagents returns the path it was given, and the
  `HistoryPathBackend` wrapper is not a composite backend, so the compaction summary may name
  `/conversation_history/<id>.md` while the bytes sit at `work/conversation_history/` — a path the
  agent cannot read. Check live; fix if real, since WS-5 snapshots exactly those files.
- **`run_python` output spills** (`reads/<op>.stdout.txt`) are written with a raw `os.open`, outside
  the quota, and a spilled run's result is then spilled a second time as `reads/<plan-op>.json`
  (16 KB inline > 12 KB receipt threshold). WS-30 brings the first under the quota; the double spill
  is harmless but wasteful.
- **Several workspace factories per process** (chat, library refresher, one per research job): the
  in-memory guards do not see each other — acceptable under WS-24, but the eviction job must not
  rely on any one factory's `_active` map.
- **Dead lifecycle code:** `authorize_cleanup`/`cleanup_authorized` gate nothing; `cleanup`,
  `purge_terminal` and `discard_failed_materialization` have no callers. Remove or reuse while
  rewriting this layer.
- **Stale manual text:** the workspace chapter says nothing writes to `reads/` and that `outputs/` is
  emptied — both wrong today (WS-20 rewrites it).

## 9. Open questions for the founder

- **Q1** — `work/` becomes per-turn (emptied at turn start) except its compaction history and large
  tool results, as the agent's manual already describes. Today its files happen to survive on the
  same machine. OK?
- **Q2** — Defaults: raw window 48 h (ruled), cache idle 30 min, cache cap 10 GiB, sweep hourly. OK?
- **Q3** — If the save cannot reach storage, the turn fails and is retried (consistent with today's
  outputs snapshot) rather than finishing without its files saved. OK?
- **Q4** — Should the person ever see these files (a download in the chat)? Out of scope here unless
  you want it; the snapshot makes it easy to add later.

## 10. Left to the builder

Table and column names; the marker's location; the manifest's exact shape beyond the fields above;
whether governed spills are stored or rebuilt from `result_ref` (WS-13); the card's bound and wording
(text reviewed by the founder); how the eviction job is scheduled within the fleet; how the lease
generation reaches the turn runner; whether hydrate/save live in the factory, the lease or a small
collaborator object, as long as every caller gets them (WS-8).

## 11. Change log

- 2026-10-21 — first draft (Claude), from rulings AW-1–AW-8 and the footprint findings.
