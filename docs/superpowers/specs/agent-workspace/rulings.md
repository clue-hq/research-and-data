# Agent workspace — rulings

Founder decisions on making the agent's workspace machine-independent (finding F3 of CRM trial 1,
and the footprint review in [`2026-10-21-workspace-footprint-findings.md`](2026-10-21-workspace-footprint-findings.md)).
Numbered AW-n, dated; superseded rulings are struck through, never deleted. AW-1 to AW-5 were first
recorded as CRM rulings R-10.4 to R-10.8 and moved here on 2026-10-21 because they govern every
agent, not only the CRM work.

## Direction

- **AW-1 (2026-10-21; was R-10.4)** **The agent's workspace no longer depends on one machine.** A
  chat's workspace is (1) its recipe, ~~rebuilt every turn from database pins as today~~ written from
  database pins, where a turn writes only the files that changed — *amended 2026-10-22 (founder):*
  nothing is emptied and rebuilt each turn; `.deepagent/` changes only after a deployment, `context/`
  only where a value changed, `inputs/` gets the new turn's input (spec WS-36); (2) one
  versioned snapshot of the files the agent made, stored in R2 with its version record in Postgres,
  written only if the previous version is still current (the check design site turns already use);
  and (3) its conversation in Postgres. A worker's disk is only a cache, emptied when a chat goes idle
  and when the worker starts, so no machine keeps residue and any machine can continue any chat.
  Researched against Claude Code cloud, Codex cloud, Cursor cloud agents, Devin, E2B and the
  Anthropic/OpenAI code-execution containers.
- **AW-2 (2026-10-21; was R-10.5)** **What is kept, and for how long.**
  - *Outcomes* (published brand and project documents, designs): already durable, unchanged.
  - *Work products* (analysis tables, scripts, drafts, the agent's notes): **as long as the chat**
    (recommended; founder agreed the direction). *Amended by AW-22:* only `outputs/` is kept for
    the chat's life; `scratch/` and `work/` go 7 days after the chat's last activity (AW-24).
  - *Raw inputs* (CRM reads, large tool results, conversation offloads): deleted **48 hours after the
    chat's last activity**, but a **receipt** of each (what was read, when, how many records, content
    hash, how to read it again) is kept for the chat's lifetime, so nothing points at a missing file
    without saying what it was.
  - The platform has no chat retention policy yet (everything is kept until a privacy erasure); work
    products will follow whatever policy is adopted.
- **AW-3 (2026-10-21; was R-10.6)** **A resumed chat runs on the current profile and skills**, not
  the ones it started with; it keeps its own files and conversation.
- **AW-4 (2026-10-21; was R-10.7)** **Staleness:** after a gap, the agent **must check how old its
  numbers and their source data are** before relying on them, and decide itself whether to read
  again; it does not have to announce this to the person. The platform supplies the facts (ages,
  receipts, expired files); the judgement is in the skills, not a code check.

- **AW-9 (2026-10-22)** **One chat, one private space; cleanup throws away whole folders.** Each
  worker owns its own area of the disk (`<root>/<worker>/`) that no other worker or process touches,
  and each chat's folder in it holds its own copy of the brand and project files instead of folders
  shared by every chat of a project. A worker wipes its whole area when it starts (as AW-1 says) and
  deletes an idle chat's whole folder; no cleanup ever works out who else is using a folder. Cost
  accepted: a chat whose next turn lands on another worker restores from its snapshot. Founder judged
  the first proposal (keep shared folders, skip ones Postgres says are in use) too risky; decided
  after researching ChatGPT, Claude.ai, Manus, Perplexity Projects, Cursor and Claude Code / Codex
  cloud, which all give each chat its own space. Spec: WS-15, WS-16, WS-37.
- **AW-10 (2026-10-22)** **No new lease.** A chat turn's save reuses the lease the work queue
  already holds for every turn (`work_lease`): the save goes through only while the worker still
  holds that lease at the same generation and the snapshot version is still the one the turn
  started from. File locks and in-memory maps remain only as guards inside one worker. Spec WS-8,
  WS-13.
