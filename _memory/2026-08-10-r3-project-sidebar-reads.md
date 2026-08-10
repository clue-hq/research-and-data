# 2026-08-10 — R3 real project and sidebar reads

## Scope completed

- Implemented **R3 only** from the ratified chat-integration recovery plan.
- Added the real tenant-scoped project-shell read and batch-hydrated project/sidebar read, then moved the frontend project and sidebar repositories fully onto those HTTP contracts.
- Did not begin R4. The project-header hamburger hover/click overlay/reflow behavior remains later-slice work.

## Backend changes

- Added `clue_spine.get_project_for_workspace` so a foreign and an unknown project are the same SQL-scoped miss.
- Added `GET /api/v1/projects/{project_id}` with the exact ratified shell: durable project metadata, honest false composer capabilities, empty context/profile catalogs, and `artifacts: []`.
- Added `GET /api/v1/projects/sidebar` with limit 1-100, stable keyset pagination, real thread title/pin/activity/status, and no cross-workspace leakage.
- The sidebar projection selects a page of projects and joins every thread in one SQL query. Open gates and busy turns are each resolved once for the whole page, so the route uses three reads when threads exist rather than an N+1 pattern.

## Frontend changes

- Added strict project-shell and sidebar wire schemas and HTTP repository adapters to the shared chat-repository seam.
- HTTP project routes now load the real shell client-side through the authenticated BFF; failure stays an error and never substitutes the fixture workspace.
- HTTP project URLs ignore fixture-only prompt/model/entity/phase preview parameters.
- A real project renders the explicit empty Gallery and hides fixture-only Target accounts, model, context-reference, plan, questionnaire, and canvas-inspector controls.
- The main sidebar now renders only real project/thread rows in HTTP mode. Project pin, rename, and delete controls are hidden because no server mutation exists; fixture mode retains its preview-only local controls.
- Updated `apps/frontend/docs/api-contracts/projects.md` with the R3 as-built status and the retained R4 boundary.

## Verification

- Ruff passed for every changed Python/test file.
- Postgres-backed targeted regression: 35 tests passed across the thread projection, R2 Home bootstrap, R3 project/sidebar reads, chat thread surface, turn submission, and auth policy.
- R3 DB acceptance proves exact project shape, foreign/missing scoped 404s, project pagination, nullable thread-title fallback, tenant isolation, and exactly three sidebar reads with 12 threads.
- Frontend: design-token build passed; ESLint passed; `tsc --noEmit` passed; full unit suite passed 117/117.
- `next build` was stopped after the optimizer again remained idle with no diagnostics for more than one minute even after `next dev` had been stopped. No production-build success is claimed; this is the same repository/Turbopack stall recorded during R2, while type/lint/unit and live dev verification are green.
- In-app browser project verification loaded real `Untitled project` metadata and the real thread, rendered `Artifacts you create will appear here`, and proved the fixture campaign, model control, Target accounts control, and fixture Gallery cards absent.
- In-app browser Home verification showed only real project/thread rows. The project menu contained only `New chat` and `Archive chats`; Pin/Edit/Remove were absent. Browser diagnostics had no application errors (only Clerk's development-key warning).
- Backend/frontend logs independently recorded 200 responses for `/api/v1/projects/{project_id}`, `/api/v1/projects/sidebar`, and `/api/v1/home` through the authenticated BFF.

## Runtime and preservation notes

- Verification continued against isolated database `clue_r2_damascus_20260810` and disposable storage root `/private/tmp/clue-r2-browser-artifacts-20260810`; the shared database was not used.
- A browser-control locator mis-hit while returning from the open project menu and invoked the supported `New chat` action once, creating empty thread `thr_7529d0a3f5c7560cbc57d8643c9fc590` in the isolated verification project. It was not deleted or hidden afterward; the original verified thread remains the delivered browser tab.
- The isolated backend and frontend were left running for inspection.
- User-owned untracked `.artifacts/` was not changed or staged.
