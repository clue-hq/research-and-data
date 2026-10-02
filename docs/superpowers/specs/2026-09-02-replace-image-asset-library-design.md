# Replace Image — two sources (upload / workspace asset library) + Brand context uploads: design

**Status:** design approved in conversation 2026-09-02 (founder rulings inline); awaiting spec review,
then an implementation plan via the writing-plans skill.
**Surface:** platform editor only (`apps/frontend/src/features/design-editor` + the chat-shell
inspector components + `features/brand-context`). Scene (ad) documents. No engine (Rust) changes,
no design-API changes, no migrations, no brand-kit writes.
**Branching:** a new lane branch off `design/scene-ad-clipboard` (it touches the same session file;
branching from the clipboard head avoids a later conflict), in its own worktree.

## 1. Problem and outcome

The ad inspector's Image field has a single "Replace image" tile that opens the OS file dialog.
Two things are wrong with it today:

1. **Refusals are silent.** `hooks/use-scene-replace-image.ts` refuses four ways without a word —
   write path not armed (view mode / read-only engine), selection not an unlocked image, selection
   changed during the upload, and the picked file deduplicating to the asset already on the node —
   so an upload can "do nothing" with no explanation. (Verified live 2026-09-02: on the shipped
   branch a normal upload DOES replace the node; the reported symptom is one of these silent paths.)
2. **There is only one source.** A user cannot pick a picture the workspace already holds — a brand
   logo, a brand image, a prior upload, an AI-generated image.

Outcome: "Replace image" offers **Upload from computer** and **Choose from asset library**; the
library is the **workspace asset registry** with the brand kit's items pinned first; every upload
already lands in that registry (no brand-kit write); the **Brand context → Assets** page shows the
same library with an "Uploads" category; and every refusal in the replace path speaks.

## 2. Founder rulings (binding)

- **R-A** "Asset library" = the **workspace asset registry** (`GET /assets`), not the brand kit's
  curated `assets.images`. Uploads join it automatically via `POST /assets`; the brand kit is
  never versioned or written by this lane.
- **R-B** The picker shows **every image in the registry** — uploads, AI-generated images, and the
  brand kit's logos + brand images — in one grid, archived hidden, **kit items pinned first** and
  badged "Brand".
- **R-C** Chooser presentation: **option A** — the existing tile keeps its pill; the pill gains a
  caret and opens a two-row menu ("Upload from computer" / "Choose from asset library"), thin-stroke
  icons (~1.1px), regular weight, **no format enumeration** in the rows.
- **R-D** Picker presentation: **option 2** — a floating panel **anchored beside the inspector over
  the stage** (canvas stays visible), 4-across thumbnails, search + type filter, "Brand kit" and
  "Workspace" sections, "In use" badge on the node's current asset, footer = "Upload from computer"
  only; closes on ✕ / Esc / outside click.
- **R-E** **Click applies immediately.** Each thumbnail click is a real write (one undo frame); the
  panel stays open; no "Use image" confirm. Undo is the way back.
