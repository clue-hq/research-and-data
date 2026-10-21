# Agent workspace — rulings

Founder decisions on making the agent's workspace machine-independent (finding F3 of CRM trial 1,
and the footprint review in [`2026-10-21-workspace-footprint-findings.md`](2026-10-21-workspace-footprint-findings.md)).
Numbered AW-n, dated; superseded rulings are struck through, never deleted. AW-1 to AW-5 were first
recorded as CRM rulings R-10.4 to R-10.8 and moved here on 2026-10-21 because they govern every
agent, not only the CRM work.

## Direction

- **AW-1 (2026-10-21; was R-10.4)** **The agent's workspace no longer depends on one machine.** A
  chat's workspace is (1) its recipe, rebuilt every turn from database pins as today; (2) one
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

## Scope, order and interim

- **AW-5 (2026-10-21; was R-10.8)** **Order and scope:** F2 first (done 2026-10-21), then F3. One
  comprehensive spec for Head of ABM chats and research runs (same workspace mechanism), and a short
  follow-up spec for design ad/web sessions (restored only when missing, so a worker can reuse a stale
  copy). Existing chats are not migrated: a chat's current folder becomes its first snapshot the next
  time it runs (default; founder did not object).
- **AW-6 (2026-10-21)** **Interim (stopgap A):** until AW-1 lands, `outputs/` is no longer emptied at
  the end of a turn — it is saved as artifacts, then reopened with its files for the chat's later
  turns (`f799a9830`). The files still go with the thread folder 24 h after the chat's last turn.
- **AW-7 (2026-10-21)** **F3 is built in its own worktree and branch**, stacked on
  `feat/crm-integration` and merging it in periodically so conflicts surface early; when either lane
  changes something the other relies on, it messages the other session. Tests use one throwaway test
  database for the F3 lane; its live checks run on the nashville stack while that lane is idle (no
  second stack database).
- **AW-8 (2026-10-21)** **Rules for other lanes until F3 lands** (guidance, and they must not hold up
  other work — e.g. CRM Phases 2 and 3):
  1. No new state that lives only on a worker's disk: anything the agent must find again goes in the
     agent's own folders (`scratch/`, `outputs/`, `reads/`), or in Postgres or R2.
  2. No new in-memory registries of folder paths like `CrmReadSinks`; F3 absorbs that one.
  3. No code that relies on `outputs/` being emptied, or on a turn running on the same machine as the
     last one.
  4. Raw reads carry enough to repeat them (action, parameters, when, how many records) — they become
     the receipts of AW-2.
