# Machine-independent agent workspace — design (F3)

**Status:** draft v2 for founder review, 2026-10-22. Branch `feat/agent-workspace-durability`
(dushanbe), stacked on `feat/crm-integration`.
**Built from:** the founder's F3 discussion of 2026-10-21, the rulings AW-1–AW-8 in
[`rulings.md`](rulings.md), the roadmap agreed the same day (Phases 0–3), and the evidence in
[`2026-10-21-workspace-footprint-findings.md`](2026-10-21-workspace-footprint-findings.md).
**Covers:** every agent that works in a platform thread folder: Head of ABM chats, ARV2 research
runs (including their reconciliation step), delegated sub-agents, account-research turns and
onboarding synthesis. Design ad and web sessions get their own short follow-up spec (AW-5).

---

## 0. How to read this spec

**This one spec covers all three build phases.** It is Phase 0 of the roadmap: the agreed text
that every phase is built from. Each build phase then gets its own implementation plan, written
when that phase starts. The shared definitions (the snapshot, the save rules) live here once, so
the phases cannot drift apart.

| Section | What it tells you |
|---|---|
| §1 Why | the problem, in plain words |
| §2 What you asked for | every requirement from our discussion, and where this spec meets it |
| §3 The phases | what each phase builds, what it delivers on its own, how we know it is done |
| §4 Decisions I need from you | every place where this spec goes beyond or differs from what we discussed, with my recommendation |
| §5–§6 | how things work today, and the design in one picture |
| §7–§9 | the requirements of Phase 1, Phase 2 and Phase 3, each in its own section |
| §10–§11 | what a person experiences when things fail, and the tests |
| §12–§14 | notes for the builder, what is left to the builder, change log |

**Labels used throughout**
- **[P1] [P2] [P3]**: the phase a requirement is built in.
- **WS-n**: a requirement's id. Plans, tests and reviews cite these ids.
- **Ruling AW-n**: a founder decision recorded in `rulings.md`.
- **Your words**: something the founder said in the discussion, quoted.
- **Claude's call**: a choice Claude made that the founder has not confirmed yet. Every one is
  listed in §4.
- **Builder's call**: any sensible choice that meets the requirement is fine.

**Words used in this spec**

| Word | Meaning |
|---|---|
| worker area | one worker's own part of the disk, `<root>/<worker>/`. No other worker or process reads or writes it (WS-15) |
| thread folder | a chat's folder inside a worker area: `<root>/<worker>/<ws>/projects/<p>/threads/<t>/` (today, before Phase 1: `<root>/<ws>/projects/<p>/threads/<t>/`) |
| recipe folders | `.deepagent/ inputs/ context/` plus `brand/ project/ attachments/`. Written from database pins; from Phase 1 only the files that changed are written (WS-36), and each chat has its own copy of the brand and project files (WS-37) |
| agent folders | `scratch/ reads/ work/ outputs/`: the files the agent makes or reads for itself. **These are what this spec makes durable** |
| snapshot | one saved version of a chat's agent folders: a file list in R2 plus the stored files it names |
| version record | one row per chat in Postgres naming the chat's current snapshot version (technical name: pointer row) |
| file list | the JSON document describing one snapshot version (technical name: manifest) |
| stored file | one file's bytes in R2, stored once under its content hash (technical name: blob) |
| local version note | a small file on the worker that says which snapshot version its copy of the folder holds (technical name: marker) |
| restore | at turn start, making the worker's copy of the agent folders equal to the current snapshot |
| save | at turn end, storing the agent folders as a new snapshot version |
| cache | a worker's copy of a thread folder, inside its own worker area. Deleting it never loses anything |
| receipt | a short record of a raw read that stays after the read's bytes expire: what it was, when, how many records, its hash, how to read it again |

---

## 1. Why

Every chat has a folder on one machine's disk. Four of its subfolders hold what the agent made or
read for itself:

| Folder | What is in it |
|---|---|
| `scratch/` | the agent's notebook |
| `outputs/` | its deliverables (analysis tables, drafts) |
| `reads/` | CRM reads and large tool results |
| `work/` | conversation offloads from compaction, and files made during a turn |

Nothing copies these folders anywhere. The next turn simply reopens the folder on the same disk.
That causes three problems.

- **Another machine cannot continue the chat.** A turn that runs on a second worker, after
  autoscaling or after a VM replacement, loses the agent's notes, drafts and reads. Its
  conversation, which is durable in Postgres, still refers to them (CRM trial 1, finding F3).
- **The files vanish after a day, and residue stays behind.** The folders are deleted 24 hours
  after a chat goes quiet, so a chat continued the next day has lost them too. The cleanup job also
  has gaps and a crash bug, and leaves leftovers on disk (findings §1).
- **Safety depends on one machine.** File locks and in-memory registries only work inside one
  machine or one process.

What the founder asked for, in their words (2026-10-21): *"any chat thread's workspace whether its
an year old one or a new one, is assembled, when the user continues a chat in it, stays for
sometime, but then also removed, with no remaining residual footprints, but then when its continued
again in another vm instance (think from pov of autoscaling), it has the same agent workspace and
environment, as if nothing ever changed."*

How other products do it (researched 2026-10-21: Claude Code cloud, Codex cloud, Cursor cloud
agents, Devin, E2B, the Anthropic and OpenAI code-execution containers): no machine owns anything.
The environment is rebuilt from a recipe, durable state lives off the machine with a record saying
which version is current, and the local disk is a cache that can be deleted at any time. This spec
applies that to the one piece we are missing: the agent's own files.

---

## 2. What you asked for, and where this spec meets it

Every requirement from the discussion and the rulings, with the phase and the requirements that
meet it. The **Status** column says whether the spec meets it as discussed, or differs (then §4 has
the decision).

