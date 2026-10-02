# Ad-Editor Integration — Execution Plan (AD0–AD5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mount the clue-design scene (ad) editor — CanvasKit + SkParagraph over the Rust `lumen-core` engine — inside the platform frontend's dummy-designed ad shell, with every §1-contract inspector control live against the engine through CAS-committed operations, on both the artifact route and the chats route.

**Architecture:** Extract the React-free scene engine layer from `subsystems/clue-design/apps/editor/src/engine/` into `apps/frontend/src/features/design-editor/engine/scene/` behind the existing injected `DesignEditorConfig`; vendor `canvaskit.wasm` + `lumen_wasm` + Inter TTFs through `scripts/copy-design-vendor.mjs`; bind the already-lifted dummy ad inspector at the adapter seam (`scene-hydrate` / `scene-apply`), mirroring the completed W0–W5 web-editor integration exactly.

**Tech Stack:** Next.js 16 (webpack build / turbopack dev), React 19, TypeScript, Zod, `node:test` via `tsx --test`, canvaskit-wasm 0.41.1 (exact pin), wasm-pack (Rust `lumen-wasm`), FastAPI (platform + design API).

**Spec:** `docs/specs/ad-editor-integration/ad-inspector-mapping-contract.md` (v1 RATIFIED + amendments 1–3 — the normative ruling record) + `docs/specs/ad-editor-integration/ad-editor-disparity-inventory.md` (evidence) + `docs/superpowers/plans/2026-08-19-ad-editor-integration.md` (study findings §1–§3, decision register §5 — all twelve closed). This plan supersedes that document's §4 phase sketches with executable tasks; its §1–§3/§6–§7 remain the study record.

---

## Global Constraints

Copied from the contract's inherited laws and the W0–W5 regime. Every task's requirements implicitly include these.

- **Dummy UI is presentation truth and ceiling.** Lift verbatim, bind at the seam, never invent UI. Engine-forced new visible chrome ships only after founder-approved mockups (§6 of the contract; the gate register below).
- **Contract partitions are law**: §1 wired / §2 founder-ordered deltas / §3 visible-but-inert / §5 hidden-dropped / §6 mockup-gated / §7 future / §8 engine changes (none authorized; one decision pending — see Gate E).
- **Never browser→FastAPI.** All design traffic through `/api/clue/design` (authenticated BFF) or the new `/api/clue/design-public` passthrough (Task AD1.7). The scene engine slice reads **no** ambient environment (`process.env`, `NEXT_PUBLIC_*`) — enforced by a sibling no-env-reads test.
- **Process:** Opus implements; the orchestrating session reviews every diff inline; TDD on pure adapters against **harvested real fixtures** (never hand-written shapes); browser proof + local commit per task; **never push**; no AI attribution in commits.
- **Gates per task:** `cd apps/frontend && npm run design-system:build && npm test && npm run lint && npm run build`. Root `make check` at each phase close. Backend tasks: the platform's pytest suite for touched modules.
- **Engine edits** (there are none authorized): would require mirroring into both copies byte-identically + `cargo build -p lumen-api-helper --release` + design-API restart + wasm rebuild.
- **Test runner is `find src -name '*.test.ts' | xargs tsx --test`** — no `.test.tsx`, no DOM renderer. Hook/component logic lives in pure decision modules. Ported vitest tests run behind `src/features/design-editor/engine/__tests__/vitest-shim.ts` (extend only when a newly ported test needs it).
- **Components never import `data/` or the engine** (eslint `no-restricted-imports` enforces); adapters may import data-layer constants.
- **Key naming:** platform artifact `kind` for scenes is `"ad"`; the design DB `doc_kind` is `"scene"`. Never confuse the two vocabularies at the seam.
- **Version pins:** `canvaskit-wasm` **exactly `0.41.1`** (no caret — render parity); `lumen_wasm_bg.wasm` ≤ 3 MB gzip (build fails at ≥ 3145728 bytes).
- Zoom transforms clamp to the engine's `[0.1, 2.0]`; the ratified 10–150% @ 5% menu sits inside it.

---

## Founder-gate register (mockups & decisions — schedule these early, none block AD0/AD1)

| Gate | What | Blocks | Owner action |
|---|---|---|---|
| **G-A** | Selection outline + move/resize handle visuals (§6.1) | AD2.5's visible outline; Lane C entirely | Orchestrator produces 2–3 SVG-overlay options as browser screenshots; founder picks |
| **G-B** | "Leaves your brand palette" note design + wording (§6.2) | AD4.0's custom-hex confirmation note (picker itself unblocked) | Same |
| **G-C** | Crop focal-point dot (§6.3) | Lane A's Crop mode reveal (Fit/Fill unblocked) | Same |
| **G-D** | ~~Engine-forced state wordings (§6.6)~~ — **RULED & SHIPPED 2026-08-21.** Founder: "approve them as is from the mvp editor only, no separate banner needed… for readonly also keep them same as that in other mode only", then, on the browser preview: "all 4 previews look good… proceed with them just the way you showed them to me." So: the MVP editor's `EngineDisabledBanner` + `HeuristicMeasurementBanner` ported whole (copy test-locked against `EditorChrome.tsx`), read-only sharing the degraded-text treatment rather than a canvas-specific one, and the CAS conflict staying the inspector note (D10). Implemented in `scene-artifact-canvas.tsx` (`SceneEngineBanners`) + `scene-engine-banners.ts`; browser-proven against forced real failures. Three deviations disclosed at the preview and taken: opaque background (upstream's 15%-alpha wash is illegible over a dark artboard), the two banners stack (upstream pins both at `top:14px`), and the command chip names *this* repo's command. | ~~Showing the banners~~ nothing | ~~Orchestrator proposes copy~~ done |
| **G-E** | **§8 transparency decision — evidence now complete.** AD1 verification (scouts, 2026-08-20) is definitive: the raster export paints an unconditional opaque-white background (`lumen-skia/src/render.rs:207-212`), regression-locked by `raster_export.rs::empty_page_rasters_as_white_paper_not_black`, with no options struct to thread a flag through. The engine change = a field on `ExportProfile` + threading through `PageRasterizer::rasterize_page` + a conditional at the white-paint site. | Lane D's transparency checkbox (everything else in export unblocked) | Founder authorizes the engine change **or** rules the checkbox out of v1. Until ruled: the checkbox is **not rendered** (fail-honest; a toggle that changes nothing is worse than absence). |
| **G-F** | Export print-extras options in dummy style (§6.5) — PDF digital/print intent, bleed & marks, sRGB/CMYK | Those extra options only | Browser demo per the founder's standing instruction |
| **G-G** | The 23-file dummy delta committed + pushed by the co-founder | **All of AD0**; nothing else | Record the commit hash in the contract header slot |

The CAS-conflict message needs **no** gate: D10 ratified the web editor's already-approved string ("Document moved on — reloaded.").

---

## File map (what exists at the end)

```
apps/frontend/
  next.config.ts                                     MODIFY  (webpack fallbacks for canvaskit)
  package.json                                       MODIFY  (canvaskit-wasm 0.41.1 dep)
  scripts/copy-design-vendor.mjs                     MODIFY  (scene vendor section)
  public/vendor/{canvaskit,wasm,fonts}/              GENERATED (gitignored)
  src/app/api/clue/design-public/[...path]/
    route.ts, public-proxy-handler.ts, route.test.ts CREATE  (D8 headerless passthrough)
  src/features/design-editor/
    engine/scene/                                    CREATE  (~30 extracted modules, listed in AD1.3–AD1.6)
    engine/scene/__tests__/                          CREATE  (ported tests + no-env-reads-scene.test.ts)
    adapter/scene-hydrate.ts (+.test.ts)             CREATE
    adapter/scene-apply.ts (+.test.ts)               CREATE
    adapter/scene-layers.ts (+.test.ts)              CREATE
    adapter/scene-export.ts (+.test.ts)              CREATE
    adapter/__fixtures__/scene-nodes.ts              CREATE  (harvested)
    adapter/gallery.ts                               MODIFY  (kind-aware)
    components/scene-artifact-canvas.tsx (+.module.css)  CREATE
    hooks/use-scene-editing-session.ts               CREATE
    hooks/use-scene-manual-edits.ts                  CREATE
    hooks/use-scene-inspector-writes.ts              CREATE
    model/artifact.ts                                (unchanged — kind "ad" already in contract)
  src/features/chat-shell/
    components/image-inspector.tsx                   MODIFY  (AD0 re-lift + §2 deltas + real props)
    components/ad-dummy-inspectors.tsx               CREATE  (AD0 re-lift from dummy delta)
    components/web-inspector.tsx                     MODIFY  (RadiusControls hoisted out; AD0 re-lift)
    components/inspector-primitives.tsx              MODIFY  (RadiusControls hoisted in; delta re-lift)
    components/artifact-stage.tsx                    MODIFY  (scene canvas in the ad branch)
    components/artifact-header.tsx                   MODIFY  (zoom options; export wiring props)
    components/chat-surface.tsx                      MODIFY  (real ad-inspector props)
    components/editor-surface.tsx                    MODIFY  (ad dock added)
    model/chat-shell.ts                              MODIFY  (AD0 re-lift: new selection kinds)
    model/image-export.ts                            MODIFY  (JPEG dropped)
    hooks/use-image-export-controller.ts             MODIFY  (transparency per Gate E; addressing)
platform/api/clue_api/
  design_leg_wiring.py                               MODIFY  (gallery kind widening)
  chat/router.py                                     MODIFY  (list kind mapping)
scripts (platform dev):
  seed such that AD2.2 defines                       CREATE
```

---

# Phase AD0 — Shell completion (gated on G-G, parallel with AD1)

### Task AD0.1: Re-lift the 23-file dummy delta

**Files:**
- Create: `apps/frontend/src/features/chat-shell/components/ad-dummy-inspectors.tsx`
- Modify: `apps/frontend/src/features/chat-shell/components/{image-inspector.tsx,inspector-primitives.tsx,web-inspector.tsx,chat-shell.module.css}`, `apps/frontend/src/features/chat-shell/model/chat-shell.ts`, plus whatever else the 23-file delta touches inside lifted files (the delta is authoritative)
- Copy: any new icon files the delta adds under `public/icons/chat-shell/`
- Modify: `docs/specs/ad-editor-integration/ad-inspector-mapping-contract.md` (fill the pin-hash blank)

