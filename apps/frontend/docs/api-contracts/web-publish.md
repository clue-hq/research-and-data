# Web publish API contract

Status: resolved and implemented, 2026-09-02 (F5 multi-page sites and publishing).

Unlike the other files in this folder, this is not a frontend-authored proposal. The publish
surface already exists on the **design API** (`subsystems/clue-design/apps/api/lumen_api/main.py`)
and the shell was wired to it; this file records the contract as it actually is, per the branch
charter's rule that a resolved contract decision is written back here.

## Boundary

The design API speaks workspace-header auth (`X-Workspace-Id`) and never faces a browser. Every
call below goes through the BFF proxy at **`/api/clue/design/...`**
(`src/app/api/clue/design/[...path]/design-proxy-handler.ts`), which proves the platform session,
re-authorizes the workspace, and stamps the workspace header server-side. Browser-supplied
credentials and workspace headers are dropped. Only `accept`, `content-type`, `idempotency-key`,
and `last-event-id` cross.

The shell talks to publishing only through `WebPublishRepository`
(`src/features/design-editor/data/web-publish.repository.ts`), which has a fixture adapter and an
HTTP adapter over the routes below. The share menu never sees a URL it built itself.

## Rulings this surface implements

- **R-F5-1 — the public URL shape is configuration.** No host constant is compiled into the API or
  the client; the server computes every absolute URL.
- **R-F5-2 — the publish unit is the SITE.** All pages go up under one slug in one revision; there
  is no per-page publish state.
- **R-F5-3 — the dialog slug is the site slug**, and the home page keeps the route `/`.
- **R-F5-4 — indexing law is unchanged.** An ordinary site follows the toggle; the server ORs the
  document's durable ABM `noindex`, so the toggle can never un-noindex an ABM account page.
