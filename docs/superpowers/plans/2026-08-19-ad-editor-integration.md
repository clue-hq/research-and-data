# Ad-design (scene) editor integration — plan of action

**Status 2026-08-20: SUPERSEDED for execution.** All twelve §5 decisions are closed and the
contract is frozen; the task-level execution plan is
**`2026-08-20-ad-editor-integration-execution-plan.md`** — implementers work from that document.
This one remains the study record (§1 findings, §2 gap register, §3 laws, §5 decision register,
§6 traps, §7 out-of-scope) and is no longer the source of phase scope.

**Original status line: DRAFT — awaiting founder review of the decision register (§5) before any phase starts.**
Date: 2026-08-19. Branch context: `integration/frontend-design-part-iv-v2` (W0–W5 website-editor
integration COMPLETE; chat-flow integration COMPLETE; genweb slices 0–2 landed).

This plan is the ad-editor sibling of `2026-08-17-website-editor-integration.md` (W0–W5). It
covers: mounting the CanvasKit/SkParagraph **scene editor** (the ad-design editor from
`subsystems/clue-design`) in the platform shell, merged with the dummy frontend's **ad inspector
toolbar** (`image-inspector.tsx`, already lifted in W0 and sitting inert), following the exact
laws, process, and phase shape that made the website editor land clean.

**Done means:** a user opens an ad artifact at
`/projects/{id}/artifacts/{artifactId}` (or via `?surface=ad` on the chats route), sees the real
scene rendered by CanvasKit inside the dummy's artboard card, selects elements on the canvas,
edits them through the dummy's ad inspector (every §1-contract control live against the Rust
engine with CAS + undo/redo), and exports the ad through the dummy's export menu — with visual
parity to the dummy shell and zero invented UI.

---

## 1. Study findings — the three-sided map (verified 2026-08-19)

### 1.1 The dummy frontend (port-of-spain, branch `codex/chat-shell`, HEAD `c7f2bc5`)

- The ad editor is a **mode of the same chat shell**, not a separate screen: `kind=ad` on the
  artifact route / `?surface=ad` on the chats route selects `ImageInspector` over `WebInspector`
  and `.imageOutputStage`/`.imageCanvas` over the web stage. ~90% of chrome is shared.
- **The canvas is a designed hole.** `artifact-stage.tsx` renders
  `<div aria-label="Empty ad output canvas" className={styles.imageCanvas} />` — no fake canvas,
  no selection chrome, no zoom transform. The artboard chrome to preserve: centered card,
  `min(76%, 640px)`, `aspect-ratio: 1`, 0.5px hairline border, 2px radius, subtle card shadow,
  40px stage padding.
- **Four inspector schemas** (canvas / text / image / button), each today an independent
  `useInspectorController` state island. Controls inventory (the raw material for the §2 mapping
  contract): canvas → size presets + background fill (solid / linear / radial with a real 2–6
  stop gradient editor + angle); text → color, font (Inter/Satoshi Variable/Season Serif/DM
  Mono), size/weight, 3+3 alignment, stroke, X/Y position, rotation, arrange (z-order + align);
  image → link, image upload + fill mode (Fit/Fill/Stretch/Tile), radius (shares
  `RadiusControls` from `web-inspector.tsx`); button → link, style
  (Primary/Secondary/Transparent/Critical), token colors, L/T/R/B padding. All schemas end with
  the shared `AdLayers` panel — currently a hardcoded 8-row fixture list including rows
  (Rectangle, Ellipse, Group) that have **no inspector schema at all**.
- **A tool palette was authored but never built**: `ImageEditorTool = "image" | "pointer" |
  "shape" | "stroke" | "text"` + `.editorToolButton` CSS + exported icons in
  `public/icons/chat-shell/editor/` + `editor.tool.change`/`editor.viewport.change`/
  `editor.zoom.change` event names in the contract doc. Nothing consumes them.
- **Zoom is a decorative string** (`"23%"` default, menu 23/50/75/100) — never applied to a
  transform. Export menu (`image-export-menu.tsx`): PNG/JPEG/SVG/PDF × 1x–4x (raster only) ×
  transparent background (PNG/SVG only), with a collapsible preview region carrying
  `data-artifact-export-preview="ad"` as an explicit real-render mount hook.
