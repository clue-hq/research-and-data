# 2026-10-22 — Agent workspace F3: spec settled for Phase 1

Lane: dushanbe, branch `feat/agent-workspace-durability` (stacked on `feat/crm-integration`).
Docs: `docs/superpowers/specs/agent-workspace/` — spec `2026-10-21-agent-workspace-durability-design.md`
(draft v2), `rulings.md` (AW-1–AW-17), footprint findings.

## State
- Spec reorganised by phase (P1 core, P2 retention and honesty, P3 remaining workspaces and proof),
  WS-1–WS-37; §2 traces every discussed requirement (D-1–D-35); §2.4 future scope (F-1 routing,
  F-2 early restore, F-3 design follow-up spec); §4 decisions.
- Decided today (founder): AW-9 each worker owns its own disk area, each chat its own folder with its
  own brand/project copy, start-up wipes the whole area; AW-10 reuse fleet `work_lease`; AW-11 cache
  idle 30 min; AW-12 routing / early restore are future scope; AW-13 CRM reads stored in the
  snapshot as raw inputs; AW-14 `work/` kept for the chat's life (compaction folders stay raw);
  AW-15 unsaved turn fails and is retried; AW-16 Phase 1 carries its robustness tests; AW-17 10 GiB
  area cap. AW-1 wording amended: recipe folders are written only where changed (WS-36).
- Still open, deliberately later (founder): Q7 release rule, Q8 Stage-0 trial folders, Q11
  downloads, Q10's expiry-job timing.

## Next
- Founder's final read and approval of the spec, then the Phase 1 plan (superpowers:writing-plans).
- Builder check owed in Phase 1: who reads the shared project-library tree that
  `project_library_refresh.py` maintains (spec §12).

## Lessons
- The founder found a single spec covering several phases confusing when nothing in it said so.
  State the phase of every requirement and list every difference from what was discussed.
- "Rebuilt every turn" described blunt current code, not a design need; check wording against the
  code before it becomes a ruling.

## Closing note — Phase 1 built and live-checked (2026-10-22)
- Plan `docs/superpowers/plans/2026-10-22-agent-workspace-phase-1-core.md` Tasks 1–12 done on
  `feat/agent-workspace-durability`; ledger with every ruling in
  `.superpowers/sdd/2026-10-22-agent-workspace-phase-1-core/progress.md` (deleted after review).
