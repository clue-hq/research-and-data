# Website-Editor Platform Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mount the co-founder's chat-shell editor UI in `apps/frontend` at the artifact routes and bind its website-editor inspector to the real web editor engine, per the fully-ratified 42-item mapping contract.

**Architecture:** The dummy editor shell (presentation-only, DOM-event seams) is lifted verbatim into the platform frontend; the web engine layer (`webDocuments` / `webClassFacets` / `webBridge`) is extracted behind injected config and reached through the existing authenticated BFF; a thin adapter binds inspector events → engine facets/props with the edit-queue/reconcile discipline preserved. Ad/scene editor, export/share chrome, publish/subdomain serving, and agent streaming are explicitly out of scope here — separate plans.

**Tech Stack:** Next.js App Router (apps/frontend, npm), TypeScript, the design subsystem's TS engine layer (`subsystems/clue-design/apps/editor/src/engine`), FastAPI design API (`subsystems/clue-design/apps/api`), platform BFF (`apps/frontend/src/auth` + `/api/clue` proxy).

**Spec:** `docs/specs/website-editor-integration/web-inspector-mapping-contract.md` (binding, fully ratified) + `docs/specs/website-editor-integration/decisions-recorded.md` (founder decision record). Background: `docs/specs/design-integration-master-plan.md` §3-IV.

## Global Constraints

