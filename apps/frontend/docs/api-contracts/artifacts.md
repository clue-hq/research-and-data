# Artifacts API contract

Status: as-built contract for the cross-project artifacts library, ratified 2026-09-15.
Spec: `docs/superpowers/specs/2026-09-15-artifacts-page-integration-design.md` (repo root).

The dummy's `/artifacts` read `workspace.artifacts` per project. In this repo `workspace.artifacts`
is the schema-hard empty tuple; the library reads ONE workspace-wide endpoint instead.

## Reads (`/frontend/v1`, server, `fetchRead`)

`GET /frontend/v1/artifacts?cursor=&limit=` → `{ "data": { "artifacts": [...] }, "meta": { "next_cursor": string|null } }`
Default limit 50, max 200. Keyset cursor over `(updated_at DESC, id DESC)`; bad cursor → 400 `INVALID_CURSOR` (the accounts list's convention on this surface).
Rows are the workspace-wide form of the per-project design-artifact feed (leg-derived; a document
no leg names is not listed). Archived rows ARE included; the per-project feed excludes them.

Row: `id`, `document_id`, `project_id`, `project_title`, `kind` (`web`|`ad`), `title`, `status`,
`current_version`, `created_at`, `updated_at`, `origin_thread_id`, `artifact_type|null`,
`width_px|null`, `height_px|null`, `account: null | { id, name, domain|null, account_entity_id|null }`,
`archived_at|null`, `saved: bool`, `last_viewed_at|null` (the caller's own marks).
Thumbnails are not on the wire: `/api/clue/design/documents/{document_id}/thumbnail?v={current_version}`.

## Per-user marks (`/frontend/v1`, browser, `fetchMutation`)

`PUT /frontend/v1/artifacts/{id}/saved` body `{ "saved": bool }` → `{ "data": { "saved": bool } }`
`POST /frontend/v1/artifacts/{id}/viewed` → `{ "data": { "last_viewed_at": string } }`
401 without an authenticated principal; 404 `ARTIFACT_NOT_FOUND` for a document outside the workspace.

## Document writes (design API through `/api/clue/design`)

`PUT /documents/{id}/title` body `{ "title": string }` → `{ "schema_version": 1, "document_id", "title" }`
  Governed tool `design_rename_document@1`; bumps `current_version`; refuses a finalized document (409).
`PUT /documents/{id}/archived` body `{ "archived": bool }` → `{ "schema_version": 1, "document_id", "archived_at": string|null }`
  Governed tool `design_set_document_archived@1`; no version bump; archive and publish are independent.
Both tools are registered ungranted and human-only.

### Site documents (Wave 2 Contract 2; read by `src/features/site-editor/data/site.repository.ts`)

- `GET /documents/{id}` → for `doc_kind: "site"`: `{ id, doc_kind: "site", title, scene: <Contract 1 site>, current_version, undo_stack: [], redo_stack: [] }` (plan K4; anything but `site` is refused by the seam).
- `PUT /documents/{id}/site` body `{ site, base_version, intent? }` → `{ document: { id, current_version, doc_kind: "site" } }`. Refusals: 409 `edits.base_version_mismatch` (+ `current_version`), 422 `site.invalid` (+ `errors[]`), 409 `document.agent_run_active`, 409 `document.kind_unsupported`.
- `POST /documents/{id}/site/undo` · `/redo` body `{ base_version }` → `{ document, undone_batch_id | redone_batch_id }`; 409 `undo.empty` · `redo.empty`.
- `GET /documents/{id}/site/versions?limit=` → `{ versions: [{ batch_id, version, actor_kind, intent, created_at }] }`, newest first.
- `POST /documents/{id}/site/versions/{batch_id}/restore` body `{ base_version }` → `{ document }`; 404 `version.not_found`. The restore is itself an undoable write.
- `POST /documents/{id}/site/section-links` → `{ schema_version: 1, links: [{ name, digest, token, expires_at, props_schema }] }` (Contract 4; Lane B Task 16).
- `GET /documents/{id}/site/brand` → `{ schema_version: 1, brand: BrandData }` (Lane A Task 13).
- Refusal bodies are FastAPI `{ detail: { code, message, current_version?, errors? } }` or `{ detail: "<string>" }`.
- Save policy (frontend): one request in flight, edits coalesce into the newest site, a 409 shows "Document moved on — reloaded." and reloads; the app is the only side that saves.

## Chats route vocabulary

`?open=<artifactId>` on `/projects/:id/chats/:chatId` is read ONCE at mount, resolved against the
project's own feed (unknown ids are ignored), opens that artifact tab, and is never written back.
This answers the open 2026-08-19 question on artifact identity in shared links; `?artifact=` stays
forbidden. Documents keep `?document=<path>`.

## Library behaviour

Whole library server-rendered by walking the cursor. Collections: All (not archived), Saved (saved
and not archived), Archived. Default sort last-viewed (own mark, falling back to updated_at).
Account filter/group options come only from accounts on artifacts. Open editor creates a thread
under the artifact's project titled with the artifact's title and navigates with `?open=` and
`surface=web|ad`. Open source conversation → the origin thread. Copy link → the editor route
`/projects/:id/artifacts/:artifactId`. Downloads: ads = real engine export (PNG 1x–4x, SVG, PDF);
web pages = Export, the design API's self-contained static-site zip
(`GET /documents/{id}/web/export` through the design BFF). Create in chat → `/`.