- **AW-11 (2026-10-22)** **A chat's folder on a worker is deleted after 30 minutes idle.** Only the
  disk copy goes; the next turn restores it from R2. Kept at 30 minutes after the founder heard
  that production runs one chat worker and a longer window (24 h) would keep more returns warm.
  Spec WS-16, `CLUE_AGENT_WORKSPACE_CACHE_IDLE_S=1800`.
- **AW-12 (2026-10-22)** **Measure first; two speed measures are future scope.** Sending a chat's
  next turn to the worker that ran it last, and restoring files early when the person opens the
  chat, are not built in Phases 1–3. They stay in the spec's future scope (§2.4, F-1 and F-2):
  routing when production runs more than one chat worker, early restore if measured cold restores
  miss their targets (WS-19, WS-20).
- **AW-13 (2026-10-22)** **CRM reads are stored in the snapshot.** Their raw records exist nowhere
  else (only the action, parameters, time and record count are durable), so the snapshot copies
  them into R2 as raw inputs: removed 48 hours after the chat's last activity, receipts kept (AW-2).
  Large tool results, already stored in full, may point to that copy instead of being stored twice
  (builder's call). Spec WS-4, WS-23, WS-27.
- **AW-14 (2026-10-22)** **`work/` is kept for the chat's whole life, like `scratch/`.** *(Amended by
  AW-22 and AW-24: both are kept 7 days after the chat's last activity, not for its whole life.)* It is not
  emptied between turns. Its files are work products, except the compaction offloads
  (`work/conversation_history/`, `work/large_tool_results/`), which stay raw inputs under AW-2. The
  agent's manual, which today calls `work/` per-turn scratch, is rewritten to match (spec WS-32).
  Spec WS-4, WS-6, WS-23.
- **AW-15 (2026-10-22)** **A turn whose files cannot be saved fails and is retried.** *(Amended by
  AW-18: the save is retried, the turn is not re-run.)* The save is
  retried a few times; if storage is still unreachable, the turn fails and the work queue runs it
  again, as it does today when `outputs/` cannot be saved. A turn never finishes with its files
  unsaved, so no later turn can silently restore an older version. Spec WS-9, §10.
- **AW-16 (2026-10-22)** **Phase 1 carries its own robustness proofs.** Two workers on one chat, a
  warm second turn that downloads nothing, kill mid-turn before and after the save, a refused
  zombie save, cleanup never touching another worker's area, two chats never sharing a folder, and
  a first live check on the dushanbe stack. Phase 3 keeps the clean-machine restore, the research
  reconciliation test and the final live timing. Spec §11.
- **AW-17 (2026-10-22)** **Each worker area is capped at 10 GiB.** Over the cap, idle chat folders are
  deleted, oldest first; a safety net behind the 30-minute rule (AW-11).
  `CLUE_AGENT_WORKSPACE_CACHE_MAX_BYTES=10737418240`.
- **AW-18 (2026-10-22)** **A failed save does not re-run the turn** (amends AW-15). By the time the
  save runs the agent's work is done and the runtime has marked the turn ended, so a re-run would
  repeat it and pay twice; and today a failed outputs snapshot fails the turn with no retry. The
  save is retried 3 times; if storage is still unreachable the turn fails, the worker keeps its local
  copy marked unsaved, and the chat's next turn saves it. A failed restore, which happens before the
  agent starts, does re-run the turn. Spec WS-9, §10; plan decision 1.
- **AW-19 (2026-10-22)** **Worker areas are claimed by lock, not named.** A worker takes the first
  free `<root>/workers/area-<n>` by holding an exclusive lock on `area-<n>.lock` while it runs, and
  wipes it before use; at start-up it also deletes every other area whose lock it can take. No
  configuration; no leftover areas. Requires the workspace root on local disk (locks are unreliable
  on network drives). Spec WS-15, WS-16; plan decision 2.
- **AW-20 (2026-10-22)** **No shared project library on disk.** Each chat keeps its own copy (AW-9),
  so the refresher stops writing a shared tree and the API process stops building a workspace
  factory. A privacy erasure that changes library content without moving its digest bumps
  `project_library_epoch`, which the digest includes, so every chat's copy resyncs next turn. Spec
  §12; plan decision 3.
- **AW-21 (2026-10-22)** **Privacy erasure covers the records about a person, not mentions in chat
  files.** A person's erasure removes what the platform keeps *about* them (the contact, its claims,
  the research and provider data tied to them), as it already does. It does not search agent chat
  files (notes, tables, scratch) for the person's details; those traces may stay until the chat is
  deleted or the 48-hour raw-input expiry (AW-2) removes them. Founder: *"its fine if some traces of
  the person, which are not stored in hashed db records are left"* — no platform where people talk
  to an LLM can erase every mention of someone. Consequences: (1) snapshot files keep sharing one
  stored file per content hash in the workspace (no per-chat copies); (2) a chat whose saved file is
  byte-identical to something later privacy-erased skips that file on restore, drops it from its
  file list, never stores it again and tells the agent at its next turn, instead of failing every
  turn (the review's I1; Phase 2); (3) WS-31 shrinks to deleting a chat's or project's snapshots and
  letting the existing purge remove bytes nothing else holds.
- **AW-22 (2026-10-22)** *(Window amended to 7 days by AW-24.)* **The agent's working files are kept 30 days after the chat's last
  activity.** Three windows instead of two (amends AW-2 and AW-14):
  - `outputs/` (the files meant for the person): kept for the chat's life;
  - `scratch/` and `work/` apart from its two compaction folders (the agent's notes, tables,
    scripts, drafts): deleted **30 days** after the chat's last activity;
  - raw inputs (`reads/`, `work/conversation_history/`, `work/large_tool_results/`): 48 hours, as
    AW-2.

  Every deleted file keeps its entry in the file list, marked expired, and the agent is told at turn
  start (WS-28), exactly as for raw inputs. Chosen after comparing ChatGPT (sandbox files gone after
  about an hour idle), Claude.ai (created files kept for the conversation) and Manus (intermediate
  code and temporary files dropped when an idle task's computer is recycled after 7 or 21 days; its
  outputs and uploads restored). Founder: *"go with 30 days for scratch and work."*
- **AW-24 (2026-10-22)** **Working files are kept 7 days, not 30; the expiry job runs hourly.**
  `scratch/` and `work/` (apart from its compaction folders) are deleted **7 days** after the chat's
  last activity (`CLUE_AGENT_WORKSPACE_WORKING_RETENTION_S=604800`); founder: *"you can make this 7
  days for now."* The retention expiry job (WS-26) checks every hour
  (`CLUE_AGENT_WORKSPACE_RETENTION_SWEEP_INTERVAL_S=3600`), so a file goes up to an hour after its
  limit (Q10 decided).
- **AW-25 (2026-10-22)** **The person never sees or downloads the agent's workspace files** (Q11);
  the snapshot stays internal. **Stage-0 trial workspaces are left as they are for now** (Q8): no
  change in Phase 2 (they currently compose with snapshots on, review minor M2). Founder: *"NO THEY
  CANT SEE or download them"*; *"yeah let them be for now."*
- **AW-26 (2026-10-23, amended the same day)** **Only a chat's own working files are swept;
  nothing a person or another system owns is ever deleted automatically.**
  - *Never swept automatically:* uploads, artifacts people made in the Gallery, the `outputs/`
    copies saved at each turn's end, research final outputs (claims, results, receipts), provider
    data. Whether any of these may ever be swept needs its own careful discussion once the system
    has matured. Founder: *"this ws-30's scope is too big … let the system get a little more
    mature"*; *"even the final research and its claim as well you dont delete them … you can
    delete all their scratch and rough work but not their final output."*
  - *Swept in Phase 2:* a file that lives only in a chat's (or a run's) agent folders — `scratch/`,
    `work/`, `reads/`, old versions' files, an erased chat's files — has its bytes deleted from R2
    once no snapshot holds it: on expiry (48 h raw inputs, 7 d working files), on a newer version
    dropping it, on erasure. Founder: *"i only meant them for other stray files, not files that
    came under work/ scratch/ and other things limited to just a chat thread."*
  - *How it is made safe (WS-30):* snapshot files get their own storage area,
    `<workspace>/agent-workspace/<sha256>`, as design sessions have `<workspace>/design/<sha256>`.
    Only snapshots ever write there, so "nothing holds it" is one check over snapshot holds and a
    deletion can never touch an upload, a Gallery artifact or a research output even when the
    bytes are identical. **The conversation itself is never deleted** by any of this: a chat's
    messages (`agent_thread_message`) are what every turn's history is loaded from and nothing
    but a DSAR touches them; the `work/conversation_history/` offload is only a copy. Amends AW-21's first consequence (snapshot files no longer share storage
    with other kinds of file; chats still share identical files with each other). WS-31a is
    dropped: a privacy erasure of research or provider data can no longer land on a chat's file.
