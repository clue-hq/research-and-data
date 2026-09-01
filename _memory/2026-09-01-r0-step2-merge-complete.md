# 2026-09-01 — R0 step 2 COMPLETE: comprehensive merged into design-improvement

Executed per `docs/specs/ARV2-R0-foundations-plan.md` Part 6 step 2, both founders signed off.
Opus subagents executed under a no-decisions rule (every ambiguity escalated to the Fable
orchestrator); every subagent claim re-verified first-hand before the next step.

## The commit chain (all local, NOT pushed)

- `498bbf283` (branch `merge/comprehensive-remint`) — pre-merge re-mint: comprehensive's
  colliding head-of-abm profiles v37/v38 → v41/v42 and recipe0-stage0 v17/v18 → v20/v21, all
  pins repointed incl. one reconstructed aggregate-sha test pin.
- `fccc0bef7` — seam-freeze draft (`docs/specs/ARV2-R0-seam-freeze.md`, awaiting the joint
  founder session; 5 decision boxes).
- `aacdb977c` — the merge itself (parents fccc0bef7 + 498bbf283). 14 content conflicts resolved
  per pre-decided policy. **Mints head-of-abm v43** (see below). Active recipe stays v19; v20/v21
  seeded replay-only in `HISTORICAL_REPLAY_ONLY_RECIPE_FILENAMES`.
- `4bc287072` — alembic join `44039cb83844` (parents `6eff96862040` design + `612428f3731f`
  research). db-smoke up→base→up green on throwaway DB `clue_smoke_design_improvement`
  (created+dropped); shared dev DB `clue` verified untouched (313 tables before and after).
- `997409ea1` — merge-defect repairs: (A) router.py gate-approval backfill block moved back to
  its parent-2 position AFTER the `_validated_submission_context` binding (the merge had placed
  it above the binding it reads → F821/UnboundLocalError; pure reorder, byte-identical content);
  (B) restored the dropped `});` in `chat-transcript.test.ts` at the C5 splice; (C) comprehensive
  contract test pin v42 → v43; (D) ruff-format of the two merge-introduced files only.

## The v43 ruling (the merge's one product decision)

v40 (design line) and comprehensive's profile (re-minted v42) were DIVERGENT SIBLINGS — v42 pins
the retired `open_design_leg@1` so it can never build on this branch; v40 pins the pre-pilot
directive tool @3 while the merged authority table auto-carried @5. **Active profile is now v43 =
v40 (prompt v7, open_design_leg@4, x-ai/grok-4.6) + comprehensive's directive contract
(draft_account_research_directive@5 + account-deep-steering v8).** Full diff between the parents
was exactly five deltas; three keep v40's side. Founder instruction "handle the new head-of-abm
skill" is satisfied — the pilot-hardened skill is live, not inert catalog bytes.
`PROJECT_CONVERSATION_AGENT_PROFILE_ID = head-of-abm@v43`.

## Final verified state (attested first-hand at 997409ea1)

- Tree clean; single alembic head `44039cb83844`; stash holds one pre-merge `uv.lock` drift
  entry (deliberately not popped).
- `ruff format --check`: exactly the 10 PRE-EXISTING unformatted files (3 migrations,
  composer_context, chat/schemas, 3 design files, 2 tests). `ruff check`: exactly the 9
  PRE-EXISTING findings (2×SIM300, 2×I001, 2×F401 sqlalchemy, 2×F401 alembic.op, 1×E501 — the
  F401 pairs are in the OLDER merge migrations `6eff96862040`/`7247c55459c4`, alembic-template
  noise). `make typecheck`: only the pre-existing `ad_assets.py:149` error.
- Full suite at M3 time: 6 failed / 2931 passed / 2594 skipped; after `997409ea1` the 2
  merge-caused failures are fixed → **4 remaining failures, all PRE-EXISTING on the design line
  before this work** (baselined on a detached checkout of fccc0bef7, which had 12):
  1. `test_catalog::test_real_folder_catalog_is_strict_versioned_and_provider_neutral` — the
     catalog list is missing a v40 entry (pre-existing gap).
  2. `test_agent_registry_wiring::test_registry_resolves_exact_reviewed_profiles_and_stable_manifests`
     — OTHER roles' stale sha pins (head-of-abm's own pin now measured-correct for v43).
  3. `test_agent_registry_wiring::test_design_profile_resolves_with_the_full_granted_write_surface`.
  4. `test_toolbelt_wiring::test_build_toolbelt_registers_the_full_set` — two causes: stale
     count (`len(registry.names()) == 118` vs 119 measured) + whatever else the baseline red held.
  The merge work incidentally FIXED 8 pre-existing reds (v39-stale assertions, resource-map
  count, s4e surface, three pilot-budget-controls cases, the single-head lineage test).
- Frontend: `design-system:build` PASS, `lint` 0 errors (2 pre-existing warnings), `build` PASS,
  `npm test` **2060/2060**.

## Open / next (R0 checklist)

- Step 3 (flag-posture + `.env.example` parity commit) — NOT started; founder re-emphasized the
  parity rule: every flag flipped or introduced must land in `.env.example` with its new value in
  the same commit. Missing-from-example flags to add: CLUE_MEMORY_ENABLED,
  CLUE_SELF_SERVE_PROVISIONING_ENABLED, CLUE_FRONTEND_READ_ENABLED, CLUE_FRONTEND_CORS_ALLOW_ORIGINS.
- Step 4 (two inversion fixes + readiness floor) — NOT started.
- Step 6 seam-freeze session — draft ready (`docs/specs/ARV2-R0-seam-freeze.md`).
- The 4 pre-existing test reds — candidates for a small debt-payoff commit, need owner decision.
- Temp worktrees removed; branch `merge/comprehensive-remint` kept (merge parent, harmless).
- `.env` file: absent in this workspace — when one is provisioned, remember env-value-wins
  reconciliation against the merged `.env.example`.
