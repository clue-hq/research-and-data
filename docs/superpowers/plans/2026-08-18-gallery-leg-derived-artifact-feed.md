# Gallery leg-derived artifact feed (v1) — implementation plan

Status: RATIFIED by founder 2026-08-18 (all three rulings below). Execution: a **dedicated
parallel worktree** branched from `integration/frontend-design-part-iv-v2` (istanbul), merged
back into that branch when done — per the standing parallel-worktree pattern. Do NOT execute
on the main integration branch.

Suggested branch name: `feature/gallery-leg-derived-feed`.

**Parallelism (founder, 2026-08-18):** while this worktree runs, the istanbul branch
(`integration/frontend-design-part-iv-v2`) continues the remaining W4 schema work. The file
surfaces barely overlap — W4 lives in `web-inspector.tsx`, the hydrate/apply adapters, and
`webClassFacets` (both trees); this plan lives in the chat router, the artifact repository,
the gallery model/card, and the artifact page. The ONE shared file is `editor-surface.tsx`
(this lane changes only the `artifacts` prop feed and the `documentIds` map) — keep that
edit minimal so the merge stays one-hunk. If W4 lands adapter changes first, rebase early
rather than resolving late.

## Story

The lifted gallery (W0.5) renders with an empty artifact list — "dummy means empty, never
fake." The founder's end goal, stated and ratified 2026-08-18: **every artifact created
inside a project must appear in that specific project's gallery, and only there.** A
workspace-wide list was considered and REJECTED (it would show every project's documents in
every gallery). The ratified approach is **leg-derived v1**: `design_leg` binds
`thread_id → document_id`, `agent_thread` carries `project_id`, and in the real product path
an artifact created inside a project is created by the agent in a project thread — which
opens a leg. So a per-project gallery read is one join, and it is project-correct today.

When this lands, the gallery goes from honestly-empty to showing real cards, the
gallery→artifact click-through becomes testable end to end, and the precondition of W0.5
founder Decision 2 (retire the old `/projects/{id}/gallery` screen once the new gallery has
real data) is met — the route swap itself is a SEPARATE follow-up, not this plan.

## Ratified rulings (founder, 2026-08-18 — do not re-litigate)

1. **Leg-derived v1, not workspace-wide.** Per-project galleries via the leg join. Known,
   accepted gap: a document with no leg belongs to no project and appears in no gallery.
