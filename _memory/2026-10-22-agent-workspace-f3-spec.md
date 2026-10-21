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
