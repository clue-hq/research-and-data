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

## ADDENDUM (same day) — steps 3, 4, 5 COMPLETE

- `1d4cc0d8b` — step 3 flag posture: entity-research runtime + both Sumble gap flags → false;
  CLUE_MEMORY_ENABLED=false + CLUE_SELF_SERVE_PROVISIONING_ENABLED=false added (parity gaps
  closed); CLUE_FRONTEND_CORS_ALLOW_ORIGINS placeholder. Note: the file deliberately carries the
  opposing integration_pilot overlay block; the runtime-flag comment warns about it.
- `49647391f` — inversion (a) fixed: `check_claim_value_entailment` returns False (admitted,
  unjudged) when no judge is composed; red-proof test
  `tests/stage0/test_c8_evidence_ergonomics.py::test_typed_value_without_a_judge_is_admitted_unjudged_r0`
  (agent proved red against the old code, I re-ran green against clue-pg-semarang:55110).
  KNOWN RESIDUAL: interview.py's CORROBORATION-INDEPENDENCE INVARIANT comment (~L895) still says
  interview claim values are strings by construction — premise narrowed (typed values now also
  land under `client_interview` when unjudged); safe direction (one source_key = one source),
  moot while the Corroborator is uncomposed; comment not updated (out of scope).
- `deb31c686` — inversion (b) fixed: inline Sumble Corroborator deleted; materialization always
  RESOLVED on the provider value. No tests pinned CONFLICT/CORROBORATED from this path; enum and
  consumers untouched.
- `88f42e548` — DEEP_SPEND readiness floor min_verified_claims 1 → 0 (would deadlock with
  verification off; human override remains the governing gate).
- `068fa858b` — step 5: CLUE_VERIFICATION_ENABLED=false (.env.example L187), flipped only after
  the inversion fixes per plan ordering. Proof set (70 tests) green in both env postures.
- Baseline correction: the pre-existing-red list is wider than the R0 note above recorded —
  add `test_toolbelt_wiring::test_out_of_order_matrix` (same root cause as the full-set red) and
  6 reds in `tests/stage0/test_phase_c5_recipe0.py` ("project product confirmation requires an
  established workspace client") — ALL confirmed failing at pristine `1d4cc0d8b` base by the
  step-4 agent. Total known pre-existing debt: 4 + 1 + 6 = 11 test reds, owners undecided.

## R0 exit-gate status after steps 2-5

MET: merged branch; single alembic head (44039cb83844); old lane inert by posture (runtime flag
false; launch tools refuse typed); interview writes typed values with verification off (proven);
db-smoke green; frontend gate green (2060/2060).
NOT YET: `make check` fully green (11 documented pre-existing reds — debt-payoff needs an owner
ruling); seam docs signed (draft ready, joint session pending); step 7 frontend contract-gap
ruling session; step 8 ARV2 skeleton (flag + empty driver + catalog folder + Secrets.ai_ark_api_key).

## ADDENDUM 2026-09-03 — plan delta after the Person-Depth + One-Account runs
Read first-hand: `.context/arv2-person-depth/`, `.context/arv2-one-account-aiark/` (chicago), the
`head-of-abm-agent-refinements/` program, and the new frontend truth `clue-frontend/chat-shell`
@ `b24f547`. Written up as **`docs/specs/ARV2-plan-delta-2026-09-03.md`** (amends R1–R5 content,
not order) + three amendments applied to the seam-freeze DRAFT. Two coordination facts: chicago
does NOT have the R0 commits (push/merge before R1); Aryan's memory note reports Apollo + AI Ark
keys pasted in an untracked chat attachment — rotate both.

## ADDENDUM 2026-09-04 — plan v2 (accounts integration) + name correction
- **Name correction:** git authorship shows the chicago PoC/spec commits are by Shashank Keshri;
  this machine's git user is akeshri003. So **Aryan = tech founder (this session's user): platform
  agent/onboarding/ICP/project context. Shashank = non-technical co-founder: research PoCs, frontend
  specs, accounts integration.** The R0 plan and 09-03 delta used the names swapped in places —
  read by role. New docs are written by role.
