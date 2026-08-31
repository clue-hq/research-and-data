# 2026-08-10 — LANE F CLOSE-OUT: the M8D R11 DEEP-phase bridge is DONE (R11.1–R11.5)

Branch `platform/lane-f-r11-bridge`, 14 local commits off hub head `d9bed0d0`. Nothing pushed.
Spec: `docs/specs/M8D-R11-deep-phase-bridge.md` (RATIFIED; §5 frozen ACs; §6 rulings a–f;
§6b mechanical amendment; §7 kickoop). Process: Opus implementers per slice, orchestrator
(Fable) planned/reviewed/debugged every diff + independently re-ran the gates (founder
directive). SDD ledger (gitignored): `.superpowers/sdd/M8D-R11-deep-phase-bridge/progress.md`.

## What landed, by slice

- **F0 docs `405d3d64`, `4537b5d6`** — ratification, R11.5 scope-in, frozen ACs, demarcation
  §2.6 amendment, §6b re-entrant-hold note.
- **F1 (R11.4+R11.1) `2659a2bf`,`b7b9e7b0`,`34d17024`** — `DeepFleetExternalWait` core delta
  (+ dual-shape DEEP validation arm); join-only `EntityResearchDeepPhaseHandler` replacing the
  quarantine handler (state table per spec §4; cost copied from settled `spent_cents`, never
  re-gated); **re-entrant holds**: `REENTRANT_HOLD_KEY` in `durable/project.py` (resume re-runs
  the handler; stock gates byte-identical) + `ReentrantHoldNotSubmittable` (submit_checkpoint
  refuses a hold — closes the approve-a-hold-fakes-DEEP-completion hole found in review).
- **F2 (R11.2) `bb7e8abd`** — `_deep_fleet_due` wake source (terminal/suspended fast path OR
  `next_poll_at` fallback; ACTIVE-at-DEEP anti-spin guard; fail-closed ws+project scoping),
  registered unconditionally; `fleet_main` wake loop now always starts (the old all-flags-off
  short-circuit would have stranded every parked DEEP run).
- **F3 (R11.3) `67a9616d`** — `build_entity_research_account_resolver`: latest fleet run
  (§6c), terminal jobs with outcome ∈ {completed, needs_review} (exhausted/budget_stopped/
  cancelled/failed censused out via metrics), honest AccountSpec fields
  (tier = "entity_research_selection" constant — M8D has no tier axis; contact_profiling_allowed
  =False), typed `EntityResearchRunMissing` in BOTH toggle states. Swapped at run_composition
  (shared instance: VERIFICATION + HANDOFF sweep) and run_verification@1 (+ precondition
  `entity_research_run_missing`, defense in depth). Silent-zero defect closed.
- **F4 (R11.5) `51b80e88`..`b71dd12e`** — `ClaimReferenceSource` chain in
  `contact_eligibility.py`: M8D coverage source (authoritative once the latest fleet run
  published ≥1 coverage row; claim_refs + member scoping post-redirect) → legacy
  references_index fallback. Governance below the source fully shared. Zero caller edits
  (signature unchanged) — handoff reader, C7 committee view, FI-2 read layer, Lane E probe all
  inherit. New controller-free `account_research_coverage.py` (gateway isolation preserved);
  C7 composition query budget 30→31 (one bounded lookup, commented).
- **F5 `4dc90be1`,`84764d95`** — composed e2e acceptance
  (`tests/integration/test_r11_lane_f_acceptance.py`, both toggle states): hold→refuse-submit→
  launch→resume→WAITING_EXTERNAL→suspend→PAUSED→terminal→DEEP COMPLETED (no
  `account_deep_launch` row anywhere) → VERIFICATION (enabled: real selection+judge; disabled:
  `verification_enabled=false`+skip, zero gateway calls) → HANDOFF doorstep (fail-closed, flag
  off) + committee non-empty + no contact launch + replay idempotency + red-proof vs the
  quarantine handler. Plus a real pre-existing fix: `session_factory` threaded into the
  composed VERIFICATION registration (was reaching past injected factories to the process
  default).

## Verification

Per-slice: all targeted suites green on fresh DBs, independently re-run by the orchestrator;
every red proven pre-existing (temp-worktree repro at pre-slice heads / stash repro /
documented dev-.env auth-mode class / shared-DB ordering). Final gates: ruff clean, mypy 630
files clean, import contracts 25/0, single Alembic head `5d7ab295742b` (NO migration in the
lane), R1 quarantine gate untouched and green, acceptance 12/12. Boot smoke with full `.env`:
projections app + fleet composition construct in both toggle states, wake loop starts with all
provider flags off. **No provider spend was made; a paid live canary is deliberately left for
separate founder authorization.**

## Founder-visible flags (decisions/awareness, none blocking)

1. **§6b is realized as re-entrant holds** (spec amended in place). Phase-2 frontend: a DEEP
   hold is a resume-shaped state discriminated by `reentrant_hold` in the checkpoint payload —
   never an approvable gate card (approval attempts get the typed refusal).
2. **`run_verification@1` no longer emits the undeclared `verification_enabled` reference** —
   it was a latent ToolContractViolation on first-ever success (schema `PhaseAccountsOutput`
   never carried it; profiles pin the output schema sha). Surfacing the toggle in the tool
   result requires a governed profile revision — founder call, not made here.
3. **Accepted-outcome gate** for verification selection = {completed, needs_review} (mirrors
   Lane E). One-line change if a different set is ever wanted.

## Cross-lane follow-ups routed to owners (not Lane F edits)

- FI-2: `test_frontend_read_contacts.py` docstring ("committees empty until R11") now stale;
  AC10's fuller form (HTTP contacts endpoint over an M8D fixture) needs membership +
  project-run-context plumbing in FI-2's suite; product-pin fallback-run serving gap unchanged
  (§6f OUT).
- M7/boot: `register_boot_handlers` (REVIEW) still has no conn-factory seam (same class as the
  F5 verification fix).
- B4 test-order fragility (`test_b4_composed_run_db` — sibling suite leaves a committed
  drive_run task): suite-owner cleanup.
- Value narrative: with the bridge landed, `CLUE_VALUE_NARRATIVE_SYNTHESIS_ENABLED` can be
  flipped after merge — committees resolve on real M8D runs now (the E3 refusal path only
  fires on genuinely committee-less accounts).

## Merge notes (for the hub integrator)

No migration → no `alembic merge` expected. The lane touches `run_composition.py`,
`toolbelt_wiring.py` (tool body only — no tool added/removed, counts unchanged),
`contact_eligibility.py`, `external_research_wake.py`, `fleet_main.py`,
`account_research_fleet.py` (read helpers), frozen-core `external_research.py` (+ exports),
`durable/project.py` (+ exports) — watch for conflicts with any parallel lane editing those.
After merge, phase-2 project-run screens may treat DEEP/VERIFICATION as composed; HANDOFF
stays behind `c7_production_handoff_enabled`.
