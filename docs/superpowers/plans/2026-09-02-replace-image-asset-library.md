# Replace Image — two sources + workspace asset-library picker + Brand context uploads: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (Opus-only
> implementers; every review, verification and decision is the orchestrator's — founder ruling
> 2026-09-02) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** "Replace image" on a selected ad image offers *Upload from computer* and *Choose from asset
library* (the workspace asset registry, brand-kit items pinned), each pick is one undoable write,
every refusal speaks, and the Brand context Assets page lists the same library with an "Uploads"
category.

**Architecture:** Approach 1 of the spec — client-composed library. A new pure adapter composes the
registry list (`GET /assets`) with the brand kit's asset ids; a new session hook owns fetch/pick;
`pick` reuses the upload path's own placement batch (`upsert_asset` + `place_asset_in_node`) through
`applyOps`; presentation stays in chat-shell components fed by props; Brand context imports the same
pure composer. No backend, no engine, no migrations, no brand-kit writes.

**Tech Stack:** TypeScript / React (Next.js App Router), `@base-ui/react` (Menu, already used for
Select/Popover), zod (Brand context models), node:test via `npx tsx --test`, eslint.

**Spec:** `docs/superpowers/specs/2026-09-02-replace-image-asset-library-design.md`

## Global Constraints

- Platform editor only: `apps/frontend/src/features/design-editor`, the chat-shell inspector
  components, `features/brand-context`. Scene (ad) documents. The design subsystem's own editor copy
  is untouched.
- No engine (Rust) changes, no design-API changes, no migrations, and **the brand kit is never
  written** (founder ruling R-A).
- All document writes go through `SceneManualEdits.applyOps(operations, intent)` — one pick = one
  batch = one undo frame (R-E). The batch is `sceneImagePlacementOperations(node, record)` verbatim.
