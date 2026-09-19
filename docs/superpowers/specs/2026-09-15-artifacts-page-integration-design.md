# Artifacts page — frontend ⇄ backend integration design

**Status:** design for founder review, 2026-09-15. Nothing in this document is implemented.
**Branch:** `artifacts-page` (worktree `melbourne`, target `integration/design-improvement`).
**Discussion record:** `_memory/2026-09-15-artifacts-page-exploration.md`.
**Presentation truth:** the co-founder's dummy frontend at
`/Users/aryankeshri/conductor/workspaces/clue-frontend/port-of-spain`, commits `45892a6`
"feat: add cross-project artifacts home" and `93c6120` "fix: align artifact controls with design
system"; its own description is `docs/artifacts-home.md` in that checkout.

## 1. What this integrates, and what it does not

The dummy's `/artifacts` is the cross-project library over the same records the project galleries
show: grid and list views, search, sort, group, filters, a preview dialog with editor, conversation,
link, and download actions, and Saved / Archived / rename / last-viewed marks that live in browser
storage for the demo and disappear when an API is configured. This repo's `apps/frontend` already
lists Artifacts in the sidebar (`src/config/navigation.ts`) but has no route and no feature, so the
link is a 404 today.

Every screen element is lifted from the dummy and bound to real data at the repository seam, per
`apps/frontend/docs/architecture/frontend.md` and the presentation-truth rule: no invented UI, no
fixture data in HTTP mode, honest absence over fabricated values.

Founder rulings from the 2026-09-15 discussion fix the scope:

| Point | Ruling |
| --- | --- |
| Data source | One workspace-wide backend read (Option A), not the dummy's per-project fan-out |
| Page-load model | The whole library is server-rendered by walking the cursor |
| Project documents (plan, ICP, personas) | Not in the library |
| Account attribution | Name and domain from the design account row, plus a link to the Accounts screen when the account-entity join exists (Option B); the account filter lists only accounts that appear on artifacts |
| Download | Ads use the real engine export (PNG 1x–4x, SVG, PDF); web pages offer one Export — the design API's self-contained static-site zip (`GET /documents/{id}/web/export` through the design BFF) — with no format menu (founder ruling 2026-09-16 supersedes the thumbnail-only ruling) |
| CSV control | The dummy's conditional stays; no design artifact carries table rows, so it never renders |
| Preview | The dummy's dialog, unchanged |
| Open editor | Creates a new chat thread under the artifact's project and opens the artifact as an editor tab there, via a new read-once `?open=` param (ratified here; the forbidden `?artifact=` form is not revived) |
| Open source conversation | In scope; links to the origin thread |
| Copy artifact link | The artifact's editor route |
| Create in chat | Home (`/`) |
| Saved, Archived, rename, last-viewed | All four built with real backend writes |
| Archive vs publish | Independent: archiving never unpublishes, unpublishing never archives |
| The two new document tools | Registered ungranted and human-only, like the noindex tool |

## 2. Architecture

### 2.1 Where the code lives

**Platform backend (`platform/api/clue_api`).** One new module `frontend_read/artifacts.py` on the
existing `/frontend/v1` router: the library read and the two per-user mark writes. It rides
`CLUE_FRONTEND_READ_ENABLED`, the shared error envelope, and the workspace resolver. The
workspace-wide SQL lives next to the per-project feed query in `design_leg_wiring.py`, and the two
share one row mapper so nothing is written twice.

**Design subsystem (`subsystems/design/clue_design`, `subsystems/clue-design/apps/api`).** Two
governed document tools, rename and set-archived, following the noindex pattern exactly: a DAL
function, a store method, a `DesignTool` class registered in the design toolbelt, a route in the
design API that invokes it through `run_design_tool`, and an authority entry on the platform side.

**Frontend (`apps/frontend`).** A new feature `src/features/artifacts/` lifted from the dummy
(`components/artifact-library.tsx`, `components/artifact-library-preview.tsx`,
`components/artifact-library.module.css`, `model/`, `data/`, `hooks/`), the route
`src/app/(protected)/artifacts/{page,loading,error}.tsx`, and hand-applied changes to the shared
gallery files (`features/gallery/model/project-gallery.ts`, its controller and toolbar). The
dummy's browser-storage organization hook is replaced by repository calls.

### 2.2 Contract shape