- **Visual parity is absolute.** The dummy UI (`clue-hq/clue-frontend@codex/chat-shell`) is baseline and ceiling. Only the contract §2 founder-ordered deltas may deviate. Any new user-visible element/state requires a founder decision first.
- **The contract partitions are law**: §1 wired, §3 inert, §2 hidden-by-ruling, §4 invisible-but-alive (agent-only), §5 Layout-only fallback. Do not re-litigate.
- **One authorized engine change**: the radius facet in `webClassFacets.ts` (contract §8). Nothing else in the engine may change.
- **Data-integrity guarantee** (contract §4): every write path must round-trip `tag`/`anchor_id` on sections and never clobber unrelated props/classes (facet discipline: rewrite only your own tokens; `:`-variant tokens are opaque).
- The design API is workspace-header-auth only — it must NEVER be reachable directly from browsers; all frontend calls go through the authenticated BFF (`/api/clue/...`).
- `apps/frontend` check gate: `npm run design-system:build && npm run lint && npm run build`. Root gate: `make check`. Commit locally at every task boundary; **never push**.
- Frontend repo-seam discipline: Zod schema + repository interface with fixture + HTTP adapters per feature; presentation stays transport-free.
- Local commits only, no AI attribution, feature-branch work (current branch lineage: `integration/frontend-design-part-iv-v2` / this workspace's branch).

---

## Phase W0 — Shell lift (the dummy renders in our app)

Reference material: the bifurcation inventory (this session, 2026-08-17). Source checkout: clone `clue-hq/clue-frontend` branch `codex/chat-shell` to a temp dir at execution time.

**Scope note (founder instruction: website editor only).** The ad-side files (`image-inspector.tsx`, `image-export-menu.tsx`, `use-image-export-controller.ts`, `model/image-export.ts`) are copied in W0.1 **only because `artifact-header.tsx` imports them** (its ad-kind branches) and verbatim copying preserves visual parity with zero edits — they remain unmounted and unwired throughout this plan (no ad artifact reaches the route in this scope). The ad-editor plan activates them later. Nothing in W1–W5 touches them.

### Task W0.1: Lift the editor-shell file set

**Files:**
- Create (copied verbatim from the branch): `apps/frontend/src/features/chat-shell/components/{web-inspector,image-inspector,inspector-primitives,artifact-header,artifact-tabs,artifact-action-menu,artifact-share-menu,image-export-menu,chat-shell-icon}.tsx`
- Create: `apps/frontend/src/features/chat-shell/hooks/{use-inspector-controller,use-artifact-tab-controller,use-artifact-action-menu-controller,use-artifact-sharing-controller,use-artifact-toolbar-controller,use-image-export-controller}.ts`
- Create: `apps/frontend/src/features/chat-shell/model/{chat-shell,artifact-actions,artifact-sharing,image-export}.ts` + their `.test.ts` files
- Create: `apps/frontend/public/icons/chat-shell/` — ONLY the ~45 referenced assets (15 root glyphs per `CHAT_SHELL_ICON_GEOMETRY`, `inspector/shared/*.svg` (~29), `inspector/web/image-preview.png`); do NOT copy the ~46 unreferenced dirs (`action-menu/`, `editor/`, `export-menu/`, `shell/`, `inspector/exported/`)

**Interfaces:**
- Produces: the component set later tasks mount; `ChatShellInspectorSelection`, `ChatShellOpenArtifact`, `CHAT_SHELL_INSPECTOR_SELECTIONS` from `model/chat-shell.ts` (trim `ChatShellInitialState` to what the artifact routes need).

- [ ] Copy the files; run existing co-located model tests (`npx vitest run src/features/chat-shell`) — they must pass unchanged.
- [ ] Verify `@base-ui/react` is in `apps/frontend/package.json` (it is on both sides per the drift report — assert, don't assume version compat: `npm ls @base-ui/react`).
- [ ] `npm run lint && npm run build` green.
- [ ] Commit: `feat(part4): lift the chat-shell editor component set verbatim`.

### Task W0.2: Bisect `chat-shell.module.css` into an editor-only stylesheet

**Files:**
- Create: `apps/frontend/src/features/chat-shell/components/chat-shell.module.css` (editor slice ~2,200 of 2,941 lines)

Per the bifurcation inventory's line map: keep 302–2890 editor ranges (tabs 302–530, header 531–551, srOnly 552–562, share/export 618–1304, action menus 1305–1557 **minus** the B-only `.chatSessionMenu` block at 1429–1440, device/zoom/stage 1558–1698, inspector 1699–2865, keyframes 2867–2890) plus `.inspectorDock`/`.chatBody` (241–268), the responsive/reduced-motion tail (2891–2941, trimmed to editor selectors), and a **duplicated copy of the shared button-reset rule (85–120) narrowed to editor selectors only**. Drop the dead blocks (`.imageEditorToolbar`, `.editorTool*`, `.galleryEmptyStage`, `.chatTitleButton*`, `.smallIconButton`, `.artifactTab` single). Preserve the `--chat-shell-*` alias block (lines 2–8) and remap it onto our `globals.css` `--clue-ds-*` tokens; audit all ~40 consumed `--clue-ds-*` vars exist in our frontend's design system, adding missing ones to the alias block only.

- [ ] Bisect per the line map; grep every lifted `.tsx` for `styles.` references and assert 1:1 class coverage (`grep -oP 'styles\.\w+' | sort -u` vs class list in the CSS).
- [ ] `npm run design-system:build && npm run build` green.
- [ ] Commit: `feat(part4): editor-only stylesheet bisected from chat-shell.module.css`.

### Task W0.3: Sever Gallery + write the editor-only controller

**Files:**
- Modify: `apps/frontend/src/features/chat-shell/components/artifact-stage.tsx` — remove the `ProjectGallery` import and the gallery else-branch; render only when an artifact is active; add `galleryTabVisible={false}` gating to `ArtifactTabs` usage (the fixed Gallery tab and its `onOpenGallery` become prop-gated, default off).
- Create: `apps/frontend/src/features/chat-shell/hooks/use-editor-shell-controller.ts` (~120 lines): the editor half of the branch's `use-chat-shell-controller.ts` — `openArtifacts`, `activeArtifactId`, `activateArtifact`, `openArtifact`, `closeArtifact` (fallback when last tab closes: stay on the artifact route empty state, NOT gallery), `setArtifactTitleFor`, `artifactMaximized` + Escape listener, `editing`, `inspectorSelection`. Delete the `createInitialOpenArtifacts` default-tab fabrication (contract: the artifact list is the source of tab truth).
- Test: `apps/frontend/src/features/chat-shell/hooks/use-editor-shell-controller.test.ts` — tab activate/close-adjacency semantics (close active → next, last → previous), rename, maximize toggle, editing toggle.

- [ ] Write the failing controller tests first (`npx vitest run …use-editor-shell-controller`), implement, pass.
- [ ] Commit: `feat(part4): editor-only shell controller; gallery severed per ruling`.

### Task W0.4: Mount at the artifact routes

**Files:**
- Modify: `apps/frontend/src/app/(protected)/projects/[projectId]/artifacts/[artifactId]/page.tsx` — replace the `notFound()` stub with the editor shell mount (full-width presentation), behind the protected layout; until W1 lands data, render the shell with an empty-state artifact (geometry stable, "Empty web output canvas" div — exactly the dummy's own empty state).
- Create: `apps/frontend/src/features/chat-shell/components/editor-surface.tsx` — the composition the branch's `chat-shell-view.tsx` provided, re-authored for our shell: artifact rail (tabs+header+stage) full-width at the artifact route; the inspector dock replaces the conversation column in split view (deferred to the chat-flow integration — this plan mounts full-width only; note it in the file header). **[SUPERSEDED 2026-08-17 by ruling R2 / Phase R:** the split-view pane state is `?surface=web|ad` + `?edit=` + `?selection=` on the chats route (`/projects/{id}/chats/{chatId}`), with artifact identity in the path (`/artifacts/{artifactId}`); the `?artifact=` param named here was never built and must not be introduced — see the canonical-routes section of `apps/frontend/docs/api-contracts/projects.md`.**]**

- [ ] `npm run build`; manually verify in the browser (`/projects/<any>/artifacts/<any>` renders the shell empty state pixel-matching the dummy; use the reference PNGs under the branch's `public/figma/chat-shell/reference/`).
- [ ] Commit: `feat(part4): editor shell mounted at the project artifact route`.

### Task W0.5: Lift the gallery module as presentation-only chrome (founder amendment, 2026-08-17)

Founder amendment after W0.4: the gallery module IS lifted after all — as **dummy chrome, zero
functionality** — because severing the Gallery tab put the shell below the visual-parity
baseline (the tab and gallery view are part of the final design). Ratified decisions:
- **Decision 1:** closing the last artifact tab falls back to the **gallery** surface
  (restores the original semantics; supersedes the W0.3 stay-on-empty-state ruling).
- **Decision 2:** the lifted gallery is the intended future gallery and will REPLACE the
  existing `/projects/{id}/gallery` screen — but the route swap is **deferred** until the
  gallery gets real data (post-W1.3); swapping now would regress a data-wired screen to an
  empty dummy. Recorded as follow-on work.
- **Dummy means empty, not fake:** the gallery renders with an empty artifact list (its
  designed `galleryEmptyStage` state). No fixture artifacts appear in the authenticated app.

**Files:**
- Modify: `apps/frontend/src/features/projects/model/project-workspace.ts` — additive,
  backward-compatible extension: `GalleryCollateralTypeSchema`, `GallerySizeCategorySchema`,
  `ProjectArtifactSizeSchema`, and the branch's seven optional `ProjectArtifact` fields
  (`accountId`, `accountName`, `collateralType`, `createdAt`, `lastViewedAt`, `size`,
  `updatedAt`). All optional — existing parsers/fixtures unaffected.
- Create (verbatim): `apps/frontend/src/features/gallery/` — components
  (`project-gallery`, `project-gallery-view`, `gallery-toolbar`, `gallery-artifact-card`,
  `project-gallery.module.css`), `hooks/use-project-gallery-controller.ts`,
  `model/project-gallery.ts` + test.
- Create: `apps/frontend/src/features/gallery/model/project-gallery.test.fixture.ts` — the
  branch fixture's 7 artifact entries, extracted verbatim; the test's fixture import repoints
  here (one-line documented deviation: our `project-workspace.fixture.ts` has
  `artifacts: []` and stays untouched).
- Modify: `chat-shell.module.css` — restore the two `galleryEmptyStage` blocks excised in
  W0.2 (un-narrow the grouped `.outputStage, .galleryEmptyStage` rule; restore the
  standalone block).
- Modify: `use-editor-shell-controller.ts` — minimal `surface: "artifact" | "gallery"`
  state returns: `open-gallery` action; activate/open → artifact; close-last-tab → gallery
  (Decision 1). Tests updated first (TDD).
- Modify: `artifact-stage.tsx` — gallery else-branch restored (renders `ProjectGallery`
  with the passed artifact list — empty for now), `galleryTabVisible` flipped on,
  `surface` threaded from the controller again.
- Modify: `editor-surface.tsx` — passes `artifacts={[]}` (honest empty) and the gallery
  callbacks.

- [ ] Model extension + gallery lift + fixture; gallery model tests green.
- [ ] Controller surface TDD (close-last-tab → gallery; open-gallery; activate returns to artifact).
- [ ] Browser-verify: Gallery tab present (matches `artifact-tabs.png` reference exactly now), click → gallery empty state, close last tab → gallery, activate tab → artifact surface.
- [ ] Commit: `feat(part4): gallery module lifted as presentation-only chrome per founder amendment`.

**Phase W0 exit gate:** the dummy editor shell renders inside our authenticated app, visually identical to the co-founder's build (reference-PNG comparison), no data wired, `npm` gate green. *(Amended by W0.5: "visually identical" now includes the Gallery tab and empty gallery surface.)*

---

## Phase W1 — Engine extraction + hosting foundation

### Task W1.1: Extract the web engine slice as a package

**Files:**
- Create: `apps/frontend/src/features/design-editor/engine/` — copied, import-adjusted modules from `subsystems/clue-design/apps/editor/src/engine/`: `webDocuments.ts`, `webClassFacets.ts`, `webBridge.ts`, `webRichText.ts`, plus a NEW `config.ts` replacing `editorConfig.ts`:

```ts
export interface DesignEditorConfig {
  apiBase: string;            // "/api/clue/design" (BFF prefix), never a FastAPI origin
  fetchImpl?: typeof fetch;   // injected; BFF cookies ride along, no X-Workspace-Id in browser
}
```

The BFF injects `X-Workspace-Id` server-side from the session (pattern: `apps/frontend/src/auth/authenticated-backend.ts`). Every module-level `lumenFetch`/`NEXT_PUBLIC_*` read is replaced by config passed at construction. No `process.env` reads in the copied modules (add a lint assertion test that greps for it).

**Interfaces:**
- Produces: `fetchWebDocument(config, id)`, `applyWebOperations(config, docId, ops, baseVersion, intent)`, `renderWebDocument(config, id, mode)`, the facet API (`parseFacet`, `setFacet`, per-facet families), `WebNode`, `WebSelection`, `WebOperation` types — signatures preserved from the source modules except the added leading `config`.

- [ ] Copy + adjust; port the engine's co-located web tests (`webClassFacets`, `webDocuments` unit tests) into `apps/frontend`; all green under vitest.
- [ ] Write the no-`process.env` guard test.
- [ ] Commit: `feat(part4): web engine slice extracted behind injected config`.

### Task W1.2: BFF route for the design API

**Files:**
- Create: `apps/frontend/src/app/api/clue/design/[...path]/route.ts` — authenticated proxy to the design API (`LUMEN_API_BASE_URL` env, server-side only), stamping `X-Workspace-Id` from the platform session; follow the existing `/api/clue/[...path]/route.ts` proxy pattern exactly (auth, error envelope, no caching).
- Test: `apps/frontend/src/app/api/clue/design/route.test.ts` — unauthenticated → 401; authenticated forwards with workspace header; design-API 4xx passes through.

- [ ] TDD per the existing proxy's test pattern; green; commit: `feat(part4): authenticated BFF proxy for the design API`.

### Task W1.3: Artifact → design-document read seam

The artifact page stub's blocker ("no project-artifact read contract"). Minimal v1: resolve `{projectId, artifactId}` → `{kind:"web", documentId, title, status}`.

**Files:**
- Create (backend): a read-only endpoint on the platform API surface (composition root `platform/api/clue_api/`) that maps a platform artifact id to its design document — **contract-gap review required with the founder if no such linkage row exists yet**; if design documents are not yet registered as platform artifacts, the v1 seam is `documentId == artifactId` behind a typed resolver so the URL shape survives the later linkage.
- Create (frontend): `apps/frontend/src/features/design-editor/data/artifact.repository.ts` + Zod `model/artifact.ts` (`ChatShellArtifact` shape from the contract doc: `{id, projectId, kind, title, currentVersionId, status, capabilities}`), fixture + HTTP adapters per the repo-seam convention.
- Test: repository tests against fixture adapter; HTTP adapter against the BFF route with a mocked backend.

- [ ] Implement TDD; commit: `feat(part4): artifact→document read seam (v1)`.

### Task W1.4: Vendor asset hosting

**Files:**
- Create: `apps/frontend/scripts/copy-design-vendor.mjs` — copies `@tailwindcss/browser` dist → `apps/frontend/public/vendor/tailwind-browser.js` (closing the upstream build gap: no script produces this file anywhere today) — wired into `prebuild`/`predev`.
- Note: wasm/canvaskit/fonts are NOT needed for the web editor (iframe renderer); explicitly out of scope here (ad-editor plan owns them). `web-rich-text-runtime.js` is injected by the design API into the srcdoc — served API-side, nothing to host here; verify that assumption with one render smoke test in W2.

- [ ] Script + `package.json` wiring; `npm run build` green; commit: `feat(part4): vendor asset pipeline for the web preview`.

**Phase W1 exit gate:** from an authenticated session, the BFF can fetch a real web document and its render HTML end-to-end (proved by repository integration tests); zero direct-to-FastAPI calls from browser code (grep guard test).

---

## Phase W2 — Read path (real render + hydrated selection)

### Task W2.1: Real render in the artifact stage

Mount the sandboxed `srcdoc` iframe (per `WebEditorApp.tsx:979-1036` semantics: `sandbox="allow-scripts"`, per-render nonce, loading/ready/error/empty states) inside the dummy's flush `.webCanvas` viewport. **Change vs source**: the stage must be an unbounded scroll container — drop the dummy's fixed `aspect-ratio:1448/1086` letterbox (this is a rendering-correctness fix, not a visual redesign; the dummy doc itself says the backend owns the page document inside the stable viewport).

- Files: `apps/frontend/src/features/design-editor/components/web-artifact-canvas.tsx`; modify `artifact-stage.tssx` empty-state branch to mount it when a document loads.
- [ ] Browser-verify: open a real seeded web document → the page renders in the shell. Commit.

### Task W2.2: Selection bridge + inspector hydration

Port the bridge listener (`useWebBridgeSelection` semantics: `lumen-web-bridge` postMessage channel, source-window + nonce validation) → selection state `{node: WebNode, nodeInfo: WebSelection}`.

Build the **hydration adapter** (pure, heavily unit-tested — this file IS the mapping table §1):

```ts
// features/design-editor/adapter/hydrate.ts
export function hydrateInspectorState(node: WebNode, classes: string): Partial<InspectorState>
// kind → schema: text→text, image→image, button→button, icon→icon(layout-only),
// container→container, section→section, root→canvas; embed/component→layout-only fallback (§5)
// facet parses: textColor/bgColor token → ColorControl theme value; textSize ramp → {xs:"12",…,2xl:"24",3xl:"32"};
// fontWeight → {normal:"Regular",medium:"Medium",semibold:"Semi Bold",bold:"Bold"};
// textAlign → horizontalAlignment; display → {flex:"Flex",grid:"Grid",hidden:"Hide"};
// direction/gap/flexWrap → section fields; paddingX/paddingY → the two padding boxes;
// objectFit → {contain:"Fit",cover:"Fill",fill:"Stretch"}; radius facet → radius fields;
// button variant → {primary:"Primary",secondary:"Secondary",ghost:"Transparent"};
// image href/new_tab, button href/new_tab → link fields.
```

- [ ] Test-first with one fixture per schema (real `WebNode` JSON snapshots harvested from a seeded doc); wire `useInspectorController` to accept hydrated initial state (the seam the dummy doc names: "hydrated from an InspectorSelection"). Commit per schema-fixture batch.

### Task W2.3: Real layer tree (depth-capped)

Replace the fixture trees: build rows from the document node hierarchy (names, kind→icon map, selection wiring), **cap displayed nesting at depth 1** (ruling 41); selecting a row sends bridge `selectNode`.

- [ ] Unit tests: tree-building from a nested fixture doc (cap, kind icons, active row). Browser-verify selection round-trip both directions (canvas click ↔ layer row). Commit.

**Phase W2 exit gate (founder demo):** click any element on a real rendered page → the correct schema opens with that element's real values; inert/hidden partitions visibly correct per contract §2/§3. **PASSED — founder sign-off 2026-08-18.** The W2.3 editing-dock composition is ratified with it: R6 stands as designed (inspector takes the conversation column; Edit-only entry; send-dismisses-dock on the chat screen — full ruling recorded at R6 in the Phase-C plan, 2026-08-18).

---

## Phase W3 — First write flow: text schema

### Task W3.1: Event seam grows addressing

Extend `dispatchInspectorEvent` detail with `{selectionId, artifactId, documentVersion}` (the contract-doc amendment; additive — presentation components pass through what the controller holds).

### Task W3.2: The write adapter + edit discipline

```ts
// features/design-editor/adapter/apply.ts
export function inspectorChangeToOperation(detail, node): WebOperation | null
// text: fontSize→textSize facet set; fontWeight; textColor(token); horizontalAlignment→textAlign;
// padding.x/y → paddingX/paddingY (nearest SPACING_STEP); variant select → set_node_props text variant;
// lineSpacing → lineHeight facet.
```

Port `useWebManualEdits` semantics exactly: one in-flight mutation (`busy`), `base_version` on every apply, 409 → quiet reload + info note, 422 → first diagnostic inline (the dummy's existing note/error slots in the inspector header — no new UI). Debounce free-text inputs on blur/Enter commit (the dummy's own commit model).

- [ ] TDD the adapter per control; browser-verify: edit typography on a real page, reload → persisted. Commit per control group.

### Task W3.3: Save-failure micro-decision ⚠️ FOUNDER GATE — **DECIDED 2026-08-18**

**Founder ruling: inline only.** The save-failure surface is the existing red line under the
inspector header (the W3.2 floor) — no additional UI. Accepted trade-off, stated with the
ruling: strict visual minimalism is preserved, at the cost that a failure can be missed or
become invisible when the inspector closes. Revisiting that trade-off is a new ruling (the
contract's §7 item 5 keeps the other failure surfaces — version-refused, publish-failure —
open for their own flows).

### Task W3.4: Undo/redo wired to the engine (founder addition, 2026-08-18)

Added by founder order once W3's writes were sequenced: live writes with a visibly inert
Undo/Redo in the action menu reads as broken, not unbuilt — so the wiring ships with the first
write flow. Everything below the UI already exists; this is wiring, not construction:

- The dummy's artifact action menu ships **Undo ⌘Z / Redo ⇧⌘Z** (lifted W0.1, inert since).
  Bind those two items — and their keyboard shortcuts — to the extracted engine's web
  undo/redo call (`engine/webDocuments.ts` `path: "undo" | "redo"` →
  `POST /documents/{id}/web/undo|redo` via the BFF).
- `LoadedWebDocument.undoDepth`/`redoDepth` drive the two items' disabled states (the same
  contract the source topbar used); refresh the document + re-render after a completed
  undo/redo (the returned version is the new `base_version`).
- Same edit discipline as W3.2: one in-flight mutation, quiet reload on 409.
- No new UI anywhere — the menu items and shortcuts are the dummy's own.
- Scope note: this is the *web editor document* undo stack (engine-owned, server-side). It is
  NOT a general chrome/undo system; the chrome flows (versions, export, share) keep their own
  future contracts.

- [ ] Wire + disabled states; browser-verify: edit typography (W3.2), undo → change reverts and
  persists reverted on reload, redo → reapplies; menu items disable at empty stacks. Commit.

**Phase W3 exit gate:** text schema fully live per contract §1 rows 4–7 + §2 additions (variant, line-spacing); undo/redo live against real edits (W3.4); founder browser sign-off. **PASSED — founder sign-off 2026-08-18** (known caveat carried into W4, on the record: the color popover's theme list is still the fixture palette; real theme-token options ride W4's color flow).

---

## Phase W4 — Remaining schemas + the radius facet

> **W4 fan-out rulings (founder, 2026-08-18 — binding):**
> **(F1) Three-lane split approved.** Lane A (trunk workspace): W4.4 → W4.5 → W4.9 → W4.6.
> Lane B (worktree `feature/w4-lane-b-image-button`): W4.2 → W4.3. Lane C (worktree
> `feature/w4-lane-c-richtext-components`): W4.8 → W4.7. W4.10 on the trunk after both
> merges (B merges first, C rebases then merges). Lane briefs:
> `docs/superpowers/plans/2026-08-18-w4-lane-b-brief.md` / `…-w4-lane-c-brief.md`.
> **(F2) "Radius (all)" CLEARS per-corner overrides** — an all-corners radius write also
> clears the four corner facets (adapter-level, each facet clearing only its own family;
> the §4 facet law is untouched; NO engine change). Owned by W4.2.
> **(F3) Theme-tab curation: hide only the technical `palette-*` ramp tokens** (~28 of 52
> remain). Applied on the trunk in the W4.0 mapper before the lanes forked, so every
> color-consuming task inherits it.
> Pre-existing substrate both lanes consume: the W4.1 radius facets (both engine copies)
> and the W4.0 theme-token feed (`ThemeColorsContext` + `buildThemeColorOptions`).

One task per schema, same TDD adapter pattern as W3 (hydrate fixture → failing adapter test → wire → browser-verify → commit). **Each schema task also applies that schema's contract-§2 deltas to its `web-inspector.tsx` schema component** — text: hide vertical alignment, padding 4→2 (in W3); section: hide Link-to; every schema: padding 4→2 where present — these are the only permitted UI edits and each cites its ruling number in the commit message:

- **W4.1 Radius facet (engine, contract §8):** add `radiusFacet` + four corner facets to `subsystems/clue-design/apps/editor/src/engine/webClassFacets.ts` (`rounded`, `rounded-tl/tr/bl/br` families, arbitrary `[Npx]` values), mirrored into the extracted copy; parse/set unit tests both places; the "rewrite only own tokens" facet law holds.
- **W4.2 Image:** link/new-tab props; Replace = file input → asset upload (`POST /assets` via BFF) → `upsert_asset`+`replace_asset` ops; Mode (minus Tile); radius via W4.1.
- **W4.3 Button:** link props; variant map (minus Critical); token color buttons → token popover (reuse ColorControl Theme tab pattern) → `bg-`/`text-` facets.
- **W4.4 Container & Section:** style tokens; display segmented; section direction/gap/wrap (gap coerced to nearest step); **props-preservation regression test: a style edit on a section round-trips `tag`/`anchor_id` byte-identically** (contract §4 guarantee).
- **W4.5 Canvas:** background token on page root.
- **W4.6 Icon:** layout-only rendering path (hide icon sections per 18b).
- **W4.7 Custom-component props form:** port `WebCustomComponentInspector`'s schema-driven form section (checkbox/select/number/text per manifest `props_schema` → `set_custom_component_props`); status/republish/Edit-with-AI chrome stays OUT (contract 34 scope).
- **W4.8 Conditional Link-to (rich-text ranges):** rich-text session port (double-click → Lexical session, toolbar as-is per ruling 24); Link-to section visibility bound to live range selection; link edits through the toolbar's validated href path.
- **W4.9 Visibility eye:** wire to display facet `hidden`; lock stays inert (39).
- **W4.10 Node-op keyboard audit (ruling 29):** verify what keyboard node operations the web
  editor actually has (the scene editor's shortcut map does not apply to the web stack). Wire
  nothing new; if delete/duplicate/reorder have no keyboard path on web, record that in the
  contract's future-work register (§7) rather than inventing UI — per the minimalism rule.
  **DONE 2026-08-19 — recorded as contract §7 item 8:** the web editor has NO keyboard path
  for any node operation, in our stack or upstream (`WebEditorApp` carries only ⌘Z/⇧⌘Z; the
  bridge only rich-text Escape/⌘-Enter + Escape-clears-selection; the scene editor's
  Delete/Backspace does not apply); the engine op vocabulary (`InsertNode`/`RemoveNode`/
  `MoveNode`) is fully present, so the substrate needs zero work. Nothing wired, per rule.

**Phase W4 exit gate:** every §1 contract row demonstrably live; every §3 row demonstrably inert; every §2 hidden row absent; schemas fan-out-parallelizable after W4.1 lands. **PASSED 2026-08-19** — consolidated browser sweep on the fully-merged union (all three lanes + chat-flow): §1 **22/22 live** (row 12 presence-only per its lane-B full-upload proof; row 34 proven on the lane-C seeded doc, the trunk doc carrying no custom component), §2 **6/6 absent**, §3 **5/5 provably inert** (engine version unchanged), chat-route union spot-check green; both test documents restored node-identical (version counters advance by design). Evidence: `.playwright-mcp/w4gate-*.png` + the sweep report; fan-out-parallelizability was proven by the three lanes themselves (independent worktrees, mechanical merges). The founder-facing acceptance walk remains W5's.

---

## Phase W5 — Acceptance audit

- [x] **W5.1 Contract audit:** walk all 42 items against the running app in the browser; produce `docs/specs/website-editor-integration/acceptance-record.md` (item → observed state → pass/fail), fixing fails before recording. **DONE 2026-08-19 — 41/41 substantive PASS.** One defect surfaced and fixed before recording (`15d7a6c8`: §5 fallback kinds — embeds/components — now render Layout-only via the mapper's `layoutOnly` flag, which the view had never consumed).
- [x] **W5.2 Visual parity pass:** side-by-side against the dummy build + reference PNGs for every schema and chrome state; founder review. **FOUNDER-WAIVED 2026-08-19** (extensive personal manual testing; "nothing broke visual parity drastically"). The completed comparison pass (13 states vs reference PNGs + a live dummy-HEAD baseline) is registered in the acceptance record: 11/13 parity, reference-PNG set found stale (3 apparent diffs are reference staleness), findings D1–D4 registered as founder-waived polish candidates (D1 — the color popover overflows the viewport with no scroll — is functional, flagged for a ruling).
- [x] **W5.3 Gates:** `apps/frontend` npm gate + root `make check` green; `_memory/` close-out note; final commit. **DONE 2026-08-19** — frontend design-system:build/test 772-772/lint/build all green; `make check` carries only the 5 pre-existing reds recorded at the Part-III merge (other lanes'; zero backend paths in W0–W5's range).

**Phase W5 complete 2026-08-19 — awaiting founder sign-off on the acceptance record.**

**Done means:** a marketer opens a web artifact in the platform shell, sees the co-founder's exact UI, edits text/image/button/container/section/canvas properties that persist through the real engine, and everything the contract says is inert/hidden/invisible behaves exactly that way.

---

## Sequencing & parallelism

W0 → W1 → W2 → W3 strictly sequential (each proves the next's substrate). W4.1 first within W4, then W4.2–W4.9 parallelizable 2–3 at a time (separate worktrees per the repo's parallel-slice pattern). W5 last. Founder gates: W2 exit demo, W3.3 micro-decision, W5.2 parity review. Estimated 16–23 working days total per the phase-wise timeline already approved.
