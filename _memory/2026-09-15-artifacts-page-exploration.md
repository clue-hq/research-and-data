# 2026-09-15 — Artifacts page (`/artifacts`): exploration before integration planning (no code changed)

**Lane:** branch `artifacts-page` (worktree `melbourne`, target `integration/design-improvement`). Exploration only.

## Presentation truth (the dummy)

- `/Users/aryankeshri/conductor/workspaces/clue-frontend/port-of-spain`, commits `45892a6` "feat: add
  cross-project artifacts home" + `93c6120` "fix: align artifact controls with design system"; doc
  `docs/artifacts-home.md`. Route `src/app/artifacts/{page,loading,error}.tsx`; feature
  `src/features/artifacts/{components,data,hooks,model}` (~1.3 kLOC incl. 585-line CSS module).
- Data: `getArtifactLibrary()` = sidebar project list → `getProjectWorkspace(id)` per project in
  batches of 6 → `collectProjectArtifacts` dedups by `(projectId, artifactId)`. Reads
  `workspace.artifacts` (the dummy's fixture-backed `ProjectArtifact[]`). `failedProjects` surfaced
  as a warning; all-failed throws. Demo-only (no API base URL): saved/archived/rename/last-viewed in
  `localStorage` (`clue:demo-artifact-organization:v1`); with an API those controls are hidden and
  `update` throws "needs an artifact write API".
- UI: `ApplicationShell activeHref="/artifacts"`; header + "Create in chat" (→ `/`); collections
  All/Saved/Archived (Saved/Archived demo-only); `GalleryToolbar controller library` (adds Project
  group, Account/Type/Project A–Z sorts, Project filter section); grid reuses `GalleryArtifactCard`
  with a footer (project, save, download original); list = table (Name/Account/Type/Project/Last
  edited); `ArtifactLibraryPreview` `<dialog>`: image + page nav (`canvasPagePaths`), details
  (account/type/project/size/last edited), Open editor (`projectArtifactHref(...&edit=1`), Open
  source conversation, Copy link, Download preview via `ImageExportMenu` → canvas re-encode of the
  thumbnail (PNG/JPEG/SVG-wrapping-PNG/PDF), Original image, CSV for `tableContent`.
- Shared-file edits in the same commit: `project-gallery.ts` (+`project` on cards, `projectIds`
  filter, `project` group, three sorts, honest `defaultAccount` → "No account"), controller
  (`projects`, `toggleProject`), `gallery-toolbar.tsx` (`library` prop), `chat-shell.tsx` (demo
  organization plumbing), `artifact-stage.tsx` (thumbnail `<img>`), `use-image-export-controller`
  (`onExport` hook), `ProjectArtifactSchema` (+`projectId`, `projectTitle`).

## This repo today

Frontend (`apps/frontend`):
- `src/config/navigation.ts` already lists `/artifacts` (and `/templates`) under workspace nav;
  **no route exists** (`src/app/(protected)/artifacts` absent → 404). No `src/features/artifacts`.
- `workspace.artifacts` is the schema-hard empty tuple; real cards come from
  `loadGalleryFeed(backendDesignArtifactRepository(), projectId)` → `GET /api/v1/projects/{id}/design-artifacts`
  → `toProjectArtifact` (thumbnail `/api/clue/design/documents/{doc}/thumbnail?v=`), plus project
  documents from `GET /frontend/v1/projects/{id}/documents` rendered as document cards
  (`documentGalleryCards`). Gallery model diverged from the dummy (honest-absence account/size/type,
  `documents` type, `GalleryType`), so the dummy's diffs must be re-applied by hand, not copied.
- Card open goes through `galleryCardTarget` (chat-surface.tsx ~732): document → named tab; table →
  target-accounts; else `shell.openArtifact`. The artifact route `/projects/{id}/artifacts/{aid}`
  mounts `EditorSurface` from the feed (no `kind`/`edit` query needed).
- Server project list: `getSidebarProjects()` is fixture-only; HTTP sidebar loads client-side via
  `chatRequest` over the BFF (`resolveChatTransport`). Server reads use
  `fetchAuthenticatedClueBackend` / `fetchRead` (`/frontend/v1`).
- Real export exists (`use-scene-export` → design engine, 3 formats × 4 scales); the dummy's
  canvas re-encode of a thumbnail would be a downgrade.
- `/accounts/{id}/artifacts` exists but the backend serves `artifacts=()` (D0 ruling S9: account
  artifact binding is a later slice).

Backend:
- Per-project only: `chat/router.py` `GET /projects/{id}/design-artifacts` (leg-derived via
  `design_leg_wiring.project_design_documents`; `DISTINCT ON document` latest leg → origin thread;
  rows: id/title/status/doc_kind/current_version/created/updated/artifact_type/page px). No account
  on the wire. Sidebar `GET /projects/sidebar` is paginated (default 50, max 100).
- No workspace-wide artifact list, no artifact metadata mutations (rename/save/archive/last-viewed),
  no "artifact" table — the artifact id IS the design-document id (W1.3 v1 fallback).
- `design_document` carries a nullable `account_id` for 1:1 web pages (G2 ruling 2026-08-19;
  `design_accounts.get_web_account`) — not surfaced on the feed today.
- Project documents list is per project (`frontend_read/project_documents.py`).

## Founder rulings (2026-09-15, later the same day)

1. Data source: ONE workspace-wide read `GET /frontend/v1/artifacts` (Option A), never the dummy's
   per-project fan-out (sidebar pagination blinds it; no account on the per-project wire).
2. Whole library server-rendered by walking the cursor.
3. Project documents (plan/ICP/persona) are NOT in the library.
4. Account attribution Option B: name + domain from `design_account`, link to `/accounts/{id}` only
   when `account_entity_id` exists; the filter lists only accounts that appear on artifacts.
5. Download: ads = real engine export via `POST /documents/{id}/export` (design BFF; PNG 1x–4x,
   SVG, PDF); web pages = "Download preview (PNG)" = the thumbnail, no format menu. CSV: dummy's
   conditional stays (never renders).
6. Preview dialog kept as the dummy's. Open editor = create a NEW thread under the artifact's project
   (title = artifact title) and land with the artifact tab open via a new read-once `?open=<id>`
   param on the chats route (resolved against the project feed, canonicalized away; `?artifact=`
   stays forbidden). Open source conversation = the origin thread. Copy link = the editor route.
   Create in chat = Home.
7. ALL FOUR marks are built with real backend writes: rename + set-archived as governed design tools
   (`design_rename_document@1`, `design_set_document_archived@1`), registered UNGRANTED and
   human-only like `design_set_web_noindex`; saved + last-viewed as platform writes on
   `/frontend/v1` over a new `design_document_user_mark` table. Archive and publish are independent.
   Rename bumps `current_version` (title is derived from document JSON on every state write; the
   editor's 409 quiet-reload absorbs it); the editor header rename is wired to the same route.
   Archived rows leave `project_design_documents` (gallery, project library, agent listing);
   by-id reads unchanged.

Facts verified for the ruling: no bookmark/favourite/viewed table anywhere; `design_document.status`
is scene-derived free text (unusable as archive); no rename route exists on either side and the
editor's rename is local tab state; `erase_platform_user` updates in place (marks need an explicit
DELETE). Governance: design mutations must be toolbelt tools (`test_write_path_governance.py`),
authority table asserted at 134 (`test_tool_authority_audit.py`), precondition matrix in
`test_toolbelt_wiring.py`.

**Design spec written: `docs/superpowers/specs/2026-09-15-artifacts-page-integration-design.md`
(for founder review; no code yet).** **Implementation plan written 2026-09-15:
`docs/superpowers/plans/2026-09-15-artifacts-page-integration.md` — 16 tasks (lane + contract; two migrations;
workspace query + feed filter; the read; marks + erasure; design DAL; design tools/routes; authority entries;
frontend model/repos; gallery changes; document writes + ad export; library screen; `?open=`; header rename;
gates + walk). Execution not started.**

## Gaps (for the founder discussion, as first presented)

1. Route + feature missing entirely; nav link is dead today.
2. Data source: dummy's N×`getProjectWorkspace` fan-out vs one workspace-wide read
   (`/frontend/v1/artifacts` or `/api/v1/design-artifacts`) — sidebar pagination means the fan-out
   misses projects beyond page 1.
3. Documents: our gallery shows plan/ICP/persona cards; the dummy's home predates them — include?
4. Account attribution: feed carries none; `design_document.account_id` exists for web pages.
5. Organization writes (save/archive/rename/last-viewed): no backend; dummy hides them in API mode.
6. Download: reuse the real scene export vs the dummy's thumbnail re-encode; CSV needs
   `tableContent` (target-accounts cards are not design artifacts here).
7. Preview dialog's "Open editor" link shape (`?kind=&edit=1`) vs our route.
