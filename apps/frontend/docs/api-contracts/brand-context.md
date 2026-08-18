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