- **There is no ad data model in the dummy.** No zod schema, no repository, no layer types —
  the chat-shell feature has zero fixtures for ads. `docs/api-contracts/chat-shell.md` is the
  newer authority (`ChatShellArtifact`, `InspectorSelection`, `InspectorBackgroundFill`, the
  `clue:inspector-*` CustomEvent seam with dotted property paths like `position.x` /
  `radius.topLeft`, and the hard rule **"one ad is one artifact"**).
- Undo/redo live in `ArtifactActionMenu` (⌘Z/⇧⌘Z rows + a Versions flyout), same as web.

### 1.2 The real scene editor (`subsystems/clue-design/apps/editor`)

- **Renderer:** `CanvasKitCanvas` (1,354 L) over `canvaskit-wasm@0.41.1`
  (`MakeWebGLCanvasSurface` with software fallback; single-threaded, **no COOP/COEP, no
  workers, no SharedArrayBuffer** — the biggest de-risking fact for embedding). A legacy Konva
  path survives behind `NEXT_PUBLIC_LUMEN_CANVASKIT`; selection chrome is deliberately an SVG
  overlay so hover never redraws wasm. Text is SkParagraph (`drawDescriptors.ts` 1,185 L)
  with **measure-then-inject**: browser measures with SkParagraph, feeds metrics into the Rust
  engine (`lumen-skia` cannot target wasm32).
- **Engine:** `lumen-core` (scene model: pages/nodes/slots/assets; `NodeKind = Frame | Group |
  Rect | Ellipse | Line | Text | Image | Vector | AutoLayout | Instance`; Paint = Solid |
  LinearGradient | RadialGradient | Token; effects; taffy layout; authoritative `hit_test.rs`)
  wrapped by `lumen-wasm` (`LumenEngine.loadScene/applyOperations/hitTest/setMeasurements/...`,
  3 MB gzip budget enforced). 21-op vocabulary (`update_node`, `insert_node`, `move_node`,
  `place_asset_in_node`, `add_page`, `finalize_template`, …) with three-state `FieldPatch`
  semantics, plus the invertible structured-edit layer.