2. **Card preview:** real documents have no thumbnails. `ProjectArtifact.imagePath` becomes
   OPTIONAL (additive); the gallery card renders its existing frame WITHOUT artwork when
   absent — no invented/placeholder imagery. Real thumbnails are recorded future work (the
   design subsystem's capture pipeline can feed this later).
3. **Web documents only in v1.** Scene/ad documents stay out of the gallery until the
   ad-editor plan (consistent with the standing "website editor only" scope).

**Two durable contract rules to record while implementing** (in
`apps/frontend/docs/api-contracts/projects.md` alongside the endpoint):
- Every future artifact-creation surface (the gallery's "create a new artifact" affordance,
  Duplicate, any non-agent path) MUST write project linkage at creation time.
- This read is replaced WHOLESALE when the real platform-artifact registry (documents
  registered as platform artifacts with project linkage) lands. No incremental migration.

## Schema + code facts (verified 2026-08-18 — trust these, spot-check cheaply)

- `design_document`: `workspace_id` (NOT NULL), `doc_kind` (`web|scene`), `title`, `status`,
  `current_version`, `created_at`, `updated_at`. **No project column.**
- `design_leg`: `workspace_id`, `thread_id`, `parent_execution_id` (uuid NOT NULL),
  `document_id` (**nullable**), `state`. The dev DB currently has **zero rows**.
- `agent_thread`: has `project_id`.
- The W1.3 single-artifact endpoint lives at `platform/api/clue_api/chat/router.py:1002`
  (`GET /api/v1/projects/{project_id}/design-artifacts/{artifact_id}`) — workspace fail-closed
  project + document reads, `doc_kind web|scene → kind web|ad` mapping, wire envelope
  `{data: {id, project_id, document_id, kind, title, status, current_version_id}}`. The list
  endpoint is its sibling; copy its auth/scoping posture exactly.
- Frontend seam (W1.3): `apps/frontend/src/features/design-editor/data/artifact.repository.ts`
  (`DesignArtifactRepository.get`, fixture + HTTP adapters) and `model/artifact.ts`
  (`ChatShellArtifactSchema` + `DesignArtifactWireSchema`).
- Gallery model: `apps/frontend/src/features/projects/model/project-workspace.ts` →
  `ProjectArtifactSchema` — REQUIRED today: `imagePath` (ruling 2 makes it optional),
  `editedLabel`, `originRunId`, `originThreadId`, `type`. The card
  (`features/gallery/components/gallery-artifact-card.tsx`) renders `artifact.imagePath` via
  next/image at two sites — both must null-guard under ruling 2.
- The editor surface already wires the click-through: gallery card →
  `onOpenGalleryArtifact` → `controller.openArtifact({id, kind, title})`. It needs the
  card's id to BE the artifact id (== document id, v1 seam) and the `documentIds` map to
  cover every listed document, not just the route's.

## Slices (commit per slice; TDD where a pure function exists)

### Slice 1 — backend list read

- `GET /api/v1/projects/{project_id}/design-artifacts` (chat router, beside W1.3's single).
- Query: legs for the project's threads (`design_leg JOIN agent_thread ON thread_id`,
  project + workspace fail-closed exactly like the sibling) → DISTINCT non-null
  `document_id` → `design_document` rows in the caller's workspace with `doc_kind = 'web'`
  (ruling 3). Order: `updated_at DESC`.
- Wire: `{data: [{id, project_id, document_id, kind, title, status, current_version_id,
  created_at, updated_at, origin_thread_id}]}` — the W1.3 item shape plus the three new
  fields. `origin_thread_id`: any one of the doc's legs' threads (latest leg wins).
- DB-gated tests (run against a real dev DB, the W1.3 tests' pattern): (1) two projects,
  two docs, strict cross-exclusion — THE test that proves the founder's requirement;
  (2) foreign-workspace invisibility; (3) no legs → empty list; (4) two legs, one doc →
  one item; (5) legs with NULL document_id skipped; (6) scene doc excluded.

### Slice 2 — frontend repository + mapper

- `DesignArtifactRepository.list(projectId)` — fixture + HTTP adapters; wire list schema in
  `model/artifact.ts` (item = existing wire item + the three new fields).
- Pure mapper (new file, e.g. `features/design-editor/adapter/gallery.ts`):
  wire item → `ProjectArtifact`: `id` = artifact id; `type: "website"`;
  `collateralType: "website"` (check the enum's actual values before hardcoding); real
  `createdAt`/`updatedAt`; `editedLabel` derived from `updated_at` (match the dummy's label
  style, e.g. "Edited <relative>"); `originThreadId` = the leg thread (REAL data);
  `originRunId` — no run exists; make it optional in the schema (additive) OR derive a
  sentinel — prefer OPTIONAL, same additive treatment as `imagePath`; NO `imagePath`
  (ruling 2). TDD the mapper.
- Model edits (additive only): `imagePath` and `originRunId` optional; card null-guards its
  two `next/image` sites (frame renders without artwork). The gallery's
  `normalizeGalleryArtifact`/`defaultSize` must tolerate the optionals — check its tests.

### Slice 3 — wiring

- The artifact page (`(protected)/projects/[projectId]/artifacts/[artifactId]/page.tsx`)
  additionally calls `repository.list(projectId)` server-side (same
  `fetchAuthenticatedClueBackend` primitive; any refusal → empty list, never a crash).
- `EditorSurface`: `artifacts` prop gets the mapped cards (replacing `artifacts={[]}`);
  `documentIds` map extends over the whole list (`{[item.id]: item.documentId}`).
- Known dummy-faithful behavior (do not "fix"): opening from a card switches tabs without
  changing the URL — tabs are shell state.
- The chats-route rail (ChatSurface) is OUT of scope here; note only.

### Slice 4 — dev backfill + browser proof

- Backfill one leg for the seeded doc `doc_31126145a0aa4753920629ae323a301b` →
  the demo project's thread (`agent_thread` of `prj_79aa603b3c3853898045e3cfa414e136`;
  a thread exists: `thr_4ef1f65aee39574e8290f60cf3b32a40`). `parent_execution_id` is
  NOT NULL — borrow a real execution id from that thread's rows; if an FK blocks synthetic
  values, insert the minimal companion row (synthetic dev data — acceptable, this DB is
  synthetic-only by standing ruling).
- Browser walk on the live stack: Gallery tab → the "Insight Health homepage" card (frame,
  real title, real edited label, NO artwork) → click → tab opens → page renders → editing
  works on the opened doc. Negative: a second project's gallery shows no card (create a
  second project or assert via the API with a second seeded project+thread+leg+doc).
- Gates: `npm run design-system:build && npm run lint && npm run build` + full `npm test`;
  backend tests green; ruff clean if Python touched.

## Verification environment (from the istanbul session notes — full recipe in
`_memory/2026-08-17-w01-shell-lift-file-set.md`, "Live authenticated browser run" +
its LUMEN_CORE_HELPER amendment)