| # | What you asked for | Source | Met by | Phase | Status |
|---|---|---|---|---|---|
| D-1 | Any chat, new or a year old, continued on any machine, finds the same files the agent left | your words; AW-1 | WS-1–WS-11 | P1 | as discussed |
| D-2 | The copy on a machine stays only while useful, then is removed with no residue | your words; AW-1 | WS-15–WS-17 | P1 | decided 2026-10-22 (Q1, AW-9) |
| D-3 | A chat's workspace = its recipe + one versioned snapshot in R2 with its version record in Postgres + its conversation; the disk is only a cache | AW-1 | WS-1–WS-3, WS-6 | P1 | as discussed |
| D-4 | A new version is written only if the previous one is still current (the design site-turn check) | AW-1 | WS-8 | P1 | as discussed |
| D-5 | Restore only when the local copy is not that exact version (compare versions, not "is the folder there") | roadmap P1 | WS-6 | P1 | as discussed |
| D-6 | Upload only changed files | roadmap P1 | WS-3, WS-8 | P1 | as discussed |
| D-7 | `outputs/` is never emptied again | roadmap P1; AW-6 (stopgap) | WS-4 | P1 | as discussed |
| D-8 | Turn start takes a database lease, replacing file locks and in-memory maps | roadmap P1 | WS-13 | P1 | decided 2026-10-22 (Q2, AW-10): the existing lease is reused |
| D-9 | Replace today's cleanup job, its crash bug and its gap for chats waiting on an answer | roadmap P1 | WS-15–WS-17 | P1 | as discussed |
| D-10 | `run_python` and CRM reads keep working unchanged | roadmap P1 | WS-6, WS-14 | P1 | as discussed |
| D-11 | Absorb the CRM reads registry (`CrmReadSinks`); no new in-memory path registries | AW-8.2 | WS-14 | P1 | as discussed |
| D-12 | A resumed chat runs on the current profile and skills, keeping its own files and conversation | AW-3 | WS-18 | P1 | as discussed (already true today; kept true and tested) |
| D-13 | Not slower for the person | your words: *"i hope of all of this will not make our experience very slow for the user right?"* | WS-19, WS-20; §2.4 | P1 | decided 2026-10-22 (Q3, AW-12): measure first; two speed measures kept as future scope |
| D-14 | Production-grade robustness: no half-written snapshots, no silent overwrites, integrity checks, safe retries, nothing left behind, one place to erase, proven by tests | your words: *"production grade robustness and efficiency"*; my 7 properties of 2026-10-21 | see §2.1 | P1–P3 | as discussed |
| D-15 | Existing chats are not migrated; a chat's current folder becomes its first snapshot | AW-5 | WS-22 | P1 | as discussed |
| D-16 | Rollout behind a flag | roadmap P3 | WS-21 | P1 (flag), P3 (rollout) | as discussed; the flag must exist from the first code (env parity rule) |
| D-17 | Which folder belongs to which tier | roadmap P0 | WS-4, WS-5, WS-23 | P1 (folders), P2 (tiers) | decided 2026-10-22 (Q5, AW-14): `work/` kept for the chat's life |
| D-18 | Work products (tables, scripts, drafts, notes) kept as long as the chat | AW-2 | WS-23 | P2 | **changed 2026-10-22 (AW-22):** `outputs/` for the chat's life; `scratch/` and `work/` 30 days after last activity |
| D-19 | Raw inputs (CRM reads, large tool results, conversation offloads) deleted 48 hours after the chat's last activity | AW-2; your words: *"48 hours after the long activity i think is good enough"* | WS-23, WS-24, WS-26 | P2 | as discussed |
| D-20 | A receipt for every raw input, kept for the chat's lifetime: what, when, how many records, content hash, how to read it again | AW-2 | WS-25 | P2 | as discussed |
| D-21 | The agent is told at turn start what files exist from earlier, how old they are, and what has expired | roadmap P0/P2; my proposal of 2026-10-21 | WS-28 | P2 | as discussed |
| D-22 | The agent checks how old its numbers and source data are before relying on them after a gap, decides itself whether to read again, and need not tell the person | AW-4; your words: *"the agent need not explicitly state the user, but yes it must check the staleness of its numbers"* | WS-29 | P2 | as discussed |
| D-23 | Your case: the agent did an analysis, the chat sat idle a week, the input files are gone, but the agent's state says "done". It must not build on files that are gone without knowing | your words (2026-10-21) | WS-25, WS-28, WS-29 | P2 | as discussed |
| D-24 | Privacy erasure covers snapshots | roadmap P2 | WS-31 | P2 | decided 2026-10-22 (AW-21): erasure covers records about a person, not mentions in chat files; release timing still Q7 |
| D-25 | Stored files that no snapshot points to anymore are deleted | roadmap P2 | WS-30 | P2 | as discussed |
| D-26 | Skill and manual text reviewed by you before it is written | standing rule; roadmap P0 | WS-29, WS-32 | P2 | as discussed |
| D-27 | Research runs: their reconciliation step reads the source run's snapshot, not local disk | roadmap P3 | WS-33 | P3 | as discussed |
| D-28 | Delegated sub-agents get the same mechanism | roadmap P3 | WS-12, WS-34 | P1 (mechanism), P3 (checked) | as discussed |
| D-29 | Stage-0 trial workspaces get the same mechanism | roadmap P3 | WS-12 | — | **differs: Q8** |
| D-30 | Robustness tests: kill a worker mid-turn, two workers on one chat, restore on a clean machine | roadmap P3 | §11 | P1 (basic), P3 (full) | decided 2026-10-22 (Q9, AW-16) |
| D-31 | A live measurement of restore time | roadmap P3; my caveat "we should measure it, not assume it" | WS-20, §11 | P1 (first), P3 (final) | as discussed |
| D-32 | One comprehensive spec for chats and research runs; design ad and web sessions in a short follow-up spec | AW-5; your words: *"well defined and very comprehensive"* | this document; §2.2 | P0 | as discussed |
| D-33 | Other lanes follow AW-8 meanwhile, and F3 must not hinder CRM Phases 2 and 3 | AW-8; your words | WS-14, §12 | all | as discussed |
| D-34 | Recipe folders are not emptied and rebuilt every turn; only what changed is written | your words (2026-10-22) | WS-36 | P1 | as discussed |
| D-35 | One chat, one private space: no folder on disk is shared by two chats or two workers, so cleanup never has to work out who is using what | your words (2026-10-22): *"i think this is a little risky design"*; AW-9 | WS-15, WS-16, WS-37 | P1 | as discussed |

### 2.1 The seven production-grade properties

These are the seven properties I promised on 2026-10-21. Each one maps to requirements and tests.

| Property | Requirements | Tests (§11) |
|---|---|---|
| No half-written snapshots: files are stored before the version record moves | WS-8 | 3 |
| No silent overwrites: a version is written only if the previous one is still current | WS-8, WS-10 | 4 |
| Integrity: every restored file is checked against its hash | WS-6 | 1, 9 |
| Safe retries: save and restore can be repeated after a crash | WS-11 | 3 |
| Nothing left behind: disk is a cache; stored files nothing points to are deleted | WS-15–WS-17, WS-30 | 6, 8 |
| One place to erase | WS-31 | 7 |
| Proven, not assumed: kill mid-turn, two workers, clean machine, live timing, flag | WS-20, WS-21, WS-35, §11 | all |

### 2.2 Not in this spec

- **Design ad, web and site sessions.** These use a different folder (`LUMEN_AGENT_WORKSPACE_ROOT`)
  and are covered by the follow-up spec (AW-5). It will move them from "restore when missing" to
  the version check that site turns already use, and clean up their logs and asset cache.
- **The checkpoint growth.** Each turn copies the whole conversation into its own checkpoint
  (findings §2). This is a separate item, and nothing here makes it worse.
- **A retention policy for chats themselves.** There is none today. Work products follow whatever
  policy is adopted later (AW-2).
- **A hosted sandbox for `run_python`.** It keeps using each worker's own Docker, since the files
  are local again after a restore.
- **F11** (`.py` files refused in the sandbox) is owned by the CRM lane.

### 2.3 Failures even if it "works"

- A turn silently runs with an empty or stale workspace when its real files exist.
- The agent tells the person something is done, or quotes numbers, from files that are gone,
  without knowing they are gone.
- Two workers' saves interleave and corrupt a chat's files.
- A noticeably slower first reply, or a turn that fails because a cache was cleaned.
- Erased personal data survives in a snapshot, a cache folder or a forgotten stored file.

### 2.4 Future scope (decided not to build now)

Each item below was discussed and deliberately left out of Phases 1–3. It stays on the list, with
what should trigger it. A plan picks it up when its trigger is met; WS-20's measurements are the
evidence for the first two.

| Item | What it does | Build it when | Source |
|---|---|---|---|
| **F-1 Send a chat back to the worker that ran it last** | when a chat's next turn is queued, prefer the worker whose area already holds its folder, if that worker has a free slot | production runs **more than one chat worker** (today it runs one, so every turn already lands on the same worker) | Q3, AW-12 |
| **F-2 Restore early** | start restoring a chat's files when the person opens the chat or starts typing, not when the turn starts | WS-20 shows cold restores **missing the WS-19 targets** (typical chat p95 over 1 s) or people noticing a slower first reply | Q3, AW-12 |
| **F-3 The design follow-up spec** | design ad and web sessions move from "restore when missing" to the version check; their logs and asset cache get cleaned | after Phase 1 lands | AW-5 |

---

## 3. The phases

| Phase | What it builds | What it delivers on its own | Requirements | Done when |
|---|---|---|---|---|
| **P0: the spec** | this document | the agreed text every plan is built from | — | you approve it, with the §4 decisions answered |
| **P1: the core** | version record and snapshot in R2; restore at turn start; save at turn end; recipe folders updated only where changed; each worker its own disk area and each chat its own copy of the brand and project files; the disk becomes a cache; the old cleanup job retired; the flag | **Fixes F3.** Any worker can continue any chat with all of its files. No residue on disk. Research runs, delegations, account research and onboarding synthesis get it too, through the shared workspace layer | WS-1–WS-22, WS-36, WS-37 | §11 tests 1–4, 6, 8, 10, 11, 13, 14 pass; the first live check passes with timings recorded. **Status: P1 built; live check passed 2026-10-22** (branch `feat/agent-workspace-durability`; not in production until P2) |
| **P2: retention and honesty** | tiers; 48-hour expiry of raw inputs; receipts; the expiry job; the turn-start file list; the staleness instruction; the manual rewrite; erasure; deleting stored files nothing points to | Raw CRM data no longer kept beyond 48 hours. The agent always knows what it has, how old it is and what expired. Privacy erasure reaches the snapshots | WS-23–WS-32 | §11 tests 5 and 7 pass; you have reviewed and approved the skill and manual text |
| **P3: remaining workspaces and proof** | research reconciliation reads snapshots; every other caller checked; the full robustness tests; final live measurement; rollout | Every agent workspace is machine-independent, and it is proven | WS-33–WS-35 | §11 tests 9 and 12 pass; the full robustness suite passes |
| **Follow-up spec** | design ad and web sessions | — | separate document | — |

