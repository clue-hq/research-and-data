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
    (recommended; founder agreed the direction).
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
- **AW-14 (2026-10-22)** **`work/` is kept for the chat's whole life, like `scratch/`.** It is not
  emptied between turns. Its files are work products, except the compaction offloads
  (`work/conversation_history/`, `work/large_tool_results/`), which stay raw inputs under AW-2. The
  agent's manual, which today calls `work/` per-turn scratch, is rewritten to match (spec WS-32).
  Spec WS-4, WS-6, WS-23.
- **AW-15 (2026-10-22)** **A turn whose files cannot be saved fails and is retried.** The save is
  retried a few times; if storage is still unreachable, the turn fails and the work queue runs it
  again, as it does today when `outputs/` cannot be saved. A turn never finishes with its files
  unsaved, so no later turn can silently restore an older version. Spec WS-9, §10.

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