- Every refusal reports through `writes.reportError` (the inspector's existing error slot); no new
  failure UI; exact sentences in Task 3.
- Chooser = option A (caret on the existing pill; two rows; thin ~1.1px-stroke icons; regular
  weight; **no format enumeration**). Picker = option 2 (floating panel anchored beside the
  inspector over the stage; search + category chip; "Brand kit" then "Workspace" sections; "Brand"
  and "In use" badges; footer = "Upload from computer" only; closes on ✕ / Esc / outside click).
- Library contents (R-B): every non-archived registry image (`raster_image`, `vector`, `logo`
  kinds), kit items pinned first (kit order), then registry in the server's order
  (`updated_at desc`), deduped by id (kit wins).
- Brand context (R-F): kit ∪ registry, deduped; kit items keep kit categories; registry-only →
  `upload`, or `ai-generated` when `source.kind === "generated"`; filter menu gains "Uploads".
- Runner: `npx tsx --test <file>` from `apps/frontend/` (node:test + `node:assert/strict`); eslint
  zero errors AND zero warnings on touched files; frontend gate at rung close:
  `npm run design-system:build && npm run lint && npm run build`, full `npm test` (baseline 2462
  pass / 0 fail / 1 skip — must not regress).
- Local commits only; never push; no AI-attribution trailers; commit messages exactly as written.
- Design tokens for new chrome: Satoshi via `--clue-ds-product-typography-ui-regular-font-family`;
  page `var(--chat-shell-page)`, neutral `var(--chat-shell-neutral)`, borders
  `var(--chat-shell-border)` / `var(--chat-shell-subtle-border)`, primary dark `#44483F`, radius
  6–10px, popup shadow `0 8px 24px rgb(0 24 62 / 12%)` (the inspector's own popup shadow).

## Ground truth (2026-09-02 tree; verify before editing)

- `data/assets.ts` — `uploadWebAsset` + `WebAssetUploadError`; `DESIGN_API_BFF_PREFIX =
  "/api/clue/design"` (`data/design-bff.ts:8`). `AssetRecord` type comes from
  `../engine/asset-types` (vendored closure; same shape as `engine/scene/contracts.ts:327`:
  `id, label, kind, status, source{kind:…}, media?{digest…}, raster?, vector?, provenance?`).
- Design API `GET /assets?kind=&include_archived=&limit=&offset=` (`lumen_api/main.py:6993`) → `{
  assets: AssetRecord[] (bare public records), count, limit, offset }`; DAL orders `updated_at
  DESC, asset_id`; `kind` is a single value per call (`clue_design/assets.py`).
- `adapter/scene-apply.ts` — `sceneImageReplacementTarget(node): ImageNode | null` (image kind,
  unlocked); `sceneImagePlacementOperations(node, record): Operation[] | null` (null when
  `asset_id` and alt text unchanged) → `buildNodePlacementOperations` = `[upsert_asset,
  place_asset_in_node]`.
- `hooks/use-scene-replace-image.ts` — `createSceneReplaceImageHandler(readDeps)`; deps
  `{ applyOps, canApply, clearMessages, documentId, node, onError, upload }`; refusals throw
  `SceneReplaceImageRefused` WITHOUT `onError` (the bug). Test file
  `hooks/use-scene-replace-image.test.ts` (node:test, fixtures `adImage()`, `HARVESTED_AD_PAGE`,
  `AD_DOCUMENT_ID` from `adapter/__fixtures__/scene-nodes.ts`).
- `hooks/use-scene-editing-session.ts` — `:519` composes `useSceneReplaceImage({ applyOps,
  canApply, clearMessages, documentId: activeDocumentId, node: primaryNode ?? null, onError:
  writes.reportError })`; `:380-403` fetches the brand kit detail (`fetchBrandKitDetail(designBffConfig(),
  brandKitId, brandKitVersion)` → `BrandKitDetailPayload` = the kit's `brand_kit_json`; typed
  loosely — `collectKitFontFaceRefs` narrows `assets.fonts` via `unknown`); return block `:700+`
  exposes `onReplaceImage`, `imageAi`, `inspectorError`, … .
- `features/chat-shell/components/inspector-primitives.tsx` — `InspectorImageUpload({ disabled,
  onFileSelect, src })`: pill `<button aria-label="Replace image">` + hidden `<input type=file
  accept="image/png,image/jpeg,image/webp,image/gif,image/svg+xml">`; local FileReader preview
  reverting when `onFileSelect` rejects. Base UI: `import { Popover } from "@base-ui/react/popover"`,
  `import { Select } from "@base-ui/react/select"`; `@base-ui/react/menu` is installed.
  CSS module `chat-shell.module.css` (`.inspectorSelectPopup`, `.inspectorSelectItem` are the
  popup/row styles to echo; `.imageReplaceField`, `.visuallyHiddenInput`).
- `features/chat-shell/components/image-inspector.tsx` — `AdImageInspector` (`:882-896`, props
  `onReplaceImage`, `imageAi`) renders `<InspectorImageUpload disabled={inert} onFileSelect={onReplaceImage}
  src={state.imagePreviewSrc} />` at `:961`; `ImageInspector` (`:1020`) threads `onReplaceImage`/
  `imageAi` to it at `:1178`. Surfaces pass `onReplaceImage={sceneSession.onReplaceImage}` and
  `imageAi={sceneSession.imageAi}` (`chat-surface.tsx:378,399`; `editor-surface.tsx:166,205`); the
  inspector sits in `<div className={styles.inspectorDock}>` (`chat-surface.tsx:337/365`) and the
  artifact area is `<section aria-label="Artifact workspace" className={styles.artifactWorkspace}>`
  (`artifact-stage.tsx:242`).
- Brand context: `data/brand-context.repository.ts::readWorkspace` (reads `/brand-kits`, the kit,
  `/assets/{id}` per kit id → `toBrandContextWorkspace(kit, { assetRecords })`);
  `model/brand-context-mapping.ts` `kitAssetEntries(kit)` (module-private; category: logos →
  `logo`, images → `role==="screenshot" ? "mockup" : "background"`), `toAssets(kit, records)` builds
  `BrandAsset` (`visual.imagePath = ${DESIGN_ASSET_BFF_PREFIX}/${id}/bytes`); `model/brand-context.ts`
  `BrandAssetCategorySchema = z.enum(["logo","background","mockup","ai-generated"])`,
  `BrandAssetSchema`; `hooks/use-brand-context-controller.ts:18-24` `assetFilterOptions`;
  name/description edits are LOCAL DRAFTS (`assetDrafts`) — nothing writes, so no gating is needed.
  `components/assets-panel.tsx:231-235` renders `.assetCard` → `.assetCardPreview` / `.assetCardMeta`.
  Tests: `data/brand-context.repository.test.ts` (`stubDesignApi(routes)`, `HARVESTED_BRAND_KIT`,
  `HARVESTED_ASSET_RECORDS` from `data/__fixtures__/harvest`).

---

### Task 1: `listImageAssets` — the registry read

**Files:**
- Modify: `apps/frontend/src/features/design-editor/data/assets.ts`
- Test: `apps/frontend/src/features/design-editor/data/assets.test.ts` (extend)

**Interfaces:**
- Produces: `IMAGE_ASSET_KINDS = ["raster_image", "vector", "logo"] as const`;
  `listImageAssets({ fetchImpl }?): Promise<AssetRecord[]>` — one `GET
  ${DESIGN_API_BFF_PREFIX}/assets?kind=<k>&include_archived=false&limit=200&offset=<n>` per kind,
  paging while a page is full, concatenated in kind order then server order; throws
  `WebAssetUploadError`-shaped errors (`WebAssetListError`) on a non-ok response.

- [x] **Step 1: Write the failing tests** (append to `data/assets.test.ts`; keep its existing
  imports — it already imports `uploadWebAsset`; add `listImageAssets`, `IMAGE_ASSET_KINDS`,
  `WebAssetListError`)

```ts
function record(id: string, kind: "raster_image" | "vector" | "logo" = "raster_image"): AssetRecord {
  return { id, kind, label: id, status: "ready", source: { kind: "uploaded", filename: `${id}.png`, uploaded_by: null } };
}

function listStub(pages: Record<string, AssetRecord[][]>) {
  const calls: string[] = [];
  const fetchImpl = (async (input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://x");
    calls.push(`${url.pathname}${url.search}`);
    const kind = url.searchParams.get("kind") ?? "";
    const offset = Number(url.searchParams.get("offset") ?? 0);
    const page = pages[kind]?.[offset / 200] ?? [];
    return new Response(JSON.stringify({ assets: page, count: page.length, limit: 200, offset }), {
      status: 200, headers: { "content-type": "application/json" },
    });
  }) as typeof fetch;
  return { calls, fetchImpl };
}

test("listImageAssets reads every image kind, archived excluded, in kind order then server order", async () => {
  const { calls, fetchImpl } = listStub({
    raster_image: [[record("r1"), record("r2")]],
    vector: [[record("v1", "vector")]],
    logo: [[record("l1", "logo")]],
  });
  const records = await listImageAssets({ fetchImpl });
  assert.deepEqual(records.map((r) => r.id), ["r1", "r2", "v1", "l1"]);
  assert.deepEqual(IMAGE_ASSET_KINDS, ["raster_image", "vector", "logo"]);
  for (const kind of IMAGE_ASSET_KINDS) {
    assert.ok(calls.includes(`/api/clue/design/assets?kind=${kind}&include_archived=false&limit=200&offset=0`), kind);
  }
});

test("listImageAssets pages while a page is full", async () => {
  const full = Array.from({ length: 200 }, (_, i) => record(`r${i}`));
  const { calls, fetchImpl } = listStub({ raster_image: [full, [record("r200")]], vector: [[]], logo: [[]] });
  const records = await listImageAssets({ fetchImpl });
  assert.equal(records.length, 201);
  assert.ok(calls.some((c) => c.includes("kind=raster_image") && c.includes("offset=200")));
  assert.ok(!calls.some((c) => c.includes("kind=raster_image") && c.includes("offset=400")));
});

test("listImageAssets refuses with the API's words on a non-ok response", async () => {
  const fetchImpl = (async () =>
    new Response(JSON.stringify({ detail: { code: "auth.workspace", message: "workspace header missing" } }), {
      status: 401, headers: { "content-type": "application/json" },
    })) as typeof fetch;
  await assert.rejects(listImageAssets({ fetchImpl }), (error: unknown) => {
    assert.ok(error instanceof WebAssetListError);
    assert.equal(error.message, "workspace header missing");
    assert.equal(error.status, 401);
    return true;
  });
});
```

- [x] **Step 2: Run to verify it fails**

Run: `cd apps/frontend && npx tsx --test src/features/design-editor/data/assets.test.ts`
Expected: FAIL — `listImageAssets` / `IMAGE_ASSET_KINDS` / `WebAssetListError` are not exported.

- [x] **Step 3: Implement** (append to `data/assets.ts`)

```ts
/** The registry kinds that paint as pictures — what the asset-library picker and the Brand
 * context Assets page list. Fonts, documents and `other` never appear there. */
export const IMAGE_ASSET_KINDS = ["raster_image", "vector", "logo"] as const;

const LIST_PAGE_SIZE = 200;

/** A typed refusal from the registry list seam — the same shape as the upload's. */
export class WebAssetListError extends Error {
  readonly code: string | null;
  readonly status: number;
  constructor(message: string, options: { code?: string | null; status: number }) {
    super(message);
    this.name = "WebAssetListError";
    this.code = options.code ?? null;
    this.status = options.status;
  }
}

interface AssetListPayload {
  assets?: AssetRecord[];
  detail?: { code?: string; message?: string } | string;
}

/**
 * Every non-archived image asset in the workspace registry, through the authenticated BFF
 * (`GET /assets`), one request per image kind (the route filters a single `kind`), paged while a
 * page comes back full. Order is kind order, then the server's own (`updated_at desc`).
 */
export async function listImageAssets(
  { fetchImpl }: { fetchImpl?: typeof fetch } = {},
): Promise<AssetRecord[]> {
  const doFetch: typeof fetch = fetchImpl ?? ((input, init) => fetch(input, init));
  const records: AssetRecord[] = [];
  for (const kind of IMAGE_ASSET_KINDS) {
    for (let offset = 0; ; offset += LIST_PAGE_SIZE) {
      const response = await doFetch(
        `${DESIGN_API_BFF_PREFIX}/assets?kind=${kind}&include_archived=false&limit=${LIST_PAGE_SIZE}&offset=${offset}`,
      );
      let payload: AssetListPayload = {};
      try {
        payload = (await response.json()) as AssetListPayload;
      } catch {
        // A non-JSON body keeps the status-shaped message below.
      }
      if (!response.ok || !Array.isArray(payload.assets)) {
        const detail = payload.detail;
        const message =
          typeof detail === "string"
            ? detail
            : (detail?.message ?? detail?.code ?? `Asset list failed with status ${response.status}`);
        throw new WebAssetListError(message, {
          code: typeof detail === "string" ? null : (detail?.code ?? null),
          status: response.status,
        });
      }
      records.push(...payload.assets);
      if (payload.assets.length < LIST_PAGE_SIZE) break;
    }
  }
  return records;
}
```

- [x] **Step 4: Run to verify it passes**

Run: `cd apps/frontend && npx tsx --test src/features/design-editor/data/assets.test.ts && npx eslint src/features/design-editor/data/assets.ts src/features/design-editor/data/assets.test.ts`
Expected: all PASS; eslint clean.

- [x] **Step 5: Commit**

```bash
git add apps/frontend/src/features/design-editor/data/assets.ts apps/frontend/src/features/design-editor/data/assets.test.ts
git commit -m "feat(design-editor): listImageAssets — registry read for the asset library"
```

---

### Task 2: `adapter/scene-asset-library.ts` — the pure library composer

**Files:**
- Create: `apps/frontend/src/features/design-editor/adapter/scene-asset-library.ts`
- Test: `apps/frontend/src/features/design-editor/adapter/scene-asset-library.test.ts`

**Interfaces:**
- Produces:
  ```ts
  export type AssetLibraryCategory = "logo" | "background" | "mockup" | "ai-generated" | "upload";
  export interface KitLibraryEntry { assetId: string; category: "logo" | "background" | "mockup" }
  export interface AssetLibraryItem { record: AssetRecord; pinned: boolean; inUse: boolean; category: AssetLibraryCategory }
  export function kitLibraryEntries(kit: unknown): KitLibraryEntry[]           // from a brand_kit_json
  export function registryCategory(record: AssetRecord): "ai-generated" | "upload"
  export function composeAssetLibrary(args: { registry: readonly AssetRecord[]; kitEntries: readonly KitLibraryEntry[]; inUseAssetId: string | null }): AssetLibraryItem[]
  export function filterAssetLibrary(items: readonly AssetLibraryItem[], filter: { query: string; category: AssetLibraryCategory | "all" }): AssetLibraryItem[]
  ```
  Rules: pinned = id ∈ kit entries (kit order first, then registry server order); dedupe by id (kit
  wins — the kit's category, the registry's record); archived (`status === "archived"`) dropped even
  if the server sent one; a kit entry with no registry record is dropped (nothing to paint);
  `inUse = record.id === inUseAssetId`; `filterAssetLibrary` matches `label` (and `media.filename`)
  case-insensitively and `category` exactly (`"all"` passes).

- [x] **Step 1: Write the failing tests**

```ts
import assert from "node:assert/strict";
import { it } from "node:test";
import type { AssetRecord } from "../engine/scene/contracts";
import {
  composeAssetLibrary,
  filterAssetLibrary,
  kitLibraryEntries,
  registryCategory,
} from "./scene-asset-library";

function rec(id: string, extra: Partial<AssetRecord> = {}): AssetRecord {
  return { id, kind: "raster_image", label: id, status: "ready",
    source: { kind: "uploaded", filename: `${id}.png`, uploaded_by: null }, ...extra };
}
const GENERATED: AssetRecord = rec("gen1", { source: { kind: "generated", request_id: null, model: "x" } });

it("reads logo variants and images out of a brand_kit_json, in kit order, deduped", () => {
  const kit = { assets: {
    logos: { mark: { variants: [{ asset_id: "logo_a" }, { asset_id: "logo_b" }] }, wordmark: null },
    images: { hero: { asset_id: "img_h", role: "hero" }, shot: { asset_id: "img_s", role: "screenshot" }, dup: { asset_id: "logo_a" } },
  } };
  assert.deepEqual(kitLibraryEntries(kit), [
    { assetId: "logo_a", category: "logo" }, { assetId: "logo_b", category: "logo" },
    { assetId: "img_h", category: "background" }, { assetId: "img_s", category: "mockup" },
  ]);
  assert.deepEqual(kitLibraryEntries(null), []);
  assert.deepEqual(kitLibraryEntries({ assets: { fonts: {} } }), []);
});

it("categorizes registry-only records: generated → ai-generated, everything else → upload", () => {
  assert.equal(registryCategory(GENERATED), "ai-generated");
  assert.equal(registryCategory(rec("u")), "upload");
  assert.equal(registryCategory(rec("w", { source: { kind: "website", url: "https://x", captured_at: null } })), "upload");
});

it("pins kit items first in kit order, then the registry in server order, deduped with the kit winning", () => {
  const registry = [rec("new1"), rec("logo_b", { label: "from registry" }), GENERATED, rec("logo_a")];
  const items = composeAssetLibrary({
    registry,
    kitEntries: [{ assetId: "logo_a", category: "logo" }, { assetId: "logo_b", category: "logo" }],
    inUseAssetId: "new1",
  });
  assert.deepEqual(items.map((i) => [i.record.id, i.pinned, i.category, i.inUse]), [
    ["logo_a", true, "logo", false], ["logo_b", true, "logo", false],
    ["new1", false, "upload", true], ["gen1", false, "ai-generated", false],
  ]);
  assert.equal(items[1].record.label, "from registry"); // the registry's record, the kit's category
});

it("drops archived records and kit entries with no registry record", () => {
  const items = composeAssetLibrary({
    registry: [rec("live"), rec("gone", { status: "archived" })],
    kitEntries: [{ assetId: "missing", category: "logo" }],
    inUseAssetId: null,
  });
  assert.deepEqual(items.map((i) => i.record.id), ["live"]);
});

it("filters by query (label or filename, case-insensitive) and by category", () => {
  const items = composeAssetLibrary({
    registry: [rec("Hero Banner"), rec("team", { media: { filename: "Team-Photo.JPG" } }), GENERATED],
    kitEntries: [], inUseAssetId: null,
  });
  assert.deepEqual(filterAssetLibrary(items, { query: "hero", category: "all" }).map((i) => i.record.id), ["Hero Banner"]);
  assert.deepEqual(filterAssetLibrary(items, { query: "photo", category: "all" }).map((i) => i.record.id), ["team"]);
  assert.deepEqual(filterAssetLibrary(items, { query: "", category: "ai-generated" }).map((i) => i.record.id), ["gen1"]);
  assert.equal(filterAssetLibrary(items, { query: "", category: "all" }).length, 3);
});
```

- [x] **Step 2: Run to verify it fails**

Run: `cd apps/frontend && npx tsx --test src/features/design-editor/adapter/scene-asset-library.test.ts`
Expected: FAIL — module not found.

- [x] **Step 3: Implement**

```ts
import type { AssetRecord } from "../engine/scene/contracts";

/**
 * The asset library, composed on the client (spec approach 1): the workspace registry with the
 * brand kit's own pictures pinned first. Pure — the Brand context page imports the same functions
 * so the two surfaces can never disagree on what the library is.
 */

export type AssetLibraryCategory = "logo" | "background" | "mockup" | "ai-generated" | "upload";

export interface KitLibraryEntry {
  assetId: string;
  category: "logo" | "background" | "mockup";
}

export interface AssetLibraryItem {
  record: AssetRecord;
  /** A brand-kit item — listed first and badged "Brand". */
  pinned: boolean;
  /** The asset currently placed on the selected node. */
  inUse: boolean;
  category: AssetLibraryCategory;
}

/** Kit logo variants then kit images, kit order, deduped — from a `brand_kit_json` of unknown
 * shape (the editor's kit payload is typed loosely; narrow, never trust). */
export function kitLibraryEntries(kit: unknown): KitLibraryEntry[] {
  const assets = (kit as { assets?: unknown } | null | undefined)?.assets;
  if (!assets || typeof assets !== "object") return [];
  const { logos, images } = assets as { logos?: unknown; images?: unknown };
  const entries: KitLibraryEntry[] = [];
  const seen = new Set<string>();
  const push = (assetId: unknown, category: KitLibraryEntry["category"]) => {
    if (typeof assetId !== "string" || assetId.length === 0 || seen.has(assetId)) return;
    seen.add(assetId);
    entries.push({ assetId, category });
  };
  if (logos && typeof logos === "object") {
    for (const logo of Object.values(logos as Record<string, unknown>)) {
      const variants = (logo as { variants?: unknown } | null)?.variants;
      if (!Array.isArray(variants)) continue;
      for (const variant of variants) push((variant as { asset_id?: unknown })?.asset_id, "logo");
    }
  }
  if (images && typeof images === "object") {
    for (const image of Object.values(images as Record<string, unknown>)) {
      if (!image || typeof image !== "object") continue;
      const { asset_id, role } = image as { asset_id?: unknown; role?: unknown };
      push(asset_id, role === "screenshot" ? "mockup" : "background");
    }
  }
  return entries;
}

/** Structural on purpose: the Brand context page passes its own zod-parsed list record. */
export function registryCategory(record: { source: { kind: string } }): "ai-generated" | "upload" {
  return record.source.kind === "generated" ? "ai-generated" : "upload";
}

export function composeAssetLibrary({ registry, kitEntries, inUseAssetId }: {
  registry: readonly AssetRecord[];
  kitEntries: readonly KitLibraryEntry[];
  inUseAssetId: string | null;
}): AssetLibraryItem[] {
  const byId = new Map<string, AssetRecord>();
  for (const record of registry) {
    if (record.status === "archived" || byId.has(record.id)) continue;
    byId.set(record.id, record);
  }
  const items: AssetLibraryItem[] = [];
  const placed = new Set<string>();
  for (const entry of kitEntries) {
    const record = byId.get(entry.assetId);
    if (!record || placed.has(entry.assetId)) continue;
    placed.add(entry.assetId);
    items.push({ record, pinned: true, inUse: record.id === inUseAssetId, category: entry.category });
  }
  for (const record of byId.values()) {
    if (placed.has(record.id)) continue;
    items.push({ record, pinned: false, inUse: record.id === inUseAssetId, category: registryCategory(record) });
  }
  return items;
}

export function filterAssetLibrary(
  items: readonly AssetLibraryItem[],
  filter: { query: string; category: AssetLibraryCategory | "all" },
): AssetLibraryItem[] {
  const query = filter.query.trim().toLocaleLowerCase();
  return items.filter((item) => {
    if (filter.category !== "all" && item.category !== filter.category) return false;
    if (!query) return true;
    const haystack = `${item.record.label} ${item.record.media?.filename ?? ""}`.toLocaleLowerCase();
    return haystack.includes(query);
  });
}
```

- [x] **Step 4: Run to verify it passes**

Run: `cd apps/frontend && npx tsx --test src/features/design-editor/adapter/scene-asset-library.test.ts && npx eslint src/features/design-editor/adapter/scene-asset-library.ts src/features/design-editor/adapter/scene-asset-library.test.ts`
Expected: PASS; eslint clean.

- [x] **Step 5: Commit**

```bash
git add apps/frontend/src/features/design-editor/adapter/scene-asset-library.ts apps/frontend/src/features/design-editor/adapter/scene-asset-library.test.ts
git commit -m "feat(design-editor): pure asset-library composer (kit pinned, registry, categories)"
```

---

### Task 3: Every replace refusal speaks (the bug fix) + `accept` drops GIF

**Files:**
- Modify: `apps/frontend/src/features/design-editor/hooks/use-scene-replace-image.ts`
- Modify: `apps/frontend/src/features/chat-shell/components/inspector-primitives.tsx` (the
  `accept` attribute only)
- Test: `apps/frontend/src/features/design-editor/hooks/use-scene-replace-image.test.ts` (extend)

**Interfaces:**
- Produces (exported constants, reused by Task 4):
  ```ts
  export const NOT_ACCEPTING_EDITS = "This document isn't accepting edits right now.";
  export const NOT_AN_IMAGE_TARGET = "Select an unlocked image to replace.";
  export const SELECTION_MOVED = "The selection changed while the upload was running — try again.";
  export const SAME_IMAGE_IN_USE = "That's the image already in use.";
  ```
  Behaviour: each refusal calls `deps.onError(<sentence>)` and THEN throws `SceneReplaceImageRefused`
  (the panel's preview still reverts). The same-asset case (adapter returns null) now reports and
  throws instead of returning silently. Upload failures unchanged (the API's words).

- [x] **Step 1: Write the failing tests** (append; build deps directly so the test does not
  depend on the file's `harness` internals)

```ts
import {
  NOT_ACCEPTING_EDITS, NOT_AN_IMAGE_TARGET, SAME_IMAGE_IN_USE, SELECTION_MOVED,
  SceneReplaceImageRefused,
} from "./use-scene-replace-image";

function speakingDeps(over: Partial<{
  armed: boolean; documentId: string | null; node: Node | null; upload: (f: File) => Promise<AssetRecord>;
}> = {}) {
  const errors: string[] = [];
  const applied: Operation[][] = [];
  const deps = {
    applyOps: (ops: Operation[]) => { applied.push(ops); return true; },
    canApply: () => over.armed ?? true,
    clearMessages: () => undefined,
    documentId: over.documentId === undefined ? AD_DOCUMENT_ID : over.documentId,
    node: over.node === undefined ? (adImage() as Node) : over.node,
    onError: (message: string) => { errors.push(message); },
    upload: over.upload ?? (async () => RECORD),
  };
  return { applied, deps, errors };
}

test("a refusal because the write path is not armed SPEAKS, then throws", async () => {
  const { deps, errors } = speakingDeps({ armed: false });
  await assert.rejects(createSceneReplaceImageHandler(() => deps)(pngFile()), SceneReplaceImageRefused);
  assert.deepEqual(errors, [NOT_ACCEPTING_EDITS]);
});

test("a refusal because the selection is not an unlocked image SPEAKS", async () => {
  const locked = heroWith((node) => { node.locked = true; });
  const { deps, errors } = speakingDeps({ node: locked });
  await assert.rejects(createSceneReplaceImageHandler(() => deps)(pngFile()), SceneReplaceImageRefused);
  assert.deepEqual(errors, [NOT_AN_IMAGE_TARGET]);
  const text = speakingDeps({ node: adTokenText() as Node });
  await assert.rejects(createSceneReplaceImageHandler(() => text.deps)(pngFile()), SceneReplaceImageRefused);
  assert.deepEqual(text.errors, [NOT_AN_IMAGE_TARGET]);
});

test("a refusal because the selection moved during the upload SPEAKS", async () => {
  const gate = deferred<AssetRecord>();
  let current: Node | null = adImage() as Node;
  const errors: string[] = [];
  const deps = () => ({
    applyOps: () => true, canApply: () => true, clearMessages: () => undefined,
    documentId: AD_DOCUMENT_ID, node: current,
    onError: (m: string) => { errors.push(m); }, upload: () => gate.promise,
  });
  const run = createSceneReplaceImageHandler(deps)(pngFile());
  current = adTokenText() as Node;
  gate.resolve(RECORD);
  await assert.rejects(run, SceneReplaceImageRefused);
  assert.deepEqual(errors, [SELECTION_MOVED]);
});

test("uploading the very image already in use SPEAKS instead of silently doing nothing", async () => {
  const same = heroWith((node) => { if (node.kind.kind === "image") node.kind.asset_id = RECORD.id; });
  const { applied, deps, errors } = speakingDeps({ node: same });
  await assert.rejects(createSceneReplaceImageHandler(() => deps)(pngFile()), SceneReplaceImageRefused);
  assert.deepEqual(errors, [SAME_IMAGE_IN_USE]);
  assert.equal(applied.length, 0);
});
```

- [x] **Step 2: Run to verify it fails**

Run: `cd apps/frontend && npx tsx --test src/features/design-editor/hooks/use-scene-replace-image.test.ts`
Expected: the four new tests FAIL (constants not exported; `errors` empty; the same-asset case
resolves instead of rejecting). Existing tests stay green — if any existing test asserted that a
refusal does NOT report, update it and state why in the test.

- [x] **Step 3: Implement** — in `use-scene-replace-image.ts`, add the four exported constants above
  `REPLACE_IMAGE_INTENT`, and edit `createSceneReplaceImageHandler`:

```ts
    if (!documentId || !before.canApply()) {
      before.onError(NOT_ACCEPTING_EDITS);
      throw new SceneReplaceImageRefused(documentId ? "the write path is not armed" : "no document is armed");
    }
    if (!target || !sceneImageReplacementTarget(target)) {
      before.onError(NOT_AN_IMAGE_TARGET);
      throw new SceneReplaceImageRefused("this selection takes no image");
    }
    // … upload as today …
    if (!after.node || after.node.id !== target.id || after.documentId !== documentId) {
      after.onError(SELECTION_MOVED);
      throw new SceneReplaceImageRefused("the selection moved during the upload");
    }
    if (!sceneImageReplacementTarget(after.node)) {
      after.onError(NOT_AN_IMAGE_TARGET);
      throw new SceneReplaceImageRefused("the node was locked during the upload");
    }
    const operations = sceneImagePlacementOperations(after.node, record);
    if (!operations) {
      after.onError(SAME_IMAGE_IN_USE);
      throw new SceneReplaceImageRefused("the asset is already in use");
    }
```

  (Keep the order: the "not armed" check must precede the target check so a view-mode refusal reads
  "not accepting edits", matching the clipboard lane's wording.) In `inspector-primitives.tsx`,
  change the input's `accept` to `"image/png,image/jpeg,image/webp,image/svg+xml"` with a one-line
  comment: the server's sniff refuses GIF, so the dialog must not offer it.

- [x] **Step 4: Run to verify it passes**

Run: `cd apps/frontend && npx tsx --test src/features/design-editor/hooks/use-scene-replace-image.test.ts && npx eslint src/features/design-editor/hooks/use-scene-replace-image.ts src/features/design-editor/hooks/use-scene-replace-image.test.ts src/features/chat-shell/components/inspector-primitives.tsx`
Expected: PASS; eslint clean.

- [x] **Step 5: Commit**

```bash
git add apps/frontend/src/features/design-editor/hooks/use-scene-replace-image.ts apps/frontend/src/features/design-editor/hooks/use-scene-replace-image.test.ts apps/frontend/src/features/chat-shell/components/inspector-primitives.tsx
git commit -m "fix(design-editor): every replace-image refusal speaks; file dialog stops offering GIF"
```

---

### Task 4: `use-scene-asset-library` — fetch on open, pick = the upload's batch

**Files:**
- Create: `apps/frontend/src/features/design-editor/hooks/use-scene-asset-library.ts`
- Test: `apps/frontend/src/features/design-editor/hooks/use-scene-asset-library.test.ts`
- Modify: `apps/frontend/src/features/design-editor/hooks/use-scene-editing-session.ts` (keep the
  kit's library entries from the existing brand-kit effect; compose the hook; expose `assetLibrary`)

**Interfaces:**
- Consumes: Task 1 `listImageAssets`; Task 2 `composeAssetLibrary`, `filterAssetLibrary`,
  `kitLibraryEntries`, types; Task 3 sentences; `sceneImageReplacementTarget`,
  `sceneImagePlacementOperations` (`adapter/scene-apply.ts`).
- Produces:
  ```ts
  export interface SceneAssetLibraryBinding {
    isOpen: boolean; open: () => void; close: () => void;
    items: AssetLibraryItem[];            // already filtered by query/category
    loading: boolean; error: string | null;
    query: string; setQuery: (q: string) => void;
    category: AssetLibraryCategory | "all"; setCategory: (c: AssetLibraryCategory | "all") => void;
    pick: (assetId: string) => void;       // one applyOps, or a spoken refusal
    refresh: () => void;
    thumbnailUrl: (record: AssetRecord) => string;   // `${DESIGN_API_BFF_PREFIX}/assets/${id}/bytes`
  }
  export interface SceneAssetLibraryDeps { applyOps; canApply; documentId; node; onError; kitEntries; list; readonly? }
  export function createSceneAssetLibraryPick(readDeps: () => SceneAssetLibraryDeps, findRecord: (id) => AssetRecord | null): (assetId: string) => boolean
  export function useSceneAssetLibrary(options): SceneAssetLibraryBinding
  ```
  The session exposes `assetLibrary: SceneAssetLibraryBinding` (offered only when a document is armed,
  the `arrange` precedent).

- [x] **Step 1: Write the failing tests** (the pure pick handler; the hook's React plumbing is
  untestable under `tsx --test` and stays thin)

```ts
import assert from "node:assert/strict";
import test from "node:test";
import { AD_DOCUMENT_ID, adImage, adTokenText } from "../adapter/__fixtures__/scene-nodes";
import { sceneImagePlacementOperations } from "../adapter/scene-apply";
import type { AssetRecord, Node, Operation } from "../engine/scene/contracts";
import { NOT_ACCEPTING_EDITS, NOT_AN_IMAGE_TARGET, SAME_IMAGE_IN_USE } from "./use-scene-replace-image";
import { createSceneAssetLibraryPick } from "./use-scene-asset-library";

const LOGO: AssetRecord = { id: "asset_logo", kind: "logo", label: "Cursor mark", status: "ready",
  source: { kind: "uploaded", filename: "mark.svg", uploaded_by: null } };

function picker(over: Partial<{ armed: boolean; node: Node | null; documentId: string | null }> = {}) {
  const applied: { intent?: string; operations: Operation[] }[] = [];
  const errors: string[] = [];
  const deps = () => ({
    applyOps: (operations: Operation[], intent?: string) => { applied.push({ intent, operations }); return true; },
    canApply: () => over.armed ?? true,
    documentId: over.documentId === undefined ? AD_DOCUMENT_ID : over.documentId,
    node: over.node === undefined ? (adImage() as Node) : over.node,
    onError: (m: string) => { errors.push(m); },
  });
  const pick = createSceneAssetLibraryPick(deps, (id) => (id === LOGO.id ? LOGO : null));
  return { applied, errors, pick };
}

test("a pick applies exactly the upload path's placement batch, once, as its own intent", () => {
  const { applied, errors, pick } = picker();
  assert.equal(pick(LOGO.id), true);
  assert.equal(applied.length, 1);
  assert.equal(applied[0].intent, "inspector: replace image from library");
  assert.deepEqual(applied[0].operations, sceneImagePlacementOperations(adImage() as Node, LOGO));
  assert.deepEqual(applied[0].operations.map((op) => op.kind), ["upsert_asset", "place_asset_in_node"]);
  assert.deepEqual(errors, []);
});

test("picking the asset already in use speaks and applies nothing", () => {
  const same = adImage() as Node;
  if (same.kind.kind === "image") same.kind.asset_id = LOGO.id;
  const { applied, errors, pick } = picker({ node: same });
  assert.equal(pick(LOGO.id), false);
  assert.deepEqual(applied, []);
  assert.deepEqual(errors, [SAME_IMAGE_IN_USE]);
});

test("guards speak with the replace path's own sentences", () => {
  const unarmed = picker({ armed: false });
  assert.equal(unarmed.pick(LOGO.id), false);
  assert.deepEqual(unarmed.errors, [NOT_ACCEPTING_EDITS]);
  const text = picker({ node: adTokenText() as Node });
  assert.equal(text.pick(LOGO.id), false);
  assert.deepEqual(text.errors, [NOT_AN_IMAGE_TARGET]);
  const noDoc = picker({ documentId: null });
  assert.equal(noDoc.pick(LOGO.id), false);
  assert.deepEqual(noDoc.errors, [NOT_ACCEPTING_EDITS]);
});

test("an unknown asset id is a refusal, not a throw", () => {
  const { applied, errors, pick } = picker();
  assert.equal(pick("asset_nope"), false);
  assert.deepEqual(applied, []);
  assert.deepEqual(errors, ["That image is no longer in the library."]);
});
```

- [x] **Step 2: Run to verify it fails**

Run: `cd apps/frontend && npx tsx --test src/features/design-editor/hooks/use-scene-asset-library.test.ts`
Expected: FAIL — module not found.

- [x] **Step 3: Implement**

```ts
"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  sceneImagePlacementOperations,
  sceneImageReplacementTarget,
} from "../adapter/scene-apply";
import {
  composeAssetLibrary,
  filterAssetLibrary,
  type AssetLibraryCategory,
  type AssetLibraryItem,
  type KitLibraryEntry,
} from "../adapter/scene-asset-library";
import { listImageAssets } from "../data/assets";
import { DESIGN_API_BFF_PREFIX } from "../data/design-bff";
import type { AssetRecord, Node, Operation } from "../engine/scene/contracts";
import {
  NOT_ACCEPTING_EDITS,
  NOT_AN_IMAGE_TARGET,
  SAME_IMAGE_IN_USE,
} from "./use-scene-replace-image";

/**
 * The asset-library picker's binding (spec §4.1–4.3). The ONE decision it does not own is the
 * placement: `pick` is the Replace-image upload flow with the upload removed — the same adapter
 * gate and the same `upsert_asset` + `place_asset_in_node` batch, so a pick and an upload are
 * indistinguishable in the document's history (one undo frame each, founder ruling R-E).
 */

export const LIBRARY_PICK_INTENT = "inspector: replace image from library";
const ASSET_GONE = "That image is no longer in the library.";

export interface SceneAssetLibraryDeps {
  applyOps: (operations: Operation[], intent?: string) => boolean;
  canApply: () => boolean;
  documentId: string | null;
  node: Node | null;
  onError: (message: string) => void;
}

/** Pure: guards in the replace path's order, then one batch or one sentence. Returns whether the
 * engine took the batch. */
export function createSceneAssetLibraryPick(
  readDeps: () => SceneAssetLibraryDeps,
  findRecord: (assetId: string) => AssetRecord | null,
): (assetId: string) => boolean {
  return (assetId) => {
    const deps = readDeps();
    if (!deps.documentId || !deps.canApply()) {
      deps.onError(NOT_ACCEPTING_EDITS);
      return false;
    }
    if (!deps.node || !sceneImageReplacementTarget(deps.node)) {
      deps.onError(NOT_AN_IMAGE_TARGET);
      return false;
    }
    const record = findRecord(assetId);
    if (!record) {
      deps.onError(ASSET_GONE);
      return false;
    }
    const operations = sceneImagePlacementOperations(deps.node, record);
    if (!operations) {
      deps.onError(SAME_IMAGE_IN_USE);
      return false;
    }
    return deps.applyOps(operations, LIBRARY_PICK_INTENT);
  };
}

export interface SceneAssetLibraryBinding {
  isOpen: boolean;
  open: () => void;
  close: () => void;
  items: AssetLibraryItem[];
  loading: boolean;
  error: string | null;
  query: string;
  setQuery: (query: string) => void;
  category: AssetLibraryCategory | "all";
  setCategory: (category: AssetLibraryCategory | "all") => void;
  pick: (assetId: string) => void;
  refresh: () => void;
  thumbnailUrl: (record: AssetRecord) => string;
}

export function useSceneAssetLibrary(options: SceneAssetLibraryDeps & {
  kitEntries: readonly KitLibraryEntry[];
  list?: () => Promise<AssetRecord[]>;
}): SceneAssetLibraryBinding {
  const { applyOps, canApply, documentId, kitEntries, list = listImageAssets, node, onError } = options;
  const [isOpen, setOpen] = useState(false);
  const [registry, setRegistry] = useState<AssetRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<AssetLibraryCategory | "all">("all");

  // Latest-value ref, written in a passive effect (this repo's react-hooks rule).
  const depsRef = useRef<SceneAssetLibraryDeps>({ applyOps, canApply, documentId, node, onError });
  useEffect(() => {
    depsRef.current = { applyOps, canApply, documentId, node, onError };
  });
  const registryRef = useRef(registry);
  useEffect(() => { registryRef.current = registry; });

  const fetchGeneration = useRef(0);
  const refresh = useCallback(() => {
    const generation = ++fetchGeneration.current;
    setLoading(true);
    setError(null);
    void list()
      .then((records) => { if (generation === fetchGeneration.current) setRegistry(records); })
      .catch((cause: unknown) => {
        if (generation !== fetchGeneration.current) return;
        setError(cause instanceof Error ? cause.message : String(cause));
      })
      .finally(() => { if (generation === fetchGeneration.current) setLoading(false); });
  }, [list]);

  // Fetch on OPEN, never on mount — the picker is rare and the registry is not small.
  const open = useCallback(() => { setOpen(true); refresh(); }, [refresh]);
  const close = useCallback(() => setOpen(false), []);
  useEffect(() => { setOpen(false); }, [documentId]);

  const inUseAssetId = node?.kind.kind === "image" ? node.kind.asset_id : null;
  const items = useMemo(
    () => filterAssetLibrary(composeAssetLibrary({ registry, kitEntries, inUseAssetId }), { query, category }),
    [category, inUseAssetId, kitEntries, query, registry],
  );

  const pickRef = useRef<((assetId: string) => boolean) | null>(null);
  const pick = useCallback((assetId: string) => {
    pickRef.current ??= createSceneAssetLibraryPick(
      () => depsRef.current,
      (id) => registryRef.current.find((record) => record.id === id) ?? null,
    );
    pickRef.current(assetId);
  }, []);

  const thumbnailUrl = useCallback(
    (record: AssetRecord) => `${DESIGN_API_BFF_PREFIX}/assets/${encodeURIComponent(record.id)}/bytes`,
    [],
  );

  return { category, close, error, isOpen, items, loading, open, pick, query, refresh, setCategory, setQuery, thumbnailUrl };
}
```

  Session wiring (`use-scene-editing-session.ts`): (1) add `const [kitEntries, setKitEntries] =
  useState<KitLibraryEntry[]>([]);` and in the existing brand-kit effect's `.then((detail) => …)`
  add `setKitEntries(kitLibraryEntries(detail));` (import `kitLibraryEntries`, type
  `KitLibraryEntry` from `../adapter/scene-asset-library`); reset to `[]` when `brandKitId` is null.
  (2) directly after the `useSceneReplaceImage` composition:

```ts
  // Replace-image lane: the asset-library picker. Same deps as the upload above — a pick IS a
  // replace with the upload step removed (spec §4.2) — plus the kit's own asset ids for pinning.
  const assetLibraryBinding = useSceneAssetLibrary({
    applyOps: writes.applyOps,
    canApply: writes.canApply,
    documentId: activeDocumentId,
    kitEntries,
    node: primaryNode ?? null,
    onError: writes.reportError,
  });
  const assetLibrary = activeDocumentId && scene ? assetLibraryBinding : undefined;
```

  (3) add `assetLibrary,` to the returned object (alphabetical, near `arrange`).

- [x] **Step 4: Run to verify it passes**

Run: `cd apps/frontend && npx tsx --test src/features/design-editor/hooks/use-scene-asset-library.test.ts src/features/design-editor/hooks/use-scene-replace-image.test.ts && npx eslint src/features/design-editor/hooks/use-scene-asset-library.ts src/features/design-editor/hooks/use-scene-asset-library.test.ts src/features/design-editor/hooks/use-scene-editing-session.ts`
Expected: PASS; eslint clean (no unused vars — `useMemo`/`useState` all used).

- [x] **Step 5: Commit**

```bash
git add apps/frontend/src/features/design-editor/hooks/use-scene-asset-library.ts apps/frontend/src/features/design-editor/hooks/use-scene-asset-library.test.ts apps/frontend/src/features/design-editor/hooks/use-scene-editing-session.ts
git commit -m "feat(design-editor): asset-library binding — fetch on open, pick reuses the replace batch"
```

---

### Task 5: The chooser menu on "Replace image" (option A) + prop threading

**Files:**
- Modify: `apps/frontend/src/features/chat-shell/components/inspector-primitives.tsx`
  (`InspectorImageUpload`)
- Modify: `apps/frontend/src/features/chat-shell/components/image-inspector.tsx` (`AdImageInspector`
  + `ImageInspector` props)
- Modify: `apps/frontend/src/features/chat-shell/components/chat-surface.tsx:378-399` and
  `editor-surface.tsx:166-205` (pass `assetLibrary={sceneSession.assetLibrary}`)
- Modify: `apps/frontend/src/features/chat-shell/components/chat-shell.module.css` (menu styles)
- Create: `apps/frontend/src/features/chat-shell/components/replace-image-menu.logic.ts`
- Test: `apps/frontend/src/features/chat-shell/components/replace-image-menu.logic.test.ts`

**Interfaces:**
- Consumes: Task 4 `SceneAssetLibraryBinding` (only `open`).
- Produces: `InspectorImageUpload` gains `onOpenLibrary?: () => void`; when present the pill
  renders as a `Menu.Trigger` with a caret and two `Menu.Item`s; when absent (dummy path) it keeps
  today's direct file-dialog behaviour. `ImageInspector` / `AdImageInspector` gain
  `assetLibrary?: SceneAssetLibraryBinding` and pass `onOpenLibrary={assetLibrary?.open}`.
  Pure: `replaceImageMenuAction(item: "upload" | "library"): { kind: "open-file-dialog" } | { kind: "open-library" }`
  and `REPLACE_IMAGE_MENU_ROWS = [{ id: "upload", label: "Upload from computer" }, { id: "library", label: "Choose from asset library" }]` (no format text anywhere).

- [x] **Step 1: Write the failing test** (`replace-image-menu.logic.test.ts`)

```ts
import assert from "node:assert/strict";
import { it } from "node:test";
import { REPLACE_IMAGE_MENU_ROWS, replaceImageMenuAction } from "./replace-image-menu.logic";

it("offers exactly two rows, in order, with no format enumeration", () => {
  assert.deepEqual(REPLACE_IMAGE_MENU_ROWS.map((row) => row.id), ["upload", "library"]);
  assert.deepEqual(REPLACE_IMAGE_MENU_ROWS.map((row) => row.label), ["Upload from computer", "Choose from asset library"]);
  for (const row of REPLACE_IMAGE_MENU_ROWS) assert.doesNotMatch(row.label, /png|jpg|jpeg|webp|svg/i);
});

it("maps each row to its action", () => {
  assert.deepEqual(replaceImageMenuAction("upload"), { kind: "open-file-dialog" });
  assert.deepEqual(replaceImageMenuAction("library"), { kind: "open-library" });
});
```

- [x] **Step 2: Run to verify it fails**

Run: `cd apps/frontend && npx tsx --test src/features/chat-shell/components/replace-image-menu.logic.test.ts`
Expected: FAIL — module not found.

- [x] **Step 3: Implement**

`replace-image-menu.logic.ts`:
```ts
/** Option A (founder ruling R-C): the two sources behind "Replace image". Labels carry NO format
 * list — the file dialog's `accept` and the server's sniff own that. */
export const REPLACE_IMAGE_MENU_ROWS = [
  { id: "upload", label: "Upload from computer" },
  { id: "library", label: "Choose from asset library" },
] as const;

export type ReplaceImageMenuRow = (typeof REPLACE_IMAGE_MENU_ROWS)[number]["id"];

export function replaceImageMenuAction(
  row: ReplaceImageMenuRow,
): { kind: "open-file-dialog" } | { kind: "open-library" } {
  return row === "upload" ? { kind: "open-file-dialog" } : { kind: "open-library" };
}
```

`InspectorImageUpload` (add `import { Menu } from "@base-ui/react/menu";` and the logic import):
```tsx
export function InspectorImageUpload({ disabled = false, onFileSelect, onOpenLibrary, src }: {
  disabled?: boolean;
  onFileSelect?: (file: File) => void | Promise<void>;
  /** Replace-image lane (option A): when present, the pill opens a two-row menu; absent keeps
   * the dummy's direct file dialog. */
  onOpenLibrary?: () => void;
  src: string;
}) {
  // … existing preview state + selectFile unchanged …
  const openFileDialog = () => inputRef.current?.click();
  const pill = (
    <>
      <Image alt="" fill sizes="248px" src={previewSrc} unoptimized={previewSrc.startsWith("data:") || previewSrc.startsWith("/api/clue/")} />
      <span>Replace image{onOpenLibrary ? <span aria-hidden className={styles.imageReplaceCaret}>▾</span> : null}</span>
    </>
  );
  return (
    <>
      {onOpenLibrary ? (
        <Menu.Root>
          <Menu.Trigger aria-label="Replace image" className={`${styles.imageReplaceField} ${disabled ? styles.inspectorControlDisabled : ""}`} disabled={disabled}>
            {pill}
          </Menu.Trigger>
          <Menu.Portal>
            <Menu.Positioner align="center" side="bottom" sideOffset={6}>
              <Menu.Popup className={styles.replaceImageMenu}>
                {REPLACE_IMAGE_MENU_ROWS.map((row) => (
                  <Menu.Item className={styles.replaceImageMenuItem} key={row.id}
                    onClick={() => { const action = replaceImageMenuAction(row.id); if (action.kind === "open-file-dialog") openFileDialog(); else onOpenLibrary(); }}>
                    <ReplaceImageMenuIcon row={row.id} />
                    {row.label}
                  </Menu.Item>
                ))}
              </Menu.Popup>
            </Menu.Positioner>
          </Menu.Portal>
        </Menu.Root>
      ) : (
        <button aria-label="Replace image" className={`${styles.imageReplaceField} ${disabled ? styles.inspectorControlDisabled : ""}`} disabled={disabled} onClick={openFileDialog} type="button">
          {pill}
        </button>
      )}
      <input accept="image/png,image/jpeg,image/webp,image/svg+xml" className={styles.visuallyHiddenInput} disabled={disabled}
        onChange={(event) => { const file = event.target.files?.[0]; if (file) selectFile(file); event.target.value = ""; }}
        ref={inputRef} type="file" />
    </>
  );
}

function ReplaceImageMenuIcon({ row }: { row: "upload" | "library" }) {
  // 1.1px strokes (founder ruling R-C), currentColor.
  return row === "upload" ? (
    <svg aria-hidden className={styles.replaceImageMenuIcon} fill="none" stroke="currentColor" strokeWidth="1.1" viewBox="0 0 16 16"><path d="M8 11V3M4.5 6.5 8 3l3.5 3.5M3 12.5h10" /></svg>
  ) : (
    <svg aria-hidden className={styles.replaceImageMenuIcon} fill="none" stroke="currentColor" strokeWidth="1.1" viewBox="0 0 16 16"><rect height="5" rx="1" width="5" x="2" y="2" /><rect height="5" rx="1" width="5" x="9" y="2" /><rect height="5" rx="1" width="5" x="2" y="9" /><rect height="5" rx="1" width="5" x="9" y="9" /></svg>
  );
}
```

CSS (`chat-shell.module.css`, next to `.inspectorSelectPopup`):
```css
.replaceImageMenu {
  width: 236px;
  padding: 6px;
  border: 0.5px solid var(--chat-shell-border);
  border-radius: 10px;
  background: var(--chat-shell-neutral);
  box-shadow: 0 8px 24px rgb(0 24 62 / 12%), 0 1px 2px rgb(0 0 0 / 7%);
  color: var(--chat-shell-content);
  isolation: isolate;
}
.replaceImageMenuItem {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 34px;
  padding: 0 10px;
  border-radius: 6px;
  outline: none;
  cursor: pointer;
  font-family: var(--clue-ds-product-typography-ui-regular-font-family);
  font-size: 13px;
  font-weight: 400;
}
.replaceImageMenuItem[data-highlighted] { background: var(--chat-shell-page); }
.replaceImageMenuIcon { width: 15px; height: 15px; flex: 0 0 15px; }
.imageReplaceCaret { margin-left: 6px; font-size: 10px; color: var(--chat-shell-subtle); }
```

Prop threading: `AdImageInspector` gets `assetLibrary?: SceneAssetLibraryBinding` (type import from
`@/features/design-editor/hooks/use-scene-asset-library`) and renders
`<InspectorImageUpload disabled={inert} onFileSelect={onReplaceImage} onOpenLibrary={assetLibrary?.open} src={state.imagePreviewSrc} />`;
`ImageInspector` adds the same prop and passes `assetLibrary={assetLibrary}` at the `AdImageInspector`
call; `chat-surface.tsx` (the scene inspector block near `:399`) and `editor-surface.tsx` (near
`:205`) pass `assetLibrary={sceneSession.assetLibrary}` beside `imageAi`.

- [x] **Step 4: Run to verify it passes**

Run: `cd apps/frontend && npx tsx --test src/features/chat-shell/components/replace-image-menu.logic.test.ts && npx eslint src/features/chat-shell/components/inspector-primitives.tsx src/features/chat-shell/components/image-inspector.tsx src/features/chat-shell/components/chat-surface.tsx src/features/chat-shell/components/editor-surface.tsx src/features/chat-shell/components/replace-image-menu.logic.ts src/features/chat-shell/components/replace-image-menu.logic.test.ts && npx tsc --noEmit -p tsconfig.json 2>&1 | grep -E "inspector-primitives|image-inspector|chat-surface|editor-surface" || echo "tsc: no diagnostics in touched files"`
Expected: PASS; eslint clean; no new tsc diagnostics.

- [x] **Step 5: Commit**

```bash
git add apps/frontend/src/features/chat-shell/components/inspector-primitives.tsx apps/frontend/src/features/chat-shell/components/image-inspector.tsx apps/frontend/src/features/chat-shell/components/chat-surface.tsx apps/frontend/src/features/chat-shell/components/editor-surface.tsx apps/frontend/src/features/chat-shell/components/chat-shell.module.css apps/frontend/src/features/chat-shell/components/replace-image-menu.logic.ts apps/frontend/src/features/chat-shell/components/replace-image-menu.logic.test.ts
git commit -m "feat(chat-shell): Replace image offers upload or the asset library (option A menu)"
```

---

### Task 6: `AssetLibraryPanel` — the anchored picker (option 2)

**Files:**
- Create: `apps/frontend/src/features/chat-shell/components/asset-library-panel.tsx`
- Create: `apps/frontend/src/features/chat-shell/components/asset-library-panel.logic.ts`
- Test: `apps/frontend/src/features/chat-shell/components/asset-library-panel.logic.test.ts`
- Modify: `apps/frontend/src/features/chat-shell/components/chat-shell.module.css`
- Modify: `apps/frontend/src/features/chat-shell/components/chat-surface.tsx` and
  `editor-surface.tsx` (render the panel inside the artifact area when `assetLibrary?.isOpen`)

**Interfaces:**
- Consumes: Task 4 `SceneAssetLibraryBinding`; `onReplaceImage` (the session's upload handler) for
  the footer upload.
- Produces: `AssetLibraryPanel({ library: SceneAssetLibraryBinding; onUploadFile?: (file: File) => void | Promise<void>; anchorTop?: number })`.
  Pure logic: `ASSET_LIBRARY_CATEGORIES` (chip options: All images / Logos / Backgrounds / Mockups /
  Uploads / AI-generated images), `shouldCloseOnKey(key)`, `shouldCloseOnPointer(target, panelEl)`,
  `splitLibrarySections(items) → { brand: AssetLibraryItem[]; workspace: AssetLibraryItem[] }`,
  `nextFocusIndex(current, key, count, columns)`.

- [x] **Step 1: Write the failing tests** (`asset-library-panel.logic.test.ts`)

```ts
import assert from "node:assert/strict";
import { it } from "node:test";
import type { AssetLibraryItem } from "@/features/design-editor/adapter/scene-asset-library";
import { ASSET_LIBRARY_CATEGORIES, nextFocusIndex, shouldCloseOnKey, shouldCloseOnPointer, splitLibrarySections } from "./asset-library-panel.logic";

const item = (id: string, pinned: boolean): AssetLibraryItem => ({
  record: { id, kind: "raster_image", label: id, status: "ready", source: { kind: "uploaded", filename: null, uploaded_by: null } },
  pinned, inUse: false, category: pinned ? "logo" : "upload",
});

it("offers the Brand-context categories plus Uploads, in order", () => {
  assert.deepEqual(ASSET_LIBRARY_CATEGORIES.map((c) => c.value), ["all", "logo", "background", "mockup", "upload", "ai-generated"]);
  assert.equal(ASSET_LIBRARY_CATEGORIES.find((c) => c.value === "upload")?.label, "Uploads");
});

it("splits pinned items into the Brand kit section, the rest into Workspace, preserving order", () => {
  const { brand, workspace } = splitLibrarySections([item("a", true), item("b", false), item("c", true)]);
  assert.deepEqual(brand.map((i) => i.record.id), ["a", "c"]);
  assert.deepEqual(workspace.map((i) => i.record.id), ["b"]);
});

it("closes on Escape only", () => {
  assert.equal(shouldCloseOnKey("Escape"), true);
  assert.equal(shouldCloseOnKey("Enter"), false);
});

it("closes on a pointerdown outside the panel, not inside", () => {
  const panel = { contains: (node: unknown) => node === "inside" };
  assert.equal(shouldCloseOnPointer("inside", panel), false);
  assert.equal(shouldCloseOnPointer("outside", panel), true);
  assert.equal(shouldCloseOnPointer(null, panel), true);
});

it("moves focus across a 4-column grid with the arrow keys and clamps at the edges", () => {
  assert.equal(nextFocusIndex(0, "ArrowRight", 10, 4), 1);
  assert.equal(nextFocusIndex(3, "ArrowRight", 10, 4), 4);
  assert.equal(nextFocusIndex(9, "ArrowRight", 10, 4), 9);
  assert.equal(nextFocusIndex(0, "ArrowLeft", 10, 4), 0);
  assert.equal(nextFocusIndex(1, "ArrowDown", 10, 4), 5);
  assert.equal(nextFocusIndex(9, "ArrowDown", 10, 4), 9);
  assert.equal(nextFocusIndex(5, "ArrowUp", 10, 4), 1);
  assert.equal(nextFocusIndex(2, "Tab", 10, 4), null);
});
```

- [x] **Step 2: Run to verify it fails**

Run: `cd apps/frontend && npx tsx --test src/features/chat-shell/components/asset-library-panel.logic.test.ts`
Expected: FAIL — module not found.

- [x] **Step 3: Implement**

`asset-library-panel.logic.ts`:
```ts
import type { AssetLibraryCategory, AssetLibraryItem } from "@/features/design-editor/adapter/scene-asset-library";

export const ASSET_LIBRARY_CATEGORIES: ReadonlyArray<{ label: string; value: AssetLibraryCategory | "all" }> = [
  { label: "All images", value: "all" },
  { label: "Logos", value: "logo" },
  { label: "Backgrounds", value: "background" },
  { label: "Mockups", value: "mockup" },
  { label: "Uploads", value: "upload" },
  { label: "AI-generated images", value: "ai-generated" },
];

export function splitLibrarySections(items: readonly AssetLibraryItem[]) {
  return {
    brand: items.filter((item) => item.pinned),
    workspace: items.filter((item) => !item.pinned),
  };
}

export function shouldCloseOnKey(key: string): boolean {
  return key === "Escape";
}

export function shouldCloseOnPointer(target: unknown, panel: { contains: (node: unknown) => boolean } | null): boolean {
  return !panel || !target || !panel.contains(target);
}

/** Arrow-key focus movement over a `columns`-wide grid of `count` cells; null for keys the grid
 * does not own (Tab keeps its native meaning). */
export function nextFocusIndex(current: number, key: string, count: number, columns: number): number | null {
  if (count === 0) return null;
  const last = count - 1;
  switch (key) {
    case "ArrowRight": return Math.min(last, current + 1);
    case "ArrowLeft": return Math.max(0, current - 1);
    case "ArrowDown": return current + columns <= last ? current + columns : current;
    case "ArrowUp": return current - columns >= 0 ? current - columns : current;
    default: return null;
  }
}
```

`asset-library-panel.tsx` (props-only; no transport, no engine):
```tsx
"use client";

import Image from "next/image";
import { useEffect, useRef, useState } from "react";
import type { SceneAssetLibraryBinding } from "@/features/design-editor/hooks/use-scene-asset-library";
import type { AssetLibraryItem } from "@/features/design-editor/adapter/scene-asset-library";
import { InspectorSelect } from "./inspector-primitives";
import { ASSET_LIBRARY_CATEGORIES, nextFocusIndex, shouldCloseOnKey, shouldCloseOnPointer, splitLibrarySections } from "./asset-library-panel.logic";
import styles from "./chat-shell.module.css";

const COLUMNS = 4;

export function AssetLibraryPanel({ library, onUploadFile }: {
  library: SceneAssetLibraryBinding;
  onUploadFile?: (file: File) => void | Promise<void>;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [focusIndex, setFocusIndex] = useState(0);
  const { brand, workspace } = splitLibrarySections(library.items);
  const ordered = [...brand, ...workspace];

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (shouldCloseOnKey(event.key)) library.close(); };
    const onPointer = (event: PointerEvent) => { if (shouldCloseOnPointer(event.target, panelRef.current)) library.close(); };
    window.addEventListener("keydown", onKey);
    window.document.addEventListener("pointerdown", onPointer, true);
    return () => { window.removeEventListener("keydown", onKey); window.document.removeEventListener("pointerdown", onPointer, true); };
  }, [library]);

  const tile = (item: AssetLibraryItem, index: number) => (
    <button
      aria-label={`${item.record.label}${item.inUse ? " (in use)" : ""}`}
      aria-pressed={item.inUse}
      className={`${styles.assetLibraryTile} ${item.inUse ? styles.assetLibraryTileInUse : ""}`}
      key={item.record.id}
      onClick={() => library.pick(item.record.id)}
      onFocus={() => setFocusIndex(index)}
      onKeyDown={(event) => {
        const next = nextFocusIndex(index, event.key, ordered.length, COLUMNS);
        if (next === null) return;
        event.preventDefault();
        (panelRef.current?.querySelectorAll<HTMLButtonElement>(`.${styles.assetLibraryTile}`)[next])?.focus();
      }}
      tabIndex={index === focusIndex ? 0 : -1}
      type="button"
    >
      <Image alt="" fill sizes="72px" src={library.thumbnailUrl(item.record)} unoptimized />
      {item.pinned ? <span className={styles.assetLibraryBadge}>Brand</span> : null}
      {item.inUse ? <span className={styles.assetLibraryBadgeDark}>In use</span> : null}
      <span className={styles.assetLibraryTileName}>{item.record.label}</span>
    </button>
  );

  return (
    <div aria-label="Asset library" className={styles.assetLibraryPanel} ref={panelRef} role="dialog">
      <div className={styles.assetLibraryHeader}>
        <span>Asset library</span>
        <button aria-label="Close asset library" className={styles.assetLibraryClose} onClick={library.close} type="button">✕</button>
      </div>
      <div className={styles.assetLibraryTools}>
        <input aria-label="Search assets" className={styles.assetLibrarySearch} onChange={(event) => library.setQuery(event.target.value)} placeholder="Search" value={library.query} />
        <InspectorSelect label="Filter assets by type" onChange={(value) => library.setCategory(value as typeof library.category)} options={ASSET_LIBRARY_CATEGORIES.map((c) => ({ label: c.label, value: c.value }))} value={library.category} />
      </div>
      {library.error ? (
        <div className={styles.assetLibraryError} role="alert">{library.error} <button className={styles.assetLibraryRetry} onClick={library.refresh} type="button">Retry</button></div>
      ) : null}
      <div className={styles.assetLibraryBody}>
        {brand.length > 0 ? <><div className={styles.assetLibrarySection}>Brand kit</div><div className={styles.assetLibraryGrid}>{brand.map((item, i) => tile(item, i))}</div></> : null}
        <div className={styles.assetLibrarySection}>Workspace{library.loading ? " · loading…" : ""}</div>
        <div className={styles.assetLibraryGrid}>{workspace.map((item, i) => tile(item, brand.length + i))}</div>
        {!library.loading && ordered.length === 0 ? <p className={styles.assetLibraryEmpty}>No images match.</p> : null}
      </div>
      <div className={styles.assetLibraryFooter}>
        <button className={styles.assetLibraryUpload} onClick={() => fileRef.current?.click()} type="button">Upload from computer</button>
        <input accept="image/png,image/jpeg,image/webp,image/svg+xml" className={styles.visuallyHiddenInput}
          onChange={(event) => { const file = event.target.files?.[0]; if (file && onUploadFile) void Promise.resolve(onUploadFile(file)).then(() => library.refresh(), () => undefined); event.target.value = ""; }}
          ref={fileRef} type="file" />
      </div>
    </div>
  );
}
```

CSS (`chat-shell.module.css`) — the panel floats over the artifact area; the artifact section becomes
the positioning context:
```css
.artifactWorkspace { position: relative; }   /* add to the existing rule */
.assetLibraryPanel {
  position: absolute; left: 12px; top: 64px; z-index: 20;
  width: 300px; max-height: calc(100% - 80px);
  display: flex; flex-direction: column;
  border: 0.5px solid var(--chat-shell-border); border-radius: 12px;
  background: var(--chat-shell-neutral);
  box-shadow: 0 12px 32px rgb(0 24 62 / 14%);
  color: var(--chat-shell-content);
  font-family: var(--clue-ds-product-typography-ui-regular-font-family); font-size: 13px;
}
.assetLibraryHeader { display: flex; align-items: center; justify-content: space-between; padding: 12px 14px; border-bottom: 0.5px solid var(--chat-shell-subtle-border); font-weight: 500; }
.assetLibraryClose { border: 0; background: none; color: var(--chat-shell-subtle); cursor: pointer; font: inherit; }
.assetLibraryTools { display: flex; gap: 8px; padding: 10px 14px; border-bottom: 0.5px solid var(--chat-shell-subtle-border); }
.assetLibrarySearch { flex: 1; min-width: 0; height: 30px; padding: 0 10px; border: 0.5px solid var(--chat-shell-border); border-radius: 8px; background: var(--chat-shell-neutral); font: inherit; }
.assetLibraryBody { overflow-y: auto; padding-bottom: 8px; }
.assetLibrarySection { padding: 10px 14px 0; font-size: 11px; color: var(--chat-shell-subtle); text-transform: uppercase; letter-spacing: 0.02em; }
.assetLibraryGrid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; padding: 8px 14px 6px; }
.assetLibraryTile { position: relative; aspect-ratio: 1; overflow: hidden; border: 0.5px solid var(--chat-shell-subtle-border); border-radius: 8px; background: var(--chat-shell-canvas); padding: 0; cursor: pointer; }
.assetLibraryTile:focus-visible, .assetLibraryTileInUse { outline: 2px solid #4c8dff; outline-offset: 1px; }
.assetLibraryTileName { position: absolute; left: 0; right: 0; bottom: 0; padding: 12px 6px 4px; font-size: 10px; color: #fff; background: linear-gradient(transparent, rgb(0 0 0 / 45%)); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; text-align: left; }
.assetLibraryBadge, .assetLibraryBadgeDark { position: absolute; top: 6px; z-index: 1; padding: 2px 5px; border-radius: 4px; font-size: 9px; font-weight: 500; }
.assetLibraryBadge { left: 6px; background: var(--chat-shell-neutral); color: #44483F; border: 0.5px solid var(--chat-shell-border); }
.assetLibraryBadgeDark { right: 6px; background: #44483F; color: #fff; }
.assetLibraryEmpty { margin: 0; padding: 8px 14px 4px; color: var(--chat-shell-subtle); }
.assetLibraryError { display: flex; gap: 8px; align-items: center; padding: 8px 14px; color: #b42318; font-size: 12px; }
.assetLibraryRetry { border: 0.5px solid var(--chat-shell-border); border-radius: 6px; background: var(--chat-shell-neutral); font: inherit; font-size: 12px; padding: 2px 8px; cursor: pointer; }
.assetLibraryFooter { display: flex; padding: 10px 14px; border-top: 0.5px solid var(--chat-shell-subtle-border); }
.assetLibraryUpload { height: 32px; padding: 0 12px; border: 0.5px solid var(--chat-shell-border); border-radius: 8px; background: var(--chat-shell-neutral); font: inherit; cursor: pointer; }
```

Rendering: in `chat-surface.tsx` and `editor-surface.tsx`, inside the `<ArtifactStage …>` children
area (or immediately after it within the same relatively-positioned artifact section — pick the
nearest existing slot that is a descendant of `.artifactWorkspace`; do not add wrappers around the
stage), render
`{sceneSession.assetLibrary?.isOpen ? <AssetLibraryPanel library={sceneSession.assetLibrary} onUploadFile={sceneSession.onReplaceImage} /> : null}`.
If `ArtifactStage` accepts no children, add an optional `overlay?: React.ReactNode` prop rendered as
the last child of the `artifactWorkspace` section (pass-through only, no logic — the Task-8
`onSceneDropImageFiles` precedent).

- [x] **Step 4: Run to verify it passes**

Run: `cd apps/frontend && npx tsx --test src/features/chat-shell/components/asset-library-panel.logic.test.ts && npx eslint src/features/chat-shell/components/asset-library-panel.tsx src/features/chat-shell/components/asset-library-panel.logic.ts src/features/chat-shell/components/asset-library-panel.logic.test.ts src/features/chat-shell/components/chat-surface.tsx src/features/chat-shell/components/editor-surface.tsx src/features/chat-shell/components/artifact-stage.tsx && npx tsc --noEmit -p tsconfig.json 2>&1 | grep -E "asset-library-panel|chat-surface|editor-surface|artifact-stage" || echo "tsc: no diagnostics in touched files"`
Expected: PASS; eslint clean; no new tsc diagnostics.

- [x] **Step 5: Commit**

```bash
git add apps/frontend/src/features/chat-shell/components/asset-library-panel.tsx apps/frontend/src/features/chat-shell/components/asset-library-panel.logic.ts apps/frontend/src/features/chat-shell/components/asset-library-panel.logic.test.ts apps/frontend/src/features/chat-shell/components/chat-shell.module.css apps/frontend/src/features/chat-shell/components/chat-surface.tsx apps/frontend/src/features/chat-shell/components/editor-surface.tsx apps/frontend/src/features/chat-shell/components/artifact-stage.tsx
git commit -m "feat(chat-shell): anchored asset-library panel — brand kit pinned, click applies, upload in footer"
```

---

### Task 7: Brand context — kit ∪ registry with the "Uploads" category

**Files:**
- Modify: `apps/frontend/src/features/brand-context/model/brand-context.ts` (`BrandAssetCategorySchema`
  gains `"upload"`; `BrandAssetSchema` gains `origin: z.enum(["kit","registry"])`)
- Modify: `apps/frontend/src/features/brand-context/model/brand-context-mapping.ts` (export
  `kitAssetEntries`; add `toRegistryAssets`; stamp `origin`)
- Modify: `apps/frontend/src/features/brand-context/data/brand-context.repository.ts` (read
  `GET /assets` for the image kinds; pass the records through)
- Modify: `apps/frontend/src/features/brand-context/data/brand-context.fixture.ts` (every fixture
  asset gains `origin: "kit"`)
- Modify: `apps/frontend/src/features/brand-context/hooks/use-brand-context-controller.ts`
  (`assetFilterOptions` gains `{ label: "Uploads", value: "upload" }` before AI-generated)
- Modify: `apps/frontend/src/features/brand-context/components/assets-panel.tsx` (a "Brand" badge on
  `.assetCardPreview` when `asset.origin === "kit"`) + its CSS module
- Test: `apps/frontend/src/features/brand-context/data/brand-context.repository.test.ts` (extend)

**Interfaces:**
- Consumes: Task 2 `registryCategory` (imported from
  `@/features/design-editor/adapter/scene-asset-library` — pure, transport-free).
- Produces: `toRegistryAssets(records: DesignAssetListRecord[], kitIds: ReadonlySet<string>): BrandAsset[]`
  where `DesignAssetListRecord` = the bare public record (`{ id, label?, kind, status, source, media?, raster?, vector?, provenance? }`)
  parsed by a new `DesignAssetListRecordSchema` in `model/brand-kit.ts`; a registry asset's
  `createdAt` = `provenance.created_at ?? ""`.

- [x] **Step 1: Write the failing tests** (append to `brand-context.repository.test.ts`)

```ts
function registryRoutes(records: unknown[]): Record<string, { body: unknown }> {
  const page = (kind: string) => ({ body: { assets: records.filter((r) => (r as { kind: string }).kind === kind), count: 0, limit: 200, offset: 0 } });
  return {
    "/assets?kind=raster_image&include_archived=false&limit=200&offset=0": page("raster_image"),
    "/assets?kind=vector&include_archived=false&limit=200&offset=0": page("vector"),
    "/assets?kind=logo&include_archived=false&limit=200&offset=0": page("logo"),
  };
}

test("the Assets section lists the kit's items plus workspace uploads, deduped, categorized", async () => {
  const upload = { id: "asset_upl_1", kind: "raster_image", label: "team.jpg", status: "ready",
    source: { kind: "uploaded", filename: "team.jpg", uploaded_by: null }, media: { mime_type: "image/jpeg", byte_length: 1234, filename: "team.jpg" },
    provenance: { created_at: "2026-09-01T10:00:00Z" } };
  const generated = { id: "asset_gen_1", kind: "raster_image", label: "generated hero", status: "ready", source: { kind: "generated", request_id: null, model: "x" } };
  const kitLogoId = brandKitAssetIds(HARVESTED_BRAND_KIT)[0]; // import from "../model/brand-context-mapping"
  assert.ok(kitLogoId, "the harvested kit must carry at least one asset");
  const kitDup = { id: kitLogoId, kind: "logo", label: "dup of kit logo", status: "ready", source: { kind: "uploaded", filename: null, uploaded_by: null } };
  const { fetchImpl } = stubDesignApi({
    "/brand-kits": { body: { brand_kits: [HARVESTED_BRAND_KIT.brand_kit] } },
    [`/brand-kits/${KIT_ID}`]: { body: HARVESTED_BRAND_KIT },
    ...assetRoutes(),
    ...registryRoutes([upload, generated, kitDup]),
  });
  const { workspace } = await httpBrandContextRepository({ designFetch: () => fetchImpl }).getWorkspace();
  const byId = new Map(workspace.assets.map((a) => [a.id, a]));
  assert.equal(byId.get("asset_upl_1")?.category, "upload");
  assert.equal(byId.get("asset_upl_1")?.origin, "registry");
  assert.equal(byId.get("asset_upl_1")?.name, "team.jpg");
  assert.equal(byId.get("asset_gen_1")?.category, "ai-generated");
  assert.equal(byId.get(kitLogoId)?.origin, "kit");                 // the kit wins the dedupe
  assert.equal(workspace.assets.filter((a) => a.id === kitLogoId).length, 1);
  assert.ok(workspace.assets.findIndex((a) => a.origin === "kit") < workspace.assets.findIndex((a) => a.id === "asset_upl_1"));
});

test("a failed registry read leaves the kit's assets intact", async () => {
  const { fetchImpl } = stubDesignApi({
    "/brand-kits": { body: { brand_kits: [HARVESTED_BRAND_KIT.brand_kit] } },
    [`/brand-kits/${KIT_ID}`]: { body: HARVESTED_BRAND_KIT },
    ...assetRoutes(),
  });
  const { workspace } = await httpBrandContextRepository({ designFetch: () => fetchImpl }).getWorkspace();
  assert.ok(workspace.assets.length > 0);
  assert.ok(workspace.assets.every((a) => a.origin === "kit"));
});
```

- [x] **Step 2: Run to verify it fails**

Run: `cd apps/frontend && npx tsx --test src/features/brand-context/data/brand-context.repository.test.ts`
Expected: the two new tests FAIL (no `origin`, no uploads).

- [x] **Step 3: Implement**

`model/brand-context.ts`: `BrandAssetCategorySchema = z.enum(["logo","background","mockup","upload","ai-generated"])`;
add `origin: z.enum(["kit", "registry"]),` to `BrandAssetSchema`.

`model/brand-kit.ts`: add
```ts
/** One bare record from `GET /assets` (the list route returns records, not `{asset, created_at}`). */
export const DesignAssetListRecordSchema = z.object({
  id: z.string().min(1),
  kind: z.string(),
  label: z.string().nullish(),
  status: z.string(),
  source: z.object({ kind: z.string() }).passthrough(),
  media: z.object({ mime_type: z.string().nullish(), byte_length: z.number().nullish(), filename: z.string().nullish() }).nullish(),
  raster: z.object({ pixel_width: z.number().nullish(), pixel_height: z.number().nullish() }).nullish(),
  vector: z.object({ width: z.number().nullish(), height: z.number().nullish() }).nullish(),
  provenance: z.object({ created_at: z.string().nullish() }).nullish(),
});
export type DesignAssetListRecord = z.infer<typeof DesignAssetListRecordSchema>;
```

`model/brand-context-mapping.ts`: `export` `kitAssetEntries`; in `toAssets` stamp `origin: "kit"`;
add:
```ts
import { registryCategory } from "@/features/design-editor/adapter/scene-asset-library";

/** Registry images the kit does not carry — "Uploads", or "AI-generated images" (spec R-F). */
export function toRegistryAssets(
  records: readonly DesignAssetListRecord[],
  kitIds: ReadonlySet<string>,
): BrandAsset[] {
  const seen = new Set<string>();
  const out: BrandAsset[] = [];
  for (const record of records) {
    if (record.status === "archived" || kitIds.has(record.id) || seen.has(record.id)) continue;
    seen.add(record.id);
    const media = record.media;
    const geometry = record.vector
      ? { width: record.vector.width, height: record.vector.height }
      : { width: record.raster?.pixel_width, height: record.raster?.pixel_height };
    const createdAt = record.provenance?.created_at ?? "";
    out.push({
      category: registryCategory(record),
      createdAt,
      createdLabel: dateLabel(createdAt),
      description: "",
      dimensions: dimensionLabel(geometry.width, geometry.height) ?? UNKNOWN,
      id: record.id,
      name: record.label ?? media?.filename ?? record.id,
      origin: "registry",
      sizeBytes: media?.byte_length ?? 0,
      sizeLabel: media?.byte_length != null ? byteLabel(media.byte_length) : UNKNOWN,
      type: mediaTypeLabel(media?.mime_type ?? null),
      visual: { imagePath: `${DESIGN_ASSET_BFF_PREFIX}/${encodeURIComponent(record.id)}/bytes`, kind: "image" },
    });
  }
  return out;
}
```
and extend `toBrandContextWorkspace(kit, options)` to accept `registryRecords?: readonly DesignAssetListRecord[]`
and return `assets: [...toAssets(kit, options.assetRecords), ...toRegistryAssets(options.registryRecords ?? [], new Set(brandKitAssetIds(kit)))]`.

`data/brand-context.repository.ts::readWorkspace`: after the kit-asset hydration, read the registry
(each kind; a failure leaves `registryRecords = []` with a `console.warn`, never blanking the page):
```ts
  const registryRecords: DesignAssetListRecord[] = [];
  for (const kind of ["raster_image", "vector", "logo"]) {
    try {
      const page = (await read(`/assets?kind=${kind}&include_archived=false&limit=200&offset=0`)) as { assets?: unknown[] };
      for (const raw of page.assets ?? []) {
        const parsed = DesignAssetListRecordSchema.safeParse(raw);
        if (parsed.success) registryRecords.push(parsed.data);
      }
    } catch (error) {
      console.warn(`[brand-context] registry read for ${kind} failed; kit assets only:`, error);
    }
  }
```
and pass `{ assetRecords, registryRecords }` to `toBrandContextWorkspace`. (One page per kind is
enough for the page; the editor's `listImageAssets` pages further because it needs completeness.)

`hooks/use-brand-context-controller.ts`: insert `{ label: "Uploads", value: "upload" }` before the
AI-generated entry. `data/brand-context.fixture.ts`: add `origin: "kit"` to every asset.
`components/assets-panel.tsx`: inside `.assetCardPreview`, after `<AssetVisual …/>`, render
`{asset.origin === "kit" ? <span className={styles.assetCardBadge}>Brand</span> : null}` with CSS
`.assetCardBadge { position:absolute; left:8px; top:8px; padding:2px 6px; border-radius:4px; font-size:10px; font-weight:500; background:#fff; color:#44483F; border:0.5px solid var(--clue-ds-color-border-neutral); }`
(and `.assetCardPreview { position: relative; }` if it is not already).

- [x] **Step 4: Run to verify it passes**

Run: `cd apps/frontend && npx tsx --test src/features/brand-context/data/brand-context.repository.test.ts src/features/brand-context/model/*.test.ts && npx eslint src/features/brand-context && npx tsc --noEmit -p tsconfig.json 2>&1 | grep -E "brand-context" || echo "tsc: no diagnostics in brand-context"`
Expected: PASS (fix any existing brand-context test that built a `BrandAsset` without `origin` by
adding `origin: "kit"`); eslint clean; no tsc diagnostics.

- [x] **Step 5: Commit**

```bash
git add apps/frontend/src/features/brand-context
git commit -m "feat(brand-context): Assets lists kit items and workspace uploads (Uploads category, Brand badge)"
```

---

### Task 8: Rung close — frontend gate, live walk, close-out

**Files:**
- Create: `_memory/2026-09-02-replace-image-asset-library-close-out.md`
- Modify: this plan (tick boxes)

- [x] **Step 1: Frontend gate**

Run (from `apps/frontend/`): `npm run design-system:build && npm run lint && npm test`; then stop the
3023 dev server (kill by PID whose cwd is THIS worktree — never a sibling's), `rm -rf .next`,
`npm run build`, restart the dev server (`npm run dev -- --port 3023`).
Expected: lint 0 errors; `npm test` ≥ 2462 pass, 0 fail; build emits the route table.

- [x] **Step 2: Live walk** on the nashville stack (3023/8013/8023; recipe in
  `_memory/2026-09-01-nashville-workspace-setup.md`; Apollo test account), Cursor LinkedIn ad, Edit:
  1. select `image wash` → "Replace image" shows a caret; the menu has exactly two rows, no format text;
  2. "Upload from computer" → the OS dialog (no GIF offered) → a PNG replaces the wash; ⌘Z restores;
  3. "Choose from asset library" → the panel opens beside the inspector over the stage; Brand kit
     section first (badged), Workspace after; the current asset badged "In use";
  4. click a brand logo → canvas repaints, "In use" moves; click a prior upload; click an AI image →
     three writes; ⌘Z ×3 walks back; ⌘⇧Z forward;
  5. click the in-use tile → "That's the image already in use." in the inspector; nothing written;
  6. footer "Upload from computer" → the file appears at the top of Workspace, badged "In use";
  7. search and the category chip filter the grid; Esc / outside click / ✕ each close the panel;
  8. leave Edit mode (view) → menu rows refuse with "This document isn't accepting edits right now.";
  9. Brand context → Assets: the uploads appear under "Uploads", kit items badged "Brand", the
     AI image under "AI-generated images"; sort/search work across both.
  Record every observation (pass/defect) in the close-out; a defect opens a fix round, not a caveat.

- [x] **Step 3: Close-out** — write `_memory/2026-09-02-replace-image-asset-library-close-out.md`
  (what shipped, commits, gate numbers, walk verdicts, residuals, rulings), tick this plan, commit:

```bash
git add _memory/2026-09-02-replace-image-asset-library-close-out.md docs/superpowers/plans/2026-09-02-replace-image-asset-library.md
git commit -m "docs(memory): replace-image asset-library close-out"
```