- **R-F5-5 — the workspace handle** is auto-derived, editable until the first publish, and frozen
  after it (a live URL's host does not move).

## URL shape

Host mode, once `LUMEN_PUBLIC_PAGES_HOST_SUFFIX` is set and the workspace has a handle:

```text
{handle}.<LUMEN_PUBLIC_PAGES_HOST_SUFFIX>/{slug}{route}
```

Interim mode — the default, when the suffix is blank — serves from the request's own origin:

```text
{origin}/w/{workspace_id}/p/{slug}{route}
```

The route `/` is the site root, so the home page is the bare slug in both modes.
`LUMEN_PUBLIC_PAGES_SCHEME` (default `https`) picks the scheme in host mode. Both variables are
read at call time, and both are owned by `lumen_api/public_address.py`.

## `GET /documents/{documentId}/web/publish`

The document's durable publish state. Unpublished:

```json
{ "schema_version": 1, "published": false }
```

Published:

```json
{
  "schema_version": 1,
  "published": true,
  "slug": "abm-openai",
  "url": "https://acme.pages.cluehq.ai/abm-openai",
  "doc_version": 7,
  "status": "active",
  "publish_id": "pub_01K...",
  "manifest_digest": "sha256:...",
  "package_digest": "sha256:...",
  "html_digest": "sha256:...",
  "previous_available": true,
  "updated_at": "2026-09-02T18:04:11Z",
  "pages": [
    { "route": "/", "page_id": "page_home", "html_digest": "sha256:..." },
    { "route": "/proof", "page_id": "page_proof", "html_digest": "sha256:..." }
  ],
  "page_urls": {
    "/": "https://acme.pages.cluehq.ai/abm-openai",
    "/proof": "https://acme.pages.cluehq.ai/abm-openai/proof"
  }
}
```

`url` is absolute and is the site root. `pages` is html-free by design — route, source page id,
and that page's html digest, ordered by route. A pre-F5 publish has no page rows and answers with
an empty `pages` list; it still serves its single page at `/`, and `page_urls` still carries that
one route.

`page_urls` is the only place a public address comes from (R-F5-1). The client must render these
rather than joining `url` to a route itself: only the server knows whether this workspace's sites
are on their own host or on the interim tenant path.

## `POST /documents/{documentId}/web/publish`

Publish or republish. Body (`WebPublishRequest`), both fields optional:

```json
{ "slug": "abm-openai", "noindex": false }
```

An omitted or empty `slug` is derived from the document title. `noindex` defaults to `false` and
can only ADD the robots meta — the tool ORs the document's durable ABM flag (R-F5-4). An
`Idempotency-Key` header is accepted and forwarded.

Response:

```json
{
  "schema_version": 1,
  "slug": "abm-openai",
  "url": "https://acme.pages.cluehq.ai/abm-openai",
  "doc_version": 8,
  "runtime_version": "...",
  "publish_id": "pub_01K...",
  "manifest_digest": "sha256:...",
  "package_digest": "sha256:...",
  "html_digest": "sha256:...",
  "previous_available": true,
  "routes": ["/", "/proof"],
  "page_urls": {
    "/": "https://acme.pages.cluehq.ai/abm-openai",
    "/proof": "https://acme.pages.cluehq.ai/abm-openai/proof"
  }
}
```

`routes` is every route this publish put on the air, in document order; `page_urls` is their
absolute addresses. A server predating these fields answers with an empty list/map, and only then
does the HTTP adapter fall back to joining `url` to `routes`.

Refusals (all `{"detail": {"code", "message", ...}}`):

| Status | Code | Meaning |
| --- | --- | --- |
| 422 | `web_publish.bad_slug` | Slug fails the public-slug charset |
| 409 | `web_publish.slug_taken` | Another document already publishes at this slug |
| 409 | `document.kind_unsupported` | The document is not a website-mode document |
| 422 | `web_publish.unresolved_markers` | The page still carries `{{account.…}}` markers; carries a `markers` list |
| 409 | `web_publish.revision_conflict` | A publish-revision content address was re-used with different content; carries `publish_id` |
| 409 | `document.agent_run_active` | A design run is working on the document; carries `run_id` and no `message` |
| 502 | `web_export.failed` | The static export compile failed |

`document.agent_run_active` is the founder's 2026-10-13 ruling: a person's publish waits for the
design run to finish (`POST …/site/publish` refuses the same way; unpublish, rollback and this
route's `GET` stay open; the agent's own publish tool is not locked). The share menu disables
Publish while it can see the run and, on this refusal, shows the same line instead of the code:
"The design agent is working — publishing unlocks when it finishes."

A successful publish also **locks the workspace handle** — idempotently, and only on success, so a
refused publish leaves the marketer free to keep choosing.

## `DELETE /web/publishes/{slug}`

Take the site offline. Accepts `Idempotency-Key`. Returns:

```json
{ "schema_version": 1, "slug": "abm-openai", "status": "unpublished" }
```

404 `web_publish.not_found` when no publish exists for the slug.

**Unpublish is in the seam, no designed control.** `WebPublishRepository.unpublish` exists and the
HTTP adapter calls this route, but the designed share menu has no button that reaches it. Nothing
is invented in the UI to fill the gap — a designed control is a founder/design decision.

Also present on the design API but **not** in the shell's seam: `POST /web/publishes/{slug}/rollback`
(a current↔previous swap; a blind retry is destructive, so it is idempotency-keyed).

## `GET /workspace/handle` and `PUT /workspace/handle`

The handle is the DNS label this workspace's published sites hang off (R-F5-5).

`GET` **mints** the name-derived default rather than answering "none yet" — every workspace has an
address from the moment it exists, and a publish would have derived the same label anyway. Both
verbs return:

```json
{
  "schema_version": 1,
  "handle": "acme",
  "locked": false,
  "locked_at": null,
  "public_host": "acme.pages.cluehq.ai"
}
```

`public_host` is `null` whenever `LUMEN_PUBLIC_PAGES_HOST_SUFFIX` is unset (the dev default) —
reporting a host that has no DNS would be a URL nobody can open.

`PUT` body is `{"handle": "acme"}`. The field is required and un-defaulted: a body that forgets it
is a 422, never a silent re-derivation. Refusals:

| Status | Code | Meaning |
| --- | --- | --- |
| 409 | `workspace_handle.locked` | The workspace has already published; the handle is frozen |
| 409 | `workspace_handle.taken` | Another workspace holds this handle |
| 422 | `workspace_handle.invalid` | Not 3–63 lowercase letters/digits/inner dashes, or a reserved name |

No shell surface calls either verb yet; the handle is minted and locked server-side by the publish
path.

## Designed but unwired

Three fields exist in the share menu's advanced settings and have **no backend contract yet**.
They are flagged at their state in `src/features/chat-shell/hooks/use-artifact-sharing-controller.ts`
and persist nothing; `saveAdvancedSettings` only emits a client event.

| Field | Where | Status |
| --- | --- | --- |
| Description (300 chars, plus its "Generate" button) | Advanced → Page settings | No backend contract yet |
| Regenerate description on publish (toggle) | Advanced → Page settings | No backend contract yet |
| Custom HTML (head markup) | Advanced → Custom HTML tab | No backend contract yet |

The one advanced control that reaches the backend is **Allow search engine and AI indexing**,
which sends `noindex: !allowIndexing` on publish. The **Title** field is not flagged, but it is
not part of any publish request body either — like the three above, it rides only in the client
`clue:artifact-publishing-settings-update` event.
