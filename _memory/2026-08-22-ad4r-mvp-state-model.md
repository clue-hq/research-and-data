# 2026-08-22 — AD4.R: the ad inspector adopts the MVP state model (close-out)

Branch `integration/frontend-design-part-iv-v4`, commits `b8671f00..e74265da` (plan doc + 9 code
commits, all local, nothing pushed). Plan: `docs/superpowers/plans/2026-08-22-ad-inspector-mvp-state-model.md`
(founder-approved 2026-08-22). Regime: fresh Opus implementer per task, Opus reviewer per diff,
scoped re-review per fix round, controller-driven browser proofs against the real stack, ledger at
`.superpowers/sdd/2026-08-22-ad-inspector-mvp-state-model/progress.md` (deleted at slice close; this
note + git history are the record).

## What changed (founder ruling: React observes, the engine owns)

The inspector controller's mount-seeded copy of document values — the "third state" behind every
AD4 defect of the shape *"a control displays or commits a value the document does not have"* — is
retired on the ad lane. The invariant now: **only the accepted engine scene owns document values;
the canvas and inspector are projections; React keeps state only for UI facts and focus-scoped
drafts.**

1. `242ec881` — an accepted `applyOperations` mirrors the scene up **synchronously** (the MVP's
   accept-path shape); the passive effect keeps load/reload/relaid arrivals.
2. `8a45ea53` — `useInspectorController` gains opt-in `liveHydration`: state composes
   `{...uiState, ...hydrated}` per render (openSections stay UI-owned); the four value setters
   dispatch without recording. Default path byte-identical (web inspector untouched).
3. `324cae22` — `InspectorInput` gains opt-in `onCommitValue` self-drafting (draft while typing,
   one write on blur/Enter, no-op re-types suppressed against the LIVE value — A27 made structural);
   pure module `inspector-field-draft.ts`.
4. `70d0668a` + `57b7f621` — all four ad controller instances flip to live hydration (fixture path
   stays mount-mode); refused writes can no longer stick anywhere `state.*` is read directly.
5. `db3a486c` — canvas schema: the Custom-W/H committed/draft pair, the preset re-seed and
   `customSizeForPreset` deleted; "Custom" survives as the one honest UI-only view choice
   (`customChosen`).
6. `4d8af158` — `useAdColorRow.shown`, the stroke mint display mirrors and the local `strokeWidth`
   deleted; Font size / Stroke width / Position X/Y / Rotation move to commit-on-blur/Enter.
7. `82a36279` + `b702d293` — the alt-text committed/draft/seen triple deleted; `RadiusControls`'
   scene lane re-based on live values with per-field drafts (web lane BEHAVIORALLY identical — its
   functions untouched apart from one commented TS-narrowing line, though the shared render sites
   gained the scene/web ternary); 8 source-text ruling guards rewritten to pin the new mechanism
   (rewrite-never-delete; adapter halves + web-lane assertions untouched; mutation-tested).
8. `e74265da` — `inspectorGeneration` + `reloadPendingRef` retired; BOTH mounts (artifact route +
   chats route) key the inspector on the node id alone (contract §4's strongest form).

## Verification

- Frontend gate green at every task (final: 1754/1754, lint 0 errors, build clean); root
  `make check` green with exactly the five documented pre-existing pytest reds (3× pilot_budget,
  1× unified_agent_gate_migration, 1× o3_account_deep) — zero new, zero backend files touched.
- Browser proofs (seeded ad `doc_ad22linkedinsquare00000000001`, restored node-identical after each
  walk; final v140 = baseline values): refused writes snap back everywhere (locked Mode/weight/
  radius/alt); one intent = one document version (multi-digit, decimal, no-op re-type all proven);
  the scan-clobber, stale-W/H, three-surface-disagreement and restore-impossible defects are
  structurally dead; the mint round-trip derives with zero panel mirrors; CAS conflict → D10 note +
  fields re-derive **without remount** (DOM-probe proven) and a mid-typing focused draft survives
  the reload; both routes verified.

## Rulings and plan defects (full list in the final session summary)

- 2 plan defects found by implementers at mandated stop-gates, both ruled before damage: (1) the T7
  brief's "no direct tests" missed 8 source-text ruling guards (ruled: rewrite to pin the new
  mechanism, never delete); (2) the T8 file map missed the chats-route twin mount (ruled: both
  mounts move together).