- New inputs read first-hand: `chicago/.context/frontend-page-content/` (display grammar: fixed H1
  sections, recipes as config, Luna per section, claimIds on every sentence, display_block rows),
  `chicago/.context/display-layer-control-test/REPORT.md` (per-section + Luna + default effort;
  no cheaper model passes; ~5c/account; two upstream dedupe fixes), and `clue-frontend/port-of-spain`
  @ 6b623fe (~80% implemented; 18 cut points incl. overview rendering only "Why now"; zero
  contract-doc updates; gendered hard-codes).
- Written: **`docs/specs/ARV2-plan-2026-09-04-accounts-integration.md`** — two tracks meeting at the
  claim store: Track D (load PoC claims → display layer → read surface → re-lift; starts now) and
  Track R (R1–R4 as amended 09-03); 13 D0 rulings; contract v1 = port-of-spain models + backend
  semantics; operating model for a non-technical co-founder (charters, agents never merge, tech
  founder owns four integration points).

## ADDENDUM 2026-09-05 — plan re-based on the 5 Sep frontend (`clue-frontend` `integration/live-backend-v1` @ 84f8ee7)
Read first-hand: the model diffs (+segments, researchExcerpt, verificationKind, fitDisposition,
intro/emptyMessage, actor-based activity, account artifacts ad/email + accountId/projectName/
updatedAt, owner/createdBy nullable, fitScore nullable, contact employmentStartedAt/
linkedinFollowers/linkedinCreator/locationClaimId), Shashank's `docs/zafran-content-implementation.md`
and `docs/account-owner-motion.md` (5 Sep presentation rulings: closed toggles, no truncation,
Internal notes, Watch-outs omitted from overview, compact favicon+domain chips), and a Fable study
of components/fixtures/gates (118 tests green; fixtures parsed from the vendored spec markdown).
Updated: MASTER PLAN v1.3 (§6 contract v1 re-based, §7 output shape + presentation, §8 rulings
reduced to R1–R13, D5 resolved frontend-side), WORK-SPLIT (S1/S2/S8 + charter 6.1), GETTING-STARTED
(§3 dummy branch, PoC map, week 1), AGENT-BRIEFING (truth commit, new vocabulary, no client-side
rewriting rule). Contract doc in the dummy still not updated (D0-b).

## ADDENDUM 2026-09-07 — data-source map
Founder asked for an exact element → endpoint → SQL/column map so the frontend never derives and the
backend never reads markdown/JSON files. Two Opus study agents (backend `frontend_read/` routes with
SQL; dummy components with the field each element reads) + first-hand spot checks. Written as
`docs/specs/ARV2-DATA-SOURCE-MAP.md` (master plan v1.4 §6 pointer, D13, `display_section_recipe`
name). Load-bearing findings: (1) `display_allowed` requires STRONG identity binding by default —
lenient WEAK stamping would hide every ARV2 contact fact (ruling S10); (2) a `recipe` table already
exists (Stage-0), so display recipes are `display_section_recipe`; (3) no owner/logo/artifact-account
columns exist — S1/S2/S9; (4) `/workspace` endpoint does not exist yet (E3, new module);
(5) existing detail route returns a bare object, dummy expects `{data}`.

## ADDENDUM 2026-09-07 (later) — Aryan's rulings recorded
R1 → no dates anywhere (chips or hover); verifiedAt/publishedAt stay on the wire unrendered.
S10 → Option 2: `arv2_display_allowed` on E2–E5 (use-class + sensitive fail-close kept; WEAK binding
no longer hides outreach_safe=true claims; C7 `display_allowed` untouched). Everything else in §8
R2–R13, §12 D1–D8/D10–D13, source-map S1–S9/S11–S12 ruled as recommended. Still open: D9 (Series A
equivalence clause), seam-freeze box 2b (auto-register qualifier fields), Shashank's confirmations.

## ADDENDUM 2026-09-07 (evening) — shared base is `integration/design-improvement`
`origin/install-agent-browser-global` fast-forwarded into this branch (docs/.context only, 36 commits;
both at e81cd9d42). Founder ruled: the shared base for all three tracks (O, D, R) is
`integration/design-improvement`; getting-started + work-split updated. Historical mentions of the
old name in R0 plan / older memory notes are left as history.
