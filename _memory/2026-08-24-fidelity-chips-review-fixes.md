# 2026-08-24 — review + repair of the render-fidelity and edit-target-chips slices

Adversarial review (two independent Opus reviewers + structured pass + the
previously-skipped Postgres gates) of `194ce59a4` (render fidelity) and
`8d1c8862d` (edit-target chips). Every finding below was verified against the
working tree before fixing; all fixes are committed on this branch.

## Verification that was missing and now ran

- Provisioned `clue-pg-colombo` (pgvector:pg16, port 55220) per the
  per-worktree convention; migrated to the single head `db145059253b`;
  proved down→up reversibility of `54ae25174405` + `db145059253b`.
- The 35 DB-backed route/envelope tests both implementation sessions had to
  skip (no Postgres) all pass. Wider chat/design-leg DB suites (121 tests) pass.

## Confirmed defects fixed — render fidelity

- **Token-map wipe on reload (critical):** `use-scene-document`'s load effect
  cleared the module-scoped kit token maps on EVERY load (deps
  `[documentId, reloadToken]`), but the only re-installer is the brand-kit
  effect keyed on the pin value `id@version` — unchanged across a reload, so
  after any committed write/undo/agent turn (all bump the reload nonce) the
  canvas silently stayed on fallback tokens. Fix: both clears are now guarded
  by an `installedKitKeyRef`; the kit effect owns the clear it reports.
- **Builtin kit versioned 404 (critical):** preflight stamps kit-less scenes
  `brand_kit_platform_default@1`, but only the versionless
  `/brand-kits/{id}` route synthesizes the builtin — the versioned route
  404s (`main.py` `get_brand_kit_version` has no builtin branch). Every
  default-branded document raised "Pinned Brand Kit unavailable" + fallback
  tokens. Fix: `fetchBrandKitDetail` forces the versionless route for
  `PLATFORM_DEFAULT_BRAND_KIT_ID`.
- **Registration-failure diagnostics wiped (high):** a library face whose
  FETCH succeeded but whose DOM/CanvasKit registration failed is marked
  loaded (never retried) while its diagnostic was replaced by the next scene
  change's empty stamp. Fix: `persistentFaceDiagnostics` module cache in
  `libraryFonts.ts`, re-emitted on every run. (Fetch failures already
  retried + re-reported — unchanged.)
- **Banner severity (low):** the font banner now leads with an
  error-severity diagnostic instead of `fontDiagnostics[0]`.

## Confirmed defects fixed — edit-target chips

- **Ungated refs → thread-wide refusals (critical):** chips/refs attached with
  no `chat.designLegOpen` gate, so a selection on a gallery-opened ad or after
  leg close made every message 409. Fix: `editTargetsEnabled` mirrors the
  reference-images gate exactly.
- **Stale node ids submitted (critical):** deleted nodes stayed selected,
  chipped (raw engine id label) and submitted → server refusal wall. Fix:
  chips and the submission snapshot filter to nodes the live scene carries —
  what the bar shows is exactly what a send targets.
- **Silent Send no-op from the gallery (high):** the version-null refusal
  reported into the ad-inspector error slot (unmounted in gallery view) and
  blocked submission invisibly. Fix: `onHistoryChange` now carries
  `currentVersion`; the session remembers each document's last committed
  version so an unmounted canvas no longer erases a known version.
- **Run-time target crash (high, backend):** `_envelope` re-resolves durable
  node targets against the CURRENT scene and `resolve_scene_targets` raises —
  previously falling into the `DESIGN_LEG_TURN_CRASHED` containment (and
  converting the pinned-document-vanished graceful path into a crash). Fix:
  typed pre-dispatch refusal `DESIGN_LEG_TARGET_UNRESOLVED` via `_fail_turn`;
  leg stays `open_awaiting_user`. DB regression test added (delete targeted
  node between acceptance and dispatch).

## Adjacent breakage found at HEAD (not the two reviewed commits)

- `3b6fe69ba` (reference images) made `reference_asset_ids: []` an
  unconditional key in the scene `agent_turn` request, breaking the two
  frozen byte-for-byte envelope contract tests (only visible with a DB).
  Fixed: the key rides only when references exist (the design model defaults
  the absent key to `[]`).
- `test_p36_leg_resilience_db` gate-race test was stale against the current
  `insert_gate_answer` signature (missing `expected_subject_sha256`) —
  pre-existing, DB-gated so nothing surfaced it. Fixed.

## Verified NOT defects (so nobody re-litigates)

- The router's raw-vs-durable replay ref comparison is sound
  (`validated_context_refs` returns `tuple(refs)` unmodified).
- `_page_by_node`'s walk is cycle-safe (per-page visited set; executed).
- All design reads on the validation path are workspace-scoped.
- Migration lineage: single head; downgrade-with-rows fails loud (same class
  as `549de68ae3b9` precedent — deliberate).

## Residuals / not fixed (recorded, low severity)

- Library diagnostics can be stamped for the NEW documentId against the OLD
  scene for one load cycle during a document switch (display-only).
- A turn accepted with node targets while a leg was open but dispatched after
  it closed routes to head-of-abm, which silently ignores design focus refs.
- The inspector palette leg (`use-scene-editing-session`) still swallows kit
  fetch failures (`.catch(() => undefined)`) and skips versionless pins; the
  canvas leg is the diagnostic authority.
- `use-scene-document` has no hook-level test harness (repo has none for
  hooks); the F1 guard is covered indirectly by build/type gates + the pure
  pieces' tests. A live authenticated browser pass is still worth one manual
  check (both implementation sessions' browser automation timed out).

## Gates at close

Frontend: 2,016 tests pass; ESLint 0 errors (2 pre-existing warnings);
production build + TS pass. Backend: 56 focused + 121 wider DB tests pass;
ruff/format/mypy on changed files pass; dependency contracts pass; design
subsystem focused suites 28 pass. Nothing pushed.
