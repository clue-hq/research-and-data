# Slice 4 design — brand kit review UI + asset library + ingest surface

Implementation spec for Brand-kit Ingestion v1 slice 4 (plan §6.7/§7; slices 0–3 shipped).
**Visual system: design/DESIGN.md (Cursor extraction) — NOT moda's theme. UX anatomy:
moda's kit-page structure + ploy's asset-library structure** (studies in
BRANDKIT-INGESTION-V1-PLAN.md §1b/§2/§3). The design-system FOUNDATION IS ALREADY BUILT
(uncommitted, in tree): `apps/editor/src/app/brand/{tokens.css,brand.css,layout.tsx}` —
read all three before writing any UI. Hard rules carried from DESIGN.md §10: **no literal
colors outside tokens.css, no box-shadows (focus ring exempt), no invented radii/spacing —
compose the existing classes/vars**; ink-pill = primary action; accent never fills;
sentence case; mono (`.mono`) for data/ids/hex.

Routes are standalone Next.js app-router pages under `apps/editor/src/app/brand/` — ZERO
edits to editor-canvas files, EditorApp, styles.css, or engine/scene code. Frontend
conventions: docs/frontend-practices.md + survey notes (fetch wrappers with explicit
`apiBaseUrl` via `editorApiBaseUrl()`, plain CSS classes, vitest+RTL with
`vi.stubGlobal("fetch", …)`).

## 0. Ownership

- **Agent A (API):** apps/api additions + tests. No frontend files.
- **Agent B (kit pages):** `app/brand/page.tsx` (list), `app/brand/kits/[kitId]/page.tsx`
  + `src/components/brand/kit*` + `src/engine/brandHub.ts` + tests. May APPEND classes to
  brand.css for kit-page-specific layout (prefix `.kit-`); never edits tokens.css/layout.
- **Agent C (library + ingest):** `app/brand/library/page.tsx`, `app/brand/ingest/page.tsx`
  + `src/components/brand/library*`/`ingest*` + `src/engine/brandLibrary.ts` + tests. May
  APPEND classes prefixed `.lib-`/`.ingest-`; never edits tokens.css/layout/brandHub.ts.

## 1. Agent A — API additions (apps/api)

1. **Approval route.** `POST /brand-kits/{brand_kit_id}/approval` body
   `{"approval_status": "approved" | "draft"}` (422 otherwise). Loads latest version row,
   sets the column AND `brand_kit_json.approval_status`, persists (new Repository method
   `update_brand_kit_approval`), returns `brand_kit_detail_dto`. 404 unknown kit.
2. **Detail DTO carries the summary.** `brand_kit_detail_dto` gains
   `"brand_summary": record.get("brand_summary") or {}` (full — includes the `ingestion`
   report). Additive key; existing tests untouched.