- Founder-ratified disclosures: Font size/Stroke width/Position/Rotation commit on blur/Enter
  (per-keystroke MAY return later; needs coalescing); refused commits revert the field (the A19-era
  keep-refused-text posture retired); the fixture/dummy path no longer displays the stroke mint or
  scan restate (the dummy stops showing writes no document performed).
- T6 walk skipped mutating the seeded token fill (display half proven live — swatch resolves
  `$text.inverse`; write path unchanged since AD4.0's proof).

## Open / follow-ups

- **T10 (G-H) SHIPPED 2026-08-22, correct-base reimplementation `c31ddf96`** (a first attempt was
  accidentally built against a rewound pre-slice checkout and discarded — see the incident below).
  Founder approved the 0.45 treatment AND extended it: no human operations through the inspector
  while an agent turn runs. Gate = turn-in-flight (never leg-open; interleaving between turns
  survives); chats route only (`chat.threadBusy`, read-only); chat side status quo by ruling;
  navigation stays live; the header lock disables mid-turn but a LOCKED node keeps its unlock
  enabled. Three T7-era pins rewritten as strict supersets now also pinning the G-H gating; four
  collisions engineered around byte-exact. Proven live on the correct build: locked half (0.45 +
  native disabled + unlock carve-out + re-enable) and mid-turn half (operations gated incl. radius,
  nav live, composer status quo) against a real running thread. Residuals: secondaries
  inert-but-undimmed (A19); AI primaries' `:disabled` inherits `cursor: wait` (reads as "working"
  during someone else's turn — founder-visible); popover hex-draft mutation unguarded (both commits
  refuse); locked ROOT FRAME's Background controls look live and get refused (pre-existing);
  artifact route ungated pending a document-scoped agent-busy signal (D10 CAS remains its net).
- **INCIDENT (2026-08-22, resolved):** mid-session, a checkpoint-restore from a second agent
  session rewound branch AND worktree to the pre-slice state; T10's first attempt was built on that
  wrong base (the tell: 1750 tests vs the slice's 1754). Founder ruled: restore + redo. Branch
  reset to the slice tip, G-H docs cherry-picked, T10 redone with a mandatory base-attestation
  protocol (HEAD hash + marker facts + test count verified by the subagent before work and by the
  controller after — now standing practice, saved to persistent agent memory). The wrong-base
  implementation is preserved on branch `rescue/t10-g-h-work` for reference; safe to delete.
- **Environment findings (founder attention):** the dev stack's turn drain runs only from the
  missoula workspace's fleet worker and left a production turn queued (0 attempts) on
  thr_ad210_story_portrait — turn 212c9adc, still queued (it served as the live threadBusy source
  for the mid-turn proof; clear it when the drain is fixed). The design API on :8010 died
  mid-session and was relaunched via the sanctioned /tmp/slice4-relaunch-8010.sh.
- **Web lane migration** — its own future slice: same latent defect class, but async HTTP writes
  need optimistic hydration or a draft-until-arrival rule before `liveHydration` can flip there.
  NOT a mechanical copy of AD4.R.
- Deferred minors (final-review triage list): `mintedStrokeWidth/Color` + `radiusCommitText` now
  test-only (production-dead helpers; A9 constants must survive any cut); `finiteNumber` doc says
  "per KEYSTROKE" (stale); scene-hydrate.ts:124,136 name a deleted caller; scene-apply.test.ts:2168
  history prose; same-preset re-pick writes a same-value version (pre-existing); corner-name
  negatives in the A29 guard would false-fail on a future comment naming a corner; editQueue
  rejected-batch replay is timing-dependent (pre-existing AD3.2 semantics, observed live).
- Post-fix-wave residual cosmetics (final re-review): the A29 *wiring*-guard comment at
  scene-apply.test.ts:~2198 still carries the retired seeded-copy rationale; the never-null
  dependency sentences don't name the failed-reload error path (which nulls the scene
  non-transiently); one ~82-char comment line in use-scene-image-ai.ts.

## For Lanes B–E (binding, recorded in the parent plan's AD4 preamble)

Bind new rows as `value={state.x}` + dispatch-only commit; typed fields use `onCommitValue`;
UI-only view choices are the only schema-local state; the A26/A27/A28/A31 mirror patterns are
retired and guard-pinned against reintroduction.