Reads go through `fetchRead` on the server (`/frontend/v1`). Platform writes go through
`fetchMutation` over the same-origin BFF (`/api/clue/frontend/v1`). Document writes go through the
design BFF (`/api/clue/design`), the same seam the editor uses for its own document settings. The
frontend-authored contract is written to `apps/frontend/docs/api-contracts/artifacts.md` before
implementation, as the branch charter requires.

### 2.3 Authority

The library read and the mark writes require the project-read permission and, for the writes, a
resolved principal (user id and membership id from the request, as the bulk-action routes already
do; 401 when absent). The rename and archive tools are registered in `C6_AGENT_TOOL_AUTHORITY`
with no grant and listed in `_HUMAN_ONLY_TOOLS`; the design API's routes invoke them as
`actor="human"`. Granting either to an agent later is a reviewed profile version bump.

## 3. Backend surface

### 3.1 The library read

`GET /frontend/v1/artifacts?cursor=&limit=` → `{ data: { artifacts: [...] }, meta: { next_cursor } }`.
Default limit 50, maximum 200. Keyset cursor over `(updated_at DESC, id)` using
`clue_projections.pagination.encode_cursor` / `decode_cursor`; an unparseable cursor is `400
INVALID_CURSOR`, the accounts list's convention on this surface.

The row set is the workspace-wide form of the per-project feed: the design documents named by the
design legs of every thread in the workspace, one row per document with the latest leg's thread as
origin (`DISTINCT ON`), fail-closed on workspace at both the leg and the document. The ratified v1
gap carries over unchanged: a document no leg names belongs to no project and is not listed.
Archived rows are included (the library partitions them into the Archived collection); the
per-project feed excludes them (§3.5).

One row:

| Field | Source |
| --- | --- |
| `id`, `document_id` | the design document id (v1 identity mapping, as the feed) |
| `project_id`, `project_title` | the origin thread's project row |
| `kind` | `web` or `ad` from `doc_kind` |
| `title`, `status`, `current_version`, `created_at`, `updated_at` | the document row |
| `origin_thread_id` | the latest leg's thread |
| `artifact_type`, `width_px`, `height_px` | the document's own metadata, `null` when unrecorded (G-H) |
| `account` | `null`, or `{ id, name, domain, account_entity_id }` from the left join on `design_account` by `(account_id, workspace_id)`; `account_entity_id` is `null` when the spine join is absent |
| `archived_at` | `null` or the archive timestamp |
| `saved`, `last_viewed_at` | the caller's mark row, `false` / `null` when none |

Thumbnails are not on the wire; the frontend builds the existing BFF thumbnail URL from
`document_id` and `current_version`, as the gallery does.

### 3.2 Per-user marks

`PUT /frontend/v1/artifacts/{id}/saved` with `{ saved: bool }` → `{ data: { saved } }`.
`POST /frontend/v1/artifacts/{id}/viewed` → `{ data: { last_viewed_at } }`.

