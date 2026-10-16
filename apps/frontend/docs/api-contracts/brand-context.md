# Brand Context API contract

Status: frontend-ready proposal for backend implementation.

Owner for backend integration: Aaryan.

The frontend currently uses `fixtureBrandContextRepository`. Setting
`CLUE_API_BASE_URL` switches the page read to the HTTP repository without
changing the route, controller, or visual components.

## Product boundary

Brand Context is a workspace-level source of truth with two domains:

- **Brand kit** — colors, typefaces, text styles, and approved visual assets.
- **Knowledge** — editable Markdown documents grouped into company, product,
  audience, proof, and memory folders.

The URL owns the visible view only. Persisted assets, font files, color tokens,
document content, share permissions, and version history remain backend-owned.

## Current read contract

### `GET /api/v1/brand-context`

Returns the complete Brand Context shell required for initial render.

```json
{
  "id": "clue-brand-context",
  "name": "Clue",
  "colorGroups": [],
  "typefaces": [],
  "textStyles": [],
  "assets": [],
  "knowledgeFolders": []
}
```

The response is validated by `BrandContextWorkspaceSchema` in
`src/features/brand-context/model/brand-context.ts`.

## Proposed mutation endpoints

### Colors

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `PUT` | `/api/v1/brand-context/colors` | Replace the approved semantic color groups atomically |

Color updates should validate a complete light/dark pair for each semantic
token and create a new immutable Brand Context revision.

### Typefaces and text styles

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/api/v1/brand-context/typefaces` | Register a library typeface |
| `POST` | `/api/v1/brand-context/typefaces/uploads` | Create a signed custom-font upload |
| `POST` | `/api/v1/brand-context/typefaces/uploads/:uploadId/complete` | Validate and attach an uploaded font |
| `POST` | `/api/v1/brand-context/text-styles` | Create a reusable text style |
| `PATCH` | `/api/v1/brand-context/text-styles/:styleId` | Update a reusable text style |

Accepted custom-font extensions in the frontend shell are `.otf`, `.ttf`,
`.woff`, and `.woff2`. The backend must validate MIME type and magic bytes,
enforce a size limit, scan the file, store license/provenance metadata, and
serve fonts from an allowlisted same-origin or CORS-enabled asset domain.

Suggested upload response:

```json
{
  "uploadId": "font_upload_01K...",
  "uploadUrl": "https://signed-upload.example/...",
  "expiresAt": "2026-08-10T23:59:59Z",
  "maxBytes": 10485760,
  "allowedMimeTypes": ["font/otf", "font/ttf", "font/woff", "font/woff2"]
}
```

### Assets

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/brand-context/assets` | Paginated asset list with search, category filters, and sorting |
| `POST` | `/api/v1/brand-context/assets/uploads` | Create a signed asset upload |
| `GET` | `/api/v1/brand-context/assets/:assetId` | Asset metadata and preview URL |
| `PATCH` | `/api/v1/brand-context/assets/:assetId` | Update title and description |
| `DELETE` | `/api/v1/brand-context/assets/:assetId` | Archive an asset |

Asset URLs should be short-lived delivery URLs or stable CDN URLs according to
workspace policy. The frontend must never receive storage credentials.

Asset records expose a stable `category` (`logo`, `background`, `mockup`, or
`ai-generated`), numeric `sizeBytes`, and ISO-8601 `createdAt` in addition to
their display labels. These machine-readable fields keep filtering and sorting
out of the visual components. The proposed list query is:

```text
GET /api/v1/brand-context/assets?q=&category=logo&sort=created&direction=descending
```

`category` is independent from the file MIME-derived `type`; a logo and a
mockup can both be images while remaining separate product filters.

### Knowledge

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/brand-context/knowledge` | Folder tree and document metadata |
| `POST` | `/api/v1/brand-context/knowledge/folders` | Create a knowledge folder |
| `POST` | `/api/v1/brand-context/knowledge/documents` | Create an empty Markdown document in a folder |
| `GET` | `/api/v1/brand-context/knowledge/documents/:documentId` | Markdown document and revision |
| `PUT` | `/api/v1/brand-context/knowledge/documents/:documentId` | Save Markdown with optimistic concurrency |
| `POST` | `/api/v1/brand-context/knowledge/documents/:documentId/share-links` | Create a scoped share link |

Recommended document write request:

```json
{
  "body": "# Company Overview\n...",
  "expectedRevision": 12
}
```

### Products (resolved 2026-10-15 — product management, spec `docs/superpowers/specs/2026-10-15-product-management-design.md`)

The brand's product list is the platform's `product` table; the Product folder's pages and the
catalog follow it. Served under `/frontend/v1/brand-context` (browser: through the BFF at
`/api/clue/frontend/v1/brand-context`). Writes need `project.write`.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/products` | `{brandId, products: [{productId, name, aliases, pageDocumentId, pagePath, pagePending}], recentChanges: [{changeId, kind, text, createdAt, undoable}]}` — active products and the last 30 days of changes |
| `POST` | `/products` | Add: `{name, description?}`; the page is written in the background (`pagePending: true`) |
| `POST` | `/products/:productId/rename` | `{name}`; the old name stays as an alias, the page moves to the new name's path |
| `POST` | `/products/merge` | `{productIds, intoProductId?, newName?}`; members leave the list, their pages are retired, a fresh page is written, every project using them moves to the survivor |
| `POST` | `/products/:productId/remove` | The product leaves the list and every project using it; its page is hidden, not deleted |
| `POST` | `/product-changes/:changeId/undo` | Undo a merge or a removal |