**Release rule (AW-23, 2026-10-22): P1 may ship without P2** — there are no customers yet. Until
P2 lands nothing in a snapshot is deleted. *Superseded text:* ~~P1 can be built, merged into the branch and tested on its
own. It does not reach production without P2.~~ P1 alone would keep raw CRM records in R2 with no
expiry and outside privacy erasure, which is worse than today's 24 hours on one disk.

**Size (estimate from 2026-10-21):** three plans, each the size of F2 or a bit larger. Phase 1 is
the biggest: about two F2s.

---

## 4. Decisions I need from you

Each item below is a place where this spec differs from what we discussed, or settles something
we did not discuss. Each has my recommendation. Nothing in the build depends on these until its
phase starts. Everything Phase 1's plan needs is decided (Q1–Q6, Q9, Q10's cache values). Still
open, for later phases: Q7, Q8, Q11 and Q10's expiry-job timing.

**Q1. Cleaning the cache when a worker starts** [P1]: **decided 2026-10-22 (AW-9).**
- **The problem:** on our VM every worker shares one disk (`/srv/clue/workspaces`), and the brand
  and project files sit in folders shared by every chat of a project. Emptying the disk at
  start-up, as AW-1 says, would delete folders other workers are using mid-turn. My first answer
  (skip folders that Postgres says are in use) kept the sharing and made cleanup work out who uses
  what. You judged that risky.
- **What other products do** (ChatGPT, Claude.ai, Manus, Perplexity Projects, Cursor, Claude Code
  and Codex cloud): one chat, one private space; shared project material lives in central storage
  and each chat gets its own copy; cleanup throws away a whole space.
- **Decided:** each worker owns its own area of the disk, and each chat folder holds its own copy
  of the brand and project files (WS-15, WS-37). A worker wipes its whole area when it starts,
  exactly as AW-1 says, and deletes an idle chat's whole folder (WS-16). No cleanup ever looks at
  another worker's files.

**Q2. The lease** [P1]: **decided 2026-10-22 (AW-10): reuse the existing lease.**
- **The roadmap said:** take a database lease at turn start, replacing file locks and in-memory
  maps.
- **What already exists:** the fleet already holds a database lease for every chat turn
  (`work_lease`). Its generation number goes up on every takeover, and Postgres already allows only
  one turn per chat.
- **My recommendation:** don't add a second lease. Every save checks the existing lease's
  generation, and the version check catches the rest. File locks and in-memory maps stay only as
  same-machine guards, and nothing relies on them for safety across machines (WS-13).

**Q3. Speed measures I mentioned but this spec does not build** [P1]: **decided 2026-10-22 (AW-12):
not built now; recorded as future scope in §2.4, with what triggers each.**
- **On 2026-10-21 I listed three things that keep it fast:**
  1. send a chat's next turn to the machine that ran its last one;
  2. start restoring files when the person opens the chat;
  3. don't copy what is already stored.
- **My recommendation:** build none of the first two now. Today all workers share one VM's disk,
  so every turn already finds a warm copy. A cold restore of a typical chat is targeted at under 1
  second, against a model call of 15–25 seconds. Phase 1's live check measures it (WS-20). If it
  misses the target, we add early restore first, then routing. The third point is Q4.

**Q4. CRM reads are copied into the snapshot, not pointed to** [P1]: **decided 2026-10-22 (AW-13).**
- **I said:** CRM reads and large tool results are already stored, so the snapshot can point to
  them.
- **That is only half true.** Large tool results are stored in full (`result_ref`). CRM reads are
  not: only their action, parameters, time and record count are stored. The raw records exist only
  in `reads/`.
- **My recommendation:** the snapshot stores CRM reads as files, and they expire after 48 hours as
  raw inputs (WS-23). A large tool result may instead be rebuilt from its stored copy, at the
  builder's choice (WS-27).

**Q5. What happens to `work/` between turns** [P1]: **decided 2026-10-22 (AW-14): `work/` is kept
for the chat's whole life, like `scratch/`.**
- I had proposed emptying it at every turn start, as the agent's manual describes it ("Nothing is
  persisted from it"). You chose to keep it.
- Everything under `work/` is a work product, except the two compaction folders
  (`work/conversation_history/`, `work/large_tool_results/`), which stay raw inputs under AW-2
  (48 hours, receipts kept).
- The manual's description of `work/` changes in Phase 2 (WS-32).

**Q6. A save that cannot reach storage fails the turn** [P1]: **decided 2026-10-22 (AW-15).**
- **What happens:** the save is retried. If it still fails, the turn fails and the fleet retries
  it. This matches what happens today when `outputs/` cannot be saved.
- **Amended 2026-10-22 (AW-18), after the code survey for the Phase 1 plan:** a failed *save* does
  not re-run the turn. The agent's work is already done and the runtime has marked the turn ended,
  so a re-run would repeat it and pay twice; and today a failed outputs snapshot fails the turn
  without a retry (the line above was wrong). Instead the save is retried 3 times; if it still
  fails, the turn fails and the worker keeps its copy marked unsaved, which the chat's next turn
  saves. A failed *restore*, which happens before the agent starts, does re-run the turn.
- **The alternative:** finish the turn without its files saved. That is faster for the person in
  that moment, but the next turn on another machine would silently miss the files, which is one of
  the §2.3 failures.

**Q7. Erasure timing and the release rule** [P2]
- **The roadmap put erasure in Phase 2.** I kept it there, with the release rule in §3: P1 does
  not reach production without P2.
- **The alternative:** move erasure into P1, so that P1 can ship alone. It would still keep raw
  reads without expiry until P2.

