# Lane 2 Task 4 — project-document connection

- Founder approved step two after the MDXEditor prototype: implement the existing Plan Tab plan's
  Task 4 (model/repository/BFF), and explicitly reaffirmed the lane-plan index as authority.
  Semarang `visual-polish`; no Lane 1/backend/editor integration or environment changes.
- Added Zod wire/view/save models, canonical-path plan selection and edited labels. Reads retain
  status, nullable ICP key and front matter; writes allow only body and expectedRevision.
- Authenticated server reads list/open project documents. Browser GET/GET/PUT routes forward
  the frozen `/frontend/v1/projects/{projectId}/documents` contract through shared auth; PUT
  checks allowed origin and translates expectedRevision to expected_revision. No static tenant,
  browser credentials or fixture fallbacks. Backend statuses/body and request IDs survive.
- Browser saves keep raw Markdown, return new immutable IDs/versions, never retry/merge, and
  provide typed conflict/permission/network/unconfirmed-save errors without mutating caller data.
  Save implementation is `project-document-actions.ts`; server reads remain in the repository.
  Import that actions file from future editor hooks, not the server read repository.
- Removed only the unused ProjectPlan component/schema. Updated the canonical projects API
  contract and Task 4 checklist, including the actions split and document-wide conflict wording.
- Initial failing model test confirmed missing implementation. The direct tsx command first
  failed on sandbox IPC; node --import tsx ran focused tests, and approved npm test ran the full
  suite. Fixed test-runner env mocking and Intl's `Sept` vs required `Sep` label.
- A browser bundle check found that the originally combined read/save module included Node-only
  auth dependencies. The actions split follows Knowledge's existing pattern; a real esbuild
  browser-bundle regression now passes without server-only auth code.
- Verification: 2,245 frontend tests passed (17 new focused cases); design-system build passed;
  lint passed with only two existing unused-function warnings in design-engine canvasOperations;
  production Next build passed and includes both new route paths. Final focused lint/tests and
  git diff --check passed. A supplementary full `tsc --noEmit --incremental false` reports existing
  errors only in unchanged Brand Context, design-engine and research-task tests; no new files
  appear in its diagnostics. Evidence logs are under `.context/lane2-documents-*`.
- Runtime: direct in-app browser navigation to the API was blocked by the browser client. A
  read-only HTTP check against Semarang 3040 returned 401 AUTHENTICATION_REQUIRED as expected.
  No authenticated document save/refresh walk is claimed. Main frontend 3040 and prototype 3047
  retained their listener PIDs (62085/62879); no sibling process stopped or restarted.
- Follow-up: Task 5's Lexical coexistence decision/shared editor migration, then Task 6's Plan
  surface and draft lifecycle, Task 7's plan-part opening, Task 8's Gallery cards. The future UI
  must retain dirty drafts on failed saves, use returned IDs/revisions and gate editing through
  session permissions. Full browser save/reload/conflict acceptance belongs to those surfaces.