Both resolve the principal, confirm the document exists in the caller's workspace (`404
ARTIFACT_NOT_FOUND` otherwise), and upsert the caller's row in the marks table (§4.2). Setting the
same value twice converges. These are platform writes, not toolbelt tools: they are user metadata,
not document state, matching how the project-document PUT and the bulk actions already write on
this surface.

### 3.3 Rename

Tool `design_rename_document@1`, input `{ document_id, title }` with the title trimmed, non-empty,
at most 200 characters. Preconditions: the document exists in the workspace and is not finalized.
The DAL function, under the row lock, sets the `title` column and the document's own JSON title
(`meta.title` for a scene document, the top-level `title` for a web document) in one statement,
bumps `current_version` by one, and touches `updated_at`. The bump is deliberate: every scene and
web write rewrites the column from the JSON, so a rename that only touched the column would be
reverted by the next save, and a rename that changed the JSON without a bump would be overwritten
by an editor holding the old title. With the bump, an open editor's next write fails its
compare-and-set and takes its existing quiet-reload path. `replace_scene` already bumps without a
history row, so this is not a new pattern. Route `PUT /documents/{document_id}/title` on the design
API, returning `{ schema_version: 1, document_id, title }`.

### 3.4 Archive

Tool `design_set_document_archived@1`, input `{ document_id, enabled }` with `enabled` required
and no default (a caller who names no value cannot reach the tool, as with noindex).
Precondition: the document exists in the workspace. The DAL function sets `archived_at` to `now()`
or `NULL` and touches `updated_at`; no version bump, converges on re-run. Route
`PUT /documents/{document_id}/archived`, returning `{ schema_version: 1, document_id, archived_at }`.
Publishing is untouched in both directions.

### 3.5 Readers that change

- `design_leg_wiring.project_design_documents` gains `AND d.archived_at IS NULL`. This is the one
  statement behind the per-project gallery feed, the project library's artifact index, and the
  agent's artifact listing, so an archived document leaves all three at once.
- Single-document reads by id are unchanged: the editor route, the artifact read tool by id, the
  thumbnail, and the design API's own document routes still serve an archived document.
- `list_web_documents_for_account`, `list_running_runs`, and every publish path are unchanged.

### 3.6 Erasure

`clue_auth.store.erase_platform_user` gains one statement deleting the user's rows from the marks
table. The user row itself is never deleted, so a cascade cannot do this.

## 4. Schema changes

Two hash-id Alembic revisions off the current head, each with a matching `downgrade()`, gated by
`make db-smoke` on the lane's throwaway database.

### 4.1 `design_document.archived_at`

`ALTER TABLE design_document ADD COLUMN archived_at timestamptz NULL`, the shape of the noindex
column migration `4c02d8eac29a`.

### 4.2 `design_document_user_mark`

```
workspace_id    text        NOT NULL REFERENCES workspace (workspace_id)
user_id         text        NOT NULL REFERENCES platform_user (user_id)
document_id     text        NOT NULL
saved           boolean     NOT NULL DEFAULT false
last_viewed_at  timestamptz NULL
updated_at      timestamptz NOT NULL DEFAULT now()
PRIMARY KEY (workspace_id, user_id, document_id)
FOREIGN KEY (document_id, workspace_id) REFERENCES design_document (id, workspace_id) ON DELETE CASCADE
```

## 5. Frontend design

### 5.1 Feature layout

```
src/features/artifacts/
  model/artifact-library.ts          Zod wire → LibraryArtifact (ProjectArtifact + projectId, projectTitle,
                                     account, archivedAt, saved, lastViewedAt); dedup by (projectId, id)
  data/artifact-library.repository.ts  fetchRead walk of the cursor; fixture only when the projects
                                     transport is fixture mode, never as a fallback
  data/artifact-marks.repository.ts  saved / viewed via fetchMutation
  data/artifact-document.repository.ts  rename / archived via the design BFF; export for ads
  components/artifact-library.tsx    lifted; ApplicationShell activeHref="/artifacts"
  components/artifact-library-preview.tsx  lifted
  components/artifact-library.module.css   lifted