**Q8. Stage-0 trial workspaces stay local only** [—] *(differs from the roadmap's P3)*
- **What they are:** they come from a developer-only command (`stage0-trial`) whose folder lives in
  `/tmp`. They are never part of a customer chat.
- **My recommendation:** leave them out. They keep today's local-only behaviour (WS-12).

**Q9. Some robustness tests move to Phase 1** [P1, P3]: **decided 2026-10-22 (AW-16).**
- **The roadmap put all robustness tests in Phase 3.**
- **Why move some:** Phase 1 claims "any machine can continue any chat", and that claim needs
  proof before it is merged.
- **My recommendation:** Phase 1 includes the two-machine, kill-mid-turn and zombie-save tests
  (§11, tests 1–4). Phase 3 adds the clean-machine restore, research reconciliation and the final
  live measurement.

**Q10. Default values** [P1, P2]
- **Raw-input window: 48 hours.** This is your ruling (AW-2).
- **Decided 2026-10-22 (AW-11):** a cache folder is removed after **30 minutes** idle. I had
  proposed 24 hours once it was clear production runs one chat worker; you kept 30 minutes.
- **Decided 2026-10-22 (AW-17):** each worker area is capped at **10 GiB**; over it, idle chat
  folders are deleted, oldest first.
- **Proposed by me, still open (Phase 2):** the expiry job runs hourly.

**Q11. Should the person ever see or download these files?** [—] *(not discussed)*
- **My recommendation:** keep it out of scope for now. The snapshot makes it easy to add later.

---

## 5. Today (what this changes)

From the code on this branch. File references are for the builder.

| Piece | Today | Reference |
|---|---|---|
| Thread folder | exactly `.deepagent inputs context scratch reads work outputs`; the top level is audited | `platform/agents/clue_agents/workspace.py:105,1808-1846` |
| Recipe folders | `.deepagent/ inputs/ context/` are emptied and written again every turn, even when nothing changed, then frozen read-only; brand, project and attachments are shared libraries, written only when their content hash changes | `workspace.py:1021-1037`, `resources.py:251-330`, `agent_turn_fleet_wiring.py:657-798` |
| Agent folders | left on disk between turns; `outputs/` saved to artifacts and, since `f799a9830`, kept | `workspace.py:1209-1262` |
| Lease | `AgentWorkspaceFactory.acquire/create/release`; an in-memory `_active` map per factory; `flock` on the root and the thread | `workspace.py:1434-1806,1482-1491,515-524` |
| One turn per chat | enforced in Postgres: an advisory lock plus one queued or claimed task; the fleet `work_lease` per chat has a generation that goes up on every takeover | `agent_turn_submission.py:693-794`, `platform/fleet/clue_fleet/lease.py` |
| Profile per turn | each turn starts a new execution of the currently promoted conversation recipe and profile | `agent_turn_fleet_wiring.py:~800-840` |
| CRM reads registry | `CrmReadSinks`: a per-process map from a turn to its `reads/` folder, filled while the turn holds the lease | `platform/api/clue_api/crm/read_sinks.py`, `fleet_main.py:1120` |
| Cleanup | an hourly job deletes a thread folder 24 h after its newest turn ended; it skips `awaiting_input`; its receipt id collides on a second purge | `platform/api/clue_api/agent_cleanup.py` |
| Artifact store | files stored in R2 under `ws/sha256` with an `artifact` row; owners hold references (`retain_artifact`/`release_artifacts`); a sweep deletes the files of rows already marked erased or expired, and stored files with no `artifact` row. **It does not delete a live row that nothing references any more** (corrected 2026-10-22; `storage_wiring.py:212`, `artifacts.py:459`) | `libs/clue-storage/clue_storage/artifacts.py` |
| The precedent | design site turns: a version record `(workspace, document) → (version, manifest_sha256)`, a compare-and-set update, a local version note, restore when stale | `clue_design/sessions.py:122-157`, `lumen_api/main.py:12093-12340`, `lumen_agent/session_sync.py` |

What lands in the agent folders today:
- `reads/<plan-op>.json`: oversized tool results. The full result is also stored as the
  `result_ref` artifact (`agent_execution_wiring.py:1910-1992`), so this file can be rebuilt.
- `reads/<exec-op>.json`: CRM reads, always written. **The raw records are stored nowhere else.**
  The action, parameters, time and record count are (a parameter snapshot plus `agent_tool_result`).
- `reads/<op>.stdout.txt|.stderr.txt`: `run_python` output over 16 KB, written outside the quota.
- `work/conversation_history/<execution>.md` (plus `media/`): compaction offloads. The history
  itself stays in the checkpoint, so these can be rebuilt. `work/large_tool_results/<id>`: the
  summariser's overflow clips.
- `scratch/`, `outputs/` and other `work/` files: written by the agent and its sandbox runs,
  including binary files (`.csv .xlsx .docx .pptx .pdf .png`).

---

## 6. The design in one picture

```
            ┌──────────── Postgres ─────────────┐        ┌──────── R2 (artifact store) ─────────┐
            │ version record per chat:          │        │ file list   ws/<sha>  (JSON)         │
 turn start │  (workspace, thread) → version,   │──────▶ │ stored files ws/<sha> (by content)   │
 ──────────▶│  file list hash, last activity    │        └──────────────────────────────────────┘
            │ fleet work_lease (generation)     │                     ▲  turn end: store changed
            └───────────────────────────────────┘                     │  files, then the file list,
                    │ same version as the local note?                  │  then move the version
                    ▼ yes: use the cache   no: empty and restore       │  record (only if current)
            ┌──────────── this worker's own area of the disk (cache) ──────────────────┐
            │ thread folder: recipe folders (only changed files written, WS-36)        │
            │               agent folders  (= snapshot version N; local note kept aside)│
            │ removed when idle; removed when its chat is erased; never the only copy  │
            └───────────────────────────────────────────────────────────────────────────┘
```

**A turn, start to end:**
1. The fleet gives the turn to a worker. Postgres already guarantees one turn per chat.
2. The worker updates the recipe folders from pins, writing only the files that changed (WS-36).
3. It reads the chat's version record. If its local copy holds that version, it uses it.
   Otherwise it empties the agent folders and restores the snapshot from R2.
4. The agent works. Its files are ordinary local files, so `run_python` and CRM reads work
   unchanged.
5. At the end, the worker stores the files that changed, then the new file list, then moves the
   version record. It moves it only if the version is still the one it restored and it still holds
   the lease.
6. Later, when the chat has been idle for a while, the worker deletes its whole folder. The
   snapshot in R2 is the real copy. A worker that restarts wipes its whole area.

---

## 7. Phase 1 requirements: the core [P1]

### 7.1 The snapshot: what is stored

- **WS-1 [P1] Version record.** A new table (name is the builder's call; `agent_workspace_snapshot`
  below) holds one row per chat folder:
  - columns: `workspace_id`, `thread_id`, `project_id`, `version` (integer ≥ 1),
    `manifest_artifact_key`, `manifest_sha256`, `last_activity_at`, `updated_at`;
  - primary key `(workspace_id, thread_id)`;
  - a hand-written, reversible Alembic migration with named constraints, per the repo conventions.
- **WS-2 [P1] File list.** Each version is one JSON file list, stored as an artifact with its own
  media type (e.g. `application/vnd.clue.agent-workspace-manifest+json`).
  - **Each entry:** the file's path, `sha256`, size, media type, tier (WS-23), and `written_at`
    (when this content first appeared in the workspace).
  - **Fields Phase 2 fills:** an entry's receipt (WS-25) and its `expired_at` (WS-26). The file list
    also keeps the receipts of expired raw inputs, so they last as long as the chat.
  - **`schema_version`** is present from the first version. Phase 2 adds fields without breaking
    Phase 1 file lists.
- **WS-3 [P1] Stored files.**
  - Each file's bytes are stored once, under their content hash, in the workspace's namespace of the
    existing artifact store (`DurableAgentArtifactStore` / `clue_storage`).
  - A file whose hash is already stored is not uploaded again.
  - Binary files are supported.
- **WS-4 [P1] Folders that are saved.**

  | Folder | Saved? | Tier (applied in P2) |
  |---|---|---|
  | `scratch/` | everything | working file (AW-22) |
  | `outputs/` | everything; never emptied again | work product |
  | `reads/` | everything | raw input |
  | `work/conversation_history/` (with `media/`), `work/large_tool_results/` | everything | raw input |
  | everything else under `work/` | everything; never emptied (AW-14, Q5) | working file (AW-22) |
  | recipe folders and mounts | never; they come from database pins (WS-36) | — |

- **WS-5 [P1] Tier recorded from the start.** Phase 1 writes each entry's tier into the file list,
  even though nothing expires until Phase 2. This way Phase 2 needs no migration of file lists.

### 7.2 Turn start: getting the right files onto this machine

- **WS-6 [P1] Restore.** Before the agent or any tool touches the agent folders, and before
  `run_python` registers its mounts (`conversation_turns.py:464`), the workspace layer does the
  following:
  1. Read the version record. This is one indexed read.
  2. Compare its `(version, manifest_sha256)` with the local version note.
  3. **If they match:** use the local copy as it is. Nothing is downloaded.
  4. **If they differ, or there is no note:** bring the local copy up to date, without wiping it:
     - download the file list;
     - keep every local file whose sha256 already matches its entry;
     - download the entries that are missing or different, in parallel, with bounded concurrency;
     - delete local files that are not in the file list;
     - check each downloaded file's sha256, and stop loudly on a mismatch;
     - write each file with the workspace's normal ownership and modes (owner uid, 0600 for files,
       0700 for folders, no links);
     - write the local note last.
  5. **If there is no version record:**
     - a new chat starts empty;
     - a chat from before this change takes its agent folders from its old folder outside the
       worker areas, if that folder is on this machine, and its first save becomes version 1
       (WS-22).
  6. Nothing in the agent folders is emptied at turn start; `work/` is kept like `scratch/` (AW-14).