- **AW-23 (2026-10-22)** **Phase 1 may ship without Phase 2.** There are no customers yet, so
  the release rule of spec §3 (Q7) is dropped: until Phase 2 lands, nothing in a chat's snapshot is
  deleted (raw inputs included), and stored files of old versions are kept. **Order:** the CRM branch
  (`feat/crm-integration`, through its Phase 2 writes) is merged into the F3 branch (merge
  `7d83e34af`, migrations joined by `01baa2e73e84`); they ship as **two pull requests**, CRM first,
  then F3 with only its own commits. Founder: *"we have no customer right now. so we can ship with
  just phase 1 for now"*; *"yes go ahead with step 1, two PRs."*

## Scope, order and interim

- **AW-5 (2026-10-21; was R-10.8)** **Order and scope:** F2 first (done 2026-10-21), then F3. One
  comprehensive spec for Head of ABM chats and research runs (same workspace mechanism), and a short
  follow-up spec for design ad/web sessions (restored only when missing, so a worker can reuse a stale
  copy). Existing chats are not migrated: a chat's current folder becomes its first snapshot the next
  time it runs (default; founder did not object).
- **AW-6 (2026-10-21)** **Interim (stopgap A):** until AW-1 lands, `outputs/` is no longer emptied at
  the end of a turn — it is saved as artifacts, then reopened with its files for the chat's later
  turns (`f799a9830`). The files still go with the thread folder 24 h after the chat's last turn.
- **AW-7 (2026-10-21)** **F3 is built in its own worktree and branch** — the `dushanbe` workspace (founder, 2026-10-21) — stacked on
  `feat/crm-integration` and merging it in periodically so conflicts surface early; when either lane
  changes something the other relies on, it messages the other session. Tests use one throwaway test
  database for the F3 lane. *Amended 2026-10-21 (founder):* the dushanbe lane runs on its own existing
  stack database (`clue_nashville_pm_clone`), migrated in place to the `feat/crm-integration` head
  (`c87ba03cfc4e`); F3's live checks run on the dushanbe stack — still no new database.
- **AW-8 (2026-10-21)** **Rules for other lanes until F3 lands** (guidance, and they must not hold up
  other work — e.g. CRM Phases 2 and 3):
  1. No new state that lives only on a worker's disk: anything the agent must find again goes in the
     agent's own folders (`scratch/`, `outputs/`, `reads/`), or in Postgres or R2.
  2. No new in-memory registries of folder paths like `CrmReadSinks`; F3 absorbs that one.
  3. No code that relies on `outputs/` being emptied, or on a turn running on the same machine as the
     last one.
  4. Raw reads carry enough to repeat them (action, parameters, when, how many records) — they become
     the receipts of AW-2.