**Interfaces:**
- Consumes: the co-founder's commit on `clue-hq/clue-frontend` branch `codex/chat-shell` (hash recorded at G-G; parent `c7f2bc5`).
- Produces: the four new schema components (auto-layout / rectangle / ellipse / group) as designed static scaffolding; `ChatShellInspectorSelection` extended with the new selection kinds; `web-inspector.tsx` current with dummy HEAD again. Later tasks reference the new selection-kind strings exactly as the delta names them — **read them from the lifted `model/chat-shell.ts` after this task and use those literals everywhere** (do not invent names like `"autoLayout"` if the dummy says `"auto-layout"`).

- [ ] **Step 1:** Record the delta commit hash in the contract header slot (`_________` → the hash). Commit the doc edit separately: `docs(ad-editor): pin the dummy delta commit in the contract`.
- [ ] **Step 2:** In the dummy checkout at the pinned commit, list the delta: `git -C /Users/aryankeshri/Documents/clue-hq/clue-frontend diff --name-only c7f2bc5..<hash>`. Every file under `src/features/chat-shell/` in that list is in scope; files outside chat-shell are not (note them in the commit message as skipped).
- [ ] **Step 3:** For each in-scope file, copy byte-verbatim into `apps/frontend` at the same relative path. For `chat-shell.module.css`, apply the delta's changed ranges only (our copy is a W0.2 bisect, not the full dummy file — use `git -C <dummy> diff c7f2bc5..<hash> -- src/features/chat-shell/components/chat-shell.module.css` and apply each hunk; hunks touching never-lifted blocks named in our CSS header comment stay out).
- [ ] **Step 4:** Verify byte parity per fully-lifted file: `cmp apps/frontend/src/features/chat-shell/components/ad-dummy-inspectors.tsx <dummy>/src/features/chat-shell/components/ad-dummy-inspectors.tsx` (repeat for image-inspector, web-inspector, model/chat-shell.ts). Record any file that cannot be byte-identical (platform-only divergence, e.g. web-inspector's added props) as a documented exception with the exact hunk list.
- [ ] **Step 5:** Run the gate: `npm run design-system:build && npm test && npm run lint && npm run build`. Expected: green (the new component is not yet imported anywhere, that's fine — verify it compiles).
- [ ] **Step 6:** Commit: `feat(ad-editor): AD0.1 re-lift the co-founder's 23-file ad-schema delta (pinned <hash>)`.

### Task AD0.2: CSS + icon coverage audit

**Files:**
- Modify: `apps/frontend/src/features/chat-shell/components/chat-shell.module.css` (only if the audit finds gaps)
- Copy: missing icons into `public/icons/chat-shell/inspector/shared/` (or the delta's chosen directory)

**Interfaces:**
- Consumes: AD0.1's lifted components.
- Produces: every class referenced by the lifted ad components exists; every `InspectorIcon` name renders. The **two alignment icon families** noted in the inventory (§2.6 icon-vocabulary note: old `align-left…` on the text schema, new `align-start-vertical…` on the new schemas) are both present — reconciliation to one family is a §7 item, not this task.

- [ ] **Step 1:** Extract every `styles.<name>` reference from `image-inspector.tsx` + `ad-dummy-inspectors.tsx` + `image-export-menu.tsx` + the ad branches of `artifact-header.tsx`/`artifact-stage.tsx`: `grep -oh 'styles\.[A-Za-z]*' <files> | sort -u`. For each, `grep -c "^\.<name>" chat-shell.module.css` ≥ 1. Missing → extract that rule byte-verbatim from the dummy CSS at the pinned commit.
- [ ] **Step 2:** Extract every icon name passed to `InspectorIcon`/`ChatShellIcon` in those files; verify the SVG exists under `public/icons/chat-shell/`. Missing → copy from the dummy repo's `public/` at the pinned commit, `cmp`-verified.
- [ ] **Step 3:** Confirm the never-lifted dead blocks stay out (`.imageEditorToolbar`, `.editorToolButton*`, `.editorToolGroup` — the tool palette is §5-hidden; `public/icons/chat-shell/editor/` stays absent).
- [ ] **Step 4:** Gate + commit: `chore(ad-editor): AD0.2 ad CSS/icon coverage audit`.

### Task AD0.3: Hoist `RadiusControls` into `inspector-primitives.tsx`

**Files:**
- Modify: `apps/frontend/src/features/chat-shell/components/inspector-primitives.tsx` (add the component), `web-inspector.tsx` (remove it; import from primitives), `image-inspector.tsx` (import from primitives)

**Interfaces:**
- Produces: `export function RadiusControls({ onApplyAll?, onChange, values })` from `inspector-primitives.tsx` — signature byte-identical to today's `web-inspector.tsx:338-351`, including the optional `onApplyAll?: (value: string, clearsCorners: boolean) => void` and the documented dummy fan-out fallback when absent. `RadiusCorner`/`RadiusValues` types move with it.

- [ ] **Step 1:** Move the component + its private helpers (`NUMERIC_RADIUS`, draft state, `commitAll`, `applyAll`) verbatim; update the two import sites (`web-inspector.tsx:990` usage keeps `onApplyAll={setRadiusAll}`; `image-inspector.tsx:291` usage unchanged).
- [ ] **Step 2:** `npm test` (the web adapter tests exercise radius writes indirectly; expect green), then full gate.
- [ ] **Step 3:** Commit: `refactor(ad-editor): AD0.3 hoist RadiusControls into inspector-primitives`.

### Task AD0.4: Apply the §2 founder-ordered deltas to the lifted surface

**Files:**
- Modify: `image-inspector.tsx`, `ad-dummy-inspectors.tsx`, `artifact-header.tsx`, `model/image-export.ts`, `image-export-menu.tsx`, `hooks/use-image-export-controller.ts`

**Interfaces:**
- Consumes: contract §2 rows 1–8, §5.
- Produces: the presentation surface AD2+ binds to. Exact deltas (each is a contract citation, not a judgment call):

- [ ] **Step 1 — presets (§2.1):** In `image-inspector.tsx` replace
```ts
const SIZE_PRESETS = [
  "Linkedin square (1:1) - 1024x1024",
  "Instagram portrait (4:5) - 1080x1350",
  "Story (9:16) - 1080x1920",
] as const;
```
with corrected values + Custom:
```ts
const SIZE_PRESETS = [
  "Linkedin square (1:1) - 1200x1200",
  "Instagram portrait (4:5) - 1080x1350",
  "Story (9:16) - 1080x1920",
  "Custom",
] as const;
```
Selecting `Custom` reveals two `InspectorInput`s labeled `W`/`H` (px only) below the select, styled with the existing `.fieldGrid` pattern (the same two-input row the dummy uses for X/Y — no new CSS).
- [ ] **Step 2 — typography (§2.2/§2.3):** `FONT_SIZE_OPTIONS` select → an `InspectorInput` free number (min 1). `FONT_WEIGHT_OPTIONS` → the nine names: `["100 Thin","200 Extra Light","300 Light","400 Regular","500 Medium","600 Semi Bold","700 Bold","800 Extra Bold","900 Black"]`. H-alignment gains a fourth Justify toggle (icon exists in the shared set after AD0.2; if the dummy delta added `align-justify`, use it — else use the editor-family icon and note it). `FONT_OPTIONS` becomes a prop-fed list (default `["Inter"]`) — the real vocabulary arrives with hydration in AD2.4; the hardcoded Satoshi/Season Serif/DM Mono entries are deleted now.
- [ ] **Step 3 — image modes (§2.4):** `FILL_MODES` → `["Fit", "Fill", "Crop"] as const`. (Focal control comes with Lane A behind G-C.)
- [ ] **Step 4 — zoom (§2.5):** In `artifact-header.tsx`: `const ZOOM_LEVELS = Array.from({ length: 29 }, (_, i) => \`${10 + i * 5}%\`)` (10%–150% @ 5%); add `max-height` + `overflow-y: auto` to the zoom `.toolbarMenu` via a new modifier class lifted-style (one rule, e.g. `.toolbarMenuScrollable { max-height: 320px; overflow-y: auto; }` — this is a §2-ordered delta, not invention).
- [ ] **Step 5 — export (§2.6):** `model/image-export.ts`: `IMAGE_EXPORT_FORMATS = ["PNG", "SVG", "PDF"]`; delete `imageExportSupportsScale`'s JPEG arm. Per **Gate E**, remove the transparency toggle row from `image-export-menu.tsx` and the `transparentBackground` state from the controller (restore verbatim if the founder authorizes the engine change — note this in the code with a one-line contract citation).
- [ ] **Step 6 — removals (§2.7):** Delete the two "Link to" sections (image + button), delete `AdButtonInspector` and its `BUTTON_STYLE_OPTIONS` (button schema hidden; a `"button"` selection value routes to the image fallback branch until the model re-lift removes it), remove the eye toggle from every schema header (`InspectorHeader` call sites pass nothing for visibility → verify the header hides the eye when `onVisibilityToggle` is absent; if it doesn't, add that guard to `InspectorHeader` — presentation-only).
- [ ] **Step 7:** Gate; browser-proof the inert inspector renders each schema correctly (`npm run dev`, open the fixture ad artifact, screenshot each schema). Commit: `feat(ad-editor): AD0.4 apply the §2 contract deltas to the ad surface`.

### Task AD0.5: AD0 exit audit

- [ ] **Step 1:** Both mounts render the honest empty state (empty artboard div, inert inspector) with zero console errors; visual parity screenshots vs the dummy at the pinned commit (live dummy `npm run dev`, not stale PNGs).
- [ ] **Step 2:** Full gate + root `make check`. Update `_memory/` with an AD0 close-out note. Commit.

---

# Phase AD1 — Engine + wasm substrate (starts immediately; no founder gates)

### Task AD1.1: Vendor pipeline

**Files:**
- Modify: `apps/frontend/package.json` (add `"canvaskit-wasm": "0.41.1"` — exact, no caret), `apps/frontend/scripts/copy-design-vendor.mjs`
- Test: `apps/frontend/src/features/design-editor/iframe/vendor-runtime.test.ts` (extend) or a sibling `vendor-scene.test.ts`

**Interfaces:**
- Produces: `public/vendor/canvaskit/canvaskit.wasm`, `public/vendor/wasm/{lumen_wasm.js,lumen_wasm_bg.wasm}`, `public/vendor/fonts/Inter-{Regular,SemiBold,Bold,ExtraBold}.ttf` on every `predev`/`prebuild`. Later tasks load with `baseUrl: "/vendor/canvaskit"` and `"/vendor/wasm"`, `fontUrls` under `/vendor/fonts/`.

- [ ] **Step 1:** `npm install canvaskit-wasm@0.41.1 --save-exact` in `apps/frontend`.
- [ ] **Step 2:** Extend `copy-design-vendor.mjs` with a scene section (same style as the two existing outputs):
```js
// ── Scene editor vendor assets (ad editor, AD1.1) ──────────────────────────
// canvaskit.wasm: pinned 0.41.1 for render parity with the design subsystem.
const canvaskitWasm = require.resolve("canvaskit-wasm/bin/canvaskit.wasm");
await mkdir(join(vendorDir, "canvaskit"), { recursive: true });
await copyFile(canvaskitWasm, join(vendorDir, "canvaskit", "canvaskit.wasm"));

// Inter statics: TTF only — CanvasKit's FontMgr cannot read woff2.
const designRoot = join(projectRoot, "..", "..", "subsystems", "clue-design");
await mkdir(join(vendorDir, "fonts"), { recursive: true });
for (const face of ["Inter-Regular", "Inter-SemiBold", "Inter-Bold", "Inter-ExtraBold"]) {
  await copyFile(join(designRoot, "fonts", `${face}.ttf`), join(vendorDir, "fonts", `${face}.ttf`));
}

// lumen_wasm: stamp-preflight (rebuilds on source drift when the Rust
// toolchain is present; exits 0 otherwise), then copy the artifacts.
// Missing artifacts are a WARNING, not a failure — the editor mounts
// read-only without wasm (runtime handshake owns the hard guarantee).
execFileSync("node", [join(designRoot, "scripts", "preflight_editor_wasm.mjs")], { cwd: designRoot, stdio: "inherit" });
const wasmSrc = join(designRoot, "apps", "editor", "public", "wasm");
if (existsSync(join(wasmSrc, "lumen_wasm_bg.wasm"))) {
  await mkdir(join(vendorDir, "wasm"), { recursive: true });
  for (const f of ["lumen_wasm.js", "lumen_wasm_bg.wasm"]) {
    await copyFile(join(wasmSrc, f), join(vendorDir, "wasm", f));
  }
} else {
  console.warn("[copy-design-vendor] lumen_wasm not built — scene editor will run read-only. Fix: npm --prefix ../../subsystems/clue-design/apps/editor run build:wasm");
}
```
(The 3 MB gzip budget stays enforced where it lives — `build_wasm_core.sh` — which the preflight invokes on drift.)
- [ ] **Step 3:** Write the test (runs the pipeline, asserts `canvaskit.wasm` exists and is > 1 MB; asserts the fonts exist; asserts `lumen_wasm_bg.wasm` — when present — is < 3145728 bytes gzipped, using `zlib.gzipSync`; skips the wasm assertions with a logged note when the artifact is absent). Run: `npx tsx --test src/features/design-editor/iframe/vendor-scene.test.ts` → PASS.
- [ ] **Step 4:** Gate + commit: `feat(ad-editor): AD1.1 scene vendor pipeline (canvaskit, lumen_wasm, Inter TTFs)`.

### Task AD1.2: next.config webpack fallbacks

**Files:** Modify: `apps/frontend/next.config.ts`

- [ ] **Step 1:** Add (mirroring the design editor's own `next.config.mjs:15-20` — canvaskit's glue requires Node-builtin fallbacks):
```ts
  webpack: (config) => {
    config.resolve.alias = { ...config.resolve.alias, canvas: false };
    config.resolve.fallback = { ...config.resolve.fallback, fs: false, path: false, crypto: false };
    return config;
  },
```
- [ ] **Step 2:** **Known risk — turbopack dev.** `npm run build` uses `--webpack` (covered above); `npm run dev` is turbopack, which ignores the `webpack` key. Verify: `npm run dev`, open any page, then in AD1.6's smoke confirm `await import("canvaskit-wasm")` resolves under dev. If turbopack fails on the Node-builtin imports, add `turbopack: { resolveAlias: { canvas: { browser: "./src/features/design-editor/engine/scene/empty-module.ts" }, fs: …, path: …, crypto: … } }` with a one-line empty-module stub — record whichever outcome in `_memory/`.
- [ ] **Step 3:** Gate + commit: `chore(ad-editor): AD1.2 webpack fallbacks for canvaskit`.

### Task AD1.3: Engine extraction — tier A (pure core, zero config coupling)

**Files:**
- Create under `apps/frontend/src/features/design-editor/engine/scene/`: `contracts.ts`, `operations.ts`, `operationLabels.ts`, `sceneQueries.ts`, `textTransform.ts`, `transformerMath.ts`, `gestureMachine.ts`, `canvasSelection.ts`, `selectionChrome.ts`, `canvasViewport.ts`, `workspaceViewport.ts`, `pageGeometry.ts`, `managedGestures.ts`, `canvaskit/fontFaces.ts`
- Create: `engine/scene/__tests__/no-env-reads-scene.test.ts`
- Create ported tests: `engine/scene/__tests__/{contracts-adjacent tests as listed}.test.ts` — port `operations.test.ts` (106 L), `gestureMachine.test.ts` (167 L), `transformerMath.test.ts` (97 L), `sceneQueries.test.ts` (620 L), `selectionChrome.test.ts` (275 L), `canvasViewport.test.ts` (145 L), `workspaceViewport.test.ts` (66 L), `canvasSelection.test.ts` (141 L), `canvaskit/fontFaces.test.ts` (113 L)

**Interfaces:**
- Consumes: source files at `subsystems/clue-design/apps/editor/src/engine/` (same names). All tier-A modules import only each other + `canvaskit-wasm` types.
- Produces: the exact public APIs the scouts recorded — later tasks use them verbatim, notably: `Operation` (18 variants), `FieldPatch`/`OptionalFieldPatch` + `set()/unchanged()/clear()/nodePatch()/pagePatch()`, `updateTextNode(node, text: Partial<TextNode>)`, `updatePageSize`, `updatePageBackground(page, background: Fill[])`, `updateNodeFills/Strokes/Transform/Size/Layout`, `updateAutoLayoutNode`, `updateAutoLayoutAlignment`, `moveNodeToParent`, `gestureReducer(state, event): Reduced`, `resizeBox`, `deriveSelectionChromeModel`, `fitWorkspaceRectToViewport`, `clampWorkspaceZoom`, `screenToWorkspace`.

- [ ] **Step 1:** Copy each module verbatim; the only permitted edits are import-path adjustments (none needed within the slice — they import each other relatively) and deleting the `konva`-mention comments is NOT done (comments stay; verbatim wins).
- [ ] **Step 2:** Write `no-env-reads-scene.test.ts` — the existing guard's body with `engineDir` pointed at `engine/scene/` and made **recursive** (the scene slice has the `canvaskit/` subdir):
```ts
import test from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

test("the scene engine slice reads no ambient environment", () => {
  const root = join(dirname(fileURLToPath(import.meta.url)), "..");
  const offenders: string[] = [];
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (entry.isDirectory()) { if (entry.name !== "__tests__") walk(join(dir, entry.name)); continue; }
      if (!entry.name.endsWith(".ts")) continue;
      const source = readFileSync(join(dir, entry.name), "utf8");
      if (/process\.env|NEXT_PUBLIC_/.test(source)) offenders.push(entry.name);
      if (/localhost:8000|X-Workspace-Id/.test(source)) offenders.push(`${entry.name} (direct-API residue)`);
    }
  };
  walk(root);
  assert.deepEqual(offenders, []);
});
```
Run it → expect PASS for tier A (these modules are env-free at the source).
- [ ] **Step 3:** Port the listed tests verbatim behind the existing `vitest-shim` (`import { describe, it, expect } from "../../__tests__/vitest-shim";` — extend the shim only if a matcher is missing, and note which). Run: `find src/features/design-editor/engine/scene -name '*.test.ts' -print0 | xargs -0 tsx --test` → PASS.
- [ ] **Step 4:** Gate + commit: `feat(ad-editor): AD1.3 extract the pure scene-engine core (tier A) with ported tests`.

### Task AD1.4: Engine extraction — tier B (render + interaction math)

**Files:**
- Create: `engine/scene/renderAdapter.ts`, `engine/scene/canvasOperations.ts`, `engine/scene/canvaskitGestures.ts`, `engine/scene/alignDistribute.ts`, `engine/scene/renderDiagnostics.ts`, `engine/scene/tokenColors.ts` (renderAdapter dependency)
- Ported tests: `renderAdapter.test.ts` (1018 L), `canvasOperations.test.ts` (745 L), `canvaskitGestures.test.ts` (69 L), `alignDistribute.test.ts` (328 L), `renderDiagnostics.test.ts` (381 L)

**Interfaces:**
- Produces (used by AD2/AD3/AD4): `pageDescriptor(page)` (+ `unitScale`, `sceneUnitFromCanvas`, `canvasFromSceneUnit`, `sizeFromCanvas`), `screenToDescriptor`/`descriptorToScene`/`handleAtPoint`/`dragActionToOperations`/`resizeActionToOperation` (canvaskitGestures), align/distribute builders, `heuristicMeasurementDiagnostic(status)`.

- [ ] **Step 1:** Copy verbatim **except** one pruning in `renderAdapter.ts` per ruling D7 (Konva dropped): delete the three Konva-only exports `konvaFillProps` (:560), `konvaStrokeProps` (:585), `konvaShadowProps` (:611) and nothing else (the `shadow`/`extraShadowCount` descriptor fields stay — deleting fields would ripple; dead-but-harmless data beats a divergent port). Do **not** port `effectsRenderParity.test.ts` (it exists solely to exercise those three).
- [ ] **Step 2:** In the ported `renderAdapter.test.ts`, delete only the test cases that call the three deleted exports (identify by grep); every other case ports verbatim.
- [ ] **Step 3:** Run the scene test set + `no-env-reads-scene` → PASS. Gate + commit: `feat(ad-editor): AD1.4 extract scene render/interaction engine (tier B), Konva props dropped per D7`.

### Task AD1.5: Engine extraction — tier C (API-coupled modules onto `DesignEditorConfig`)

**Files:**
- Create: `engine/scene/editQueue.ts`, `engine/scene/documentStore.ts`, `engine/scene/structuredEdits.ts`, `engine/scene/exportRunner.ts`, `engine/scene/assetLibrary.ts`, `engine/scene/kitFonts.ts`, `engine/scene/libraryFonts.ts`, `engine/scene/wasmEngine.ts`
- Ported tests: `editQueue.test.ts` (332 L), `documentStore.test.ts` (287 L), `exportRunner.test.ts` (343 L), `structuredEdits.test.ts` (75 L), `kitFonts.test.ts` (264 L), `libraryFonts.test.ts` (319 L), `wasmEngine.test.ts` (180 L), `wasmFlags` **not ported** (flags deleted), `workspaceHeaderDefaults.test.ts` **not ported** (replaced — next step)

**Interfaces:**
- Consumes: `DesignEditorConfig { apiBaseUrl, fetchImpl }` from `../config` (the existing web seam) and `designBffConfig()` at the hook layer.
- Produces the config-injected signatures later tasks call:
  - `createEditQueue({ apiBaseUrl, documentId, localScene, onReconcile, fetchImpl? }): EditQueuePort` — **unchanged** (already parameterized).
  - `documentStore` / `structuredEdits` fetchers — every function already takes `apiBaseUrl` (or an options object); the **only** edit is the default `fetchImpl`: `lumenFetch` → plain `fetch`. Callers always pass `designBffConfig()`-derived values.
  - `activateWasmCore({ apiBaseUrl, fetchImpl?, wasmBaseUrl? }): Promise<WasmCoreActivation>` in `wasmEngine.ts` — the two env-flag functions (`wasmCoreFlagEnabled`, `canvasKitFlagEnabled`) are **deleted** (D7: CanvasKit-only, wasm always attempted; read-only is the fallback), `editorApiBaseUrl()` import replaced by the required `apiBaseUrl` argument, and `loadWasmModule`'s default `baseUrl` becomes `"/vendor/wasm"`.
  - `assetStoreBytesUrl(baseUrl, digest)` in `assetLibrary.ts` — unchanged signature; platform callers pass the **public passthrough prefix** (AD1.7), never the authenticated one.

- [ ] **Step 1:** Copy each module; apply exactly these edits per file: (a) delete `import { lumenFetch } from "./editorConfig"` and replace default parameters `fetchImpl = lumenFetch` with `fetchImpl = fetch` (document at each site: "workspace auth is the BFF's job — the browser never stamps headers"); (b) in `wasmEngine.ts` additionally delete the two flag functions + their `process.env` reads and change the wasm default base. **Do not create a scene `editorConfig.ts` — the module must not exist** (the no-env-reads test enforces the vacuum).
- [ ] **Step 2:** Run `no-env-reads-scene.test.ts` → now the real assertion: PASS only after (a)+(b).
- [ ] **Step 3:** Port the listed tests; where a test asserted the `lumenFetch` default (`workspaceHeaderDefaults.test.ts`), write the inverted platform guard instead:
```ts
it("no scene engine module stamps X-Workspace-Id — the BFF owns auth", () => {
  // covered structurally by no-env-reads-scene.test.ts's direct-API residue grep
});
```
(i.e. drop the file; the residue grep in AD1.3's guard already fails on any `X-Workspace-Id` literal in the slice).
- [ ] **Step 4:** Scene tests + gate + commit: `feat(ad-editor): AD1.5 extract API-coupled scene engine onto DesignEditorConfig (env reads retired)`.

### Task AD1.6: Engine extraction — canvaskit runtime + wasm smoke

**Files:**
- Create: `engine/scene/canvaskit/{loadCanvasKit.ts,drawDescriptors.ts,skiaMeasurements.ts,imageCache.ts}`
- Ported tests: `canvaskit/__tests__/{drawDescriptors,loadCanvasKit,skiaMeasurements,imageCache}.test.ts`
- Create: `engine/scene/__tests__/wasm-artifact.test.ts` (node-side wasm round trip, artifact-gated)

**Interfaces:**
- Produces: `loadCanvasKit({ baseUrl?, fontUrls?, fetchImpl? }): Promise<CanvasKitBundle | null>` — the extraction changes the two hardcoded defaults only: CanvasKit base `"/canvaskit"` → `"/vendor/canvaskit"`, `DEFAULT_INTER_FONT_URLS` paths → `"/vendor/fonts/…"`. Also `skiaMeasurements(ck, fontProvider, scene)`, `CanvasKitImageCache({ resolveUrl, onLoad?, fetcher? })`, `subscribeTextMeasurementStatus`/`textMeasurementStatusSnapshot`, `registerKitFontFaces`.

- [ ] **Step 1:** Copy verbatim + the two default-path edits. Port the four test files.
- [ ] **Step 2:** Port the design editor's node wasm loader (`apps/editor/src/test/wasmModule.ts` → `engine/scene/__tests__/wasm-module-loader.ts`, path pointed at `public/vendor/wasm`) and write the smoke test: gated on artifact presence, `new LumenEngine(minimalSceneJson)` → `applyOperations` one `update_node` opacity patch → assert `ok`; `JSON.parse(engineVersion()).engine_commit` matches the stamp recomputed from `subsystems/clue-design/crates/lumen-core` (port the preflight's `sourceStamp()` 20-liner into the test). This is the AD1 exit-gate proof in test form.
- [ ] **Step 3:** Scene tests + gate + commit: `feat(ad-editor): AD1.6 extract canvaskit runtime; wasm round-trip + stamp smoke`.

### Task AD1.7: The D8 public-bytes passthrough

**Files:**
- Create: `apps/frontend/src/app/api/clue/design-public/[...path]/route.ts`, `.../public-proxy-handler.ts`
- Test: `apps/frontend/src/app/api/clue/design-public/route.test.ts`

**Interfaces:**
- Produces: `GET /api/clue/design-public/asset-store/{digest}` → forwards to `${LUMEN_API_BASE_URL}/asset-store/{digest}` with **zero request headers**, streams the response, passes `content-type`/`cache-control` through. Consumed by AD2.3's `resolveAssetUrl`. Constant: `export const DESIGN_PUBLIC_BFF_PREFIX = "/api/clue/design-public";` in `src/features/design-editor/data/design-bff.ts`.
- **Scope precision (implements D8 as ruled, with the verified upstream reality):** only `/asset-store/{digest}` is public upstream. `/font-library` and `/assets/{id}/bytes` **require** `X-Workspace-Id` (design API 401s without it) — they route through the existing authenticated `/api/clue/design` proxy, which is exactly the web precedent (`hydrate.ts:304` already fetches `/assets/{id}/bytes` that way). No CORS games either way: the browser only ever talks to our origin.

- [ ] **Step 1:** Write the failing test first (mirror `route.test.ts`'s harness): (1) a valid digest path forwards with `headers` empty and `cache: "no-store"` absent — use `cache: "force-cache"`? No: forward default, assert **no** `X-Workspace-Id`, **no** `authorization`, **no** `cookie` on the outgoing request; (2) response `cache-control: public, max-age=31536000, immutable` passes through; (3) a non-`asset-store/<64-hex>` path → 404 without forwarding; (4) POST → 405. Run → FAIL (module missing).
- [ ] **Step 2:** Implement:
```ts
// public-proxy-handler.ts
const PUBLIC_PATH = /^asset-store\/[0-9a-f]{64}$/;

export async function handlePublicDesignProxyRequest(
  request: Request,
  path: readonly string[],
  dependencies: { designApiBaseUrl: string; fetchImpl?: typeof fetch },
): Promise<Response> {
  if (request.method !== "GET") return new Response(null, { status: 405 });
  const joined = path.join("/");
  if (!PUBLIC_PATH.test(joined)) return new Response(null, { status: 404 });
  const fetchImpl = dependencies.fetchImpl ?? fetch;
  // Deliberately headerless (founder ruling D8): the upstream route is
  // content-addressed, immutable, and tenant-free by design ruling R-D4-7.
  const response = await fetchImpl(`${dependencies.designApiBaseUrl}/${joined}`, { redirect: "manual" });
  const headers = new Headers();
  for (const name of ["content-type", "cache-control"]) {
    const value = response.headers.get(name);
    if (value) headers.set(name, value);
  }
  return new Response(response.body, { status: response.status, headers });
}
```
`route.ts` binds it with `designApiBaseUrl: lumenApiBaseUrl()` (same import as the sibling proxy), exports `GET` only.
- [ ] **Step 3:** Test → PASS. Add `DESIGN_PUBLIC_BFF_PREFIX` to `design-bff.ts`. Gate + commit: `feat(ad-editor): AD1.7 headerless public passthrough for /asset-store (D8)`.

### Task AD1.8: AD1 exit gate

- [ ] **Step 1:** Full scene test sweep + `npm run build` with vendored artifacts present (build the wasm once: `npm --prefix ../../subsystems/clue-design/apps/editor run build:wasm`).
- [ ] **Step 2:** Root `make check`. `_memory/` AD1 close-out (record: turbopack outcome from AD1.2, shim extensions, any verbatim-port exceptions). Commit.

---

# Phase AD2 — Read path (needs AD1; AD2.5's visible outline needs Gate G-A)

### Task AD2.1: Gallery feed goes kind-aware (backend + adapter)

**Files:**
- Modify: `platform/api/clue_api/design_leg_wiring.py:437,458` + docstring `:429-431`; `platform/api/clue_api/chat/router.py:1040-1054` + docstring `:1011-1013`
- Modify: `apps/frontend/src/features/design-editor/adapter/gallery.ts` (+ its test)
- Modify: `apps/frontend/docs/api-contracts/projects.md` (record the resolved contract)
- Test: extend `tests/api/test_design_artifact_seam_db.py` (a scene doc + leg row appears in the list with `kind:"ad"`)

**Interfaces:**
- Produces: list items with real `kind` (`"web" | "ad"`); gallery cards for ads with `type: "canvas"`, `collateralType` omitted, no thumbnail (honest empty card — ratified ruling). Both mounts' existing reconstruction `kind: source.type === "website" ? "web" : "ad"` then yields `"ad"` for scene docs with **zero frontend mount changes**.

- [ ] **Step 1 (backend, TDD):** Write the failing pytest: seed via `clue_design.documents.create_document(conn, workspace_id=…, scene=<minimal scene>, doc_kind="scene")` + a `design_leg` row with `document_id` on a project thread (copy the arrangement from `tests/api/test_design_artifact_seam_db.py:168`); assert the list response contains it with `kind == "ad"`. Run → FAIL.
- [ ] **Step 2:** The four edits: add `d.doc_kind` to the SELECT (`:437`); delete the `WHERE d.doc_kind = 'web'` clause (`:458`) keeping the ORDER BY; in `router.py:1044` replace `kind="web"` with `kind="web" if document["doc_kind"] == "web" else "ad"`; update both docstrings. Run → PASS. Also run the module's existing tests.
- [ ] **Step 3 (adapter, TDD):** Failing test: a `DesignArtifactListItem` with `kind: "ad"` maps to `{ type: "canvas" }` with no `collateralType` key; a `kind: "web"` item still maps to `{ collateralType: "microsite", type: "website" }`. Implement in `toProjectArtifact`:
```ts
const ad = item.kind === "ad";
return ProjectArtifactSchema.parse({
  ...(ad ? {} : { collateralType: "microsite" }),
  type: ad ? "canvas" : "website",
  // …existing fields unchanged
});
```
- [ ] **Step 4:** Browser check: an ad card renders in the rail without a broken image (the schema's `imagePath` stays absent). Record the decision (`type:"canvas"`, no collateral type, no thumbnail) in `projects.md`. Gate both repos + commit: `feat(ad-editor): AD2.1 gallery feed serves scene documents as kind=ad`.

### Task AD2.2: Seed a realistic ad document + harvest fixtures

**Files:**
- Create: `scripts/seed_ad_document.py` (platform repo root scripts/, matching however the web seed was run — verify and colocate)
- Create: `apps/frontend/src/features/design-editor/adapter/__fixtures__/scene-nodes.ts`

**Interfaces:**
- Produces: a dev-DB scene document reachable from a project (a `design_leg` row points at it), whose tree exercises **every contract schema**: one root **Frame** (clipped, solid fill — the agent's background idiom), one **AutoLayout** child (direction row, gap, padding), two **Text** nodes (one token-bound, one with explicit family/size/weight), one **Image** node (placed asset with `fit: "cover"`), one **Rect**, one **Ellipse**, one **Group** containing two children, one **Line** (for the unrepresented-kind behavior). Fixture file exports `HARVESTED_AD_PAGE` (the GET /documents scene payload) + per-kind node accessors, with the W2.2 provenance header (document id, workspace, version, capture date, capture method).

- [ ] **Step 1:** Author the scene JSON by hand against `contracts.ts` types (or via `lumen-api-helper` `NewScene` + an operations batch — implementer's choice; the DAL path used by `tests/api/test_genweb_leg_document_birth_db.py:474` is the precedent). Insert with `doc_kind="scene"` + the leg row. Verify it renders in the **standalone** design editor (ground truth for AD2.3's visual comparison).
- [ ] **Step 2:** Harvest: `curl` GET `/documents/{id}` through the design API, paste the scene into `scene-nodes.ts` verbatim with the provenance header. Commit both: `feat(ad-editor): AD2.2 seeded ad document + harvested scene fixtures`.

### Task AD2.3: `SceneArtifactCanvas` — read-only render in the dummy artboard

**Files:**
- Create: `apps/frontend/src/features/design-editor/components/scene-artifact-canvas.tsx` (+ `.module.css`)
- Modify: `apps/frontend/src/features/chat-shell/components/artifact-stage.tsx:160-165` (the empty ad div hosts the canvas when a documentId exists)

**Interfaces:**
- Consumes: AD1's `loadCanvasKit`, `drawDescriptors`, `imageCache`, `skiaMeasurements`, `wasmEngine.activateWasmCore`, `renderAdapter.pageDescriptor`, `workspaceViewport`, `libraryFonts.loadLibraryFontFaces`, `kitFonts.loadKitFontFaces`, `documentStore` fetch, `designBffConfig()`, `DESIGN_PUBLIC_BFF_PREFIX`.
- Produces: `export function SceneArtifactCanvas({ documentId, controlsRef, onSelect, reloadToken, selectedNodeId, zoom, onFitZoom }: SceneArtifactCanvasProps)` — a `"use client"` component derived from the design editor's `CanvasKitStage` (surface creation `MakeWebGLCanvasSurface ?? MakeSWCanvasSurface`, rAF-coalesced dirty flag, dpr handling — port those mechanics; the multi-artboard workspace collapses to one artboard). Also `export interface SceneCanvasControls { hitTest(x: number, y: number): HitResult | null; refresh(): void; sceneSnapshot(): Scene | null; }` via the ref.

Behavior spec (each line is a contract citation):
1. Fetch the document through `designBffConfig()`; hold the scene in an engine instance when wasm activated, else parse-only (read-only).
2. **Stamp handshake first** (`activateWasmCore` vs `/build-info` through the BFF): `unavailable` → render the scene server-snapshot read-only, expose `engineDisabled: true` upward; the banner waits for Gate G-D (mechanism now, chrome later — D9's "never silent" is satisfied by the editor refusing edits + a console diagnostic until the approved banner lands, which must be before AD5).
3. Fonts: bundled Inter from `/vendor/fonts` (loadCanvasKit `fontUrls`), library + kit faces lazily via the **authenticated** BFF; measurement status surfaces through `textMeasurementStatusSnapshot` (banner gated on G-D).
4. Images: `new CanvasKitImageCache({ resolveUrl: (assetId) => { const digest = scene.assets[assetId]?.media?.digest?.value; return digest ? `${DESIGN_PUBLIC_BFF_PREFIX}/asset-store/${digest}` : null; }, onLoad: markDirty })`.
5. Measure-then-inject: port the `textSignature` effect exactly (dep on the text-inputs digest, never the whole scene).
6. **Fit-on-open** (§1.10): `fitWorkspaceRectToViewport({ viewport: elementSize, rect: artboardRect })`; report `Math.round(zoom*100)` snapped to the nearest 5% step via `onFitZoom` so the header menu shows it.
7. Canvas chrome (§1.1): artifact name label top-left of the artboard, `W×H` chip bottom-center — styled per the founder's Figma mocks **if the AD0.1 delta carries their CSS; if it does not, these two labels join Gate G-A's mockup sheet** (they are ratified in the contract but have no designed CSS yet — do not invent styling silently).
8. The dummy artboard chrome (centered card, hairline border, `.imageCanvas` geometry) is **preserved** — the canvas fills the existing div; no new stage CSS beyond the canvas element itself.

- [ ] **Step 1:** Build the component read-only (no selection yet); mount in `artifact-stage.tsx`'s ad branch mirroring the web branch's shape: `{activeDocumentId ? <SceneArtifactCanvas … /> : null}` inside the existing `aria-label` div (label becomes conditional like the web one: `"Ad output canvas"` / `"Empty ad output canvas"`).
- [ ] **Step 2:** Browser proof: the seeded ad renders pixel-plausibly vs the standalone editor side-by-side; fonts resolve (no heuristic status with artifacts built); images load through the passthrough (network tab shows `/api/clue/design-public/asset-store/…`, no workspace header).
- [ ] **Step 3:** Gate + commit: `feat(ad-editor): AD2.3 CanvasKit scene canvas mounted read-only in the dummy artboard`.

### Task AD2.4: `scene-hydrate` — selection → schema + values (TDD)

**Files:**
- Create: `apps/frontend/src/features/design-editor/adapter/scene-hydrate.ts` + `scene-hydrate.test.ts`

**Interfaces:**
- Consumes: `Scene`/`Node` types from `engine/scene/contracts`, the harvested fixtures, `ChatShellInspectorSelection` (post-AD0.1 vocabulary), `InspectorPresentationState`.
- Produces (mirrors the web adapter's two exports):
```ts
export interface SceneSchemaSelection {
  selection: ChatShellInspectorSelection;
  /** OQ-1: plain Frame renders the auto-layout schema with its Auto Layout
   * section suppressed. */
  suppressAutoLayoutSection: boolean;
}
export function sceneSelectionFor(node: Node, rootFrameId: string | null): SceneSchemaSelection | null;
export function hydrateSceneInspectorState(node: Node, scene: Scene): Partial<InspectorPresentationState>;
export function rootFrameId(scene: Scene, pageId: string): string | null;
```
Kind → schema mapping (contract §1.4 + OQ-1; use the delta's exact selection strings from AD0.1):

| Engine `NodeKind` | Schema | Notes |
|---|---|---|
| `text` | text | |
| `image` | image | |
| `auto_layout` | auto-layout | full sections |
| `frame` | auto-layout | `suppressAutoLayoutSection: true` (OQ-1) |
| `rect` | rectangle | |
| `ellipse` | ellipse | |
| `group` | group | no Shape/Stroke (OQ-6 — the schema component already omits them) |
| `line` / `vector` / `instance` | **`null`** | §5 unrepresented: canvas hit resolves to the nearest representable **ancestor** via the hitTest `stack`; a layer-row click is a no-op (the dummy's own dead-click precedent) |
| page/empty selection | canvas | |

Value mapping rows (each with a fixture-backed test, one test per control — the web convention):
- `opacity`: engine `0–1` → display string `String(Math.round(node.opacity * 100))` (OQ-3).
- Width/Height mode: `Dimension.kind` `"fixed"|"hug"|"fill"` → labels `Fixed|Hug|Fill`; `token` → display `Fixed` with the fixed value from computed size (documented compromise: token sizing has no dummy slot, §5). Fixed inputs shown only in Fixed mode (OQ-2) — hydrate exposes `widthMode/heightMode` + `widthFixed/heightFixed`.
- Position X/Y ← `transform.x/y` (managed nodes: computed box; pinned: `absolute_box`) — reuse the editor's `directGeometryEditable` semantics from `canvasSelection`.
- Rotation ← `transform.rotation`; fills → `ColorControl` state (solid hex / token name / gradient → `InspectorBackgroundFill{type, angle, stops[{color,position}]}` mapping `Paint.linear_gradient.angle` and stop positions 0–1 → %).
- Text: `font_family`, `font_size` (number → string), `font_weight` → the nine-name label, `align` (+ justify), `valign` (+ disabled-when-hug flag exposed as `valignDisabled`), stroke color/width from `strokes[0]`.
- Image: `asset_placement.fit` `contain|cover|crop` → `Fit|Fill|Crop`; radius from `corner` (TL/TR/BR/BL — **note the engine order is BR before BL**).
- AutoLayout: `direction Row|Column`, `wrap`, `layout.gap/grow/padding[0..3] (T,R,B,L)`, `align_x/align_y` → `Start|Center|End|Space between|Stretch`.
- Canvas schema: preset select derived from page size (exact match against the three ratified presets else `Custom` + W/H); Background ← **root frame's `fills[0]`** (§1.1 founder ruling), falling back to the `none` state when no root frame exists (writes are then no-ops — the null contract).
- Lock ← `node.locked`; title ← `node.name` (editor naming ruling).

- [ ] **Step 1:** Write the full failing test file first — one `it` per row above, against `HARVESTED_AD_PAGE` nodes, citing its contract row in the test name (`it("§1.4: opacity 0.8 hydrates as '80'")`). Run → FAIL.
- [ ] **Step 2:** Implement until green. **No component changes in this task.**
- [ ] **Step 3:** Gate + commit: `feat(ad-editor): AD2.4 scene-hydrate adapter (selection routing + value hydration, fixture-proven)`.

### Task AD2.5: Canvas selection (hitTest + outline) — outline visuals need Gate G-A

**Files:**
- Modify: `scene-artifact-canvas.tsx` (pointer handling + the SVG overlay layer)
- Create: `apps/frontend/src/features/design-editor/adapter/scene-selection.ts` + test (pure: hit-stack → representable node id)

**Interfaces:**
- Produces: `export function representableHit(stack: NodeId[], scene: Scene): NodeId | null` (walks the hit stack top-down, returns the first node whose `sceneSelectionFor` is non-null); `onSelect(nodeId | null)` fires from pointer-down (the gesture machine's press-selects semantics); the overlay renders the founder-approved outline for `selectedNodeId` using `deriveSelectionChromeModel`'s `selectionBox` (handles come in Lane C, also G-A).

- [ ] **Step 1 (pure, TDD):** `representableHit` tests on fixtures: clicking the Line inside the group selects the Group; clicking empty canvas → null (canvas schema).
- [ ] **Step 2:** Wire pointer-down → `screenToWorkspace` → artboard-local → `descriptorToScene` → `controls.hitTest` → `representableHit` → `onSelect` (coordinate chain is the scout-verified one from `CanvasKitCanvas.tsx:589-617`, single-artboard-simplified).
- [ ] **Step 3 (gated):** Render the outline per the G-A-approved visual. If G-A is still open when steps 1–2 land, ship selection **state** only (inspector follows selection; no visible outline) and record the gap — the AD2.9 demo requires G-A closed.
- [ ] **Step 4:** Browser proof + gate + commit: `feat(ad-editor): AD2.5 hitTest selection with representable-ancestor resolution`.

### Task AD2.6: Real layers tree

**Files:**
- Create: `apps/frontend/src/features/design-editor/adapter/scene-layers.ts` + test
- Modify: `image-inspector.tsx` + `ad-dummy-inspectors.tsx` — `AdLayers` takes `rows: SceneLayerRow[]` + `onSelectLayer(nodeId)` + `selectedIds: string[]` props replacing the fixture tree

**Interfaces:**
- Produces:
```ts
export interface SceneLayerRow {
  nodeId: string;
  depth: number;                       // any depth (§1.7)
  label: string;                       // node.name (editor naming)
  icon: InspectorIconName;             // kind glyphs; delta's layout-template / square-dashed
  fillSwatch?: string;                 // Rect/Ellipse solid-fill chip (§1.7)
  expandable: boolean;
  expanded: boolean;
  selectable: boolean;                 // false for line/vector/instance (dead-click)
}
export function sceneLayerRows(scene: Scene, pageId: string, expanded: ReadonlySet<string>): SceneLayerRow[];
```
Multi-select is **additive in the panel** (shift/⌘-click accumulates ids — §1.7) but the inspector renders the **first-selected** node's schema (§1.8 as amended); Arrange acts on the whole set (Lane B). Auto-scroll-to-primary + chevrons per §1.7; **no** up/down reorder buttons.

- [ ] **Step 1 (TDD):** `sceneLayerRows` tests on fixtures (depth, glyphs, swatches, selectable flags, expansion filtering).
- [ ] **Step 2:** Bind through the session hook (AD2.7 provides the props); the component edit keeps the dummy's row markup/classes byte-level (only the data source changes).
- [ ] **Step 3:** Gate + commit: `feat(ad-editor): AD2.6 real scene layers tree`.

### Task AD2.7: `useSceneEditingSession` + both mounts

**Files:**
- Create: `apps/frontend/src/features/design-editor/hooks/use-scene-editing-session.ts`
- Modify: `chat-surface.tsx` (the 2-prop `ImageInspector` placeholder → the real prop set), `editor-surface.tsx` (gains the ad dock — today `inspectorVisible` requires `kind === "web"`), `image-inspector.tsx` (accepts the web-parity prop set)

**Interfaces:**
- Consumes: the `use-web-editing-session.ts` discipline verbatim (ids-only input, owns no shell controller).
- Produces:
```ts
export function useSceneEditingSession({ activeArtifactId, documentIds }: {
  activeArtifactId: string | null;
  documentIds: Record<string, string> | undefined;
}): {
  activeDocumentId: string | null;
  addressing: { artifactId: string | null; documentVersion: number | null; selectionId: string | null };
  canvasControls: RefObject<SceneCanvasControls | null>;
  hydrated: Partial<InspectorPresentationState> | null;
  inspectorError: string | null;
  layerRows: SceneLayerRow[];
  note: string | null;
  onSelectCanvas: (nodeId: string | null) => void;
  onSelectLayer: (nodeId: string) => void;
  onWriteReload: () => void;
  redoDisabled: boolean;
  reloadNonce: number;
  selectedIds: string[];               // additive set; [0] is primary
  selection: SceneSchemaSelection | null;
  undoDisabled: boolean;
  writes: SceneManualEdits;            // AD3 fills this; stub until then
  zoom: string;                        // "45%" — fit-derived, menu-settable
  onZoomChange: (zoom: string) => void;
}
```
`ImageInspector` gains (all optional so the fixture path keeps compiling): `addressing?`, `hydrated?`, `layers?: SceneLayerRow[]`, `selectedIds?`, `onSelectLayer?`, `error?`, `note?`, `suppressAutoLayoutSection?`, `fontOptions?: string[]` — mirroring the 13-prop web branch. Both mounts remount the inspector `key={primaryNodeId ?? "canvas"}` (the web precedent; hydration is initial-state-only by design).

- [ ] **Step 1:** Implement the hook (document fetch via `designBffConfig()`, selection state, hydrate/layers derivations, fit-zoom state; `writes` stubbed as inert with `busy:false`).
- [ ] **Step 2:** `editor-surface.tsx`: `inspectorVisible` becomes kind-aware; ad → `ImageInspector` with the session props inside the same dock markup as web. `chat-surface.tsx`: replace the two placeholder props with the session set (dock routing already lands on `"ad-inspector"`).
- [ ] **Step 3:** Font options: `fontOptions` = `["Inter", …libraryFamilies, …kitFamilies]` from `fetchFontLibrary` + the document's kit (fetched once in the hook; failure → `["Inter"]`, never a crash).
- [ ] **Step 4:** Browser proof on **both** routes: select on canvas → inspector shows hydrated values; layer click → selection + auto-scroll; zero writes anywhere. Gate + commit: `feat(ad-editor): AD2.7 shared scene editing session on both mounts`.

### Task AD2.8: Zoom menu wired

**Files:** Modify: `artifact-header.tsx` (zoom props from session), `hooks/use-artifact-toolbar-controller.ts` (zoom becomes controlled/liftable), `scene-artifact-canvas.tsx` (applies the transform)

- [ ] **Step 1:** Header's ad zoom menu displays `session.zoom` and calls `session.onZoomChange`; the canvas applies `zoomWorkspaceViewportAtPoint`-derived viewport (menu-set zoom re-centers via `fitWorkspaceRectToViewport`'s pan math at the chosen zoom). Fit-on-open sets the initial value (§1.10); the 29 menu options are within the engine clamp.
- [ ] **Step 2:** Browser proof (change zoom → canvas scales; reopen → fit). Gate + commit: `feat(ad-editor): AD2.8 zoom menu drives the real viewport (fit-on-open)`.

### Task AD2.9: AD2 exit — founder demo

- [ ] **Step 1:** Walk: open the seeded ad from the gallery on both routes → real render inside the dummy card → click-select (outline per G-A) → hydrated inspector per schema → real layers → zoom. Record screenshots; root `make check`; `_memory/` note; founder demo + sign-off before AD3 writes begin.

---

# Phase AD3 — First write flow (text schema)

### Task AD3.1: `scene-apply` — inspector events → operations (TDD)

**Files:** Create: `apps/frontend/src/features/design-editor/adapter/scene-apply.ts` + `scene-apply.test.ts`

**Interfaces:**
- Consumes: the existing inspector event seam (flat `{property, selectionId, value, artifactId, documentVersion}` from `dispatchInspectorEvent`), fixture nodes, `operations.ts` builders.
- Produces:
```ts
export interface SceneChangeDetail {
  property: string;
  selectionId: string;
  value: unknown;
}
export function sceneChangeToOperation(detail: SceneChangeDetail, node: Node, scene: Scene): Operation | null;
```
Null contract identical to web (unaddressable/unknown/locked ⇒ null, never a guess). Text rows (this task wires text only; later lanes extend the same switch):

| `property` | Operation |
|---|---|
| `textColor` | `updateNodeFills(node, [{ id, paint: { kind: "solid", color: { kind: "hex", value } } }])` where `id = node.fills[0]?.id` when a fill exists; for a fill-less node, mint the `PaintId` the same way the standalone editor's fill-color write does (locate that one call site in the extracted engine — `RawStyleSection`'s write path — and reuse it; the test pins whichever helper it is). A raw hex detaches any token (§1.6 accepted trade; the note is Gate G-B chrome) |
| `fontFamily` | `updateTextNode(node, { font_family: value })` |
| `fontSize` | parse ≥ 1 → `updateTextNode(node, { font_size: n })`; NaN → null |
| `fontWeight` | nine-name label → numeric (`"600 Semi Bold"` → 600) → `updateTextNode(node, { font_weight: n })` |
| `horizontalAlignment` | `left|center|right|justify` → `updateTextNode(node, { align })` |
| `verticalAlignment` | `top|middle|bottom` → `top|center|bottom` → `updateTextNode(node, { valign })`; null when height mode is hug (the disable rule — belt and suspenders) |
| `strokeColor` / `strokeWidth` | `updateNodeStrokes(node, …)`; width 0 or color `none` → `[]` (clears) |
| `position.x` / `position.y` | freehand/unlocked: `updateNodeTransform(node, { …node.transform, x|y: n })`; pinned: `updateNodeAbsoluteBox`; layout-managed: **null** (the editor's `directGeometryEditable` gate) |
| `rotation` | transform rotation (same gating) |
| `locked` | `nodePatch({ locked: set(value) })` on the node — and lock gates every other row to null |

- [ ] **Step 1:** Failing tests — one per row, each citing its contract row, all against harvested fixture nodes (including: locked node → null; managed node position → null; hug-height valign → null; NaN size → null).
- [ ] **Step 2:** Implement → green. Gate + commit: `feat(ad-editor): AD3.1 scene-apply adapter, text rows (fixture-proven)`.

### Task AD3.2: Write controller over the extracted `editQueue`

**Files:**
- Create: `apps/frontend/src/features/design-editor/hooks/use-scene-manual-edits.ts`, `hooks/use-scene-inspector-writes.ts`
- Modify: `use-scene-editing-session.ts` (replace the stub `writes`)

**Interfaces:**
- Consumes: `createEditQueue` (AD1.5), `sceneChangeToOperation` (AD3.1), the `clue:inspector-property-change` window event with the addressing triple (the dispatcher already exists).
- Produces:
```ts
export interface SceneManualEdits {
  applyOps: (operations: Operation[], intent?: string) => void;
  undo: () => void;   // AD3.3
  redo: () => void;
  busy: boolean;
  note: string | null;    // 409 → "Document moved on — reloaded." (D10)
  error: string | null;   // 422 → first diagnostic message inline
  clearMessages: () => void;
}
```
Wiring rules (each is a ratified posture):
- One `createEditQueue` per `documentId`; `onReconcile` handler: any `ReconcileEvent` (`rejected` **and** `divergence` and `request_failed`) → `setNote("Document moved on — reloaded.")`, reload the document, `queue.resync(serverVersion)` — D10's web-style posture, deliberately **not** using the queue's optimistic divergence recovery beyond adopting the server scene. A 422-class rejection (diagnostic code from the response detail) surfaces `error` instead of `note` where the diagnostic message exists.
- The event listener mirrors `use-inspector-writes.ts` exactly: armed on `documentId` only, live values through refs, the four-line null contract (`property`/`selectionId`/`documentVersion` typed + selection match), then `sceneChangeToOperation` → `applyOps([op], \`inspector: ${property}\`)`.
- Success resync **without keyed remounts on write tokens** (§4): the inspector remount key is the node id, never the version.

- [ ] **Step 1:** Implement both hooks; unit-test the pure decision parts (`reconcileToMessages(event): {note?, error?}` extracted as a pure function with tests for the three event kinds).
- [ ] **Step 2:** Browser proof: edit font size → persists across reload; concurrent-edit simulation (second tab commits first) → the D10 note + refreshed canvas. Gate + commit: `feat(ad-editor): AD3.2 CAS write path over the scene editQueue (D10 posture)`.

### Task AD3.3: Undo/redo

**Files:** Modify: `use-scene-manual-edits.ts` (fill undo/redo via `structuredEdits.undoDocument/redoDocument`), `use-scene-inspector-writes.ts` (the `clue:artifact-action-request` listener with `kind !== "ad" → return` + the ⌘Z/⇧⌘Z keydown, web-precedent skip rules), session exposes `undoDisabled`/`redoDisabled` from the document's stack depths.

- [ ] **Step 1:** Implement (busy-guarded like the web `runHistory`; 409 → quiet reload; empty-stack → quiet resync). Action-menu rows already dispatch the event (web precedent) — verify the ad branch dispatches `kind: "ad"`.
- [ ] **Step 2:** Browser proof: edit → undo → redo across both mounts; disabled states track depths. Gate + commit: `feat(ad-editor): AD3.3 server undo/redo wired with the first write`.

### Task AD3.4: AD3 exit

- [ ] **Step 1:** Full text-schema browser sweep on both mounts (every §1.2 control), persistence + CAS + undo proofs recorded; root `make check`; `_memory/` note; commit.

---

# Phase AD4 — Schema & interaction fan-out (parallel lanes after AD4.0)

Lane discipline: AD4.0 lands on the branch first; lanes A–D then run in parallel worktrees (the W4 pattern), each extending `scene-apply.ts`'s switch + `scene-hydrate.ts` rows with fixture-proven TDD and a browser proof. Every lane task cites its contract row in tests.

> **AD4.R (2026-08-22, founder-ordered) landed between Lane A and Lane B** —
> `docs/superpowers/plans/2026-08-22-ad-inspector-mvp-state-model.md`. The ad
> inspector now runs the MVP state model: bound controls derive from live
> hydrated state (`liveHydration`), typed fields are self-drafting
> (`onCommitValue`), the accepted scene mirrors up synchronously, and the
> `inspectorGeneration` remount is retired on BOTH mounts. **Binding rules for
> Lanes B–E:** bind every new row as `value={state.x}` + dispatch-only commit
> (never a local copy, never a post-commit mirror, never a mount-seeded
> snapshot), **and hydrate must state that key for every selection the schema
> serves** — under live derivation a key hydrate omits is frozen at the mount
> seed, so an accepted write to it would be invisible (the old defect class,
> mirrored); typed fields use `onCommitValue`; UI-only view choices (the
> canvas schema's "Custom" preset selection) are the only legitimate
> schema-local state. The A26/A27/A28/A31-style mirror patterns are RETIRED —
> do not reintroduce them in new rows; the source-text guards in
> `scene-apply.test.ts` / `scene-image-ai.test.ts` / `scene-hydrate.test.ts`
> now pin the live-derivation mechanism and fail on any reintroduction.
> Disclosed behavior changes (founder-ratified): Font size, Stroke width,
> Position X/Y and Rotation commit on blur/Enter; a refused commit reverts the
> field to the document value (the old keep-refused-text posture is retired).

### Task AD4.0 (trunk): Canvas schema + color-policy substrate

**Files:** Modify: `scene-apply.ts`/`scene-hydrate.ts` (+tests), `image-inspector.tsx` (canvas schema binding), `inspector-primitives.tsx` (`ColorControl` brand-options feed), `use-scene-editing-session.ts` (brand palette fetch)

- [x] **Step 1 (presets, §1.1):** `sizePreset` → exact ratified values: `Linkedin square (1:1) - 1200x1200` → `updatePageSize(page, { …page.size, width: 1200, height: 1200, unit: "px", preset: "custom" })` (the engine has no per-platform presets — labels are client vocabulary, writes are custom sizes); Custom W/H inputs → same op (px only, min 1). TDD.
- [x] **Step 2 (background, §1.1 ruling):** `backgroundColor`/`backgroundFill` target the **root frame's fills** via `updateNodeFills(rootFrame, …)` — solid via ColorControl; gradients map the dummy's editor to `Paint.linear_gradient{angle, stops[{color:{kind:"hex"},position: pct/100}]}` / `radial_gradient{stops}` (2–6 stops). No root frame → null (AD2.4's contract). TDD both directions (hydrate + apply).
- [x] **Step 3 (color policy, §1.6):** `ColorControl`'s `options` feed = the document's brand-kit palette (fetched in the session hook from the document's `effective_brand_kit` reference through the BFF — verify the exact kit-detail route against the extracted `brandHub`/`kitFonts` modules at implementation and record it), brand swatches listed **first**, custom hex allowed. Choosing a brand swatch writes `{ kind: "token", token }`; custom hex writes solid hex. The departure **note** renders only after G-B approves its design.
- [ ] **Step 4:** Browser proof + gate + commit per step (three commits).

### Task AD4.A (lane): Image schema

**Files:** Modify: `scene-apply.ts`/`scene-hydrate.ts` (+tests), `image-inspector.tsx` (image schema), Create: `apps/frontend/src/features/design-editor/data/scene-assets.ts` (+test)

- [x] **Step 1 (fit, §1.3):** `fillMode` `Fit|Fill|Crop` → `{ kind: "update_node", node_id, patch: nodePatch({ asset_placement: set({ …node.asset_placement, fit: "contain"|"cover"|"crop" }) }) }`. Crop reveals the focal control **only after G-C**; until then Crop is selectable and writes `fit:"crop"` with the existing focal point preserved. TDD.
- [x] **Step 2 (upload, §1.3):** `scene-assets.ts`: `uploadSceneAsset(config, file): Promise<AssetRecord>` — multipart `POST /assets` through the BFF (field `file`; response `{asset}`), then apply the canonical pair `[{kind:"upsert_asset", asset}, {kind:"place_asset_in_node", node_id, asset_id, placement: {alt_text: asset.label}}]` through `applyOps` (the engine requires `upsert_asset` first — scout-verified). The dummy's `InspectorImageUpload` binds to this instead of `requestAction`. TDD the pure request-shaping.
- [x] **Step 3 (AI suite, §1.3):** Adopt the MVP editor's generate/edit/remove-background/candidate-review flows restyled in dummy primitives (`InspectorInput` + buttons — composition from existing primitives only, no new CSS beyond layout classes already present). The design-API routes are the ones the standalone `ImageInspectorSection` calls — enumerate them at implementation from `subsystems/clue-design/apps/editor/src/components/inspector/ImageInspectorSection.tsx` and route through the BFF. Candidate accept/reject applies the same op pair as upload. (This step is the lane's biggest; split into its own commit.)
- [x] **Step 4 (radius):** `radius.*` → `nodePatch({ corner: set({ top_left, top_right, bottom_right, bottom_left, token: null }) })` — a raw write clears the token (§4); TDD includes the corner-order trap (BR before BL in the engine shape).
- [ ] **Step 5:** Browser proof + commits.

### Task AD4.B (lane): The four new schemas + plain Frame

**Files:** Modify: `scene-apply.ts`/`scene-hydrate.ts` (+tests), `ad-dummy-inspectors.tsx` (bind the static scaffolding to props — the co-founder designed them read-only; binding = replacing static values/single-option selects with hydrated values + change handlers, markup preserved)

- [x] **Step 1 (Layout section, §1.4):** X/Y/W/H/Rotate per AD3.1's gating rules generalized to all kinds; `opacity` → `nodePatch({ opacity: set(pct / 100) })` clamped [0,1] (OQ-3); Width/Height mode select `Fixed|Hug|Fill` → `updateNodeSize(node, { width|height: {kind:"fixed",value} | {kind:"hug"} | {kind:"fill",value:{weight:1}} })` — fill weight fixed at 1 (fill-weight inputs are §5-hidden, OQ-2); Fixed inputs visible only in Fixed mode. TDD every row.
- [x] **Step 2 (Auto Layout section, §1.4):** Direction/Wrap → `updateAutoLayoutNode(node, { direction: "row"|"column", wrap })`; Gap/Grow/Pad T,R,B,L → `updateNodeLayout(node, { …node.layout, gap, grow, padding: [t,r,b,l] })`; Align X/Y → `updateAutoLayoutAlignment(node, alignX, alignY)` with the five anchors. Plain Frame: section suppressed (OQ-1 flag from hydrate). TDD.
- [x] **Step 3 (Shape/Stroke):** fills per the §1.6 policy (shared code path with AD4.0); radii on rectangle & auto-layout only; group renders neither (OQ-6 — scaffolding already omits). TDD.
- [x] **Step 4 (Arrange, §1.5):** z-order 4 buttons → `moveNodeToParent` index math (edge-disabled); align (2+ unlocked freehand nodes) + distribute (3+) over `alignDistribute` against `selectedIds`; Group (2+ same-parent siblings) / Ungroup (single container) via the engine's structured-edit/group builders with ⌘G/⇧⌘G in the canvas keymap. Enablement rules exposed from a pure `arrangeEnablement(scene, selectedIds)` decision module (TDD) so buttons disable honestly. 
- [x] **Step 5:** Browser proof per schema + commits. *(Lane complete 2026-08-22, commits `d3a886f0..dbc7f7a0` on the AD4.R base; final review "Approved for founder presentation"; close-out + founder-decision list in `_memory/2026-08-22-ad4b-four-schemas-lane.md`. Plain Frame browser-uncovered — no non-root frame in the seed; §1.5 bracket shortcuts implemented in the final wave with the real-hardware keyboard pass an AD5.1 residual. L19 note: align/distribute now gate on commit-reachability — honestly OFF for plain-frame children until the engine's gate/commit inconsistency is resolved.)*

### Task AD4.C (lane, gated on G-A): On-canvas direct manipulation

**Files:** Modify: `scene-artifact-canvas.tsx` (gesture host + handles overlay)

- [x] **Step 1:** Host the extracted `gestureReducer`: pointer-down builds `PressTarget` (`handleAtPoint` first against the selection box, else hit node with box+rotation from `deriveSelectionChromeModel`); move/up feed the reducer; `drag`/`resize` actions preview via the overlay and on `committed: true` emit `dragActionToOperations` / `resizeActionToOperation` (managed-layout nodes refuse per the editor's rule — the machine's host omits handles for them via `showResizeHandles`). **v1 scope exactly** (§1.9): drag-move + corner-resize; no rotate handle, no marquee, no Delete, no nudge, no double-click text (all §7). *(**Scope amended 2026-08-24, founder direction: double-click text IS shipped** — not by this lane, but by rung B of `docs/superpowers/plans/2026-08-24-rich-text-editing.md`, which ports the upstream `TextEditOverlay` into this same host with a one-batch/one-undo-frame commit and Escape-cancel. The rest of the exclusions above stand. See the §1.9 supersession note in `docs/specs/ad-editor-integration/ad-inspector-mapping-contract.md`.)*
- [x] **Step 2:** Handles render per the G-A-approved chrome. Escape cancels a live gesture (reducer up-with-no-commit); ⌘Z after a committed gesture undoes (AD3.3 path).
- [x] **Step 3:** Browser proof (drag persists, resize respects aspect-lock with Shift, locked node drags nothing) + gate + commit.

### Task AD4.D (lane): Export binding

**Files:** Create: `adapter/scene-export.ts` (+test); Modify: `use-scene-editing-session.ts` (the `clue:artifact-export-request` listener), `image-export-menu.tsx` (preview region binding)

- [ ] **Step 1 (pure, TDD):** `sceneExportProfile(format: "PNG"|"SVG"|"PDF", scale: 1|2|3|4): ExportProfile` → PNG: `{name:"ad_png", format:"png", pdf_intent:null, raster:{scale, dpi:96}, include_bleed:false, embed_fonts:false}`; SVG: `embed_fonts:true`; PDF: `pdf_intent:"preview"`, `embed_fonts:true`. And `exportFilename(title, format)` → sanitized `${title}.${ext}`.
- [ ] **Step 2:** Listener (session hook): `kind !== "ad"` → ignore; build the profile, call the extracted `createApiExportRunner({ apiBaseUrl: config.apiBaseUrl, documentId }).run` (verify the runner's exact method name from the extracted module — payload must keep **`persist_preflight: false`**, the scout-flagged load-bearing flag); on `status:"ok"` take `artifacts[0].data_url` → programmatic `<a download={filename}>` click (direct download, standing ruling); failure → first diagnostic in the menu's status line (`aria-live` span exists).
- [ ] **Step 3 (preview region):** on preview-open, run the same export at the current settings and render the `data_url` into the `data-artifact-export-preview="ad"` div as an `<img>` (§1.11 — the designed hook hosts the real render). Cache per (format, scale) until the document version changes.
- [ ] **Step 4:** Transparency checkbox: **held at Gate G-E** (removed in AD0.4; restore + wire only on founder authorization of the engine change — if authorized, that engine work is its own contract-amendment task, not this lane's). Print extras: **held at Gate G-F** (mock in browser first).
- [ ] **Step 5:** Browser proof (download PNG@2x, SVG, PDF; open each file) + gate + commit.

### Task AD4.E: Action menu + multi-select closure

**Files:** Modify: `artifact-header.tsx`/action-menu component (ad branch), session hook

- [x] **Step 1:** Rename → the platform tab-rename seam (already exists in the shell — bind, don't build); Undo/Redo rows dispatch `clue:artifact-action-request` with `kind:"ad"` (AD3.3 listens); Versions flyout stays present-and-inert (§3) — add the provable-inert test (clicking a version row changes nothing: no event listener attached). *(Landed 2026-08-22, commits `c9850b79`+`e2191d2f`: all found-wired — the menu is kind-agnostic and the header stamps `kind:"ad"`; the listener's decision extracted to pure `adActionRequest` and tested; "provable-inert" ruled document-inert per contract §3 — the guard proves `clue:artifact-version-select` has zero listeners repo-wide and pins the row wiring both directions; the version rows keep their lifted local radio. Browser-proven write-free: a version click fired zero network requests, document byte-identical. Residual: artifact rename is client reducer state only — no persistence; §7 family.)*
- [x] **Step 2:** Multi-select final state per amendment 2: additive selection in layers; inspector = first-selected schema; Arrange consumes the set. Verify no "merged panel" remnants leak into props. *(Verified + guard-pinned: additive shift/⌘/ctrl wiring and whole-set highlight pinned; merged-panel negative pinned; no remnants found. "Arrange consumes the set" is Lane B's deliverable (AD4.B step 4) — the `selectedIds`/`[0]`-primary surface it consumes is verified stable. Browser-proven: accumulate holds the first-selected schema; removing the primary promotes the next.)*
- [x] **Step 3:** Gate + commit. *(1754 → 1763 pass / 0 fail, lint 0 errors, build clean.)*

---

# Phase AD5 — Acceptance audit

### Task AD5.1: Contract walk + acceptance record

- [ ] **Step 1:** Walk **every** contract row: §1 rows demonstrably live (screenshot + the op it emitted), §3 rows provably inert, §2 deltas present, §5 rows absent (grep-proof for deleted options: `Tile`, `Critical`, `JPEG`, `Season Serif`, link sections). Fix-before-recording rule: a failing row is fixed, then recorded.
- [ ] **Step 2:** Write `docs/specs/ad-editor-integration/acceptance-record.md` (the W5 shape): per-row evidence, the G-gate closure list, residuals register.
- [ ] **Step 3:** Visual-parity pass vs the dummy at the pinned commit (live dummy dev server, side-by-side screenshots of every schema + export menu + header).
- [ ] **Step 4:** Full gates: frontend gate, platform pytest, root `make check`. Restore the seeded document node-identical after the sweep (export the scene before, compare after undo-cleanup).
- [ ] **Step 5:** `_memory/` close-out + founder walkthrough script + sign-off. Commit.

---

## Dependency graph & parallelism

```
G-G (co-founder commit) ──► AD0.1 ─► AD0.2 ─► AD0.3 ─► AD0.4 ─► AD0.5
                                                            │
AD1.1 ─► AD1.2 ─► AD1.3 ─► AD1.4 ─► AD1.5 ─► AD1.6 ─► AD1.8│
                    AD1.7 (independent after AD1.1) ────────┤
                                                            ▼
                              AD2.1 ─► AD2.2 ─► AD2.3 ─► AD2.4 ─► AD2.5* ─► AD2.6 ─► AD2.7 ─► AD2.8 ─► AD2.9 (demo)
                              (*needs G-A for visible chrome)                                                │
                                                                       AD3.1 ─► AD3.2 ─► AD3.3 ─► AD3.4 ◄────┘
                                                                                                    │
                                              AD4.0 ─►┬─ AD4.A (G-C for focal dot)                 ◄┘
                                                      ├─ AD4.B
                                                      ├─ AD4.C (G-A)
                                                      ├─ AD4.D (G-E, G-F for held items)
                                                      └─ AD4.E
                                                            │
                                                          AD5.1
```
- AD0 and AD1 are fully parallel (different files); AD0 is blocked **only** by G-G.
- AD1.7 needs only AD1.1's constants file; it can land any time.
- The mockup gates (G-A…G-F) are founder sessions the orchestrator schedules during AD1 — none blocks substrate work.
- Genweb-plan coexistence: both touch `artifact-stage.tsx` and `chat-surface.tsx`; land whichever ships first, rebase the other (standing note from the study plan).

## Effort

AD0 ~0.5d · AD1 ~2.5–3d · AD2 ~2d · AD3 ~1d · AD4 ~2.5–3d (lanes parallel in worktrees) · AD5 ~0.5–1d ≈ **9–11 focused days**.

## Traps register (verified, from the scout evidence — read before each phase)

1. **TTF only** — never ship woff2 to CanvasKit; faces register in BOTH the `TypefaceFontProvider` and DOM `FontFace` (the extracted modules do both; don't bypass them).
2. **`/asset-store` must stay headerless**; `/font-library` + `/assets/{id}/bytes` must NOT (they 401 without the workspace header) — the two-proxy split in AD1.7 is load-bearing, not stylistic.
3. **`persist_preflight: false` on every editor-initiated export** — the server default silently bumps the document version behind the edit queue (next local edit gets rejected).
4. **wasm artifacts are runtime fetches** (`webpackIgnore` dynamic import), never bundle imports; the canvaskit *glue* IS bundled (needs AD1.2's fallbacks).
5. **`CornerRadii` order is TL, TR, BR, BL** (BR before BL) — a transposed mapping renders subtly wrong.
6. **`Dimension` literals are lowercase snake** (`fixed|hug|fill|token`); `hug` carries no `value` key; wire-format minimization matters (conditional spreads, never `undefined` keys).
7. **The engine snapshot is the relaid scene** — always render `WasmEngine.scene`, never the raw server scene, or geometry desyncs (text jumps).
8. **Never key-remount the inspector on document version** (write-cycle token) — key on node id only.
9. **editQueue halts on any rejection** until `resync()` — the D10 handler must always resync or the editor silently stops persisting.
10. **The engine-stamp scope is `lumen-core` only** — a stale `lumen-export`/`lumen-skia` in the helper passes the handshake; full-fidelity parity needs `verify_handshake.mjs` in the dev loop (`LUMEN_CORE_HELPER` must point at a binary built from the same checkout).
11. **`tsx --test` runs `.test.ts` only** — no component tests; every testable decision lives in a pure module.
12. **`zoom ∈ [0.1, 2.0]`** engine clamp — the menu's 10–150% fits; never offer values outside.
13. Port-check 3030/8030/8010 before every dev launch; `LUMEN_CORE_HELPER` set or every design-tool call spawns cargo (minutes-slow).
14. **TS operation mirror is missing `set_brand_kit_ref`/`finalize_template` and `NodePatch.bleed`** vs Rust — irrelevant to this plan's surface, but do not "fix" the mirror mid-extraction (verbatim wins; it's a subsystem-owned delta).
