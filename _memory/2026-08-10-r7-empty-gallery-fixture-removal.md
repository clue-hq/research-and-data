# 2026-08-10 — R7 empty Gallery and fixture-state removal

## Scope

- Implemented repair Slice R7 only on `platform/lane-d-chat-launch`.
- Preserved the unrelated untracked `.artifacts/` directory and did not begin
  R8.
- No backend source or migration change was needed. R3 already returns the
  tenant-scoped project shell with exact `artifacts: []`; no real artifact read
  contract exists yet.

## Decisions and changes

- Reduced `ProjectWorkspaceSchema` to durable project metadata, advertised
  composer capabilities, and an exact empty artifact tuple. The real workspace
  model no longer accepts fixture plan, questionnaire, prompt, phase, model,
  agent-profile, or context-catalog state.
- Made the fixture project repository implement that same honest pre-artifact
  shell. The six fake Gallery cards and their fake plan/questionnaire/context
  payload were removed from the fixture workspace rather than retained as an
  HTTP-mode placeholder source.
- Removed fixture query parameters (`phase`, `prompt`, `model`, `entities`) from
  the project route. The project workspace controller now owns only draft text
  and conversation/artifact pane focus; dormant artifact-editor, model,
  questionnaire, phase, and context state is gone.
- Replaced the Gallery toolbar/card surface with a designed empty state:
  `No artifacts yet` and `Artifacts created in this project will appear here.`
  Target accounts, artifact editor, plan, questionnaire, search/filter/group,
  and fake card controls are not reachable from the project workspace.
- Artifact-detail routes return Next.js `notFound()` until a separately
  contracted project-artifact read exists.
- Added a transport test that resolves `CLUE_PROJECTS_API_BASE_URL` to HTTP,
  forces Home/project/sidebar failures, and proves all three reject with the
  typed API error rather than resolving any fixture.
- Recorded the R7 as-built state in
  `apps/frontend/docs/api-contracts/projects.md`.

## Verification

- `npm test` — 133 passed, 0 failed/skipped.
- Focused repository tests — 14 passed, including the new three-repository
  HTTP-failure/no-fallback case and exact empty project-shell assertions.
- `npm run lint` — pass.
- `npx tsc --noEmit` — pass.
- `npm run design-system:build` — pass.
- `npm run build -- --webpack` — pass: compilation, TypeScript, page-data
  collection, 8/8 static pages, optimization, and build traces completed. The
  existing parent-lockfile workspace-root warning remains informational.
- Database-backed `tests/api/test_project_read_surfaces_db.py` — 2 passed
  against isolated local database `clue_r2_damascus_20260810` after allowing
  the test process to access local PostgreSQL.
- `git diff --check` — pass.
- The first sandboxed TypeScript test attempt could not create its local IPC
  socket (`listen EPERM`); the same focused suite passed when rerun with the
  required local IPC permission. The first sandboxed DB attempts skipped
  because local PostgreSQL was inaccessible; the authorized local-DB run
  executed and passed both tests.
- React best-practices review: no component transport access, data-fetch
  waterfall, derived-state effect, repeated global listener, or uncleaned
  resource was added. Removing the dormant prototype state eliminated several
  unnecessary local state/effect branches instead.

## In-app browser evidence

- Real project `prj_85fe69f7aa8f5814b3e2506d65dcb215` rendered exactly
  one `No artifacts yet` heading and the designed explanatory copy.
- `Search artifacts`, `target accounts`, and `Print campaign` each had zero
  matches. No fixture toolbar or card content appeared.
- Navigating to the fixture-era project path
  `/projects/10m-landing-page-campaign` in HTTP mode rendered the controlled
  backend alert `no such project in this workspace`; neither its fixture title
  nor fixture cards appeared.
- Navigating to a guessed real-project artifact path ending in
  `/artifacts/print-campaign` rendered the framework 404. No local artifact was
  manufactured.
- The deliverable browser tab was returned to the real project's empty Gallery
  and finalized there.

## Closing state

- Frontend development server is running on port 3000; backend remains running
  on port 8000 with the isolated R2/R3 verification database.
- R7 changes and this note are ready for the focused local commit
  `fix(projects): remove hybrid Gallery fixtures`.
- No remote push was performed.
