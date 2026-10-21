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