Each write returns `{changeId, kind, text, productId, productName, pageDocumentId, pagePath,
pagePending, projectsUpdated, projectsNeedingChoice}` (`pagePath`: where the product's page lives
now; the editor follows it after a rename). A catalog line's description is the first prose
paragraph of that product's page, and saving a product page regenerates the catalog. Refusals: `404 PRODUCT_NOT_FOUND | CHANGE_NOT_FOUND`,
`409 PRODUCT_NOT_ACTIVE | PRODUCT_NAME_TAKEN | CHANGE_NOT_UNDOABLE`,
`422 NAME_INVALID | MERGE_INVALID`.

Documents name their products in front matter: the tree and document reads carry
`productIds: string[]` and `generated: boolean` (the catalog generated from the product list).
The document `PUT` accepts an optional `productIds` (Product-folder documents only; exactly one for
a `product-research` page; active products of the brand only, else `422 PRODUCT_LINK_INVALID`), and refuses a hand edit of
the generated catalog with `409 CATALOG_IS_GENERATED`.

The backend should return `409 DOCUMENT_REVISION_CONFLICT` when the expected
revision is stale. Share links require explicit scope and expiration rather
than exposing the authenticated application URL.

The CodeMirror integration is a frontend editing surface only. The API accepts
and returns the original Markdown string; it must not persist CodeMirror state,
HTML, or an editor-specific document model. The two Knowledge header actions
map to the folder and document creation endpoints above.

### Asset inline edit behavior

The grid/list overflow menu exposes Rename, Edit details, and Delete. Rename
and the detail panel's title/description controls are independent edit targets.
Each completed edit should issue a narrow `PATCH` payload rather than replacing
the entire asset record:

```json
{
  "name": "Primary logo"
}
```

The backend response must return the updated asset and revision. A failed save
keeps the local draft visible and surfaces a field-level error; it must not
silently discard the user's value when the detail panel closes.

Delete maps to the archive endpoint above. The current fixture shell hides the
asset locally so the full interaction can be reviewed; production integration
must await a successful archive response and restore the item if that request
fails. Search, category-filter, and sort state remain local query controls and
are passed to the asset-list endpoint once pagination is connected.

## Frontend URL state

The shell uses shareable query parameters:

| Parameter | Values | Ownership |
| --- | --- | --- |
| `section` | `colors`, `typography`, `components`, `spacing`, `motion`, `assets`, `knowledge` | Frontend view |
| `theme` | `light`, `dark` | Brand-palette dataset; never an application theme |
| `view` | `grid`, `list` | Asset-list view |
| `asset` | asset ID | Open asset detail |
| `file` | knowledge path | Selected document |
| `mode` | `preview`, `edit` | Document view |

Search strings, open folders, unsaved edits, and dialog visibility are local UI
state and do not need to become backend fields.

---

## Resolutions (2026-08-18, Slice 1) — the read seam meets the real store

Everything above this line is the frontend-authored **proposal**. This section
records what the backend actually serves, which side moved, and every contract
decision the read seam now encodes. Slice 1 wires **READ only**; the proposed
mutation endpoints above stay proposed.

### Source of truth — the proposal moved

`GET /api/v1/brand-context` **does not exist and is not being built.** The
workspace's brand data already lives in the design subsystem's versioned
brand-kit store (`design_brand_kit`, migration `51db518c2a68`), served by the
design API. The page reads that store instead:

| Read | Endpoint (design API) | Purpose |
| --- | --- | --- |
| List | `GET /brand-kits` | One row per kit, at its latest version |
| Detail | `GET /brand-kits/{brand_kit_id}` | `brand_kit` summary + `brand_kit_json` (the kit itself) |
| Asset record | `GET /assets/{asset_id}` | Filename, media type, byte length, geometry |
| Asset bytes | `GET /assets/{asset_id}/bytes` | The image a card renders |

- **Which kit:** the workspace's **latest brand-kit version, ANY approval
  status** — this screen is precisely the review surface for a draft kit.
- **Multi-kit workspaces:** the most recently updated kit wins (`updated_at`,
  falling back to `created_at`). `GET /brand-kits` already collapses versions,
  so "newest kit" and "its latest version" are one selection.
- **The asset-registry read is an addition the frontend asked for.** The kit
  names its assets by `asset_id` only; the panel's name/type/size/dimensions
  columns come from the registry record. One read per asset, issued in
  parallel, and a refusal degrades that row rather than the page.

### Transport — the design API never faces a browser