- **WS-36 [P1] Recipe folders: write only what changed, never empty and rebuild.** (Founder,
  2026-10-22. Numbered last so the other ids stay stable.) Today `.deepagent/ inputs/ context/` are
  emptied and written again at every turn start (`workspace.py:1026` `reset_materialized_trees`),
  even when nothing changed. From Phase 1:
  - **A file that is new, or whose content differs from this turn's pin:** write it.
  - **A file identical to this turn's pin:** leave it alone.
  - **A file this turn's pins no longer include:** delete that one file.

  What this means for each folder:

  | Folder | What it holds | When it is written |
  |---|---|---|
  | `.deepagent/` | the agent's manual, skills and profile | only when a deployment changes them (a new profile or skill version) |
  | `context/` | the project card, budget, library and brand indexes | only the files whose values changed, e.g. the budget after spending, the library index after a publish |
  | `inputs/` | this turn's inputs, e.g. `user-message.txt` | the new turn's input files; an earlier turn's input file is removed (the conversation keeps every message) |

  These files describe the current state, so a changed file is **replaced**, never appended to
  (two budgets in one file would be invalid JSON and contradictory). The files stay read-only to the
  agent, as today. Comparing by content hash is the same check the brand and project libraries
  already use (`brand_library.py:159`, `project_library.py:564`). Tested: a second turn with no
  changes writes nothing in these folders except its new input file.
- **WS-7 [P1] Local version note.** The note lives outside the agent-visible thread folder, for
  example in a sibling cache-state folder under the root. The top-level audit refuses unknown entries
  in the thread folder, and the agent must not be able to read or forge the note. The exact place is
  the builder's call.

### 7.3 Turn end: saving

- **WS-8 [P1] Save.** At the end of every turn that ran (completed, awaiting input, failed after the
  agent wrote files, or stopped), the workspace layer does the following:
  1. Walk the saved folders (WS-4).
  2. Store the files that are not stored yet, in parallel, with bounded concurrency.
  3. Build the file list and store it. `written_at` carries forward for unchanged content.
  4. Move the version record with a compare-and-set:
     - `version = version + 1 WHERE version = <the version this turn restored>`;
     - an insert for version 1;
     - only while this worker still holds the chat's fleet `work_lease` generation
       (`hold_work_lease`, as design saves do).

     The turn runner must be given `WorkContext.lease_generation`, which it is not today.
  5. Write the local note.

  **The version record moves only after every file and the file list are stored.** A version record
  therefore never names missing bytes.
- **WS-9 [P1] Save inside finalize.**
  - **For a turn that finalizes:** the save happens inside the finalization step, after the
    `outputs/` artifact snapshot and before the finalization commit
    (`agent_runtime_wiring.py:829-903`). A finalized turn always has its files saved.
  - **When storage fails:** transient errors are retried 3 times. If the save still fails,
    finalization fails and the turn fails; the worker keeps its local copy marked unsaved, and the
    chat's next turn on that worker saves it (AW-18, amending AW-15). The turn is not re-run.
  - **For a turn that ends without finalizing:** it saves on a best-effort basis when the lease is
    released.
- **WS-10 [P1] A save that loses the race.** This happens when the compare-and-set finds a newer
  version (a takeover already saved) or the lease generation has gone.
  - nothing is written;
  - the event is logged loudly with both versions;
  - the local note is removed, so the next turn on this machine restores the winning version.

  Under the one-turn-per-chat rule this should never happen. It exists so a zombie worker cannot
  overwrite a newer version.
- **WS-11 [P1] Retries and crashes.**
  - A re-claimed turn restores again. If its earlier attempt saved, it sees that version; if not,
    the previous one.
  - If a turn crashes between the save and the finalization commit, the retry starts from the newer
    version and saves again against it.
  - Saving identical content twice is harmless.

### 7.4 One hook for every agent

- **WS-12 [P1] Restore and save live in the shared workspace layer.** They sit in the factory or
  lease, not in each caller, so every agent gets them:
  - chats;
  - research runs;
  - delegated sub-agents;
  - account-research turns;
  - onboarding synthesis.

  A factory built without a snapshot store keeps today's local-only behaviour. This applies to unit
  tests and the developer Stage-0 trial command (**Q8**). Production composition roots always give
  it one.
- **WS-13 [P1] Safety rests on Postgres only** (founder, Q2, AW-10). Correctness across machines
  rests on three things only:
  - one turn per chat (Postgres);
  - the fleet lease generation;
  - the version record's compare-and-set.

  Inside one worker, its own area is used only by that worker's process, so a worker knows from
  its own running turns which chat folders are in use. `flock` and the in-memory `_active` map may
  stay as guards inside one process. Nothing may rely on them for safety across workers or
  machines.
- **WS-14 [P1] Per-turn registries come from the same hook** (AW-8.2).
  - The CRM reads registry (`CrmReadSinks`) and the sandbox registry (`SandboxWorkspaces`) map a
    running turn to its folder inside one process. That is correct across machines, because a turn
    runs in one process.
  - F3 folds their register and release into the same workspace hook (WS-12), so no caller binds
    folders on its own.
  - No new registry of this kind is added.

### 7.5 The cache: each worker's own area, thrown away whole (AW-9)

- **WS-15 [P1] Each worker owns its own area of the disk.**
  - Every chat folder a worker uses lives inside that worker's area:
    `<root>/<worker>/<ws>/projects/<p>/threads/<t>/`.
  - No other worker, and no other process, reads or writes inside it. Two workers never share a
    folder, and two chats never share a folder (WS-37).
  - **Areas are claimed, not named (AW-19).** A worker takes the first free numbered area,
    `<root>/workers/area-<n>`, by holding an exclusive lock on `area-<n>.lock` for as long as it
    runs, and wipes it before use. The operating system frees the lock when the process dies, so
    a restarted worker claims a free area and wipes it. This needs local disk: locks are not
    reliable on shared network drives.
  - A chat whose next turn lands on another worker is restored there from its snapshot (WS-6).
    That is the cost of this design: a cold restore, targeted at under 1 second for a typical
    chat (WS-19).
- **WS-16 [P1] Cleanup throws away whole folders, never pieces.**
  - **When a worker starts:** it deletes its whole area before taking any work, exactly as AW-1
    says. Nothing in it belongs to anyone else, so no check is needed. The same run clears the
    worker's own temporary leftovers from earlier crashes (e.g. `/tmp/arv2-media-*`) and sandbox
    containers carrying this worker's label.
  - **While it runs:** a periodic job deletes a chat's whole folder, with its local note, when it
    has not been used for `CLUE_AGENT_WORKSPACE_CACHE_IDLE_S` (default 1800), or, oldest first,
    when the area exceeds `CLUE_AGENT_WORKSPACE_CACHE_MAX_BYTES` (default 10 GiB). It skips the
    chats this worker is running a turn for right now, which the worker knows itself.
  - **The note goes first.** The local note is deleted before the files, so a turn that starts
    during the deletion restores instead of trusting a half-deleted folder.
  - **Erased chats:** a cached folder whose chat was erased is never used again, because its local
    note cannot match a missing version record, and the next idle run deletes it.
  - **Areas of workers that no longer exist:** at start-up a worker also deletes every other area
    whose lock it can take, since a free lock proves no live process owns it (AW-19). On
    autoscaling, a removed machine takes its disk with it.
- **WS-17 [P1] The old cleanup is retired.**
  - The 24-hour thread purge (`agent_cleanup.py`) is replaced by WS-15 and WS-16. Its crash bug and
    its `awaiting_input` gap go with it.
  - The shared library folders turns use today (`<root>/<ws>/library/brand/...`,
    `<root>/<ws>/projects/<p>/library/`, `.../attachments/`), their swap leftovers (`.old-*`,
    `.next-*`) and old replay trees (`pinned-*`) are no longer used by turns (WS-37). The old
    layout outside the worker areas is deleted once every chat has moved (WS-22).
  - `CLUE_AGENT_WORKSPACE_RETENTION_S` is retired: removed from settings and `.env.example`, with a
    note in the change log.