- **Editing machinery already exists and is rich**: pure-reducer `gestureMachine.ts`,
  drag/resize/rotate → operations, snap guides, managed-layout handoff-freeze, align/distribute,
  marquee/multi-select, `editQueue.ts` (276 L — serialized CAS commits with `base_version`,
  divergence reconciliation, richer than the web path's controller), `useEditHistory`, server
  undo/redo/checkpoints.
- **Persistence:** scene docs use the unprefixed `/documents/*` design-API routes —
  `POST /documents/{id}/operations` (row-locked CAS on `base_version`), `/undo|redo|revert`,
  `/snapshots`, `/export` (formats **Svg | Png | Pdf | FigmaManifest** — no JPEG),
  `/export-preview`, `/preflight`. No `/render` equivalent (scenes have export, not publish).
- **Fonts (the hidden hard part):** TTF/OTF only (CanvasKit can't read woff2), three sources —
  4 bundled Inter statics (the cross-runtime parity contract with server exports), the ~27-family
  curated library served by `GET /font-library` + content-addressed bytes, and brand-kit faces —
  all registered into a `TypefaceFontProvider` AND as DOM `FontFace` entries. Missing face →
  `heuristic` measurement + a loud banner. Asset bytes come from `/asset-store/{digest}`, a
  **public wildcard-CORS route that must NOT carry `X-Workspace-Id`** (a custom header breaks
  the CORS preflight).
- **The engine-stamp handshake is a deploy coupling:** browser `lumen_wasm` and server
  `lumen-api-helper` both embed a content hash of `lumen-core/src/**`; mismatch drops the editor
  to uneditable mode. The platform build must produce both from the same commit.
- **The scene agent is propose→accept, not commit:** `POST /agent/turns` runs the three-role
  deepagent and returns `{operations, draft_scene, preview_paths, stop_reason, clarification}` —
  **nothing persists server-side**. The accept seam lives in the standalone editor
  (`useAgentTurn`: replaceScene → applyOperations → optional accept-bake → commit). The web
  agent, by contrast, commits server-side under CAS. Scene turns also own the one-per-turn
  structural clarification round the web path lacks.

### 1.3 Platform integration status today

- **Part II substrate fully covers scenes**: `design_doc_kind = {scene, web}` (default
  `scene`), the 49-tool toolbelt includes the 13 scene document tools + `design_start_agent_turn`
  + asset/brand tools, the fleet's `design_job` dispatches `agent_turn` envelopes, and scene
  run events ride the same durable `run_event` stream + stream-token SSE.
- **Part III legs**: a leg pinned to a scene document dispatches `agent_turn` (the untouched
  default branch in `design_leg_wiring.py:1238-1262` after genweb B1) — **but the returned
  proposal is dropped on the floor** (no accept seam exists on the platform), legs **cannot
  create** scene documents (`design_leg_tools.py:731-737`,
  `design_leg_scene_creation_unsupported` — "scene artifacts are made in the editor"), and
  `focus_refs` never reach `target_node_ids`.
- **Platform frontend**: zero scene modules — no canvaskit-wasm dep, no wasm, no scene engine,
  no scene adapter. What IS there (lifted in W0, inert): `image-inspector.tsx` (357 L, untrimmed
  dummy schemas), `image-export-menu.tsx` + `use-image-export-controller.ts` + `model/
  image-export.ts`, `artifact-header.tsx`'s ad branches (zoom menu, Export button), and
  `chat-dock.ts` already routes `"ad-inspector"` for `artifactKind === "ad"`. The single-artifact
  read already maps any non-web `doc_kind` → `kind: "ad"` (`chat/router.py:1101`); opening one
  today renders the empty artboard div and a fixture-driven inert inspector.
- **The gallery excludes scenes at the SQL level**: `WHERE d.doc_kind = 'web'`
  (`design_leg_wiring.py:458`), and `adapter/gallery.ts` hardcodes
  `collateralType: "microsite"`.
- **The BFF proxy is already path-generic** (`/api/clue/design/[...path]` forwards any design-API
  path with server-side workspace auth) — scene document/ops/export traffic needs zero proxy
  changes. What's missing: a strategy for the public `/asset-store/{digest}` bytes and static
  vendor assets (`/canvaskit/*`, `/wasm/*`, `/fonts/*`).
- Route vocabulary is already ratified for ads: `?surface=ad` exists in R2; `?kind=ad` renders
  the ad branch on the artifact route.

### 1.4 The three size-preset vocabularies (must be reconciled in the contract)

| Source | Values |
|---|---|
| Dummy `SIZE_PRESETS` (`image-inspector.tsx:29-33`) | LinkedIn square 1024×1024 · Instagram portrait 1080×1350 · Story 1080×1920 |
| Editor `PageRail` quick sizes | Square Ad 1080×1080 · LinkedIn Wide 1200×628 · Portrait Social 1080×1350 · Email Header 600×800 |
| Rust `PagePreset` (`scene.rs:254`) | A4 · UsLetter · LinkedinAd (1200×627) · EnvelopeDl · Custom |

---

## 2. The gap register (everything required, numbered)

Backend/platform:
- **G-A1** Gallery feed is web-only (`design_leg_wiring.py:458` + `adapter/gallery.ts`
  microsite hardcode) — scene documents invisible in the rail.
- **G-A2** No scene accept/commit path on the platform: leg-dispatched scene turns produce
  proposals nobody applies. (Deferred to the chat-loop plan, §7 — but the decision shapes AD1.)
- **G-A3** Legs cannot create scene documents (typed refusal, v1 ruling "editor-first").
- **G-A4** `focus_refs` not threaded to `target_node_ids` on scene envelopes.
- **G-A5** No thumbnail/preview read for scene cards (web has `/web/render`; scenes have only
  `/export-preview` — cost untested; current ratified ruling is "real documents have no
  thumbnails").

Frontend substrate:
- **G-F1** No scene engine slice in `apps/frontend` (wasm engine wrapper, editQueue, gesture
  machine, canvaskit loader/draw/measure/imageCache, viewport, selection chrome math).
- **G-F2** No vendor pipeline for `canvaskit.wasm` (~2.9 MB gz), `lumen_wasm_bg.wasm` (≤3 MB gz
  budget), and TTF fonts; no engine-stamp preflight; no webpack `canvas: false` +
  `fs/path/crypto` fallbacks in `apps/frontend/next.config.ts`.
- **G-F3** No decision on serving `/asset-store/{digest}` bytes (public CORS route vs BFF
  proxy without the workspace header) and `/font-library` under the platform origin.

Frontend surface:
- **G-F4** The ad canvas mount: `artifact-stage.tsx`'s empty `.imageCanvas` div must become the
  CanvasKit stage + SVG selection overlay, inside the preserved dummy artboard chrome.
- **G-F5** The four ad inspector schemas are fixture state islands: need one hydrated,
  selection-driven store (the web `hydrate.ts`/`apply.ts` adapter pattern) and the
  addressing/null-write contract (W3.1 pattern).
- **G-F6** `AdLayers` is hardcoded: needs the real scene tree (and rows for kinds the dummy
  never schematized — shape/group/frame → §5 fallback rule).
- **G-F7** Zoom/viewport: menu exists, no transform; the engine's viewport machinery exists but
  the dummy has no pan/zoom affordances beyond the menu → contract ruling.
- **G-F8** Export menu unbound; engine has no JPEG; scale/transparency map to raster profile
  options; "Export = direct" founder ruling already exists (2026-08-17).
- **G-F9** No `useSceneEditingSession` (the ids-only shared-session hook that made the web
  editor's second mount trivial); `chat-surface.tsx` mounts `ImageInspector` with placeholder
  props.
- **G-F10** The dummy's per-icon set for the tool palette + `editor.*` events authored but
  unbuilt (founder scope decision).
- **G-F11** The ad-side CSS classes from the W0.2 bisect need a coverage audit
  (`.imageEditorToolbar`, `.editorToolButton*`, export-menu styles) plus the editor tool icons
  (`public/icons/chat-shell/editor/*`) which were never copied (W0 copied 47 files, inspector +
  root only).
- **G-F12** `RadiusControls` lives in `web-inspector.tsx` and is imported by
  `image-inspector.tsx` — hoist into `inspector-primitives.tsx` before fan-out.

Contract:
- **G-C1** The ad-editor equivalent of the 42-item mapping exercise has never been done — the
  lifted `ImageInspector` still carries untrimmed dummy option sets (`Tile`, `Critical`,
  `Season Serif`, the 1024×1024 preset…).

---

## 3. Laws inherited verbatim (not up for re-litigation)

1. **Dummy frontend is the sole presentation truth; the dummy UI is the ceiling.** Lift
   verbatim, bind at the seam, never invent UI. Any engine-forced new visible element/state →
   founder options first. (The scene editor's standalone chrome — SelectionOverlay handles,
   PageRail, TextToolbar, HistoryPanel, rail modes — is **not** presentation truth; only the
   dummy is. Engine *behavior* ports; standalone *chrome* does not, absent a ruling.)
2. **Contract partitions are law** (§1 wired / §2 hidden / §3 inert / §4 invisible-but-alive /
   §5 fallback / §8 enumerated engine changes, capped).
3. **Inspector docks in the chat column** (R6); composer stays; Edit-only entry; accepted send
   dismisses. `?surface=ad` + `?edit=1` + `?selection=` (R2); `?artifact=` forbidden.
4. **Never browser→FastAPI**: all traffic through `/api/clue/design` (grep-guard enforced);
   engine slice reads no env (no-env-reads test).
5. **Process**: Opus implements; the orchestrating session reviews every diff inline; TDD on
   pure adapters against real harvested fixtures; browser-proof + local commit per task; never
   push; no AI attribution.
6. **Gates** per task: `npm run design-system:build && npm test && npm run lint && npm run
   build`; root `make check` at phase close. Test runner is `tsx --test` (node:test) — hook
   semantics live in pure reducers/decision modules.
7. **Engine edits mirror into both copies byte-identically** (subsystem + vendored) and any
   `lumen-core`/helper change requires `cargo build -p lumen-api-helper --release` + design-API
   restart; wasm rebuild + stamp preflight on the frontend side.

---

## 4. Phase plan

Phase names: **AD-R** (reconnaissance/contract) → **AD0** (shell audit) → **AD1** (engine +
wasm substrate) → **AD2** (read path) → **AD3** (first write) → **AD4** (schema & interaction
fan-out) → **AD5** (acceptance). The chat-loop work (agent proposals, scene birth from chat,
gallery) is a separate follow-on plan (§7), same relationship as
`2026-08-19-chat-driven-website-generation.md` had to W0–W5.

### AD-R — reconnaissance & the mapping contract (the 42-item exercise for ads)

1. Produce the **control-by-control inventory**: every `ImageInspector` control × the scene
   engine's real property space (`Node`/`TextNode`/`Paint`/`PageSize`/ops), statused
   PARITY / MAPPABLE / NO BACKING / ENGINE GAP / NO SLOT — exactly like
   `docs/specs/website-editor-integration/decisions-recorded.md`. Pre-identified hard rows:
   - **Background fill gradients**: dummy's 2–6-stop editor ↔ engine
     `Paint::{LinearGradient,RadialGradient}` — strong PARITY candidate (better than web ever
     had).
   - **Size presets**: reconcile the three vocabularies (§1.4) into one ratified set; decide
     whether preset change = `update_page` size patch.
   - **Button**: the scene model has **no button kind** — a "button" in an ad is a
     Frame/AutoLayout + Text. Ruling needed: MAPPABLE (a tagged frame convention) vs NO BACKING
     (hide the button schema in v1).
   - **Shape/group/frame selections**: no dummy schema — apply the §5 Layout-only-fallback
     precedent (which schema renders for a Rect/Ellipse/Group selection?).
   - **Fonts**: dummy menu (Inter/Satoshi Variable/Season Serif/DM Mono) vs the curated
     library + brand-kit faces; which families ship in v1 and what the select actually lists.
   - **Fill modes**: dummy Fit/Fill/Stretch/Tile ↔ engine `asset_placement` (Tile likely NO
     BACKING).
   - **Stroke on text**, X/Y position, rotation, arrange z-order (`move_node`), 6-way align
     (`alignDistribute`) — all MAPPABLE, each needs its exact op mapping named.
   - **Export**: JPEG (engine gap — drop the option or add the format, one enumerated engine
     change candidate); scale ↔ raster profile; transparency ↔ profile background; the export
     menu's preview region (dummy-designed, keep) vs the standing "export = direct" ruling.
   - **Zoom**: wire the 23/50/75/100 menu to a real viewport transform; whether scroll/pinch
     pan-zoom enters v1 (no dummy affordance → default NO SLOT, menu-only).
   - **Tool palette / node insertion**: the authored-but-unbuilt palette — in or out of v1.
   - **On-canvas direct manipulation** (drag/resize/rotate handles, double-click text edit):
     the engine machinery exists; the dummy shows no handles. This is the **single biggest
     scope ruling** of the plan (see D1, §5).
2. Founder ratifies item-by-item → freeze
   **`docs/specs/ad-editor-integration/ad-inspector-mapping-contract.md`** with the §1–§8
   partition structure and the enumerated engine-change cap.
3. Repeat the tri-diff reconnaissance trick (`_memory/2026-08-17-frontend-tri-diff-synthesis.md`)
   only as a delta: the dummy advanced past our lift point — diff `image-inspector.tsx`,
   `artifact-header.tsx` ad branches, export menu, and the ad CSS ranges between our lifted
   copies and dummy HEAD (`c7f2bc5`), and record whether a re-lift is needed.

**Exit gate:** ratified frozen contract; open decisions D1–D12 (§5) each carry a founder ruling.

### AD0 — shell completion audit (small; the W0 analog is mostly already done)

- CSS coverage audit of the W0.2 bisect for every ad-editor class (stage, export menu, tool
  palette classes) — extract any missed ranges byte-identically.
- Copy the missing icon subsets (`public/icons/chat-shell/editor/*`, export-menu glyphs not yet
  present) — `cmp`-verified.
- Hoist `RadiusControls` from `web-inspector.tsx` into `inspector-primitives.tsx` (G-F12), a
  pure move consumed by both inspectors.
- Trim the lifted `ImageInspector` option sets to the ratified contract (the W-phase "§2 hidden
  rows" pass).
- Delta re-lift from dummy HEAD if AD-R's diff says our copies are stale.

**Exit gate:** ad chrome renders the honest empty state on both mounts, byte-parity vs dummy,
all gates green. Wiring: none.

### AD1 — scene engine extraction + wasm/font/asset pipeline (the heavy substrate phase)

1. **Extract the React-free scene engine slice** into
   `apps/frontend/src/features/design-editor/engine/scene/` (sibling of the web engine files,
   same feature so the config seam is shared): `wasmEngine.ts`, `documentStore.ts`,
   `editQueue.ts`, `gestureMachine.ts`, `canvasOperations/Selection/Viewport`,
   `transformerMath.ts`, `selectionChrome.ts`, `sceneQueries.ts`, `alignDistribute.ts`,
   `operations.ts`/`operationLabels.ts`, `canvaskit/{loadCanvasKit,drawDescriptors,
   skiaMeasurements,imageCache,fontFaces}.ts`, `renderAdapter.ts` — import-adjusted only,
   `editorConfig.ts` replaced by the existing injected `DesignEditorConfig` (asset-URL and
   font-URL builders become config fields), the `no-env-reads` grep guard extended over the
   scene slice, co-located tests ported through the vitest shim. **CanvasKit renderer only —
   the Konva fallback is not extracted** (D7).
2. **Vendor pipeline** — extend `apps/frontend/scripts/copy-design-vendor.mjs`:
   `canvaskit.wasm` → `public/vendor/canvaskit/`, `lumen_wasm` (wasm-pack build of
   `crates/lumen-wasm`, honoring the 3 MB gzip budget) → `public/vendor/wasm/`, the 4 Inter
   statics → `public/vendor/fonts/`; engine-stamp preflight (re-derive the stamp, fail the build
   on drift — the `preflight_editor_wasm.mjs` logic); wire into `prebuild`/`predev`; keep
   output gitignored; extend `vendor-runtime.test.ts` to run the pipeline.
3. **next.config**: `resolve.alias.canvas = false` + client `fallback = {fs,path,crypto:
   false}` (required by canvaskit glue; build stays `--webpack`).
4. **Bytes & fonts serving decision implemented per D8**: default recommendation — a narrow
   BFF passthrough for `/asset-store/{digest}` and `/font-library` that forwards **without**
   the workspace header (both are content-addressed/public), so the browser still talks only to
   our origin.
5. **Fleet/API parity check**: `LUMEN_CORE_HELPER` built from the same commit; document the
   handshake-mismatch posture (D9: banner + read-only canvas, never a silent dead editor).

**Exit gate:** in a scratch page/test harness, the vendored engine loads CanvasKit + lumen-wasm,
loads a real scene document fetched through the BFF, and reports `skia` measurement status —
no env reads, all gates green, engine tests ported and passing.

### AD2 — read path (the W2 analog)

1. **Backend read seam** (one platform PR): widen the gallery feed per D5 — either drop the
   `doc_kind='web'` filter with a kind-aware wire shape (`adapter/gallery.ts` maps scene →
   the ratified collateral type) or add a scene-inclusive variant; keep the single-artifact
   read's `kind: "ad"` mapping; record the decision in
   `apps/frontend/docs/api-contracts/projects.md`.
2. **`SceneArtifactCanvas`** (`features/design-editor/components/`): mounts the CanvasKit
   stage + the SVG selection-overlay layer inside the preserved `.imageCanvas` chrome slot in
   `artifact-stage.tsx` (the branch at :136-166 becomes web-canvas / scene-canvas / gallery).
   Read-only first: draw the scene, fonts registered lazily (bundled Inter + library families
   the scene references), images through the image cache, artboard sized per the page.
3. **Selection**: pointer → engine `hitTest` → selection state → overlay outline + inspector
   selection mapping (`adapter/scene-hydrate.ts`, TDD against **harvested real scene-node
   fixtures** from a seeded ad document — the W2.2 pattern). Layers panel goes real
   (`adapter/scene-layers.ts`; depth/expansion per the dummy's `InspectorLayerRow`).
4. **`useSceneEditingSession`** (ids-only, owns no shell controller — the exact
   `use-web-editing-session.ts` discipline) so the artifact route and chat route are two mounts
   of one machine; `EditorSurface`/`ChatSurface` gain the scene branch behind their existing
   kind guards; the chat dock's `"ad-inspector"` branch receives real props (replacing the two
   placeholders).
5. **Zoom menu wired** to the real viewport transform per the contract ruling (fit-derived
   percentages, no new affordances).

**Exit gate (founder demo):** open a seeded ad artifact on both mounts — the real scene renders
inside the dummy card, canvas clicks select with outlines, the layers panel is real, the
inspector shows hydrated values for the selected node — zero writes wired.

### AD3 — first write flow (the W3 analog: the text schema)

1. Addressing rides the existing W3.1 event contract (`{selectionId, artifactId,
   documentVersion}`; the null contract holds: not-addressable ⇒ not a write).
2. **`adapter/scene-apply.ts`** (pure, TDD): inspector event → scene `Operation` —
   `update_node` patches with correct `FieldPatch` three-state semantics (e.g.
   `typography.color` → text fill/style patch; `position.x` → transform patch; the exact §1
   contract rows for text).
3. **Write controller over the extracted `editQueue`** (not a re-implementation): one in-flight
   batch, `base_version` CAS, 409 → the ratified reconcile posture (D10 — recommend: adopt the
   web's honest "Document moved on — reloaded" + reload, deferring `editQueue`'s optimistic
   divergence reconciliation unless the founder wants optimistic-local as v1), 422 → first
   diagnostic inline; success → engine + inspector resync without keyed remounts on write
   tokens.
4. **Undo/redo wired with the first write** (the W3.4 lesson: live writes beside inert undo
   reads as broken) — server `/documents/{id}/undo|redo` through the same busy guard.
5. Save-failure UX: inline-only (the ratified W3.3 posture).

**Exit gate:** text edits from the inspector persist across reload with CAS + undo/redo,
browser-proven on both mounts.

### AD4 — schema & interaction fan-out (the W4 analog; parallel-lane candidate)

Shared substrate first (trunk), then lanes — same F1 discipline as W4:
- **Lane substrate (trunk):** canvas schema — page-size presets (`update_page`) + background
  fill including the gradient editor ↔ `Paint` gradients; the theme/brand-token feed for token
  controls (scene `DesignTokens` ↔ the dummy's token chips per contract).
- **Lane A:** image schema (asset replace via `POST /assets` + `place_asset_in_node`, fill
  mode ↔ `asset_placement`, radius) and — per the D2 ruling — the button-as-tagged-frame
  schema or its §2 hiding.
- **Lane B:** arrange (z-order via `move_node`, 6-way align via `alignDistribute`), stroke,
  position/rotation, opacity if ratified; the layers-panel selection of shape/group rows under
  the §5 fallback schema.
- **Lane C (only if D1 ratifies it):** on-canvas direct manipulation v1 — move/resize via the
  extracted gesture machine with the SVG handles as the founder-approved visible chrome, plus
  Escape/⌘Z parity. If D1 defers, this lane is replaced by an audit task recording the gap in
  the contract's §7 register (the W4.10 pattern: wire nothing).
- **Export binding (any lane):** `ImageExportMenu` → `POST /documents/{id}/export` with the
  ratified format/profile mapping; direct download (standing ruling); preview region per
  contract.

**Exit gate:** every §1 row demonstrably live, §3 rows provably inert, §2 rows absent — the
consolidated browser sweep, both documents restored node-identical.

### AD5 — acceptance audit (the W5 analog)

- Contract walk → `docs/specs/ad-editor-integration/acceptance-record.md` (fix-before-recording
  rule), visual-parity pass vs dummy HEAD (live second baseline, not stale PNGs), full gates
  incl. root `make check`, `_memory/` close-out, founder walkthrough script + sign-off.

---

## 5. Founder decision register (rule before the phase that names them)

**Status 2026-08-20: ALL TWELVE CLOSED.** D1–D6 and D11–D12 were ruled through the disparity
inventory's founder-annotation passes and are folded into the frozen
`docs/specs/ad-editor-integration/ad-inspector-mapping-contract.md` (the normative record);
D7–D10 were closed 2026-08-20 as recommended (contract amendment 3). Nothing in this table
gates AD-R/AD0/AD1 anymore.

| # | Decision | Gates | Recommendation |
|---|---|---|---|
| **D1** | **On-canvas direct manipulation in v1?** (drag/resize/rotate handles, double-click text edit — engine-ready, but the dummy shows no handles; selection outlines are the only ratified canvas chrome) | AD-R / Lane C | Ship **selection + move/resize** in v1 with the minimal SVG handle chrome presented as explicit founder options (screenshots) before building; defer rotate/text-overlay to v1.1. An ad editor whose canvas cannot be dragged reads as broken in a way the web editor did not. |
| **D2** | Button schema: tagged-frame convention vs hide in v1 | AD-R | Hide (§2) unless the scene template vocabulary already carries a button convention — inventory during AD-R. |
| **D3** | Size-preset vocabulary (the three conflicting sets) | AD-R | Adopt the dummy's three as labels, mapped to real px values ratified per row; add `PagePreset::Custom` passthrough. |
| **D4** | Tool palette / node insertion in v1 (authored-but-unbuilt in the dummy) | AD-R / AD4 | Out of v1 (§7 register); inserting content stays agent-driven, matching the web editor's node-op posture. |
| **D5** | Gallery: do ad/scene documents enter the rail feed now? | AD2 | Yes — kind-aware feed with the ratified collateral type; card body stays the honest no-thumbnail state (or gate a cheap `/export-preview` thumbnail behind evidence). |
| **D6** | Shape/group/frame selection fallback schema (§5 rule for kinds the dummy never designed) | AD-R | Layout-only fallback, mirroring the web §5 precedent. |
| **D7** | Konva fallback: extract or drop? | AD1 | **RULED 2026-08-20 (founder): as recommended.** Drop — CanvasKit only; the software-surface fallback already covers WebGL-less environments. |
| **D8** | `/asset-store/{digest}` + `/font-library` serving under the platform origin | AD1 | **RULED 2026-08-20 (founder): as recommended.** Narrow BFF passthrough without the workspace header (browser never leaves our origin; no CORS games). |
| **D9** | Engine-stamp mismatch UX in the platform shell | AD1 | **RULED 2026-08-20 (founder): as recommended.** Loud banner + read-only canvas (never silent), mirroring the standalone editor's posture — wording proposed to founder first (new user-facing state). |
| **D10** | CAS conflict posture: web-style reload-and-drop vs editQueue's optimistic reconciliation | AD3 | **RULED 2026-08-20 (founder): as recommended.** Web-style for v1 (honest + already ratified UX); revisit if editing feels laggy. |
| **D11** | Multi-page scenes: v1 = single-page ad ("one ad is one artifact" per the dummy contract) with multi-page/PageRail deferred? | AD-R | Yes — v1 single page; multi-artboard workspace is §7 future work. |
| **D12** | Export JPEG: drop the dummy option or add the engine format (an enumerated §8 engine change)? | AD-R | Drop in v1 (§2 hidden); PNG scale covers the use case. |

---

## 6. Traps & operational notes (inherited from W0–W5, verified applicable)

- `tsx --test`, no React renderer → pure reducers/decision modules; vitest-shim for ported
  engine tests; eslint ignores `public/vendor/**`; no sync setState in effects, no render-time
  ref writes; never key-remount on write-cycle tokens; components never import `data/` or the
  engine.
- `LUMEN_CORE_HELPER` mandatory (else per-call cargo spawns); port-check 3030/8030/8010 before
  every launch; the login/2FA recipe and browser-automation quirks in
  `_memory/2026-08-17-w01-shell-lift-file-set.md`.
- Engine edits mirror into both copies; helper rebuild + API restart after any `lumen-core`
  change; wasm rebuild + stamp preflight after the same.
- New scene-specific traps found by this study: TTF-only fonts (never ship woff2 to CanvasKit);
  fonts must register in BOTH the TypefaceFontProvider and DOM FontFace with explicit
  descriptors; `/asset-store/{digest}` must never carry `X-Workspace-Id`; canvaskit glue needs
  the webpack alias/fallbacks; wasm artifacts are lazy runtime fetches, never bundle imports;
  the 3 MB gzip budget on `lumen_wasm_bg.wasm` is enforced — engine-slice growth can fail the
  vendor build.

## 7. Explicitly out of scope (separate plans / future registers)

1. **The chat loop for ads** — the sibling of `2026-08-19-chat-driven-website-generation.md`:
   scene-turn accept path on the platform (G-A2 — the propose→accept asymmetry is the single
   largest open design question: port the accept seam vs make scene turns commit server-side
   under CAS like web turns), scene document birth from chat (G-A3), `focus_refs` →
   `target_node_ids` (G-A4), leg lifecycle UX, the clarification round's chat rendering. Plan it
   after AD2 proves the surface; several of its rulings (especially accept-seam placement)
   should be taken alongside D1 since they share the preview/accept UI question.
2. Multi-page ad sets / PageRail / infinite workspace (D11 defers).
3. Personalization surfaces (slots, binding sets, instance batches) in the platform editor.
4. Print/preflight surfaces (bleed, CMYK, imposition) — the engine has them; no dummy slot.
5. Brand-kit panel / asset browser / history panel / validation panel from the standalone
   editor — no dummy slots; agent- and backend-side behavior only.
6. Scene publish (does not exist; ads export, they don't publish).
7. Effects editing (engine renders effects; no inspector slot anywhere — dummy or standalone).

## 8. Sequencing & rough effort

```
AD-R  contract + recon        ~1–1.5 days (study done; inventory + founder session)
AD0   shell completion        ~0.5 day
AD1   engine + wasm substrate ~2–3 days   (the heavy one; nothing user-visible)
AD2   read path               ~1.5–2 days (founder demo gate)
AD3   first write             ~1 day
AD4   fan-out                 ~2–3 days   (3 lanes parallelizable in worktrees after substrate)
AD5   acceptance              ~0.5–1 day
                              ≈ 8–12 focused days end to end
```

Dependencies: AD-R gates everything; AD1 can start the moment the contract freezes (it is
contract-independent except for D7–D9); AD2 needs AD1; AD4 lanes fork only after the AD4
substrate lands on trunk (the W4.0/W4.1 lesson). Nothing here blocks — or is blocked by — the
genweb plan's remaining slices (different files, different backend seams), except that both
touch `artifact-stage.tsx` and `chat-surface.tsx`; land whichever ships first and rebase the
other.