- Browser-side design calls go through the authenticated BFF at
  `/api/clue/design/...`, which proves the platform session and stamps
  `X-Workspace-Id` server-side. **Asset `imagePath`s the page emits are always
  the BFF form** `/api/clue/design/assets/{id}/bytes` — never a design-API
  origin.
- The page itself is a Server Component and cannot call its own
  origin-relative BFF route, so it uses the server-side half of the same seam:
  `fetchAuthenticatedDesignBackend` (`src/auth/authenticated-backend.ts`), the
  design sibling of the existing `fetchAuthenticatedClueBackend` primitive the
  artifact route already uses. Same provider proof, same Clue-Postgres
  workspace re-authorization, same header. A browser-supplied workspace is
  never trusted on either path. The session is resolved **once per render** and
  shared by every read.

### Fallback semantics — the page can no longer 500

| State | What renders |
| --- | --- |
| `CLUE_API_BASE_URL` unset | The dummy fixture, exactly as lifted (local design work) |
| Configured, workspace has no kit | The designed **empty states** |
| Configured, design API refuses / session unprovable / payload unreadable | The same designed empty states |

Fixture content is **never** served to a configured deployment: showing another
company's colours to a real client would be a lie about their brand. There is
no new error affordance — that would be a new UI surface, which this slice does
not own.

### Per-section mapping

**colorGroups ← `brand_kit_json.tokens.colors`**
- Semantic roles (`surface.*`, `text.*`, `border.*`, `focus.*`) form ONE group,
  "Semantic roles"; each `palette.<family>.*` ramp becomes its own group
  ("Primary palette", "Neutral palette"). Semantic group first, then palettes
  alphabetically.
- Swatch `id` is the token path. Semantic swatches are labelled by their full
  path; ramp swatches by their stop (`50` … `950`), ordered numerically.
- `lightValue` is the token's `value.default`; `darkValue` is its
  `value.modes["theme.dark"]` — the selector the ingestion emitter writes its
  dark colorway under (`normalizer/roles.py::build_dark_colorway`).
- **A kit with no dark colorway reports `darkValue = lightValue`.** The dark
  toggle then shows the light palette, honestly, rather than a colour the brand
  never chose.
- `alias` values resolve through (bounded at 8 hops, per mode); `oklch` values
  render as CSS `oklch(...)`. A token that resolves to nothing drops its own
  swatch — one bad token never blanks the page.

**typefaces ← `brand_kit_json.assets.fonts`**
- `id` is the kit's font key, `family` the font family.
- `source` is **provenance, not file format**: an `AssetSource::System` family
  is `library`; anything else — a webfont captured from the client's own site,
  an upload — is `custom`, the brand's own face. A font with no source block
  stays `library` (we cannot claim it is theirs).

