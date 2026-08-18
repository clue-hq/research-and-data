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
| `section` | `colors`, `typography`, `assets`, `knowledge` | Frontend view |
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

### Founder-ratified surface

- **Option A** is binding: the page header shows a status chip, secondary
  **↻ Re-extract**, and primary **Approve**, immediately left of the existing
  Light/Dark control. The row remains available in the Colors, Typography,
  Assets, and Knowledge headers.
- The chip reports the store without reinterpretation:
  `draft → Draft`, `generated_unreviewed → Generated — unreviewed`, and
  `approved → Approved`. With no kit there is no chip. After approval, Approve
  disappears; Re-extract remains.
- Empty Colors/Typography panels say **"Extracting your brand from your
  website…"** while any listed job is `queued` or `running`. Otherwise they say
  **"No colors yet."** / **"No text styles yet."** Data-bearing panels are
  unchanged.

### Approval

```text
POST /api/clue/design/brand-kits/{brand_kit_id}/approval
{"approval_status":"approved"}
```

The browser calls the authenticated design BFF only. On success it refreshes
the Server Component and renders the approval state returned by the store; it
does not optimistically claim approval. There is no un-approve affordance.
The design API updates only the lineage's latest version and mirrors the value
into both the row and `brand_kit_json.approval_status`.

Approval and extraction share one client single-flight guard. Both controls
remain disabled until the ingestion-job read succeeds, and Approve is disabled
while a job is active. This is required because the approval endpoint targets
the latest version: racing a publish could otherwise approve a newly extracted
draft the person has not reviewed.

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
  and the resulting version is always `draft`.
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
publish one additional identical **draft** version. This is accepted for Slice
4: nothing auto-approves, the page selects the latest version, and the human
gate remains authoritative. Closing it later requires a durable job-to-version
receipt (not inference from payload equality).
