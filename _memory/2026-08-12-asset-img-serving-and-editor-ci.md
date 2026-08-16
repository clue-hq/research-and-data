# 2026-08-12 — Public asset serving for `<img>` (O4 seam) + editor CI port

Branch `integration/frontend-design-part-ii`. Two follow-ups from
`2026-08-12-editor-lumenfetch-defaults-fix.md`, both founder-directed: (1) close the
`<img src>` 401 class by extending `/asset-store/{digest}` content-addressing; (2) restore
editor CI.

## 1. The `<img src>` class — design

An `<img>` cannot send `X-Workspace-Id`, so the registry routes
(`/assets/{id}/bytes|thumbnail`, workspace-gated) can never serve it. The ratified shape:
image `src` URLs are always PUBLIC content-addressed `/asset-store/{digest}` (O4-exempt,
gated by the unguessable sha256; the same URLs lumen-web's published pages emit, ruling
R-D4-7), or nothing.

- **API** (`lumen_api/main.py::public_asset_record`): stamps `media.thumbnail.digest` (and,
  defensively, a missing `media.digest`) at the response boundary using
  `clue_design.storage.location_digest` — ref parsing stays server-owned; no client ever
  takes an `opaque_ref` tail. Applied at all 8 asset-record response sites (upload, qr,
  cached-generate, generate, archive, restore, get, list). Read-time + non-mutating (stored
  rows keep their shape). TDD'd in `tests/test_asset_store_serving.py` (DTO carries thumb
  digest; digest serves headerless; thumbnail-less + foreign-provider records unstamped).
- **Editor engine** (`engine/assetLibrary.ts`): `publicAssetBytesUrl` /
  `publicAssetThumbnailUrl` (record → URL | null; thumbnail prefers its own digest, falls
  back to full bytes — heavier but correct), `fetchAssetRecord` (`GET /assets/{id}` via
  lumenFetch default, 404 → null; pinned in workspaceHeaderDefaults). The registry URL
  builders are **deleted everywhere** (assetLibrary's `assetBytesUrl`/`assetThumbnailUrl`,
  brandHub's `assetBytesUrl`, brandLibrary's `assetPreviewUrl`/`assetFullUrl`) — the class
  is unrepresentable; the bare-fetch guard's philosophy applied to URLs.
  `sceneAssetBytesUrl` digest-less fallback → **null** (was a guaranteed-401 registry URL
  into imageCache's bare fetcher); imageCache already modeled null = skipped load.
  `contracts.AssetThumbnail.digest` added.
- **Hook** (`hooks/useAssetPreviewUrl.ts`): id-only sites resolve id → record (cached
  per-page-load Map; transport failures not cached) → public URL. Direct-record sites call
  the builders.
- **Components — nine surfaces** (audit said 8; `AssetPreviewImage` was a ninth):
  record-direct: AssetBrowserPanel, WebAssetDrawer, KitLogoPicker, ImageInspectorSection
  (candidate + the node's `asset` prop), EditorApp upload-reference thumb
  (`PendingReference.thumbnailUrl` now `string | null`, AgentChatPanel tolerant); hook:
  KitLogosSection, KitImagesSection (new in-file `KitImageThumb`), WebBatchDialog logo,
  AssetPreviewImage (rewritten; its onError registry-retry dance retired). KitLogosSection/
  KitImagesSection/AssetPreviewImage dropped their `apiBaseUrl` props (callers updated).

## Verification

- API: `test_asset_store_serving.py` 13/13 (3 new, RED→GREEN); custody + seam + describe
  suites 43 passed. Throwaway DB `lumen_imgfix_test` (migrated to `0bb98da7b5bb`).
- Editor: engine tests rewritten to the new contract (12/12, RED 11 first);
  workspaceHeaderDefaults now 19 pins; full suite 1094 passed with exactly the documented
  26 pre-existing failures; lint (hex + lumenFetch guard + tsc) clean; production
  `next build` green.
- **Browser (live, real Chrome via Playwright):** restarted the dev API (new code), uploaded
  a real PNG (`POST /assets` → DTO carries digest; 1×1 PNG gets no engine thumbnail → the
  full-bytes fallback path is what live-verified), created brand kit
  `brand_kit_imgfix_verify` from the acme_full fixture pointing logos+images at the upload.
  `/brand` lists it; kit detail renders mark logo + primary logo + hero image all
  `complete=true naturalWidth=1` from `/asset-store/{digest}` with exactly ONE
  `GET /assets/{id}` (hook cache dedupes across cells); logo picker grid renders; editor
  Assets panel thumbnail renders from `/asset-store/`. Zero 401s anywhere in the session.
  Headerless `curl /asset-store/{thumb-or-bytes digest}` → 200.
- Not browser-driven (mechanism identical to verified surfaces, unit-covered):
  WebAssetDrawer/WebBatchDialog inside the web editor flow; canvas placement (happy path
  byte-identical pre/post — it already used `/asset-store`; only the broken fallback became
  null).

## 2. Editor CI (`.github/workflows/editor-checks.yml`)

The old gate (`subsystems/clue-design/.github/workflows/conformance.yml`) is DEAD since the
subtree merge — GitHub runs only root `.github/`. Ported the browser-wasm-core job to the
root: paths-filtered `subsystems/clue-design/**`; npm ci → `build:wasm` (+ size budget) →
`npm run lint` → vitest excluding the two documented pre-existing red files (loud header;
fixing those 26 = deleting the excludes) → `NEXT_PUBLIC_LUMEN_WASM_CORE=1 npm run build`.
Local proof: exclusion run = 1062 passed / 0 failed; yaml parses; build green. The old
conformance.yml's rust/api jobs are deliberately NOT ported here (separate decision — the
api-persistence job predates the Postgres port; rust gates belong with the crates owner).

## 3. API route-table seam guard (added same day, founder go-ahead)

`apps/api/tests/test_workspace_seam_route_table.py` — closes the server-side twin of the
client guard: seam enforcement is per-route opt-in (`Depends(repository)` by hand), which is
how `/font-library` and `/agent/turn-preview` sat accidentally exempt until D2.5A. The guard
walks ALL APIRoutes issuing headerless requests: everything must 401
`workspace.header_required` except a justified ALLOWLIST (the six ratified exemptions:
/build-info, /asset-store/{digest}, the three /w/{ws}/p* public-serving routes, the
token-gated events GET). Drift guarded both directions (an exempt route that starts
demanding the header also fails). Detection power pinned by a self-test that plants an
ungated scratch route and asserts it's flagged. First run: 113 routes, zero violations
(107 gated + 6 allowlisted — matches the D2.5A inventory exactly).

## Residuals / notes

- R-D4-7 unchanged: `/asset-store/{digest}` resolves across tenants by ruling; Part-IV auth
  owns the serving policy for workspace-scoped blobs. This work widened *usage*, not the
  exposure class.
- Registry routes `/assets/{id}/bytes|thumbnail` remain, header-gated, for API clients
  (curl/tools) — they are simply no longer browser `<img>` surfaces.
- Dev-DB seeds left in `lumen_design_dev`: `asset_89c1dc8f6196` ("Verify logo"),
  `brand_kit_imgfix_verify` (v3) — synthetic, harmless, reusable for future live checks.
  Throwaway test DB `lumen_imgfix_test` can be dropped anytime.
- Dev servers left running: API 8002 (restarted on this code), editor 3002.