**textStyles ← `brand_kit_json.tokens.typography`**
- Ordered **largest font size first** (the type scale's own reading order); the
  wire's key order is not meaningful. Ties break on token path.
- `name` is the humanized token role (`type.body.small` → "Body small").
- **`lineHeight` is px, converted here.** The kit stores `line_height` as a
  unitless multiplier and the engine renders `font_size * line_height`
  (`text_measure.rs:563`); the table's column is px, so the mapper performs
  exactly that multiplication and rounds. A token with no line height reports
  its font size (ratio 1).
- `recommendedUse` is the token's own `description`, which website ingestion
  leaves null — so the column is **honestly empty**. Invented usage guidance
  would be words the client never wrote.

**assets ← `brand_kit_json.assets.logos` + `.images`**
- Logos first, then images; deduped by `asset_id`; image keys sort naturally
  (`img.2` before `img.10`).
- `visual` is always `{kind: "image"}` at the BFF byte path. **No gradients:**
  `constraints.allow_gradients` is a policy flag, not a colour-stop list, so no
  kit models a gradient and none is invented.
- `name`/`type`/`sizeBytes`/`sizeLabel`/`dimensions`/`createdAt` come from the
  asset registry record; without one the row shows the kit's own key and `—`
  for each unknown. `description` is the kit's `description`, else its
  `usage_note`, else empty (the describe pass is off by default).
- **`category` is the one lossy mapping, deliberately.** The screen's filter is
  a closed four-value enum (`logo | background | mockup | ai-generated`); the
  kit's image `role` vocabulary is `photo | illustration | screenshot | icon |
  og_image`. Resolution: logos → `logo`; `screenshot` → `mockup`; every other
  role → `background`. `ai-generated` is unreachable from website ingestion.
  Widening the enum to the kit's roles (or replacing the filter with them) is
  future work — see below.

**knowledgeFolders ← honest empty in v1**
- The kit has no markdown-document form. `constraints.tone` is a word list
  (e.g. `["clear", "professional"]`), not a document, and turning it into prose
  would put words in the client's mouth. The Knowledge section renders its
  designed empty state against a live kit. The dummy's knowledge fixtures show
  only in fixture mode.

**Workspace identity** — `id` is the brand-kit id, `name` the kit name; neither
is rendered today.

### Mutations — unchanged

Read only. Every client-side edit in the lifted screen (rename, delete, font
upload, markdown editing) stays client-side-inert exactly as lifted, and the
approval gate is a later slice. The proposed endpoints above remain proposals.

### Future work this slice deliberately did not do

1. **Brand knowledge documents** — a real markdown-document store behind the
   Knowledge section (and, separately, a tone/voice extraction that could feed
   it). No backend form exists today.
2. **Asset categories** — widen the screen's four-value enum to the kit's role
   vocabulary, so `photo`/`illustration`/`icon`/`og_image` stop collapsing into
   `background`.
3. **Asset geometry** — raster width/height are not measured at ingestion, so
   raster assets show `—` for dimensions; only vector assets carry a viewBox.
4. **Persistence for the lifted edits** — the proposed mutation endpoints.

---

## Resolutions (2026-08-18, Slice 4) — manual extraction and the approval gate

This section supersedes Slice 1's "Mutations — unchanged" paragraph for the two
mutations named here only. Rename/delete/upload/knowledge edits remain proposed
and client-local.

### Current surface (founder revision, 2026-09-21)

The Assets header contains **Upload assets** only. Re-extract, the approval
badge/action, and the Assets copy-link button have been removed. Its Type,
Used as and Source filters use the shared branded SelectField; the grid/list
control aligns with the fields, below their labels. Upload and asset-details
selectors use the same component.

Colors, Typography and Knowledge retain Re-extract for recovery. No Brand
context header offers approval or rejection. Empty Colors/Typography panels
still show extraction progress while a job is queued/running.

### Automatic approval

Successful website, PDF and asset-kit ingestion publishes an **approved**
brand-kit version. This happens in the ingestion worker after structural
validation, through the existing governed create/publish tool. No browser
approval request is needed. The authoring summary is computed with the approved
status so product-readiness diagnostics remain independent of approval.

Captured original website sections inherit their exact source kit version's
approval when registered, including sections arriving after publication. The
existing cascade continues to exclude dormant sections, deprecated sections
and individually reviewed repairs. Existing historical kit versions are not
rewritten. The low-level approval API remains available for compatibility.

The founder explicitly extended automatic approval to ICP/product targeting in
project chats. That flow is documented in `projects.md`: the agent applies the
selection through `configure_project_targeting@1` without an approval card.

### Re-extract

```text
POST /api/clue/design/brand-kits/ingest/website
{"url":"https://client.example","brand_kit_id":"brand_kit_ing_..."}
```

- `url` is the current kit's recorded website source, falling back to the
  newest website job's URL when the kit lacks one.
- `brand_kit_id` names the current lineage. If it already exists, the ingestion
  pipeline uses `design_publish_brand_kit_version` with the latest version as
  `expected_base_version`; the next number is allocated under the lineage lock
  and the resulting version is automatically `approved`.
- The manual wire does not accept a free-floating browser-authored `brand_id`.
  The exact join is stronger: the design DAL reads the lineage head under the
  same locked write and explicitly inherits its stored `brand_id`. A workspace
  gaining a second brand therefore cannot make a later version fall back to
  the ambiguous multi-brand heuristic or become unlinked.
- `queued`/`running` holds the button. The page polls only while state is
  unknown or active and refreshes when the job becomes terminal, so the newest
  published version replaces the prior one. A repeated click during the local
  request shares the same promise and creates no second POST.
- A failed first-time auto-ingestion may have no kit. In that bounded rescue
  case, the page enqueues the failed job's recorded website URL without a kit
  id; this is the original single-brand onboarding path. Failed jobs do **not**
  auto-refire—manual Re-extract is the only rescue.
- With neither a kit source nor a recorded website job, Re-extract is disabled
  with "No website on record". A URL input plus explicit brand picker for a new
  manual lineage is future work and needs its own founder UI ruling.

### Ingestion-job read addition

`GET /api/clue/design/brand-kits/ingest` (and the single-job endpoint) adds
nullable `website_url` to the public job DTO for `kind == "website"` only. It is
the workspace's own submitted URL, served behind workspace authorization.
The request object remains private; PDF/asset-upload request details are not
exposed and report `website_url: null`.

### Recovery residual

A client-supplied lineage's published kit currently carries no durable
producing-ingestion-job identifier. If a leased worker dies after publishing
the next version but before terminalizing its job, the reaper's re-offer can
publish one additional identical version. With automatic approval, this version
is approved too. The page selects the latest version. Closing this existing
recovery gap requires a durable job-to-version receipt (not payload equality).

---

## Resolution (2026-08-19, Slice 5) — approved kits theme new web documents

Brand approval affects document **birth only**. In the transaction that inserts a new WebDoc,
the design DAL stamps:

```json
{"theme":{"brand_kit":{"id":"brand_kit_ing_...","version":2}}}
```

when all of the following are true:

- the incoming WebDoc has no explicit `theme.brand_kit` reference;
- the workspace has exactly one platform brand, so its identity is unambiguous; and
- that brand has an approved kit version.

The chosen row is the latest **approved** version by store recency. A newer draft does not
shadow an older approved version. An explicit request reference always wins. A workspace with
multiple brands and no explicit reference remains unthemed rather than guessing; the future
multi-brand create contract must carry a `brand_id` or an explicit kit reference.

The inventory found three document-creation surfaces. Direct `POST /documents` and account
derivation converge on `clue_design.documents.create_document`; “save as template” uses
`clue_design.documents.create_web_template`. Both durable insert seams apply the same rule in
their write transaction, so the HTTP routes, design tools, and Gallery do not reimplement kit
selection.

This is intentionally **not** a `/web/theme` render fallback. Existing documents are never
rewritten when approval changes. A document created before approval keeps the platform-default
theme, and a document pinned to an older approved version stays pinned. Re-stamping an existing
document is future work and must be an explicit manual action with its own history/undo contract.
`GET /documents/{id}/web/theme` simply resolves the exact reference already stored on that
document and exposes those compiled tokens to the W4.0 color picker.

---

## Resolution (2026-08-20, design-brief slice 3) — the Knowledge section serves `design/Design.md`

This section supersedes Slice 1's **"knowledgeFolders ← honest empty in v1"** note and future-work
item 1, for the design brief only. Every other knowledge document remains unbuilt, and the
proposed `/api/v1/brand-context/knowledge/*` endpoints remain proposals.

### What changed on the backend

Website ingestion now runs a design-brief stage and attaches its output to the kit payload:

```jsonc
// GET /brand-kits/{id} → brand_kit_json
{
  "id": "brand_kit_ing_…", "version": 3, "approval_status": "approved",
  "tokens": { /* … */ }, "assets": { /* … */ },
  "brief": {                       // BrandBrief@1 — absent on a briefless kit
    "schema_version": 1,
    "characterization": { "words": ["expansive", "polished", "technical"], "support": "…", "confidence": "high" },
    "chromatic_moment": { "element": "…", "token": "surface.brand", "quiet": false, "confidence": "high" },
    "signature_compositions": [{ "name": "…", "structure": "…", "strength": "STRONG", "confidence": "high" }],
    "palette_application": [{ "token": "surface.brand", "scope": "accent-punctuation", "evidence": "…", "confidence": "high" }],
    "background_rhythm": { "bands": [{ "index": 0, "token": "surface.page", "note": "…" }], "ratio_summary": "…", "differentiation": "chromatic", "confidence": "high" },
    "typographic_posture": { "case_posture": "…", "scale_temperament": "stadium", "signature_moves": ["…"], "tokens": ["type.display"], "confidence": "high" },
    "imagery_posture": { "diet": "product-ui-led", "slots": ["…"], "absences": ["…"], "confidence": "medium" },
    "constraints": [{ "rule": "…", "scope": "buttons", "confidence": "high" }],
    "component_recipes": [{ "component": "button", "variant": "primary", "radius": "radius.button", "background": "surface.brand", "text": "text.inverse", "unmapped": ["…"], "confidence": "high" }],
    "diagnostics": [{ "observation": "…", "reason": "…" }]
  }
}
```

**No new endpoint.** The brief rides the brand-kit read the page already makes.

### What the page does with it

- `brand_kit_json.brief` → one knowledge folder **Design** holding one document
  **`design/Design.md`**, addressable at the section's existing route vocabulary:
  `/brand-context?section=knowledge&file=design%2FDesign.md&mode=preview`.
- **The markdown is a projection, never a second source of truth.** `renderBrandBrief`
  (`src/features/brand-context/model/brand-brief.ts`) is a pure function of the structured brief;
  the design agent consumes the structure, not this prose. Editing the document in the panel is
  client-local, exactly like every other lifted edit on this screen.
- The content header carries the kit's identity: `Brand kit: <id> · version <n> · <approval label>`,
  using the same ruled approval labels as the header chip.
- **D2 (founder-ruled): the rendered document is capped at 6,000 tokens**, estimated as
  characters ÷ 4 (this seam has no tokenizer). Past the cap the render drops whole trailing
  sections and says so, naming them; the stored structured brief is never truncated.
- **No brief → the file is simply absent from the listing.** A kit ingested before the brief
  existed, or one whose brief the agent refused, shows the section's designed empty state. A
  placeholder `Design.md` would read as "this brand has no design rules", which is a different
  and false claim.
- A `brief` in a shape this build cannot read parses to `null` (`.catch(null)`), so the document
  drops and the rest of the page is unaffected.

### Still future work

The dummy's other knowledge folders (Company, Product, Audience, Proof, Memories) stay absent —
nothing in the store fills them, and an empty folder tree is the honest report. A real
markdown-document store behind the section, and persistence for the lifted edits, remain
unbuilt.

## Resolution (2026-09-08, ARV2 O5) — the Knowledge folders serve the onboarding documents

This supersedes "Still future work" above for the Company, Product, Audience and Proof
folders. They are served from the platform's `brand_knowledge_document` store — the artifacts the
ARV2 onboarding run (`POST /onboarding`, O3) and the synthesis agent (O4) publish. Design keeps
riding the brand-kit read. Memories stays absent.

### Endpoints (platform API, `/frontend/v1`, `X-Workspace-Id` via the BFF / server seam)

`ARV2-ONBOARDING-PLAN.md` §7 wrote these under `/api/v1/brand-context/...`; they live on the
existing flag-gated read surface instead (same auth, tenant scoping, envelope and CORS as the
accounts screens):

| Read | Endpoint | Purpose |
| --- | --- | --- |
| Tree | `GET /frontend/v1/brand-context/knowledge[?brandId=]` | `{ brandId, folders: [{ key, label, documents: [{ id, path, title, kind, version, status, updatedAt, productId, icpKey }] }] }` |
| Document | `GET /frontend/v1/brand-context/knowledge/documents/{id}` | `{ …tree fields, markdown, frontMatter, sources: [{ section, url, title, confidence }] }` — 404 `KNOWLEDGE_DOCUMENT_NOT_FOUND`; 503 `KNOWLEDGE_STORAGE_UNAVAILABLE` |
| Onboarding status | `GET /frontend/v1/brand-context/onboarding/current` | `{ runId, status, steps: [{ kind, subjectRef, phase, status, startedAt, finishedAt, costUsd, failureCode }], costUsd }`; `status: "none"` when no run |

- **Which brand:** `brandId` when given and owned by the workspace; else the brand of the
  workspace's newest onboarding run; else the workspace's only brand; else an empty tree.
- **Servable only (founder ruling 2026-09-08):** `ready`, `proposed`, `confirmed`, highest such
  version per path. Running, empty, failed and superseded versions are not listed. The dummy has
  no status chip, so none is rendered; `status` rides the wire for a future slot.
- **Progressive fill:** the page polls the onboarding status while a run is `queued`/`running`
  and re-reads the tree when a step lands. No progress UI.

### What the page does with it

- Folders map onto the lifted `BrandKnowledgeFolderSchema` in the dummy's order — Company,
  Product, Audience, Proof, then Design (kit). `updatedLabel` is derived from `updatedAt` and
  not rendered. `title` is the document name.
- Bodies are read per document (parallel), like the asset registry reads.
- **Edit is gone (founder ruling 2026-09-08):** the Preview/Edit control is removed from the
  page for every document, Design.md included; the `mode` query parameter is ignored.
- Configured and refused → the four folders are honest empties; the fixture never serves a
  configured deployment.

The proposed mutation endpoints remain proposals.

## Resolution (2026-09-12) — Brand Context presentation repairs

The Knowledge tree uses fixed 32 px rows and non-shrinking 16 px document icons.
Long titles clip to the column and scroll once on hover or keyboard focus, returning
to the start; reduced-motion disables the animation and the full name remains
available as the button's accessible name and tooltip.

Knowledge bodies pass directly to `react-markdown` with `remark-gfm`. The custom
block parser and inline renderer are removed. CSS supplies the existing typography
for the library's semantic HTML, including tables, quotes, lists, links and code.
The page remains read-only: CodeMirror is the agreed library for future editing;
no document mutation endpoint or local editor is introduced by this repair.

The frontend font wire schema now retains the existing kit's `faces[]` fields:
`asset_id`, `source_url`, `weight`, and `style`. The typeface model adds optional
`faces: [{url, weight, style}]` and `previewFamily`. Stored faces use
`/api/clue/design/assets/{asset_id}/bytes`; when no stored asset exists, a recorded
HTTP(S) `source_url` is loaded by the browser (subject to that host's CORS policy).
Malformed faces and unusable URLs are omitted individually. The browser's `FontFace`
API registers the actual bytes under a kit/version-specific family, so two kits
cannot replace each other's sample. The sample waits for a successful font load;
missing or invalid files show “Font preview unavailable” instead of fallback glyphs.
An upright face closest to 400 is preferred, with its actual weight and style applied
without synthetic bold or italics. Every captured file for that variant is retained
so script subsets can load together. Unsourced library names must resolve to an
already registered or locally installed font. Replaced or unmounted previews release
their own registrations. Refreshed kit props update the typefaces without retaining
the initial font list; local additions and removals remain separate UI state.
No backend endpoint or stored brand-kit format changes.

Asset-detail images use the available preview width and height with `object-fit:
contain`; the 280 px cap and fixture-specific exception are removed. Description
and metadata remain alongside the preview on desktop and below it on narrow screens.

### Follow-up (2026-09-12) — Markdown Edit/Preview toggle

The founder subsequently requested a Markdown editing toggle. Knowledge now has
Preview and Edit controls. Edit lazy-loads CodeMirror with `@codemirror/lang-markdown`;
Preview passes the current draft directly to react-markdown + remark-gfm.
Discard changes restores the document read from the server. Drafts stay separate
per document path and survive switches between documents or Brand Context sections.
Switching Preview/Edit retains the current editor's undo history.

The founder subsequently authorized persistent edits (2026-09-12). **Save changes**
now calls `PUT /frontend/v1/brand-context/knowledge/documents/:documentId` through
the existing `/api/clue` BFF with `{ body, expectedRevision }`. It returns the same
detail shape as GET, with the new version and document ID. Selection stays anchored
to the document path. The repository owns transport and response validation.

Saving requires the workspace's authenticated `project.write` permission (or the
existing explicit local-header development mode). The backend records new immutable
artifact bytes, the editing user and source revision, and appends a document version.
It keeps original bytes and provenance. Stale revisions receive 409 and keep the
draft in the editor. An unchanged body creates no extra version. Failed reads and
the generated Design brief cannot be saved through this endpoint.

Editing a confirmed ICP creates a proposed version, clears the new version's old
approval fields, and retains the previously confirmed row for pinned projects.
Other replaced versions become superseded. No schema migration or new runtime
flag is required. Save failures preserve the draft; only a successful response
marks it Saved. Editing pauses during an in-flight save to keep its snapshot stable.
A browser unload warning applies while unsaved drafts exist.

CodeMirror uses its minimal setup and neutral design-token syntax styles: monospace
text, no line numbers, no folding gutter, no active-line color. The temporary-edit
banner is removed. The older O5 removal of Preview/Edit is superseded by this follow-up.

### ENG-182 asset preview follow-up (2026-09-12)

The asset dialog uses the available viewport up to 1440 × 960 px. The image fills
its display region with proportional `contain` sizing, preserving all artwork.
Desktop reserves 340–420 px for the details; at 820 px and below, the preview and
details stack. The details column spans the dialog height, with a fixed heading
and close control above independently scrolling content. Long names, descriptions
and source URLs wrap within the pane.
This is presentation-only and does not change the asset write contract above.


### Lane 2 shared Markdown editor (2026-09-14)

The approved MDXEditor replaces the Knowledge-specific CodeMirror editor. Preview is
shared `MarkdownArticle` (react-markdown + remark-gfm); editing is shared `MarkdownEditor`
with a client-only import of MDXEditor and native plugins. The PUT contract above is unchanged.
The frontend gates Edit on the authenticated workspace's `project.write` permission plus
a loaded, versioned document; the server remains the write authority.

Feature-owned sessions are keyed by workspace and document path, retaining raw saved body,
draft, base revision and returned immutable document ID. Initial Markdown normalization
and undo to the initial value do not create false drafts. Preview/Edit retains editor history.
Document switches retain drafts; clean external content and Discard explicitly reset the
editor. Dirty external refreshes keep the original save base, allowing the backend's 409
check to protect against overwrites. Failed saves keep the draft; editing is inert while saving.

Source uses the library's recovery UI. Import errors never substitute empty bytes. Source
drafts must return to valid Rich text before Save; editing itself may normalize Markdown.
Code blocks stay monospaced without a language picker or line numbers and retain their
fence metadata. Typography, colors and radii use Clue tokens; DM Mono is loaded locally.
Long inline code, URLs and source wrap; wide tables scroll inside the document.

> **Merge note (2026-09-17, PR #62 ← `research-streaming`).** The backport below was
> written while this branch lacked the ARV2 backend. After the merge the sections above
> govern: the Knowledge folders are served from the platform document store, and the
> Lane 2 shared Markdown editor replaces the read-only `react-markdown` panel. The
> asset-registry union and typeface `faces` handling from the backport remain in use.

## Local backport (2026-09-13) — Brand Context presentation

Adapted Aryan's `3903ae73`, `769b4994` and `79330214` changes from
`origin/brand-context-polish` onto Design Agent V1. The existing authenticated
brand-kit and asset read contracts remain in use; no onboarding API is added.

- Asset dialogs contain the full image within a larger responsive preview and
  keep long names/descriptions readable in the details column.
- Typeface mapping preserves the kit's `faces` (weight, style, asset ID and source
  URL). Stored faces use `/api/clue/design/assets/{id}/bytes`; remote fallback
  accepts HTTP(S) only. Font-family registration is namespaced by kit/version/role.
  A sample appears after the actual font loads, with explicit loading/unavailable
  states instead of a silent fallback. Refreshing the kit refreshes its typefaces.
- Knowledge uses `react-markdown` and `remark-gfm` for headings, lists, tables,
  links and code. Existing client-local drafts are still previewable. This does
  **not** persist edits or change the structured Design brief.

The newer onboarding Knowledge tree, polling and version-checked Markdown saves
(`2c100e8a`) depend on the upstream ARV2 backend/document store, absent on this
branch. They are not part of this backport. Importing the full upstream branch is
a separate contract and migration integration, not a presentation update.

Presentation changes do not rerun ingestion or increase source coverage. Current
website capture visits the entry URL plus explicitly supplied `page_urls`; it
does not discover linked pages. Ad-library harvesting remains a separate job.

## Asset context and bulk upload (ratified 2026-09-21)

Implementation follows the founder-authorized
[asset-context design](../../../../docs/superpowers/specs/2026-09-21-asset-context-and-bulk-upload-design.md).
The engine's asset record remains authoritative for custody, licensing and placement.
`design_asset_description` owns one generated analysis and field-level human overrides.

- `GET /assets/upload-capabilities` returns `max_bytes` and supported `formats`.
  The dialog reads the configured server limit. Advertised formats are PNG, JPEG,
  WebP, SVG and GIF. AVIF is not advertised. Animated originals are retained;
  visual analysis inspects the first frame and records that transformation.
- Multipart `POST /assets` accepts `Idempotency-Key`, `creative_type`, JSON-array
  `usage_roles`, `user_note`, and optional `brand_kit_id`. Brand association is
  explicit and workspace-validated. Registration, overrides, enrichment job and
  fleet offer commit together after byte custody. An identical replay returns
  the same asset/job; changed content or metadata under that key returns 409.
  The existing response adds `enrichment`, the effective metadata/status row.
- `GET /assets/descriptions?asset_ids=...` adds generated `analysis`, effective
  human-reference fields, `creative_type`, `usage_roles`, `classification_origin`,
  `overrides`, `source_occurrences`, `agent_context`, `revision`, `status`, and
  optional `diagnostic`. Reads batch up to 100 IDs. Legacy four-field readers remain valid.
- `PUT /assets/{id}/description` accepts partial title/description/usage/tags,
  type/roles, avoid/placement guidance and user note. Omitted fields survive.
  `reset_fields` removes named overrides; unknown fields or simultaneous assign/reset
  are rejected with 422. Changing a note marks prior analysis stale; a subsequent
  analysis receives the updated note. Human wording/classification never blocks
  refresh of other generated fields.
- `POST /assets/{id}/analysis/retry` returns the durable ingestion job. Active work
  returns 409; failed/stale assets reuse their stored originals and source history.
  `queued`, `analyzing`, `ready`, `failed`, `unsupported` and legacy `stale` are
  description states, independent of whether an asset's bytes are usable.
- Browser mutations use the authenticated design BFF. `X-Expected-Workspace-Id`
  is a precondition compared with the server-authorized workspace, never an
  authorization selector or forwarded credential. A workspace switch returns 409
  for pending requests selected in the previous workspace.

The repository reads every registry page independently of brand-kit existence,
joins metadata in batches, and supplies separate Type / Used as / Source filters.
The screen owns a three-transfer queue outside the floating dialog. Closing it
keeps transfers alive; per-file retries retain their idempotency key. Successful
files survive another file's failure. Server analysis continues through fleet
jobs after upload, independently of the browser. Reload reads persisted metadata.
Fixture and HTTP adapters implement the same operations; fixtures do not simulate
successful provider analysis.

### Asset inspector refinement (2026-09-22)

The inspector exposes **When to use** directly below the description, followed by
placement/composition and avoidance guidance when present. Pending or absent usage
guidance has an explicit empty state. Source evidence and agent interpretations
remain separate disclosures. Type and usage-role controls use the shared brand
controls; usage roles are native semantic checkboxes in one readable column.

Title, description and user context save automatically after 500 ms without an
edit and flush on blur. Type and role changes save immediately. There are no Save
buttons. A workspace-owned queue serializes writes per asset, keeps newer edits
visible while a write is pending, and preserves failed drafts with a Retry action.
Closing the inspector (button, backdrop or Escape) flushes pending edits first;
a failed save keeps the inspector open. Successful responses refresh effective
metadata, and older polling responses cannot overwrite a newer revision. This
does not add an API endpoint or change the write payload. Drafts are in-memory;
browser/process termination is not an offline persistence mechanism.

## Resolutions (2026-10-12, Wave 2 A9 Task X6) — the measured brand

The founder ruled (Q-A9-3 (c)) that the page shows what the brand-kit extraction measured on the
seller's site, drawn with the screen's existing components only.

- **The read keeps more.** `BrandKitJsonSchema` now keeps every token group the kit carries
  (`numbers`, `spacing`, `radii`, `stroke_widths`, `opacity`, `shadows` and `styles`, beside `colors`
  and `typography`), each token's `provenance`, `constraints.contrast_pairs` and `measured_components`
  (`MeasuredComponents@1`). It used to strip them. The design API already served them:
  `GET /brand-kits/{id}` returns the stored kit whole (`brand_kit_detail_dto`).
- **One reading, shared with sites.** Measured values are read through `@clue/site-kit/brand-view`,
  the functions that draw a published site, so a style is never described two ways.
- **`measured` beside `workspace` and `kit`.** `BrandContextView.measured` is `null` for a kit made
  before measurement, and the page is then exactly as it was. The designed `BrandContextWorkspace`
  shape is unchanged.
- **colorGroups** gain, after the kit's own groups, "Section backgrounds" (each `surface.band.<hex>`,
  named as the editor's Surface field names it, with its text colour) and one group per measured
  style ("Filled 1 button", "Card", "Link"), its swatches named by state and part ("Hover fill").
  Minted colours shown there leave "Semantic roles"; kit colours a style reuses (`surface.brand`) stay.
- **New sections** `components`, `spacing` and `motion`, listed in the sidebar only when the kit has
  something for them. Their words and their open design points are recorded in the Wave 2 plan
  (`docs/superpowers/plans/2026-10-12-lane-a-a9-brand-fidelity-rewrite.md`, T-A9-8 and DR-A9-1…10).