- **WS-37 [P1] Each chat has its own copy of the brand and project files.**
  - `brand/`, `project/` and `attachments/` are written into the chat's own folder, from the same
    database pins and content hashes as today, following WS-36: only files that are new or changed
    are written, and a file no longer pinned is deleted.
  - They are no longer mounted from folders shared by every chat of a project. Measured on this
    lane: a brand's files are about 350 KB to 1 MB, a project's about 25 to 50 KB, so a copy per
    chat costs little.
  - Writes the agent makes to project documents still go through the existing versioned writer to
    Postgres, so every other chat sees them on its next turn.
  - `run_python` mounts these folders from the chat's own folder, read-only, as today.

### 7.6 Profile, speed, flag and rollout

- **WS-18 [P1] A resumed chat runs on the current profile** (AW-3).
  - This is already true: each turn runs the currently promoted profile and skills.
  - Restore brings back only the agent folders. It never pins or restores a profile, a skill or any
    recipe folder.
  - Tested: a chat saved under one profile version continues under a newer one, with its files.
- **WS-19 [P1] Speed targets.**
  - **Warm turn** (the local note matches): one indexed database read, no storage calls.
  - **Cold restore, typical chat** (about 10–50 files, under 2 MB): p95 under 1 second.
  - **Cold restore, quota maximum** (400 files / 20 MB): p95 under 5 seconds.
  - **Save:** only changed files are uploaded, in parallel; p95 under 1 second for a typical turn.
  - **Transfer concurrency:** `CLUE_AGENT_WORKSPACE_TRANSFER_CONCURRENCY` (default 16).
  - **First turn of a chat on a worker:** also writes its copy of the brand and project files
    (about 1 MB, local disk), counted in the cold-restore target.
  - Early restore and machine routing are not built now (AW-12); they are future scope (§2.4),
    triggered by these targets and the measurements of WS-20.
- **WS-20 [P1] Speed is measured.**
  - Every restore and save records whether the cache was warm, the files and bytes moved, and how
    long it took. These go in the existing usage record or a sibling.
  - Phase 1's live check reports these numbers on the dushanbe stack.
- **WS-21 [P1] Settings and the flag.** Each setting goes in `libs/clue-config`, `.env.example` and
  the lane `.env` with its default, per the parity rule.

  | Setting | Default | Phase |
  |---|---|---|
  | `CLUE_AGENT_WORKSPACE_SNAPSHOTS_ENABLED` | `true` once merged (built features stay on); the emergency switch | P1 |
  | `CLUE_AGENT_WORKSPACE_CACHE_IDLE_S` | `1800` | P1 |
  | `CLUE_AGENT_WORKSPACE_CACHE_MAX_BYTES` | `10737418240` | P1 |
  | `CLUE_AGENT_WORKSPACE_TRANSFER_CONCURRENCY` | `16` | P1 |
  | `CLUE_AGENT_WORKSPACE_RAW_RETENTION_S` | `172800` | P2 |
  | `CLUE_AGENT_WORKSPACE_WORKING_RETENTION_S` | `2592000` (30 days, AW-22) | P2 |
  | `CLUE_AGENT_WORKSPACE_RETENTION_SWEEP_INTERVAL_S` | `3600` | P2 |

  With snapshots switched off, the system behaves as on `feat/crm-integration`: local folders only.
  The cache removal then uses a 24-hour idle window instead of 30 minutes, because the cache is the
  only copy. The builder must keep this fallback honest or drop it. It exists only as an emergency
  switch.