```

The page is a Server Component with `dynamic = "force-dynamic"`; it walks the cursor to the end
and renders the full library. The route's `loading.tsx` and `error.tsx` are lifted from the dummy.

### 5.2 Shared gallery changes, applied by hand

Our gallery model has diverged from the dummy's (honest-absence account, size and channel; a
`documents` type), so the dummy's diffs are re-applied onto it rather than copied: an optional
`project` on `GalleryArtifact`, a `projectIds` filter, a `project` group, the three `account-asc` /
`type-asc` / `project-asc` sorts, `projects` and `toggleProject` on the controller, and the
toolbar's `library` prop that adds the Project group, the three sorts, and the Project filter
section. The account filter's options come from accounts on artifacts only. The default sort is
last-viewed, using the caller's mark and falling back to `updated_at`.

### 5.3 Collections and marks

All = not archived; Saved = saved and not archived; Archived = archived. The Saved and Archived tabs,
the bookmark button on the card footer, and the preview's save / archive / rename controls are
always shown (the dummy hid them only because it had no API). Opening the preview posts `viewed`
fire-and-forget; a failure shows the dummy's "Preview opened. Last viewed couldn't be saved."
notice. After a rename or an archive the page re-reads (`router.refresh()`), so counts and
collections come from the server, never from local state.

### 5.4 Preview actions

| Action | Behaviour |
| --- | --- |
| Open editor | Create a thread under `projectId` titled with the artifact's title through the existing threads repository, then navigate to `projectChatHref(projectId, threadId, { open: id })` |
| Open source conversation | `projectChatHref(projectId, originThreadId)` |
| Copy artifact link | `projectArtifactHref(projectId, id)` on the current origin |
| Download (ad) | The existing export menu; `POST /documents/{id}/export` through the design BFF with the scene-export profile adapter; PNG 1x–4x, SVG, PDF |
| Export (web) | `GET /documents/{id}/web/export` through the design BFF; the self-contained static-site zip, named by the response's `content-disposition`; no menu |
| Rename | `PUT /documents/{id}/title`; then refresh |
| Save / Unsave | `PUT /frontend/v1/artifacts/{id}/saved` |
| Archive / Restore | `PUT /documents/{id}/archived`; then refresh and close |
| Account | Name with the favicon proxy by domain; links to `/accounts/{account_entity_id}` when present |
| Size | Shown only when the document records a page size |

### 5.5 The `?open=` param on the chats route

Read once at mount. The id is resolved against the project's own feed; an id not in the feed is
ignored. On a match the artifact tab opens (`shell.openArtifact`) and the URL canonicalizes to the
ordinary `surface=web|ad` pane state. Never emitted by the pane-state write-back. Documents are not
addressable by it (they have `?document=`). The contract doc records this as the answer to the open
2026-08-19 question on artifact identity in shared links.

### 5.6 Editor header rename

The editor's rename in the tab header is local state today. It is wired to the same
`PUT /documents/{id}/title` call, followed by a document reload, so the library, the gallery, and
the editor agree on the title.

## 6. Configuration and environment

No new flags. The read and the mark writes ride `CLUE_FRONTEND_READ_ENABLED`; the design routes
ride the design API's existing configuration. `.env.example` is unchanged. The lane needs its own
throwaway database and a stack wrapper next to the runbook, on the san-salvador pattern; this
worktree has no `.env` yet, so one is created at full key parity with `.env.example`.

## 7. Testing and acceptance

**Backend, on the lane database with the live-test glob excluded.**
`tests/api/test_frontend_read_artifacts_db.py`: two projects with documents; a legless document
excluded; another workspace's document excluded; the latest leg wins as origin; account present,
absent, and present without the spine join; archived rows included with `archived_at`; the
caller's marks joined and another user's marks not; stable paging across a cursor; 400 on a bad
cursor; 404 with the flag off. Mark routes: upsert, convergence, 401 without a principal, 404 on a
foreign document. Tool tests in the design API suite for rename (title and JSON updated together,
version bumped, finalized refused, empty title refused) and archive (converges, no version bump).
The three governance tests updated: `tests/agents/test_tool_authority_audit.py` (134 → 136),
`tests/api/test_toolbelt_wiring.py` (precondition matrix and counts), and the design API's
`test_write_path_governance.py` (`DESIGN_TOOL_NAMES`). The per-project feed test gains an
archived-row exclusion case. `make db-smoke` on both migrations.

**Frontend.** Node tests for the wire model, dedup, filters, sorts, grouping, and the `?open=`
resolution rule. The gate is `npm run design-system:build && npm run lint && npm run build` plus
`npm test`.

**Browser walk on the lane stack.** Real documents from two projects: counts, search, group by
project, the account filter, opening the editor in a new thread with the tab open on arrival,
opening the source conversation, copy link, an ad export in each format, a web Export zip,
rename reflected in the library and the gallery, archive and restore across collections, save and
unsave, last-viewed ordering, the empty state on a fresh workspace, and the flag-off behaviour.

## 8. Out of scope and follow-ups

- Account-scoped artifact binding beyond the design account stamp (the account workspace read's
  recorded later slice).
- A self-contained HTML export for web pages.
- Granting rename or archive to an agent role.
- A workspace-wide project-documents library.

## 9. Build order

1. Lane setup: database, `.env`, stack wrapper; the contract doc `apps/frontend/docs/api-contracts/artifacts.md`.
2. Migrations §4.1 and §4.2, `make db-smoke`.
3. Backend read §3.1 with its DB tests; the feed filter §3.5.
4. Mark writes §3.2 and erasure §3.6 with tests.
5. Design tools §3.3 and §3.4, routes, authority entries, governance tests.
6. Frontend feature §5.1–§5.4, gallery changes §5.2.
7. The `?open=` param §5.5 and the editor header rename §5.6.
8. Gates, browser walk, memory close-out.