- T10: cache sweep replaced the 24-hour purge; `CLUE_AGENT_CLEANUP_INTERVAL_S` retired;
  `CLUE_AGENT_WORKSPACE_RETENTION_S` kept only because the agent manual still quotes it — its
  sentence ("purged ... after the thread's newest turn") is now false and needs a founder-reviewed
  rewrite (Phase 2's manual rewrite).
- T11: nine scenario proofs pass (`tests/api/test_agent_workspace_scenarios_db.py`).
- T12 live check on the dushanbe stack (DB `clue_nashville_pm_clone` migrated in place to
  `cd9c1e49f6af`; dev login `aryan+clerk_test_design@…` linked to the arv2 user by a hand-inserted
  `auth_identity` row `aid_dushanbe_design_dev_login`): new chat `thr_b32c99d4…` in Conduit AI →
  v1 saved (2 files, 89 B, 937 ms); all areas wiped → cold restore on another worker (699 ms, agent
  quoted both files); later cold restores 352–420 ms (no routing, AW-12: each of the 4 workers
  restored once); warm restore 2 ms with only `inputs/user-message.txt` rewritten. 7 turns ≈ $1.39.
- Spec §12 compaction path was real: the summary named `/conversation_history/<id>.md` while the
  bytes went to `/work/...`. Fixed (`d2ec168d1`); a live compaction (~450k-token chat) is owed.
- Oddity for the review: a brand-new chat's restore logs `warm=True` with `version=None`.

## Live robustness tests A–G on the dushanbe stack (2026-10-22, after review fixes c2882e757)
Chats: Conduit `thr_65d4c3d4…` (new, legacy-planted) and `thr_b32c99d4…`. Total ≈ $2.94 (12 turns).
- A legacy import: old-layout folder planted for a new chat → restore `imported_legacy=true`, v1 saved, old folder deleted, agent quoted both files. (Every real legacy chat has an open ad design leg, so none was usable.)
- E sandbox after cold restore: run_python read restored files, wrote outputs/atrium-summary.csv (v2); a third worker restored it cold and the agent quoted it.
- F two chats: project doc written in chat A reached chat B; separate inodes per chat.
- G concurrent turns, same file name in two chats on one worker: each chat kept its own bytes; manifests match.
- C idle sweep (idle 120 s / sweep 30 s temporarily): swept 135 s after last use (688 KB), next turn restored cold.
- B freeze (SIGSTOP) mid-run_python: the frozen worker's late save was refused `fenced`, record untouched. BUT the takeover failed: `ExecutionConflict` because `pin_manifest_hash` differs per process — `proposal_policy`/`ingestion_policy` contain frozensets and `canonical_payload_digest` dumps them in PYTHONHASHSEED order (reproduced: 3 seeds → 3 digests). PRE-EXISTING (platform/execution untouched by F3); any chat-turn takeover across processes fails permanently. The failed turn also shows the person no error. Fix awaiting founder go.
- D live compaction (CLUE_AGENT_CONTEXT_WINDOW_TOKENS=120000 temporarily): history written to agent/work/conversation_history/<id>.md (511 KB), saved; after wiping every area the agent named /work/conversation_history/<id>.md from its summary and quoted the file.
.env restored to its original values after C and D; workers restarted.

## Takeover fix and test B re-run (2026-10-22, commits ad14c9790 + bddd32771)
- Fix: canonical_payload_digest sorts a set's items (ad14c9790), and the static pin catalog
  hashes the policy model itself instead of its JSON (bddd32771) — the first commit alone did not
  fix the live path, which the re-run showed. Both have cross-process tests (six PYTHONHASHSEEDs).
- Re-run 1 (freeze during run_python): the replay conflict is gone (pins now 2bf881218052 /
  6dc96e43a2f1 in every process), but the engine then abandoned the frozen worker's in-flight
  run_python node (`worker_recovery`) and failed the execution (`node_dispatch_made_no_progress`):
  a turn whose agent is mid tool call is not resumed — execution-engine design, not F3.
- Re-run 2 (freeze right after restore, before any tool call): the takeover worker restored and
  then waited on an advisory lock held by the FROZEN process's open transaction (SIGSTOP keeps the
  connection); after `kill -9` (a real crash) the lock dropped and the takeover finished the turn,
  saved v4 and the person saw the answer. Every unfrozen zombie's save was refused `fenced` (3/3).
  Restarting workers wiped every area (incl. the crashed one's); no sandbox containers left.
- Open (pre-existing, not F3): mid-tool-call turns are not resumed after a crash; a hung (not dead)
  worker holds DB locks until it dies or resumes; a failed turn shows the person no error.
- Pre-existing test failures seen (unchanged by the fix): test_recipes.py::test_latest_recipe0_…
  (test DB recipe rows) and six in tests/stage0/test_phase_c5_recipe0.py (ValidationError in
  confirm_project_product).

## Failed turns now end visibly (2026-10-22, commit 0f44c610a)
- The handler's failure branch writes `turn.failed` (no code → the chat's existing "Response
  failed") via `end_unended_turn_as_failed`, only after its own finish was accepted and only if the
  turn has no ending yet. Typed reasons wait for the person-facing error registry (founder will
  scope it separately).
- Live check: worker frozen mid-run_python → takeover gave up (engine rule) → owner wrote one
  `turn.failed` → chat shows "Response failed" after reload; the unfrozen stale worker was fenced
  and wrote no second ending; snapshot stayed at v4.

## 2026-10-22 (late): founder rulings AW-21–AW-23, CRM branch merged in

- **AW-21:** privacy erasure covers the records about a person, not mentions in chat files; snapshot
  storage stays shared per content hash; WS-31 narrowed; WS-31a (P2) = a privacy-erased file in a
  chat is skipped, not fatal (review I1). Checked in code first: one `artifact` row per
  `<ws>/<sha256>`; privacy erasure (4 sites) ignores holders and is permanent (`record_artifact`
  refuses); ordinary erasure counts snapshot holds.
- **AW-22:** `scratch/` and `work/` deleted 30 days after last activity; `outputs/` for the chat's
  life; raw inputs 48 h. Compared with ChatGPT / Claude.ai / Manus first. Phase 1 lists label
  scratch/work `work_product`; the P2 expiry job decides by path (`tier_for`).
- **AW-23:** Phase 1 may ship without Phase 2 (no customers). Note: in P1 nothing in a snapshot is
  deleted, and released old-version files are never deleted (the storage sweep only purges
  erased/expired rows and row-less blobs).
- **Merge:** `feat/crm-integration` (CRM Phase 2 writes, 44 commits) merged into this branch,
  `7d83e34af`. One conflict in `ProjectConversationTurnRunner.run` (hold_chat wrapper vs R-11.6
  card answers) — kept ours, re-applied CRM's two additions; `git diff -w HEAD` = CRM's diff only.
  Migration merge `01baa2e73e84` (F3 `cd9c1e49f6af` + CRM `f09f9e286be6`). Test DB and stack DB
  migrated to it. Two PRs planned: CRM first, then F3 (no push yet).
- **Tests:** 608 pass across the CRM + workspace suites on `clue_dushanbe_test`. Running files from
  several folders at once gives 31 setup errors (`require_profiling_db` lives in
  `tests/profiling/conftest.py`); those three files pass alone.
- **Live check (merged code):** new chat thr_efd66ef7… wrote outputs/merge-check.csv and
  scratch/merge-note.md (v1); chat folder deleted from every area; follow-up restored cold on
  another worker (2 files, 34 B, 789 ms) and the agent quoted both exactly; save `unchanged`.
  Two turns, about $0.40 (estimate). **Owed:** a CRM read through a cold restore — the dushanbe
  `.env` has no Composio keys, so CRM is off on this stack (`crm_write.handler_not_composed`).
- `.env`: added the three `CLUE_CRM_WRITE_*` keys. Pre-existing parity gap: ~40 example keys absent
  from the dushanbe `.env` (Composio/CRM among them).

## Closing note — Phase 2 built and live-checked (2026-10-24)

Branch `feat/agent-workspace-retention` (stacked on `feat/agent-workspace-durability`). Plan and
ledger: `.superpowers/sdd/2026-10-23-agent-workspace-phase-2-retention/`.

**What was built (Tasks 1–9, in commit order):** `aa9465b86` the `<ws>/agent-workspace/<sha>` key
and the three retention settings; `44641a2b2` snapshot files moved into that area and released when
no snapshot holds them; `8bc04d27c` manifest schema 2 (tier, receipt, `expired_at`); `e10246224`
`DbReceiptSource` over the rows the turn already wrote, and a save that rebases over an expiry-only
move; `7b508fb9c` `AgentWorkspaceRetentionJob` — daily, one runner at a time, busy chats skipped;
`952a9f955` `context/project/workspace_files.json` at the start of every turn; `d56292515` spec
tests 5, 6, 7 in `tests/api/test_agent_workspace_scenarios_db.py`; `b986f6fa8` manual v24 +
head-of-abm v78; `a19ddc24b` the two extra founder-approved lines of 2026-10-24 (the files card in
the manual's `context/` table; a non-CRM `reads/` spill gets "Run {tool} again with the same
arguments." instead of the `large_tool_results` sentence). Manual v24 was amended in place, not
re-minted, and the v78 profile's pin was re-digested.

**Live check (2026-10-24, dushanbe stack, $0.24 — 6 grok-4.6 generations over two turns).**
Stack DB `clue_nashville_pm_clone` migrated in place `01baa2e73e84 → 22172f5ba3cb`; API and workers
restarted clean. Turns were driven in-process (a script that calls `persist_user_turn` →
`insert_submission` → `dispatch_next_thread_turn`, exactly the route's sequence) because the stack
runs Clerk auth and there is no browser here. New chat `thr_88c1d61d57…` in project
`prj_f6369d2f…` ("Conduit for hotel groups").
- Turn 1 (37 s): `run_python` wrote `scratch/note.md` (21 B, `working_file`) and
  `outputs/table.csv` (26 B, `work_product`); restore `warm=true version=null`, save `saved` v1,
  2 uploaded.
- Job with the production windows (172800 / 604800) at a clock 8 days past the chat's last
  activity: `RetentionReport(chats_checked=1, chats_expired=1, files_expired=1, skipped_busy=0,
  stale=0)` in 1403 ms; version 2 published; `last_activity_at` correctly put back.
- Proof from the data: `scratch/note.md` is in `expired()` with a receipt, its `artifact` row has
  `erased_at=2026-10-23 22:29:25+00` and its blob is gone from R2 (`ArtifactNotFound`);
  `outputs/table.csv` is still in `live()` and its bytes still read back as `name,value/alpha,1/
  beta,2`.
- Turn 2 (56 s) restored version 2 **cold on a different worker** and the agent answered:
  "scratch/note.md is no longer there. It was written last turn and now shows as expired.
  outputs/table.csv is still present." It listed `context/project/workspace_files.json` among its
  context cards. Save `unchanged`, 0 uploaded.

**Found during the check, none of it Phase 2's own, all unowned:**
1. `agent_turn_submission` is append-only (a trigger), and the job's activity is
   `GREATEST(snapshot stamp, newest submission)`, so a chat cannot be aged by SQL alone — the check
   moved the job's clock forward by the same 8 days instead. Identical arithmetic; worth knowing
   for the next live check.
2. `AgentWorkspaceRetentionJob.run_once` has **no per-chat error isolation**: the first chat whose
   manifest blob cannot be read raises out of the whole pass. On this lane that happened at once
   (see 3). In production one damaged chat would stop the sweep for every other chat. A
   `try/except` per chat with a counted `failed` in `RetentionReport` is the obvious fix.
3. This lane's shared R2 bucket has lost blobs that its DB still references — the Phase 1 live
   check's own project document `notes/f3-shared-document-check.md` (so every turn in project
   `prj_d29bc5f5…` now fails `ArtifactIntegrityError` in the project-library compile) and at least
   one older chat's snapshot manifest. A sibling lane's orphan sweep is the likely cause; dushanbe's
   own is off. Environment damage, not code.

**Deferred / owed:** WS-27 (rebuilding a large tool result from its existing `result_ref` instead of
storing it again) was the builder's call and is not done — a large tool result is stored like any
other raw input. Phase 3 still owns tests 9 and 12 (research reconciliation; the final clean-machine
timing). The Phase 1 live compaction walk is still owed. The two findings above are unassigned.

## Final review fix wave (2026-10-24)

The fresh whole-branch review returned 0 Critical, 8 Important, 11 Minor, "merge with fixes". All
eight Important plus two must-fix minors are fixed on `feat/agent-workspace-retention`
(`4eae81b7b`..`7ed948ac1`); each has a test that was watched to fail first. Full write-up:
`.superpowers/sdd/2026-10-23-agent-workspace-phase-2-retention/fix-wave-report.md` (gitignored).

What changed that a later lane should know:

- **The expiry decides on one read.** `_expire` reads the chat's activity and version together
  and compare-and-sets the save on that version; the candidate scan now hands on only *which*
  chat (`_Chat` no longer carries version or activity). Before, due-ness came from the scan and
  the CAS from a re-read, so a turn finishing in between had its brand-new `reads/`/`scratch/`
  files expired and erased. The busy-chat skip is a courtesy, not the guarantee.
- **`WorkspaceSnapshotStore.save` takes `activity: bool = True`.** The job passes `False` and the
  stamp is simply not moved; the "put the old value back afterwards" statement is gone (it
  reverted a `touch()` landing in the window — worst for research runs and delegations, which
  have no submissions and which `_BUSY` cannot see).
- **`RetentionReport.failed`** and per-chat isolation: one unreadable chat (finding 2 above, hit
  in anger on this lane) is logged as `agent_workspace.retention.chat_failed` and stepped over.
  The candidate scan is paged with a keyset resume (`page_size`, default 500). The runbook says
  what to alert on.
- **`purge_erased_artifacts(..., sweep_expired=False)`** for the per-key caller: the store's save
  no longer runs the sweep's table-wide `expires_at` tombstone on every turn. Nothing changes for
  the fleet sweep or the DSAR callers.
- **The receipt lookup joins `execution`** so it is workspace-scoped (the operation id comes from
  a file name the agent writes), and `execution_node (operation_id)` is indexed
  (migration `3f0b61c7a2d4`, single head).
- **The card's expired list is bounded** at 200, newest first, with `omitted_expired` by folder.
- The research path's card is now proven by driving `run`, not by `inspect.getsource`; the card's
  founder-approved `note` is asserted verbatim in two suites.

Still unowned after this wave: an index on `artifact (expires_at) WHERE purged_at IS NULL` for
the fleet sweep (pre-existing, daily, off the request path); gathering a save's receipts
concurrently; whether very old expired entries should be compacted out of the stored file list
(Phase 3). The nine Minor findings not listed above were left as the review filed them.

### Phase 2 close-out: review, fix wave, and what is left (2026-10-24)

**Review** (fresh reviewer, whole branch `1eeb5a12d..e2f4689e5`): 0 Critical, 8 Important, 11 Minor,
verdict "merge with fixes". The AW-26/AW-21 line was checked and holds: the own storage area is written
by one module, the migration's CHECK makes the key shape unforgeable, both byte-destroying calls are
key-guarded, and `outputs/` cannot expire under any window including 0 (hard-coded, not a setting).

**Fix wave** (13 commits `4eae81b7b..d56c1c48e`, each test-first): all 8 Important + 2 must-fix minors.
The worst was a data-loss race — the job judged due-ness on the candidate scan's stale `last_activity`
while compare-and-setting on a re-read version, so a turn completing mid-pass had its brand-new `reads/`
and `scratch/` files expired and purged. Fixed by reading version+activity in one statement, bailing
`stale` on a mismatch, and judging on the fresh activity. The clock-winding-back finding was fixed by
DELETING the write-back: `save(activity=False)` + `_ADVANCE_QUIET`, so the job's save never stamps
activity at all. **Scoped re-review: 9/9 ADDRESSED, no new Critical/Important, "ready to merge."**

**Residuals, worth picking up (nothing blocks merge):**
- **N2 (do this first):** the `"stale"` outcome has ZERO test coverage — including the new version-mismatch
  guard that closes the data-loss race. The guard is three lines and correct by inspection, but untested.
- Four other per-key `purge_erased_artifacts` callers still run the table-wide `expires_at` UPDATE.
- No index on `artifact (expires_at) WHERE purged_at IS NULL` (another owner's table; daily, off the
  request path — deliberately not added).
- Receipt lookups are sequential, one per new file per save (the `operation_id` index landed; the
  concurrent gather did not).
- `run_retention_if_due` holds its advisory lock and an open transaction for the whole pass.
- A benign `_activity`→`read_manifest` race now counts as `failed`, the metric the runbook says to alert on.
- A save refused `stale`/`fenced` leaves orphan own-area rows nothing references (pre-existing in shape).
- Phase 1 snapshot bytes under the shared `<ws>/<sha>` keys are never reclaimed (AW-26 forbids it); a chat
  moves to the new area only on its next save. 502 kB on the dev stack.
- An agent-written file that expires gets the approved "unknown" receipt sentence ("No record of what made
  this file."), correct by design but reads oddly; a sixth approved sentence would be better.
- **Environment, not this branch:** this lane's shared R2 bucket is missing blobs the DB still references,
  including the Phase 1 live check's project document, so every turn in `prj_d29bc5f5…` fails
  `ArtifactIntegrityError`. The Phase 2 live check ran in `prj_f6369d2f…`.
- **Version claim for the merge:** this branch mints manual **v24**, head-of-abm **v78**, stage0-interview
  **v51**. The CRM lane is at v23/v77/v50 and was NOT messaged (no session addressable); if it mints the
  same numbers the merge has a clash to resolve by hand, as the 2026-09-21 merge did.