- **WS-22 [P1] No migration** (AW-5). Existing chats get no backfill.
  - The first turn of an old chat (no version record yet) takes its agent folders from its old
    folder at `<root>/<ws>/projects/<p>/threads/<t>/`, if it is on this machine, into its folder in
    the worker area, and saves them as version 1. The old folder is then deleted.
  - An old chat whose old folder is not on this machine starts with empty agent folders, as it
    would today on another machine.
  - Once Phase 1 has run for longer than the old 24-hour cleanup window, the whole old layout
    outside the worker areas is deleted by one cleanup step (builder's call how).

---

## 8. Phase 2 requirements: retention and honesty [P2]

### 8.1 Tiers, receipts and expiry

- **WS-23 [P2] Tiers** (AW-2).

  | Tier | Folders | Kept for |
  |---|---|---|
  | Outcomes | published documents, designs, research claims | untouched; already durable |
  | Work product | `outputs/` | the chat's lifetime (until the chat is erased; there is no chat retention policy yet) |
  | Working file (AW-22) | `scratch/`, and `work/` apart from its two compaction folders | bytes deleted **30 days after the chat's last activity** (`CLUE_AGENT_WORKSPACE_WORKING_RETENTION_S`, default 2592000); the entry stays, marked expired |
  | Raw input | `reads/`, `work/conversation_history/`, `work/large_tool_results/` | bytes deleted **48 hours after the chat's last activity** (`CLUE_AGENT_WORKSPACE_RAW_RETENTION_S`, default 172800); the receipt stays for the chat's lifetime |

- **WS-24 [P2] Last activity** is the newest of these events:
  - a turn submission;
  - a turn reaching a terminal or awaiting-input state;
  - a save.

  It is kept in `last_activity_at` on the version record (written from Phase 1, used from Phase 2).
- **WS-25 [P2] Receipts.** Every raw input carries a receipt, built at save time from durable rows
  the turn already wrote. A receipt holds:
  - **what produced it:** the tool and operation id. The file name is the operation id: a CRM read
    uses the executor operation id, a spill uses the plan operation id. Both can be looked up
    through `execution_node` / `agent_tool_result`.
  - **for a CRM read:** the provider, the action, a reference to the stored parameters, the record
    count, the total, and whether more pages exist;
  - **when it was produced, and its size and sha256;**
  - **how to read it again, in plain words.** For example "run_crm_action HUBSPOT_SEARCH_DEALS with
    the same parameters", or "rebuilt from this conversation's history" for compaction files.

  A file with no matching durable row still gets a receipt, with source "unknown". It is never
  dropped silently.
- **WS-26 [P2] The expiry job.** A periodic fleet job runs every
  `CLUE_AGENT_WORKSPACE_RETENTION_SWEEP_INTERVAL_S` (default 3600), with one runner at a time like
  the storage sweep. It:
  1. finds chats with raw inputs (48 hours) or working files (30 days, AW-22) past their window and
     no queued or running turn;
  2. writes a new snapshot version without those files' bytes, keeping their receipts, marked with
     `expired_at`, and using the same compare-and-set as a turn's save;
  3. releases its hold on the stored files.

  A chat with a live turn is skipped and retried next cycle.

  **Expiry belongs to a file list entry, never to the artifact row.** The artifact row's expiry
  (`artifact.expires_at`) is per content hash, so a raw read and a draft with identical bytes would
  share it. A row that has been expired and erased can also never be recorded again
  (`record_artifact` refuses it). **Required, and tested:** reading identical bytes again after a raw
  input expired must work.

  **Phase 1 file lists label `scratch/` and `work/` files `work_product`** (Phase 1 has two tiers).
  The expiry job decides a file's window from its path (`tier_for`), not from the stored label, so
  Phase 1 file lists need no migration; Phase 2 adds the `working_file` label for new saves.
- **WS-27 [P2] Large tool results may be rebuilt.** A spill whose full result is already stored
  (`result_ref`) may be restored from that artifact instead of being stored twice (Q4, AW-13). This is
  the builder's call. Either way, the agent sees the same file while it is within its window.

### 8.2 What the agent is told

- **WS-28 [P2] Turn-start file list for the agent.** Each turn's context includes a bounded list of
  the agent's earlier files, built from the version record and file list, not from the disk:
  - for each live file: its path, folder, size, age (from `written_at`) and tier;
  - for each expired raw input: its receipt (what it was, when it was read, how many records, how to
    read it again).

  Where it goes:
  - **chats:** added with the other project-context artifacts
    (`agent_turn_fleet_wiring.py:_compose_project_context`, layer L3, re-sent on continued turns);
  - **research runs:** the research equivalent (`account_research_turn_wiring.py:555-684`).

  A large workspace is summarised by folder beyond a bound, and the list says what was left out. The
  bound is the builder's call; the wording is reviewed by you.

  **How this answers your case (D-23).** The agent did an analysis, the chat sat idle for a week, and
  the CRM reads behind it expired. On the next turn the agent sees:
  - its script and results, still there, with their age;
  - the expired reads, with their receipts.

  It knows the numbers are a week old, the source data is gone, and how to read it again.
- **WS-29 [P2] Staleness instruction** (AW-4). The skills tell the agent:
  - after a gap, check how old its numbers and their source data are before relying on them;
  - decide for itself whether to read again;
  - it does not have to tell the person.

  This is skill text, not a code check. It is presented to you before it is written.

### 8.3 Erasure and storage cleanup

- **WS-30 [P2] Stored files are deleted when nothing points to them.**
  - Snapshots hold their stored files and file lists through the artifact store's reference
    mechanism (`retain_artifact` / `release_artifacts`, or an equivalent owner table).
  - Each version holds the files it names. Replacing a version releases the files only the old
    version used.
  - **Nothing deletes a released file today** (corrected 2026-10-22: the existing purge only
    deletes files whose row is already marked erased or expired, and row-less blobs). So WS-30
    adds the step: after a save or an erasure releases a version's holds, each released file is
    checked under its row lock with `erase_if_unreferenced` (it counts snapshot holds and live
    claims), and one that nothing holds is marked erased; the existing purge then deletes its bytes.
    A file another chat, an upload or a claim still holds is left alone. In scope for Phase 2
    (founder, 2026-10-22).
  - Older versions are kept only as long as the builder needs them for the compare-and-set.
    Builder's call: keep the current version only, or the current one plus one.
- **WS-31 [P2] Chat and project erasure** (narrowed by AW-21). A person's privacy erasure stays as
  it is today (the records kept about the person); it does not search chat files for their details.
  Erasing a chat or a project:
  - deletes the version records and file lists involved, and releases their stored files, which the
    existing purge then deletes (respecting other live references);
  - leaves cached copies on any machine to be removed by WS-16 within one cleanup interval;
  - never lets those cached copies be used in the meantime, because their local note cannot match a
    missing version record.

  The erasure tests prove that no erased content remains in R2 after the purge.
- **WS-31a [P2] A privacy-erased file in a chat is skipped, not fatal** (AW-21; the Phase 1 review's
  I1). Snapshot files share one stored file per content hash in the workspace, so a chat's file can
  be byte-identical to something a person's erasure later removes. Restore skips such a file and
  drops it from the chat's file list; a save never stores those bytes again; the agent's turn-start
  list (WS-28) names the file as erased. Today such a chat fails every turn.

### 8.4 The manual

- **WS-32 [P2] Manual rewrite.** The workspace chapter of the agent's manual is rewritten to say:
  - what each folder keeps, and for how long;
  - that `outputs/` lasts for the chat;
  - that `scratch/` and `work/` are deleted 30 days after the chat's last activity (AW-22), and
    `work/`'s compaction folders expire like `reads/`;
  - that `reads/` expire and leave receipts;
  - where the turn-start file list is.

  Today's chapter is wrong on two points: it says nothing writes to `reads/`, and that `outputs/` is
  emptied. The text is presented to you before it is written.

---

## 9. Phase 3 requirements: remaining workspaces and proof [P3]

- **WS-33 [P3] Research reconciliation reads the snapshot.**
  - The reconciliation step stops copying the source run's `work/ scratch/ reads/` from local disk
    (`quality_research_wiring.py:1084-1111`).
  - It restores the source chat's snapshot, or reads its file list and stored files directly, and
    copies from that.
  - If the source has no snapshot, it says so in its log and in the reconciliation input instead of
    silently copying nothing.
- **WS-34 [P3] Every other caller checked.** Delegated sub-agents, account-research turns and
  onboarding synthesis already get restore and save from Phase 1 (WS-12). Phase 3 checks each one
  end to end, with its own thread id, and fixes any caller that bypasses the shared layer. Short-lived
  threads expire like any other.
- **WS-35 [P3] Proof and rollout.**
  - The full robustness suite (§11) passes.
  - The final live measurement of restore time is recorded.
  - The flag's emergency path (WS-21) is exercised once.
  - Then the feature is rolled out with its flag on.

---

## 10. What a person experiences when things fail

| Situation | What happens |
|---|---|
| R2 unreachable, local copy current | the turn runs normally; starting a turn needs no storage |
| R2 unreachable, local copy stale or missing | the turn fails with a retryable error and the fleet retries it; it never runs on a stale or empty workspace when a snapshot exists |
| R2 unreachable at save | retried 3 times; then the turn fails, the worker keeps its copy marked unsaved, and the chat's next turn saves it (AW-18) |
| Worker dies mid-turn | the turn is picked up again, possibly elsewhere, restores the last saved version and resumes its checkpoint |
| A zombie worker saves late | refused by the lease generation or the compare-and-set; logged |
| Cache deleted by hand or removed as idle | the next turn restores; nothing is lost |
| A worker restarts | it wipes its own area; its chats restore on their next turn, on whichever worker takes it; no other worker is affected |
| Raw input expired [P2] | the file is gone; the turn-start list shows its receipt; the agent reads again if it needs to |
| Disk full during restore | the turn fails retryably; the half-written folder and its note are removed |
| A file list or stored file fails its hash check | the turn fails loudly; mismatched bytes are never restored |

---

## 11. Tests

Per the founder's standing rule, these are scenario tests through the real code paths, plus live
checks.

| # | Test | Phase |
|---|---|---|
| 1 | **Two machines, one chat:** two factories with different cache roots, one database and one storage. A turn on A writes `scratch/`, `outputs/` and a CRM read; the next turn on B sees exactly those files; a third turn back on A notices its copy is stale and restores B's version | P1 |
| 2 | **Warm path:** a second turn on the same root makes no storage calls | P1 |
| 3 | **Kill mid-turn:** a turn dies before the save, and another after it; the retry on another root sees the right version and finalizes once | P1 |
| 4 | **Zombie save** is refused, both for a stale version and for a lost lease generation | P1 |
| 5 | **Raw expiry:** with a 0-second window, the expiry job removes the `reads/` bytes and keeps the receipt; the next turn's list shows it; reading identical bytes again works | P2 |
| 6 | **Work products survive** a cache wipe (P1) and the expiry job (P2) | P1, P2 |
| 7 | **Erasure:** version records, file lists and stored files are gone after the purge; a cached folder on another root is never used and is removed by the next cleanup | P2 |
| 8 | **Cleanup stays in its own area:** a worker's start-up wipe removes its whole area and nothing in another worker's area, even while that worker runs a turn; the idle job removes an idle chat's folder and skips the chats this worker is running | P1 |
| 9 | **Research reconciliation** across two roots reads the source run's snapshot | P3 |
| 10 | **Sandbox after restore:** `run_python` reads and writes restored files (ownership, modes, policy sweep) | P1 |
| 11 | **Migration** up, down and up again, with a single Alembic head | P1 |
| 12 | **Clean-machine restore and final live check:** on the dushanbe stack, a real chat turn; delete the whole cache root; continue the chat; the agent finds its files; warm and cold timings recorded (WS-20) | P1 (first run), P3 (final) |
| 13 | **Recipe folders updated in place:** a second turn on the same root with no changes writes only its new input file; a changed budget replaces only `budget.json`; a removed document's file is deleted; a new skill version rewrites only `.deepagent/` | P1 |
| 14 | **Chats never share a folder:** two chats of one project on one worker each get their own copy of the brand and project files; deleting one chat's folder leaves the other's turn untouched; a project document written in one chat appears in the other's next turn | P1 |

Also tested in their phases: WS-18 (profile on resume, P1), WS-26's re-read of identical bytes (P2),
and WS-28's list contents for live and expired files (P2).

---

## 12. Found while surveying (for the builder)

- **The compaction file path is unverified.** deepagents returns the path it was given, and the
  `HistoryPathBackend` wrapper is not a composite backend. The compaction summary may therefore name
  `/conversation_history/<id>.md` while the bytes sit at `work/conversation_history/`, a path the
  agent cannot read. Check live in Phase 1 and fix if real, since WS-4 saves exactly those files.
  **Real; fixed in P1 (2026-10-22):** the summariser now writes the history under
  `/work/conversation_history/` itself, so the path it names is the path the bytes are at. A live
  compaction (a chat past about 450k tokens) is still owed; the manual tool refuses below the
  threshold.
- **`run_python` output spills** (`reads/<op>.stdout.txt`) are written with a raw `os.open`, outside
  the quota. A spilled run's result is then spilled a second time as `reads/<plan-op>.json` (16 KB
  inline is over the 12 KB receipt threshold). In Phase 1, bring the first under the quota. The
  double spill is harmless but wasteful. **Done in P1:** spills go through the workspace backend's
  quota-checked write; the double spill remains.
