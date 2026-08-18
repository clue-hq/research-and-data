# 2026-08-18 — Gallery leg-derived artifact feed v1 (parallel worktree lane)

Branch: `feature/gallery-leg-derived-feed` (renamed from `integration/frontend-design-part-iv-v4`
by founder order). Merge target: `integration/frontend-design-part-iv-v2` — local merge only,
founder pushes. Plan: `docs/superpowers/plans/2026-08-18-gallery-leg-derived-artifact-feed.md`
(ratified; do not re-litigate rulings 1–3).

## Progress

- **Slice 1 DONE** (`7ef5adb5`): `GET /api/v1/projects/{project_id}/design-artifacts` beside the
  W1.3 sibling in `platform/api/clue_api/chat/router.py`; leg-derived query in
  `design_leg_wiring.py` (DISTINCT ON legs, double workspace pin, web-only, latest-leg-wins
  origin_thread_id, ORDER BY updated_at DESC, d.id tie-break). Six DB-gated tests in
  `tests/api/test_design_artifact_feed_db.py` (cross-exclusion, foreign-ws, no-legs, dedup,
  NULL-doc legs, scene excluded) — run against the shared 55040 dev DB, rolled-back txns.
- **Slice 2 DONE** (`549a411b`): `DesignArtifactRepository.list(projectId)` (fixture + HTTP),
  `DesignArtifactListItemSchema`/`DesignArtifactListWireSchema` in `model/artifact.ts`,
  TDD'd mapper `features/design-editor/adapter/gallery.ts` (wire→ProjectArtifact; timestamp
  normalization to Z-form is load-bearing — backend serves `+00:00` isoformat, gallery schema
  is Z-only `z.string().datetime()`). Additive model edits: `imagePath`/`originRunId` optional;
  card + artifact-gallery + artifact-viewer null-guards. 517/517, lint/build green.
  - Decision: `collateralType: "microsite"` (enum has no "website"; gallery's own
    `defaultCollateralType` maps website→microsite; plan pre-authorized the enum check).

## Explicit NOT-YET-TESTED register (founder asked for this list to be kept)

1. [S1] `ORDER BY d.updated_at DESC` has no test — no test returns two documents in one feed.
2. [S1] Latest-leg-wins tie-break on `leg.id` at equal `created_at` untested.
3. [S2] `utcInstant` TypeError branch (unparseable timestamp) untested.
4. [S2] Wire-schema rejection paths (missing origin_thread_id/timestamps) untested.
5. [S2] `editedLabelFor` direct call on bad input → "Last edited NaN years ago" (unreachable
   via `toProjectArtifact`); untested, unfixed.
6. [S2] Relative-label wording past "yesterday" is extrapolated, not dummy-attested — founder
   glance due at Slice-4 browser QA.
7. [S1] No LIMIT/pagination; no index on `design_leg.document_id` — volume behavior unmeasured.
8. [S2] `artifact-viewer.tsx:158` export anchor `href={undefined}` when no imagePath
   (unreachable today; unpinned by tests).

## Open next

- Slice 3 (wiring: artifact page list fetch + EditorSurface cards/documentIds — ONE-HUNK edit
  in editor-surface.tsx, W4 lane shares that file) — in progress, implemented directly in the
  controller session by founder order.
- Slice 4 (leg backfill for `doc_31126145a0aa4753920629ae323a301b` → thread
  `thr_4ef1f65aee39574e8290f60cf3b32a40`, browser proof, gates, contract recording in
  `apps/frontend/docs/api-contracts/projects.md`).

## Slice 3 DONE (2026-08-18, controller-implemented by founder order)

- `439f53cd`: artifact page fetches the list server-side (Promise.all with the single resolve;
  refusal → empty list), maps cards via `toProjectArtifact`, builds `documentIds` over the WHOLE
  feed (+ route artifact merged in — a legless route doc still renders); `EditorSurface` gains
  optional `artifacts` prop → `ArtifactStage` (replacing `artifacts={[]}`); stale W0.5
  "empty until fed" comment updated. Editor-surface diff kept minimal for the W4-lane merge.
- `64b25711` (ruling, flagged for founder at Slice-4 QA): killed the fabricated "OpenAI"
  account fallback on real cards — `GalleryArtifact.account` optional, honest absence in card
  badge/list row/filter menu/search/group-by-account (unattributed group label is EMPTY pending
  founder wording). Fixture artifacts unchanged. 4 new tests.
- Gates: 521/521 tests, lint clean, build green. NOT yet browser-proven (Slice 4).
- Untested residual: the page's server-component glue (browser proof covers it);
  editedLabel uses server-local timezone at render time.

## Slice 4 DONE (2026-08-18) — backfill + live browser proof; plan complete

- **Backfill:** two `design_leg` rows (state `closed/locked` so the one-open-leg-per-thread
  slot stays free), borrowing real execution `e5524948-…` (executions are workspace-scoped;
  no thread column exists on `execution`): seeded doc → demo thread, and a NEW second chain
  for the negative — project `prj_gallerynegcheck0000000000000001` ("Gallery cross-exclusion
  check") + thread + doc `doc_d81363ab82cf4f16bd468bbb3ec67895` ("Second project landing
  page", created wire-true via the design API). The second project is intentionally left in
  the workspace for the founder's own check (delete its rows to remove it from the rail).
- **Live proof (authenticated 3030 stack):** demo project's Gallery tab → "1 artifacts",
  the Insight Health card (real title, "Last edited today", EMPTY preview frame, no account
  badge; the one <img> is the designed type icon) → close-tab fallback → CARD CLICK reopened
  the tab and the real page rendered (srcdoc w/ tailwind-browser + lumen-web-bridge) →
  Edit → subheadline select (node `sub`, schema `text`, real values: size 20, center) →
  size 20→24 wrote v29→30 (`text-2xl` in render) → menu Undo reverted v30→31. Negative:
  project 2's gallery shows ONLY its own card; project 1's shows only Insight. Screenshots
  `/tmp/slice4-gallery.png`, `/tmp/slice4-clickthrough.png`, `/tmp/slice4-negative.png`.
- **Gates:** frontend 521/521, lint clean, build ✓, design-system ✓; backend feed tests 6/6
  vs 55040. Contract + the two durable rules recorded in
  `apps/frontend/docs/api-contracts/projects.md` ("Gallery leg-derived design-artifact feed").
- **Worktree env gotchas (recovered this session):** ankara had NO root `.env` and NO
  `apps/frontend/.env.local` (both gitignored, not copied by Conductor) — without the latter
  the frontend silently runs FIXTURE auth (the "hello@aakash.design" dummy onboarding) and
  the artifact page falls back to "Web output". Copied both from istanbul. The design API ran
  with istanbul's prebuilt `lumen-api-helper` (no Rust divergence between the branches).
  Browse-daemon: `Network.clearBrowserCookies` is not CDP-allowlisted; the custom dropdowns
  are BUTTONs with role=option popovers (`$B select` fails; click the option).
- **Founder-glance items at sign-off:** the "Last edited …" wording ladder past "yesterday"
  (extrapolated), and the unattributed-account presentation (empty group label under
  group-by-account; no badge) — both my rulings, both one-line to reword.
- Stack LEFT RUNNING for founder sign-off (3030/8030/8010; logs /tmp/ankara-*.log).