3. **Description routes** (backed by slice-3 `DescriptionStore`):
   - `GET /assets/descriptions?asset_ids=a,b,c` → `{"schema_version":1, "descriptions":
     {asset_id: {title, description, usage, tags, origin, updated_at}}}` (missing ids
     simply absent; cap 200 ids).
   - `PUT /assets/{asset_id}/description` body `{title?, description?, usage?,
     tags?: [str]}` → `DescriptionStore.put_human` (partial update: merge with existing
     row's fields) → returns the row. 404 only if the asset record doesn't exist.
4. **Job list.** `GET /brand-kits/ingest` → `{"jobs": [ingestion_job_dto…]}` most-recent
   50 (new `IngestionJobStore.list_recent(limit)`). Register BEFORE
   `GET /brand-kits/ingest/{job_id}`? NO — FastAPI matches literal `/brand-kits/ingest`
   only when the path has no extra segment, so ordering vs the param route is safe either
   way; still place it adjacent and add a route test.
Tests: `tests/test_ingestion_ui_api.py` — approval happy/invalid/404 + detail dto
summary key; descriptions GET batch/PUT partial merge/put_human origin + 404; job list
ordering + shape. Run the ingestion route suites for regressions.

## 2. Shared frontend contracts

`src/engine/brandHub.ts` (Agent B owns; C imports read-only):
```ts
export interface BrandKitListEntry { id, version, name, approval_status, product_ready,
  source, description, created_at, updated_at }           // from GET /brand-kits summaries
export async function fetchBrandKitList(options): Promise<BrandKitListEntry[]>
export interface BrandKitDetail { brandKit: BrandKitListEntry; kitJson: any;
  summary: any; diagnostics: any[] }                       // GET /brand-kits/{id} (+ brand_summary)
export async function fetchBrandKitDetailFull(options, id): Promise<BrandKitDetail>
export async function setBrandKitApproval(options, id, status): Promise<BrandKitDetail>
export function assetBytesUrl(apiBaseUrl, assetId): string  // `${base}/assets/${id}/bytes`
```
`src/engine/brandLibrary.ts` (Agent C owns): `fetchLibraryAssets` (reuse GET /assets via
assetLibrary.fetchAssets patterns; limit 200), `fetchDescriptions(ids)`,
`saveDescription(id, patch)`, `startWebsiteIngest(url, name?)`, `startPdfIngest(file)`,
`startAssetIngest(files)`, `fetchIngestJob(jobId)`, `fetchIngestJobs()`.
All follow documentStore.ts style: explicit `{ apiBaseUrl }` options, throw on non-2xx.

Pages are client components (`"use client"`) with hook-local state; loading = quiet
`.caption` text; errors = `.status-pill is-error` inline. No new deps.

## 3. Agent B — kit pages (moda anatomy, Cursor skin)

### /brand (list)
`.eyebrow` "Brand kits" + `.headline` "Your brand, distilled." · grid (`.grid-cards`) of
`.brand-card is-clickable` per kit: name (`.title` 26px), source chip (`website|pdf|
asset_upload|…`), `.status-pill is-approved|is-draft`, version + created `.caption`,
description 2-line clamp `.mono`? no — body text muted. Empty state: `.dropzone`-style
card linking to /brand/ingest. Top-right actions: `.btn btn-primary` "Ingest a brand" →
/brand/ingest.

### /brand/kits/[kitId] (detail/review — section order per moda's kit page)
1. **Identity header:** name as `.display` WITH terminal period ("Insight Health.") ·
   under it: source + url + captured date (`.caption .mono`) · status pills · kit
   description paragraph (`--text-body-lg`, muted) · action row: Approve (`.btn
   btn-primary`, becomes ghost "Revert to draft" when approved) + "Open editor" ghost.
2. **Colors** — light + dark colorway cards side by side (`.brand-card`): grouped rows
   (Backgrounds / Text / Accent / Borders — group labels `.eyebrow`) of
   `swatch + role name + hex in .mono` (light uses `value`, dark card uses the
   `modes["theme.dark"]` values; dark card gets `.status-pill` "captured"/"synthesized"
   from summary.ingestion.dark_colorway). Below: **palette ramps** (`.ramp-row` for
   palette.primary.* and palette.neutral.* sorted by stop) and **extras** as chips with
   swatch + name (palette.extra.*).
3. **Typography:** per font in kitJson.assets.fonts — `.brand-card` with family name
   `.title`, a specimen line "Aa Bb Cc 123" rendered in the family with fallback stack
   (inline style fontFamily is ALLOWED here — it's data, not chrome), faces table
   (`.brand-table`: weight/style/source-url-status) and the **availability warning** when
   faces are empty: `.status-pill is-draft` "Font files not sourced — upload or pick an
   alternative" + suggestion chips (Inter · Work Sans · DM Sans, static). Then the type
   ramp table from kitJson.tokens.typography (`role / family / size / weight / lh`,
   sizes in `.mono`).
4. **Logos:** `.grid-cards` of `.asset-thumb` (img src=assetBytesUrl) per variant with
   `color_mode` chip; reversed variants render the thumb on `--ink` background (inline
   style backgroundColor var reference ok). Group captions primary/mark/wordmark.
5. **Images:** `.grid-cards` thumbs; title/description from kit asset fields when present
   (title `.body`, description `.caption` clamp-2).
6. **Voice & rules:** tone chips; `constraints.accessibility_notes`/imagery/print as
   `.hairline-list`; `summary.ingestion.rules` (kind chip + text) — don'ts get
   `.diag-code`-style leading "don't" chip.
7. **Ingestion report** (`.brand-card` on `--bg-card-01`): stats line (`.mono`), gaps as
   chips, **role_assignments table** (`.brand-table`): token `.mono` / swatch+hex /
   basis chip (evidence=green-wash, derived=chip, default=draft-pill) / pointer
   `.caption .mono` truncated.
8. **Diagnostics:** `.diag-list` with severity classes, collapsed behind a ghost button
   toggle ("Show N diagnostics").
Approve flow: optimistic pill flip + `setBrandKitApproval`; failure reverts + inline
error pill.
Tests (`__tests__/BrandKitPages.test.tsx`): list renders kits + empty state; detail
renders sections from a fixture detail payload (build a small kitJson fixture inline —
reuse shapes from apps/api golden fixtures); approve click issues POST and flips pill;
font-warning renders when faces empty; dark pill shows "synthesized".

## 4. Agent C — library + ingest

### /brand/library (ploy anatomy, Cursor skin)
Layout: left sidebar (200px) + content. Sidebar: "All assets" + tag filters computed from
fetched asset records' tags (counts, `.chip is-selected` on active) — provenance tags
(brand-ingestion, upload, website…) and kind tags (logo/photo/illustration…) mixed, like
ploy. Content: `.field` search input (name/title substring) + grid/table toggle (two
`.btn-quiet` icons) · **grid** = `.grid-cards` of `.asset-thumb` + title line (description
title ?? label ?? filename) + kind chip · **table** = `.brand-table` (thumb 32px, name,
kind, size, created, sorted by created desc).
**Detail lightbox** on click (`.lightbox-overlay`/`.lightbox-panel`): left = large
preview (checkerboard-free, `--bg-card` backdrop); right panel (320px, hairline-left):
**Title / Description / Usage** — each a view row with a `.btn-quiet` "Edit" toggling a
textarea + Save (`saveDescription`; origin becomes human — show "edited" `.caption`
after) — plus read-only Filename (`.mono`), Type, Dimensions (when in record metadata),
Created, Tags as chips. Esc/overlay-click closes. This is ploy's exact detail anatomy in
our skin.

### /brand/ingest (three intake paths + moda-style progress)
Three `.brand-card`s in a row: **Website** (url input + name optional + `.btn-primary`
"Scan site"), **Brand PDF** (`.dropzone` + file input, application/pdf), **Assets**
(`.dropzone`, multiple). Submit → POST → switch the card column to a progress panel:
`.stage-line` (stage text from job), `.progress-track/.progress-fill` (width =
progress*100%), poll `fetchIngestJob` every 1.5s until terminal. Succeeded → success row
with kit name + `.btn-primary` "Review kit" → /brand/kits/{id}. Failed → `.status-pill
is-error` + error message + retry ghost. Below: "Recent ingestions" `.hairline-list` from
`fetchIngestJobs` (kind chip, stage/status, when, link when succeeded).
Tests (`__tests__/BrandLibraryIngest.test.tsx`): library renders assets + tag filter
narrows + search; lightbox opens, edit-save PUTs and re-renders; ingest website submit
POSTs + polling reaches succeeded (fake timers) + link rendered; failed job shows error.

## 5. Verification (both frontend agents)

`cd apps/editor && npm run lint && npx vitest run src/components/brand src/app/brand
--reporter=basic` (plus your own test files) — and `npm run test` full suite for
regressions. DO NOT run `npm run dev` (browser verification happens after landing, by the
orchestrator per docs/frontend-practices.md §5).

## 6. Out of scope

Dark mode for the brand section (tokens only ship light; DESIGN.md §3.7 gap), asset
delete/re-tag, kit editing (values are read-only in v1 — approval + descriptions are the
only mutations), editor-shell restyle (the Cursor skin stays inside /brand until the
frontend-revamp phase), pagination (limit 200), i18n.