- **There are several workspace factories per process:** chat, the library refresher, and one per
  research job. Their in-memory guards do not see each other. Under WS-15 they must all use the
  worker's own area, and the idle job must ask the worker which turns it is running, not any one
  factory's `_active` map.
- **Other processes that write under the root (settled, AW-20).** The project library refresher
  (`project_library_refresh.py`) rebuilt a shared project library tree on disk; only turns read it,
  and turns now keep their own copies (WS-37). The refresher stops writing to disk, and the API
  process stops building a workspace factory. A privacy erasure that changes a library file without
  moving its digest bumps a new `project_library_epoch` row instead, which the digest includes, so
  every chat's copy resyncs on its next turn.
- **Production layout.** `/srv/clue/workspaces` stays one bind mount into the containers
  (`deploy/vm/compose.yaml`); the worker areas are folders inside it. The `run_python` sandbox's
  host paths change with the folder layout.
- **Dead lifecycle code:** `authorize_cleanup` and `cleanup_authorized` gate nothing, and `cleanup`,
  `purge_terminal` and `discard_failed_materialization` have no callers. Remove or reuse them while
  rewriting this layer (Phase 1).
- **Quotas are unchanged.** The profile quotas (20 MiB, 400 files, 4 MiB per file) still bound the
  workspace, and so they also bound the snapshot.
- **Other lanes (AW-8).** The CRM lane keeps working on `feat/crm-integration`. This branch merges it
  in periodically, and either lane messages the other when it changes something the other relies on.
  F3 must not ask the CRM lane to wait.

---

## 13. Left to the builder

- table and column names;
- where the local note lives;
- the file list's exact shape beyond the fields above;
- whether large tool results are stored or rebuilt from `result_ref` (WS-27);
- how many old versions to keep (WS-30);
- the bound on the agent's file list (its wording is reviewed by the founder);
- how the old layout is removed after Phase 1 (WS-22);
- how the cleanup and expiry jobs are scheduled within the fleet;
- how the lease generation reaches the turn runner;
- whether restore and save live in the factory, the lease or a small helper object, as long as every
  caller gets them (WS-12).

---

## 14. Change log

- 2026-10-21: first draft (Claude), from rulings AW-1–AW-8 and the footprint findings. WS-1–WS-32
  in topic order; open questions Q1–Q4.
- 2026-10-22: v2 (Claude), after the founder asked which phase each part belongs to.
  - **Added:** §0 (how to read); §2, a table tracing every discussed requirement (D-1–D-33) to its
    requirements and phase; §3, the phases, with what each delivers and when it is done; §4, one
    list of decisions (Q1–Q11), naming every place the spec differs from the discussion or the
    roadmap.
  - **Reorganised:** requirements are grouped by phase and **renumbered WS-1–WS-35 in phase order**.
    No plan cited the old numbers.
  - **New requirements:**
    - WS-5: the tier is recorded from Phase 1;
    - WS-14: `CrmReadSinks`, per AW-8.2;
    - WS-18: profile on resume, per AW-3 (it was missing);
    - WS-34 and WS-35: checks and rollout.
  - **Plain words used:** version record, file list, stored file, local version note.
  - **Release rule added:** P1 does not reach production without P2.
- 2026-10-22: WS-36 added (founder): recipe folders are updated only where something changed, never
  emptied and rebuilt every turn. WS-6 now brings a stale local copy up to date (keeps matching
  files, downloads the rest, deletes extras) instead of emptying it. D-34 and test 13 added.
- 2026-10-22: Q1 decided (founder, AW-9), after research into ChatGPT, Claude.ai, Manus, Perplexity
  Projects, Cursor and Claude Code / Codex cloud. Each worker owns its own disk area (WS-15); cleanup
  throws away whole folders and a worker wipes its whole area at start-up (WS-16); each chat has its
  own copy of the brand and project files instead of shared folders (WS-37, new). WS-6, WS-13,
  WS-17, WS-19 and WS-22 updated to match; D-35, test 14 and the §10 restart row added; test 8
  rewritten.
- 2026-10-22: Q2 decided (AW-10): reuse the fleet `work_lease`, no new lease. Q10 partly decided
  (AW-11): cache idle window 30 minutes.
- 2026-10-22: Q3 decided (AW-12): routing and early restore not built now; added §2.4 Future scope
  (F-1 routing, F-2 early restore, F-3 design follow-up spec) with their triggers.
- 2026-10-22: Q4 decided (AW-13): CRM reads are stored in the snapshot as raw inputs; large tool
  results may point to their existing `result_ref` copy (builder's call).
- 2026-10-22: Q5 decided (AW-14): `work/` is kept for the chat's whole life as a work product,
  apart from its two compaction folders (raw inputs). WS-4, WS-6, WS-23 and WS-32 updated.
- 2026-10-22: Q6 decided (AW-15): a save that still fails after retries fails the turn, and the
  fleet retries it. Q1–Q6 are now decided.
- 2026-10-22: Q9 decided (AW-16): Phase 1 carries tests 1–4, 8, 13, 14 and a first live check;
  Phase 3 keeps the clean-machine restore, research reconciliation and the final live timing.
  Q10's cache cap decided (AW-17): 10 GiB per worker area.
- 2026-10-22: founder confirmed the Phase 1 plan's decisions: AW-18 (a failed save does not
  re-run the turn; amends AW-15), AW-19 (worker areas claimed by lock), AW-20 (project library
  epoch; no shared library on disk). WS-9, WS-15, WS-16, §10 and §12 updated.
- 2026-10-22: corrections. WS-30 and §5's artifact-store row wrongly said the existing purge
  deletes files nothing references; it does not, so WS-30 now adds that step (kept in Phase 2,
  founder). WS-32 updated for AW-22.
- 2026-10-22: AW-23 (founder): P1 may ship without P2 (Q7 decided); the CRM branch merged into
  this one (`7d83e34af`); two pull requests, CRM first.
- 2026-10-22: AW-22 (founder): `scratch/` and `work/` are deleted 30 days after the chat's last
  activity; `outputs/` stays for the chat's life. D-18 changed; WS-4, WS-23, WS-26 and the flag
  table updated. Compared with ChatGPT, Claude.ai and Manus first.
- 2026-10-22: AW-21 (founder): privacy erasure covers the records about a person, not mentions in
  chat files. D-24 decided; WS-31 narrowed to chat and project erasure; WS-31a added (an erased
  file is skipped, not fatal — the review's I1). Snapshot storage stays shared per content hash.
- 2026-10-22: Phase 1 built (plan `docs/superpowers/plans/2026-10-22-agent-workspace-phase-1-core.md`,
  Tasks 1–12) and the first live check passed on the dushanbe stack: a new chat saved version 1
  (2 files, 89 bytes, 937 ms); after every worker area was wiped, the follow-up restored on another
  worker cold (2 files downloaded, 699 ms) and the agent quoted both files exactly; a turn on a
  worker holding the current copy restored warm (2 ms, nothing downloaded) and wrote only
  `inputs/user-message.txt` among the recipe folders. Seven turns cost about $1.39. §12's
  compaction path was real and is fixed; a live compaction is still owed.
