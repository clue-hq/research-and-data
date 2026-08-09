# 2026-08-10 — R6 shared project shell and sidebar

## Scope

- Implemented repair Slice R6 only on `platform/lane-d-chat-launch`.
- Preserved the unrelated untracked `.artifacts/` directory and did not begin
  R7.
- No backend source change or migration was needed. R3 already provides the
  real tenant-scoped, batch `GET /api/v1/projects/sidebar` surface; R6 consumes
  it through the existing frontend repository seam.

## Decisions and changes

- Moved the Home, project-catalog, and project-workspace routes under one
  persistent `ProjectApplicationShell` owned by the protected layout. Removed
  the page-local Home and `/projects` shell mounts, and wrapped no account
  feature files.
- Added the executable desktop state table
  `collapsed | hover-preview | pinned-expanded`. Focus/pointer entry previews,
  delayed focus/pointer departure dismisses only a preview, click pins from
  collapsed/preview, and click while pinned collapses.
- Kept preview absolute so it overlays without changing content width; pinned
  state participates in the flex layout and reflows the workspace. The Home and
  project-catalog routes retain the existing collapsed icon rail, while a
  project workspace uses the overlay/reflow behavior requested by R6.
- Replaced the project header's `Go to home` navigation button with the shared
  shell control. It now has truthful action labels, `aria-controls`, and
  `aria-expanded`; Escape closes preview and internal/sidebar closes restore
  focus to the project trigger.
- Preserved the mobile drawer and its trigger, added focus restoration on
  close, and reserved project-header space for the mobile trigger.
- Kept one sidebar controller mounted across Home-to-project navigation. Its
  real repository read now re-runs on pathname changes, so a newly-created Home
  project appears without a browser restart.
- Recorded R6 as implemented in
  `apps/frontend/docs/api-contracts/projects.md`.

## Verification

- `npm test` — 132 passed, 0 failed/skipped. Four new pure state-table tests
  cover preview entry, preview-only dismissal, pinning from collapsed/preview,
  and collapse from pinned.
- `npm run lint` — pass.
- `npx tsc --noEmit` — pass.
- `npm run design-system:build` — pass.
- `npm run build -- --webpack` — pass, including production compilation,
  TypeScript, page generation, and trace collection.
- The default Turbopack `npm run build` was attempted twice but remained idle
  after Next.js inferred `/Users/aryankeshri` as the workspace root from an
  unrelated parent lockfile. The supported webpack build avoided that existing
  repository/root-discovery issue; no R6 source failure was involved.
- Existing database-backed R3 project/sidebar API acceptance — 2 passed.
- `git diff --check` — pass.
- React best-practices review — no new fetch waterfall, duplicated global
  listener, render-derived state effect, component-local transport access, or
  uncleaned timer/listener. The initial ref-tainted context shape was caught by
  the React compiler lint and corrected before verification.

## In-app browser evidence

- Home at `http://localhost:3000/` rendered exactly one `Main navigation`
  complementary region. It began with four real project rows; the 250 px
  sidebar reflowed Home content to x=250.
- Created project `prj_85fe69f7aa8f5814b3e2506d65dcb215` with thread
  `thr_c042b61233135a94be26dc2b99d28073` through the real Home bootstrap.
  Client-side navigation kept exactly one sidebar mounted and the catalog
  refreshed from four to five project rows without a full browser restart.
- In pinned state the project main surface measured 1078 px wide at x=250 with
  a 250 px sidebar. Collapsed state measured 1328 px at x=0. Keyboard focus
  preview showed the 250 px sidebar at x=0 while the main surface remained
  1328 px at x=0, proving overlay rather than reflow.
- The project trigger changed between `Collapse sidebar`/expanded=true and
  `Pin sidebar open`/expanded=false. Escape returned preview to collapsed and
  left focus on `project-sidebar-toggle`. No `Go to home` control existed and
  the URL did not change during sidebar interactions.
- Browser diagnostics contained no application errors; only the expected
  Clerk development-key warning and development HMR messages were present.

## Closing state

- The verified frontend development server was restarted on port 3000 after
  the production build; the backend remains on port 8000 against the isolated
  `clue_r2_damascus_20260810` database.
- R6 implementation, verification, and this session note are ready for the
  focused local commit `fix(shell): unify project sidebar behavior`.
- No remote push was performed.