- Three servers: platform API 8030 (`clue_api.projections_main:app`), design API 8010
  (`lumen_api.main:app` — **MUST set `LUMEN_CORE_HELPER` to the prebuilt release helper**,
  else every engine call pays ~1.1s cargo spawn), frontend 3030 (env overrides
  `CLUE_API_BASE_URL`/`CLUE_APP_ORIGIN`/`LUMEN_API_BASE_URL`).
- Headless sign-in: `onboarding+clerk_test_20260814@example.com` / `pass@123` /
  code `424242` → select workspace `ws_8040294627e146ae93f753ec0d3e1726`.
- Browser-tooling gotchas (hard-won): `$B fill` does not trigger React controlled-input
  onChange — use the native value setter + input event in one `$B js`; check lint with
  `tail -2` (never `tail -1`); srcdoc greps must anchor to the node (class strings repeat).

## Repo lint rules that WILL bite (learned on W2/W3)

- `react-hooks/set-state-in-effect`: no synchronous setState in effects — use keyed remounts
  for identity changes, stamped-derivation for data reloads. Never key-remount on write-cycle
  tokens (that was a founder-visible defect).
- `react-hooks/refs`: no render-time ref writes — update latest-value refs in a passive effect.
- `no-restricted-imports`: `components/` may not import from `data/` — transport lives in
  hooks.
- A hook prop named `document` shadows the global — attach listeners to `window`.

## Out of scope (recorded, not forgotten)

- The `/projects/{id}/gallery` route swap (W0.5 Decision 2 follow-up — now unlocked, its own
  task after this merges).
- Real thumbnails (capture pipeline), the chats-route rail feed, gallery filters' deeper
  vocabulary, scene/ad documents, the platform-artifact registry.

## Done means

A user in the demo project opens the Gallery tab and sees the project's real web documents as
cards (title + edited label, no artwork), clicks one, and lands in a working editor tab for
that document; a different project's gallery does not show it; all gates green; the endpoint
and the two contract rules recorded in `apps/frontend/docs/api-contracts/projects.md`; session
note in `_memory/`. Merge the worktree branch back into
`integration/frontend-design-part-iv-v2` (local merge, no push — the founder pushes).

Estimated effort: ~1 focused working day (backend 2–3h, frontend 2–3h, wiring + backfill +
browser proof 1–2h).