- **R-F** Brand context Assets page lists **kit items ∪ workspace registry images** (deduped by id);
  kit items keep their kit categories; non-kit registry images are **"Uploads"** (or "AI-generated
  images" when generated); the filter menu gains one entry; grid otherwise unchanged.
- **R-G** Approach 1 (client-composed library): no new backend endpoint; the editor and the Brand
  context page each compose the library from the two existing reads.

## 3. Ground truth (verified in-session, file:line at 2026-09-02 tree)

- `hooks/use-scene-replace-image.ts` — `createSceneReplaceImageHandler` sequencing: gate → upload →
  re-gate → `sceneImagePlacementOperations(node, record)` → `applyOps`. The four refusals throw
  `SceneReplaceImageRefused` without `onError`; only upload failures report.
- `adapter/scene-apply.ts:~1321-1345` — `sceneImageReplacementTarget(node)` (image kind, unlocked)
  and `sceneImagePlacementOperations(node, record)` → `buildNodePlacementOperations` =
  `[upsert_asset(record), place_asset_in_node(nodeId, assetId, placement)]`, alt text preserved;
  returns null when `asset_id` and alt text are unchanged (same-asset no-op).
- `features/chat-shell/components/inspector-primitives.tsx` — `InspectorImageUpload` (tile + pill +
  hidden `<input type=file accept="image/png,image/jpeg,image/webp,image/gif,image/svg+xml">`,
  local FileReader preview that reverts when `onFileSelect` rejects). `image-inspector.tsx:961`
  renders it with `disabled={inert}` and `onFileSelect={onReplaceImage}`.
- `hooks/use-scene-editing-session.ts:519` composes `useSceneReplaceImage` with the session's
  `writes`, `activeDocumentId`, `primaryNode`; the session already loads the brand kit detail
  (`fetchBrandKitDetail`) for fonts.
- `data/assets.ts:41` `uploadWebAsset` → BFF `POST /api/clue/design/assets` (multipart; shaped
  refusals). Design API `GET /assets` (`lumen_api/main.py:6993`): `kind`, `q`, `include_archived`,
  `limit≤200`, `offset` → `{assets: AssetRecord[]}`. `GET /assets/{id}` exists.
- Brand kit JSON `assets` = `{fonts, logos{<role>: {variants[{asset_id,…}]}}, images{<key>:
  {asset_id,…}}}` (`design_brand_kit.brand_kit_json`; versions immutable; `approval_status`).
- `features/brand-context/data/brand-context.repository.ts:77-105` `readWorkspace`: reads
  `/brand-kits`, the selected kit, then `GET /assets/{id}` per kit asset id. Categories
  (`hooks/use-brand-context-controller.ts:18-24`): all / logo / background / mockup / ai-generated.
  Detail dialog edits name/description through `brand-kit-actions.ts` (kit writes).
- Thumbnail/bytes URL: `adapter/scene-canvas-view.ts:404` `sceneAssetPassthroughUrl` (digest
  passthrough, the same resolver the canvas paints from). `AssetRecord.source.kind` ∈
  `uploaded | generated | edited | vectorized | website`.
- Design tokens (for the new chrome): Satoshi; page `#F8F9FB`, neutral `#FFFFFF`, borders
  `#D6D9E0` / subtle `#E6E9ED`, primary dark `#44483F`, radius 8–10px, shadow
  `0 1px 2px rgb(0 0 0 / 6.67%)` (+ a soft `0 8px 24px rgb(0 30 75 / 12%)` for floating panels).

## 4. Design

### 4.1 Components and data flow

- **`data/assets.ts` → `listImageAssets({ fetchImpl })`**: `GET /assets?kind=…&include_archived=false`
  for kinds `raster_image`, `vector`, `logo` (one request per kind, merged; `limit=200`, paged by
  `offset` until short). Returns `AssetRecord[]`; refusals shaped exactly like `uploadWebAsset`.
- **`adapter/scene-asset-library.ts` (pure)**: `composeAssetLibrary({ registry, brandKit, inUseAssetId })`
  → `AssetLibraryItem[]` = `{ record, pinned, inUse, category }`. Rules: kit ids = every
  `logos[*].variants[*].asset_id` ∪ `images[*].asset_id`; pinned items first (kit order), then
  registry by `created_at` desc; dedupe by id (kit wins); archived excluded; `category` per R-F
  (kit logo → `logo`, kit image → its kit role else `background`, registry generated →
  `ai-generated`, else `upload`); `inUse` = `record.id === inUseAssetId`. Plus
  `filterAssetLibrary(items, { query, category })` (label contains, case-insensitive; category
  `all` passes everything).
- **`hooks/use-scene-asset-library.ts`**: composed by the session beside `useSceneReplaceImage`.
  Binding `{ isOpen, open, close, items, loading, error, query, setQuery, category, setCategory,
  pick, refresh }`. Fetches on `open()` (never on mount); merges with the session's kit detail;
  `pick(assetId)` per §4.2; `refresh()` re-fetches (called after an in-panel upload).
- **`InspectorImageUpload` (chat-shell)**: the pill becomes a menu trigger (caret); menu rows
  "Upload from computer" (→ the hidden input, as today) and "Choose from asset library" (→
  `onOpenLibrary`). Icons thin-stroke; no format text. `accept` loses `image/gif`.
- **`AssetLibraryPanel` (chat-shell, new)**: props-only; anchored beside the inspector over the
  stage (absolute within the artifact workspace, left edge at the inspector's right edge, top
  aligned with the Image field, width ~300px, max-height the stage's, scroll inside). Header
  "Asset library" + ✕; toolbar search + category chip (same category labels as Brand context);
  sections "Brand kit" / "Workspace" with 4-across thumbnails (digest passthrough URLs; `alt` =
  label); badges "Brand" (pinned) and "In use"; footer "Upload from computer". Closes on ✕, Esc,
  outside pointerdown. Keyboard: arrow keys move focus across thumbnails, Enter picks.
- **Session wiring**: `use-scene-editing-session.ts` composes the hook and hands the binding down
  the same prop path `onReplaceImage` takes (`ImageInspector` → `InspectorImageUpload` /
  `AssetLibraryPanel`).

### 4.2 Write path and undo

`pick(assetId)`: guards at click time (armed document; `sceneImageReplacementTarget(node)`;
`writes.canApply()`), then `sceneImagePlacementOperations(node, record)` — the upload path's own
decision — and ONE `writes.applyOps(ops, "inspector: replace image from library")`. One undo frame
per click; the panel stays open; the "In use" badge moves to the picked item (the session's node
re-renders from the applied scene). Null from the adapter (same asset + same alt) → the sentence
in §4.3, no write. The in-panel "Upload from computer" calls the existing `onReplaceImage(file)`
then `refresh()`. Nothing writes the brand kit.

### 4.3 Error handling (all through `writes.reportError` → the inspector's existing error slot)

Replace handler (bug fix): before each `throw new SceneReplaceImageRefused(...)`, report —
- not armed / cannot apply → "This document isn't accepting edits right now."
- selection not an unlocked image → "Select an unlocked image to replace."
- selection moved during the upload → "The selection changed while the upload was running — try again."
- adapter null (same asset) → "That's the image already in use."

Picker: registry fetch failure → inline line in the panel (API's words) + Retry; the Brand kit
section still renders from in-memory kit data. Engine-refused pick → the engine's own message
(existing `applyOps` behaviour). Upload refusals unchanged (server detail verbatim). A pick is one
atomic batch: a refusal applies nothing and the panel stays open.

### 4.4 Brand context

`brand-context.repository.ts::readWorkspace` additionally calls `listImageAssets` and merges via
the SAME pure `composeAssetLibrary` (imported from `design-editor/adapter/scene-asset-library.ts`
— a pure, transport-free module, so the import crosses no seam the frontend architecture guards;
one implementation, one test suite, never a mirror). `BrandAssetCategory` gains
`upload`; `assetFilterOptions` gains `{ label: "Uploads", value: "upload" }` between Mockups and
AI-generated images; kit items carry a "Brand" badge on the card. Detail dialog: name/description
editing stays available for kit items (writes the kit, as today) and is **read-only for non-kit
items** with the note "Uploaded assets can't be renamed here yet." Sort/search/link unchanged.

### 4.5 Testing (node:test via `tsx --test`)

- `adapter/scene-asset-library.test.ts`: pinning order, dedupe (kit wins), archived excluded,
  category assignment for every `source.kind`, `inUse` marking, filter by query/category.
- `hooks/use-scene-asset-library.test.ts` (pure handler over a deps object, the lane's pattern):
  fetch on open not mount; `pick` builds exactly `sceneImagePlacementOperations`'s batch and calls
  `applyOps` once; same-asset pick reports and applies nothing; each guard's sentence; `refresh`
  after an in-panel upload; fetch failure surfaces + Retry re-fetches.
- `hooks/use-scene-replace-image.test.ts`: the four refusal sentences reach `onError` (red first).
- `data/assets.test.ts`: `listImageAssets` kinds, archived flag, paging, refusal shaping.
- Chat-shell logic files: chooser menu intent (which row → which action), panel close predicates
  (Esc, outside pointerdown, ✕), keyboard navigation — pure functions with tests; components stay
  logic-free.
- Brand context: repository merge against the fixture (`upload` / `ai-generated` categories,
  dedupe), filter option present, non-kit read-only detail.
- Rung close: `npm run design-system:build && npm run lint && npm run build`, full `npm test`
  (baseline 2462 pass / 0 fail after the clipboard lane), and a live walk on the nashville stack:
  both chooser rows; pick a brand logo, a prior upload, an AI image (three undo frames, ⌘Z×3
  restores); "In use" moves; in-panel upload appears at the top and is applied; each refusal
  sentence; Brand context shows the upload under "Uploads" with kit items badged.

## 5. Out of scope (v1)

Preview-then-commit picking (R-E chose immediate apply); renaming/describing registry assets from
the Brand context page; brand-kit membership changes of any kind; a server-side library endpoint;
multi-select; the web-document inspector.
