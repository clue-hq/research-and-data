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
