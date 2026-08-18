# 2026-08-17 — Phase W0 COMPLETE: Shell lift W0.1–W0.4 (website-editor integration)

Branch: `integration/frontend-design-part-iv-v2` (istanbul workspace). Plan:
`docs/superpowers/plans/2026-08-17-website-editor-integration.md`; binding contract:
`docs/specs/website-editor-integration/web-inspector-mapping-contract.md`.

## Done

Task W0.1 complete — commit `b2e974b7` (`feat(part4): lift the chat-shell editor component set verbatim`), 69 files, 4,355 insertions, all byte-identical to source.

- Source: fresh `--depth 1` clone of `clue-hq/clue-frontend@codex/chat-shell` at `/tmp/clue-frontend-chat-shell` (temp; re-clone for W0.2 if gone).
- Copied into `apps/frontend/src/features/chat-shell/`: 9 components (web-inspector, image-inspector, inspector-primitives, artifact-header, artifact-tabs, artifact-action-menu, artifact-share-menu, image-export-menu, chat-shell-icon), 6 hooks, 4 model files + 3 co-located `.test.ts` (`image-export.ts` has no test file upstream — the plan's "~their tests" covers only the 3 that exist).
- Assets `apps/frontend/public/icons/chat-shell/`: exactly 47 — 15 root glyphs (matches `CHAT_SHELL_ICON_GEOMETRY` 1:1), all 31 `inspector/shared/*.svg` (plan estimated ~29; actual glob is 31, all reachable via the dynamic `${INSPECTOR_ICON_ROOT}/shared/${name}.svg` path in inspector-primitives), and `inspector/web/image-preview.png`. Excluded per plan: `action-menu/`, `editor/`, `export-menu/`, `shell/`, `inspector/exported/`, and the other 4 files in `inspector/web/` (only image-preview.png is referenced).
- Verbatim-ness verified with `cmp`/`diff` per file (22 source + 47 assets).

## Verification

- Co-located tests: 6/6 pass unchanged. **Plan correction:** the plan says `npx vitest run` but neither repo has vitest — both use `node:test` via `tsx --test` (`npm test` = `find src -name '*.test.ts' | xargs tsx --test`). Ran with the repo's real runner.
- `@base-ui/react@1.6.0` installed, same `^1.6.0` pin both sides. Fresh workspace had **no node_modules** — ran `npm ci` first.
- `npm run design-system:build` ✓, `npm run lint` ✓, `npm run build` ✓ (build tolerates the not-yet-existing `chat-shell.module.css` import because nothing mounts the components yet and CSS-module imports are ambient-typed; the stylesheet is W0.2's deliverable — expected, per plan sequencing).

## Import self-containment (checked before copy)

The 22-file set imports only: react, next/image, lucide-react, @base-ui/react/{popover,select}, each other, and `./chat-shell.module.css` (W0.2). Zero repository/fetch/transport imports — confirms the bifurcation report's liftability claim. `artifact-stage.tsx` deliberately NOT copied in W0.1 (it's W0.3's modify-target; it carries the one Gallery cross-import).

## W0.2 done — commit `61eaadc5` (editor-only stylesheet)

2,667-line editor slice assembled from the source's 2,941 lines via `sed` range extraction
(deterministic; every output line verbatim from source except six known rewrites: the alias
carrier, three narrowed selectors, the `.outputStage {` splice, the trimmed tail).

**Four line-map corrections vs the plan's bifurcation map** (found by the styles.* coverage
check, verified in source):
1. `.iconButtonPressed` (source 237–239) + the `.iconButton` base (215–227), hover (137–143),
   and `:active` (232–235) rules live in the *dropped* chat region 121–240 but style kept
   editor classes — included, narrowed to editor selectors only (`.smallIconButton`,
   `.chatTitleButton` dropped from the groups).
2. `.toolbarMenuAnchor` (596–599) and `.toolbarMenu` (601–616) live in the dropped
   editor-toolbar gap 563–617 but are live, referenced classes — included verbatim.
3. The dead `@container (max-width: 720px)` block styling only `.imageEditorToolbar`/
   `.editorToolButton` (source 1328–1340) sat *inside* the share/export keep range — excised.
4. `.imageEditorToolbar` at 545–550 sits inside the "header 531–551" range — excised
   (header keep = 531–544).

**Alias carrier decision:** the `--chat-shell-*` block (source lines 2–8, verbatim) is defined
on `.artifactWorkspace, .chatBody, .inspectorDock` — the editor roots — because the source
carried it on the chat-level `.shell` grid, which is not lifted. W0.4's editor-surface must
mount inside one of those three classes for the vars to resolve.

**Known upstream defect (kept for verbatim parity):** `styles.inspectorSectionCompact` is
referenced in `inspector-primitives.tsx:171` but defined NOWHERE in the source repo — the
dummy build has the same no-op behavior. Flag to co-founder; do not "fix" without a ruling.

**Coverage state:** all other styles.* refs from the 9 lifted components resolve 1:1;
CSS classes not referenced by the lifted set are exactly the W0.3/W0.4-awaited stage/view set
(`artifactWorkspace, chatBody, inspectorDock, outputStage, imageCanvas, imageOutputStage,
webCanvas, webOutputStage, shellPanelOpen`). All 35 consumed `--clue-ds-*` tokens exist in
`packages/design-system/generated/tokens.css` + `globals.css`; zero alias-block additions.
`galleryTab*` classes KEPT (referenced by lifted artifact-tabs.tsx; prop-gated off in W0.3).
Gates green: design-system:build ✓ lint ✓ build ✓.

## W0.3 done — commit `a5cd7fcd` (editor-only controller, gallery severed)

- `hooks/use-editor-shell-controller.ts`: pure exported reducer (`editorShellReducer` +
  `createInitialEditorShellState` + `EditorShellState`/`EditorShellAction`) wrapped by a thin
  `useReducer` hook (`useEditorShellController(initial: EditorShellInitialState)`).
  **Testing pattern decision:** no React renderer exists on either side (both repos test with
  `tsx --test`/node:test only), so hook semantics live in the pure reducer and the 10 tests in
  `use-editor-shell-controller.test.ts` drive it directly. Source semantics preserved exactly
  (close active → `remaining[closedIndex] ?? remaining[closedIndex-1] ?? null`; open dedupes +
  activates + editing=false + selection=canvas; rename trims/ignores-empty; set-editing(true)
  resets selection to canvas; Escape restores maximize via document keydown effect).
  **Dropped by design:** the `surface` chat/gallery machine (artifact route is always the
  artifact surface — closing the last tab leaves `activeArtifactId: null` empty state, never
  gallery) and `createInitialOpenArtifacts` fabrication (artifact list = source of tab truth).
  `EditorShellInitialState` is the "trimmed ChatShellInitialState" realized as a new narrow
  type — the verbatim model file stays untouched.
- `components/artifact-stage.tsx` (new here; branch source modified): no ProjectGallery import,
  no gallery else-branch (`showingArtifact = artifactKind !== null`), no
  artifacts/projectTitle/surface/onOpenGallery* props; passes `galleryTabVisible={false}` and
  hardcodes `surface="artifact"` to ArtifactTabs. Keeps `onTogglePanel` pass-through (W0.4
  decides its meaning at the full-width route).
- `components/artifact-tabs.tsx` (only non-verbatim edit to a W0.1 file): `galleryTabVisible`
  prop default **false** gating the gallery segment; `onOpenGallery` optional. Everything else
  byte-identical.
- Gates: 16/16 chat-shell tests, lint ✓, build ✓.

## W0.4 done — commit `857f4bbc` (mounted at the artifact route). **Phase W0 exit gate met.**

- `components/editor-surface.tsx`: full-width re-authoring of the branch's chat-shell-view
  (no chat pane). **Load-bearing detail:** the wrapper carries `styles.shellPanelOpen` —
  `.artifactWorkspace` is born `opacity: 0` (entry transition) and only the lifted
  `.shellPanelOpen .artifactWorkspace` rule makes it visible. Wrapper is
  `grid h-full min-h-0 w-full grid-cols-1` (Tailwind), stage stretches to fill.
  `?artifact=` split view + inspector dock deferred to chat-flow integration (noted in file
  header); full width shows no inspector, matching the dummy's maximized presentation.
  "Close artifact panel" tab action is a deliberate no-op (no chat pane to return to; wiring
  is a split-view decision).
- Page mounts the dummy's empty-state web artifact keyed to the route's `artifactId`
  (`title: "Web output"` — the source default), until W1 lands the read seam.
- **Dev-mode fact:** auth is env-gated (`CLUE_AUTH_ENABLED`); no `.env` in the workspace →
  protected layout renders with null session → route directly viewable at
  `localhost:3000/projects/<any>/artifacts/<any>`. Dev server: `npm run dev` in apps/frontend.
- **Browser-verified** (gstack browse, headless Chromium, 1600x1000): zero console errors;
  all 47 icon assets 200; Edit toggles pressed/knockout state + `data-editing`; maximize
  toggles + Escape restores; close-last-tab → `tabs:0, kind:none`, workspace stays mounted,
  no gallery anywhere. Screenshots: `/tmp/w04-artifact-route.png`, `/tmp/w04-final-empty-state.png`.
- **Reference-PNG caveat for W5's parity pass:** `reference/web-editor-header.png` actually
  depicts the AD-kind header — its Export button and center URL field are `kind === "ad"`
  branches of the verbatim artifact-header component; the web header (title + device + Edit +
  Share) matches by byte-verbatim construction. `artifact-tabs.png` matches ours minus the
  founder-ordered Gallery-tab severance. Don't re-litigate these at W5.

## W0.5 done — commit `38942d3b` (gallery lifted as presentation-only chrome; founder amendment)

Founder amended the gallery-severed ruling after W0.4: the gallery module IS lifted, as dummy
chrome, to restore full visual parity with the final design. **Two ratified decisions:**
1. Close-last-artifact-tab → **gallery** surface (original semantics restored; supersedes the
   W0.3 stay-on-empty ruling — do not resurrect the old ruling).
2. The lifted gallery is the intended REPLACEMENT for the existing `/projects/{id}/gallery`
   screen; **route swap deferred until the gallery gets real data (post-W1.3)** — swapping now
   would regress a data-wired screen to an empty dummy. This is recorded follow-on work.

Delivered: `features/gallery` verbatim (8 files); gallery-local test fixture (branch fixture's
7 artifact entries; our `project-workspace.fixture.ts` has `artifacts: []` and stays
untouched — the test's import repoint is the one sanctioned deviation); additive
`project-workspace.ts` model extension (3 gallery schemas + 7 optional `ProjectArtifact`
fields — full suite 323/323 green, nothing existing affected); `galleryEmptyStage` CSS blocks
restored; editor controller gains the `artifact|gallery` surface pair + `open-gallery` (12
reducer tests, TDD); stage/tabs/editor-surface wired with `artifacts={[]}` (dummy = EMPTY,
never fixture data in the authenticated app). Browser-verified: Gallery tab (tab strip now
matches `artifact-tabs.png` reference exactly), gallery empty state with full toolbar,
close-last-tab → gallery, zero console errors. Screenshots `/tmp/w05-*.png`.

Note: gstack tooling appended `.gstack/` to the repo `.gitignore` during the browse run —
left uncommitted for founder review.

## Phase W1 — engine + hosting foundation. COMPLETE (W1.1–W1.4).

W1.1–W1.3 executed in prior sessions (details in the "Implement Shell Lift" transcript):
- **W1.1** `054ef225` — web engine slice (`webDocuments`/`webClassFacets`/`webBridge`/
  `webRichText` + `config.ts`/`asset-types.ts`) in `features/design-editor/engine/`, behind
  injected `DesignEditorConfig` (`apiBaseUrl` kept over the plan's `apiBase` — signature
  preservation). 103 ported engine tests via a vitest-shim over node:test; `no-env-reads.test.ts`
  guard (engine dir greps clean of `process.env`/`NEXT_PUBLIC_`).
- **W1.2** `14cf7a94` — authenticated BFF proxy `/api/clue/design/[...path]`
  (`design-proxy-handler.ts`, testable-handler pattern): re-authorizes workspace via
  `authenticatedBackendContext`, stamps `X-Workspace-Id` server-side, drops spoofed browser
  headers, refuses dot-segments; `LUMEN_API_BASE_URL` server-only accessor in `auth/config.ts`.
- **W1.3** `3ea8f5c1` — artifact→document read seam v1. Contract-gap finding: design documents
  are NOT platform artifacts (only leg-level `design_leg.thread_id→document_id`, no project
  column); sanctioned fallback `documentId == artifactId` behind
  `GET /api/v1/projects/{id}/design-artifacts/{id}` (chat router, workspace-scoped fail-closed,
  real title/status/current_version via `clue_design.documents`; `web|scene`→`web|ad`).
  Frontend: `model/artifact.ts` (ChatShellArtifact + `documentId`), `data/artifact.repository.ts`
  fixture+HTTP adapters.

### W1.4 done — commit `43a373b5` (vendor asset pipeline; this session)

- `apps/frontend/scripts/copy-design-vendor.mjs` (house style of `sync-brand-assets.mjs`):
  `require.resolve("@tailwindcss/browser")` — the package **main IS the browser bundle**
  (`dist/index.global.js`, 282KB IIFE) — copied → `public/vendor/tailwind-browser.js`.
- `@tailwindcss/browser@^4.3.3` added to dependencies (**the upstream editor's own pin**;
  editor package.json line 28). Upstream gap confirmed before building: the design editor's
  `public/` dir doesn't exist in-tree and its prebuild copies only canvaskit/fonts/
  web-rich-text — `WebEditorApp.tsx:75` loads `/vendor/tailwind-browser.js`, and the agent
  runtime (`web_substrate.py:~3560`) inlines the same file with a graceful-absent fallback.
- Wired `prebuild` + `predev` in apps/frontend package.json; `/public/vendor/` gitignored
  (generated artifact, matching upstream's generated-public-assets discipline). Proven by
  deleting the dir and running `npm run build` — prebuild regenerates it.
- Gates: design-system:build ✓ lint ✓ build ✓ tests 443/443 ✓.
- Nothing references `/vendor/tailwind-browser.js` in our tree yet — **W2.1's srcdoc canvas
  is the consumer** (per WebEditorApp semantics); the W2 render smoke test must also verify
  the plan's assumption that `web-rich-text-runtime.js` is injected API-side (nothing to host).

**Phase W1 exit gate status:** BFF fetch of a real web document proven by W1.3's DB-gated
backend tests + repository/proxy tests; browser code has no FastAPI origin to call (engine
no-ambient-env guard + `LUMEN_API_BASE_URL` server-only + BFF-prefix `apiBaseUrl` contract).
The render-HTML-in-browser smoke is W2.1's opening move per the plan's own W1.4 note.

## Live authenticated browser run — 2026-08-18 (post-W1.4, real stack)

Founder-requested real-browser verification of W0+W1 on a fresh port pair (3030/3020 coexist).
**Launch recipe that works (all from repo root; `set -a; source .env; set +a` first):**
- Platform API 8030: `.venv/bin/python -m uvicorn clue_api.projections_main:app --host 127.0.0.1
  --port 8030` with `CLUE_AUTH_CLERK_AUTHORIZED_PARTIES` extended to include
  `http://localhost:3030` (shell env overrides .env for pydantic-settings).
- Design API 8010: `.venv/bin/python -m uvicorn lumen_api.main:app --host 127.0.0.1 --port 8010`
  with `CLUE_STORAGE_FS_ROOT=/tmp/lumen-dev-storage` (lumen_api IS importable from the root
  venv post-Part-II; same shared Postgres 55040/clue). **MANDATORY (latency, found 2026-08-18):
  also set `LUMEN_CORE_HELPER=<repo>/subsystems/clue-design/target/release/lumen-api-helper`
  (build once: `cargo build -p lumen-api-helper --release` in subsystems/clue-design, ~73s).
  Without it the API falls back to `cargo run` PER ENGINE CALL (~1.1s spawn each) — founder
  observed every edit taking ~2.5s (op POST 1512ms + render 965ms; engine work itself is
  ~8ms). With the helper: op POST ~366ms (engine 21ms + toolbelt durable journal 119ms +
  Postgres persist ~150ms), render ~147ms, total ~0.5s/edit. BFF overhead is only ~30-60ms/req
  (Next dev log: next.js 3-8ms, proxy.ts 5-11ms); the platform API (8030) is not on the design
  write path at all.**
- Frontend 3030: from apps/frontend, `npm run dev -- --port 3030` with shell overrides
  `CLUE_API_BASE_URL=http://127.0.0.1:8030 CLUE_APP_ORIGIN=http://localhost:3030
  LUMEN_API_BASE_URL=http://127.0.0.1:8010` (`.env.local` stays pinned to the 3020/8020 pair;
  Next lets shell env win). predev runs the W1.4 vendor copy automatically.
- **Auth in headless browse:** the provisioned platform user (`usr_8930c3…`, ws Insight Health
  `ws_8040294627e146ae93f753ec0d3e1726`, prj `prj_79aa603b3c3853898045e3cfa414e136`) maps via
  `auth_identity` to Clerk test-mode user `onboarding+clerk_test_20260814@example.com` —
  sign in through /onboarding/sign-in-email (creds recorded in the shell-lift transcript),
  second factor = Clerk test-mode fixed code `424242`, then select-workspace. Desktop-Chrome
  cookie import was a dead end (`__client_uat=0` — user's Chrome signed out of localhost).
- Seeded the first real web document via the design API:
  `POST :8010/documents {doc_kind:"web", title:"Insight Health homepage"}` with
  `X-Workspace-Id` → `doc_31126145a0aa4753920629ae323a301b`.

**Verified live (authenticated session):** artifact route renders the full shell (rail +
Gallery/Web-output tabs + header + empty canvas); gallery empty state with toolbar; Edit
toggles `data-editing`; Share card (slug field, publish, ZIP/PDF tiles); close-last-tab →
gallery fallback; `/vendor/tailwind-browser.js` 200 (W1.4); BFF design proxy
`GET /api/clue/design/documents/{id}` 200 real doc (W1.2); render
`…/web/render?mode=editor&runtime_src=%2Fvendor%2Ftailwind-browser.js` 200, HTML cites the
vendored runtime; W1.3 seam `GET /api/clue/api/v1/projects/{prj}/design-artifacts/{doc}` 200
exact wire shape (`documentId == artifactId`, real title/status). Zero console errors beyond
Clerk dev-keys warning. Screenshots `/tmp/w1-run-*.png`.
Quirk: browse `click @ref` on the tab-close button timed out under the share popover; a JS
`aria-label` click works. Complex multi-statement `$B js` exprs return empty — use
window-state two-step or simple exprs.

## Phase R+C lane merged in — 2026-08-18, merge commit `92de3c14`

Founder-ordered merge of `platform/comprehensive-account-contact-research` (missoula worktree)
into this branch. That lane forked at `83e30893` (so it already carried all of W0 incl. the
gallery) and added: Phase C chat chrome complete (`91c80755` — chats route renders the designed
chat shell around production chat; old workspace artifacts pane DELETED), home composer C-4,
chat header/session menu R5, artifact-route full-width fix under restored `.shellPanelOpen`
grid (`de668a88`), dev session-controls overlay removal (`416ba297`), gallery rail CSS fix
(`f093a22f`). Two conflicts resolved:
1. `_memory/…w01-shell-lift-file-set.md` add/add → ours (superset; theirs was W0-era).
2. `application-shell.tsx` — **their lane carried a pre-ruling overlay/collapsed carve-out for
   the artifact route** (they never got `c1c413cd`); resolved to the dated founder ruling
   2026-08-17 (rail pinned-expanded on ALL project routes) with Phase C's C-3 rationale folded
   into the comment. If the founder ever wants the collapsed-editor presentation back, that is
   a new ruling, not a resurrection.
Post-merge fix `bcdd3827`: eslint now ignores `public/vendor/**` (the W1.4 vendored bundle was
scanned → 355 warnings; lint is clean again). Gates: 466/466 tests, lint 0/0, build ✓.
**Live-verified on the 3030 stack:** `/projects/{id}/gallery` → `/chats/{thread}?surface=gallery`
(intent carried); threadless absorber canonicalizes to `/chats/{default}`; chats route shows
designed chat chrome + the NEW gallery in the artifact rail (old "No artifacts yet" pane gone);
artifact route unchanged (rail visible, workspace opacity 1, Gallery+artifact tabs).
Browse-daemon note: session state does not survive daemon restarts — re-run the sign-in replay
(email/password → 424242 → workspace click) when `goto` lands on /sign-in.

## W2.1 done — commit `a747df65` (real web render in the artifact stage, 2026-08-18)

- `design-editor/components/web-artifact-canvas.tsx` (+ module css): keyed-remount client
  component; `sandbox="allow-scripts"` srcdoc iframe, per-render bridge nonce in a ref (the
  W2.2 listener seam), WebEditorApp state set. Empty/error copy verbatim from source; loading
  line is neutral ("Loading preview…") — deliberate single copy deviation (source's
  "Generating…" describes agent-turn loads). Keyed remount avoids the react-hooks
  set-state-in-effect lint (sync setState in effects is now an ERROR in this repo).
- **W1.1 contract correction (live-found):** engine URLs are `new URL(path, apiBaseUrl)` —
  a path-prefix apiBaseUrl ("/api/clue/design") THROWS, and even an absolute base would drop
  the prefix. Working form: `data/design-bff.ts::designBffConfig()` — apiBaseUrl = page
  origin + fetchImpl re-mounting every engine URL under the same-origin BFF prefix. Engine
  verbatim; engine/config.ts doc corrected. All engine callers (W2.2+, W3 writes) must use
  `designBffConfig()`, never a raw prefix.
- Stage: `.webCanvas` drops the `aspect-ratio: 1448/1086` letterbox, `.webOutputStage` →
  flex column, canvas `flex: 1 1 auto` (ratified rendering-correctness deviation; comment at
  the CSS site). ArtifactStage takes optional `activeDocumentId`; chat-surface (Phase C rail)
  unchanged — no canvas on the chats route until split-view wiring.
- Page: server-side artifact fetch via `httpDesignArtifactRepository({baseUrl: "",
  fetchImpl: fetchAuthenticatedClueBackend})`; ANY refusal → null → W0.4 dummy empty mount
  (verified: unknown id keeps "Web output" tab + empty canvas, zero iframes). Real artifact →
  real title/kind + `documentIds` map into EditorSurface.
- **Browser-verified on the live 3030 stack:** seeded content into
  `doc_31126145a0aa4753920629ae323a301b` via `POST :8010/documents/{id}/web/operations`
  (base_version 0 → 1; hero section/text/button with Tailwind classes) — renders in-shell
  (dark hero, styled CTA ⇒ vendored tailwind runtime executed in the srcdoc). Srcdoc carries
  `web-rich-text` (API-injected — the W1.4 verify-in-W2 assumption CONFIRMED, nothing to host
  frontend-side) and `lumen-web-bridge` + nonce. Error state proven live too (the pre-fix
  Invalid-base-URL render showed "Preview failed" + message). Screenshot /tmp/w21-real-render.png.

## W2.2 done — commit `c77b743f` (selection bridge + inspector hydration, 2026-08-18)

- `hooks/use-web-bridge-selection.ts`: verbatim port of the editor's `useWebBridgeSelection`
  (full surface incl. rich-text/move/resize seams W3+ consumes). ONE mechanical adaptation:
  callback refs update in a passive effect — this repo's react-hooks lint makes render-time
  `ref.current =` writes and sync-setState-in-effect ERRORS (they also forced W2.1's keyed
  remount and W2.2's stamped-derivation patterns; remember for future ports).
- `hooks/use-web-render.ts`: render fetch + per-render nonce moved OUT of the canvas — the
  repo's no-restricted-imports rule (rightly) forbids `components/` importing `data/`; W2.1's
  canvas import of design-bff was a violation hidden by a `tail -1` misread. Canvas is now
  pure presentation; ALWAYS run `npm run lint 2>&1 | tail -2` (the summary line), not tail -1.
- `hooks/use-web-artifact-selection.ts`: the plan's `{node, nodeInfo}` join — doc loaded via
  BFF (its `currentVersion` is W3's `base_version` source), bridge selections stamped by
  document id and derived (stale never served).
- `adapter/hydrate.ts` = the contract §1 table (kind→schema incl. 18b icon layout-only, §5
  fallback→container+layoutOnly, root→canvas; facet maps; §6(5) out-of-ramp sizes omitted;
  R3 two-axis padding with truthful zeros; tokens hydrate as NAMES — token→hex needs the
  server-compiled web theme, W4's color flow; radius awaits the W4.1 facet). 14 TDD tests
  against REAL harvested fixtures (`adapter/__fixtures__/web-nodes.ts`, doc
  `doc_31126…` v2 — harvested via a throwaway lumen API on :8011; the doc now carries one
  node of every kind incl. icon/embed/image + `asset_fixture_logo`).
- `use-inspector-controller.ts` (chat-shell): optional `hydrated` partial merged over the
  dummy defaults at mount; callers remount per selection.
- Editor-surface exposes `data-selected-node`/`data-selected-schema` (no invented UI — the
  inspector itself mounts at the split view / W2 exit demo).
- **Browser-verified live**: iframe click → cta→`button`, headline→`text`, ficon→
  `icon:layout-only` on the data attributes; bridge outline drawn; link navigation blocked.
  Browse tip: `$B frame 'iframe[title="Website preview"]'` enters the srcdoc frame;
  `$B frame main` returns. Gates: 480/480, lint clean, build ✓. Servers stopped after.

## Plan amendment 2026-08-18 — W3.4 added; resize registered (commit `ea4e7b6d`)

Founder-ordered after the W2.2 move/resize/undo scope review: **W3.4** wires the dummy's
action-menu Undo ⌘Z / Redo ⇧⌘Z (+ shortcuts) to the engine's existing web undo/redo
(`webDocuments.ts:1673` → `POST /documents/{id}/web/undo|redo`; `undoDepth`/`redoDepth`
drive disabled states) — now part of the W3 exit gate, so writes never ship beside inert
undo chrome. **Resize** is contract §7 item 6 (never in the 42-item inventory — no dummy
affordance; bridge `resize-node` seam + width/height facets ready; needs a founder ruling on
capability AND affordance to enter scope). **Moving** unchanged: ruling 29 keyboard-only +
W4.10 audit.

## W2.3 done — commit `7a36d68f` (real layer tree; editing docks the inspector). **Phase W2 code-complete; founder demo pending.**

- `adapter/layers.ts` (+7 TDD tests on the harvested fixture): hierarchy rows, names→labels
  (fallback id), kind→dummy-icon-vocab (section/container→div, text→type, button→rectangle,
  image→image, icon→apple, else div), **depth cap 1 per ruling 41** (depth-1 nodes never
  expandable — subtree has no rows). `WebLayerIcon` mirrors InspectorLayerRow's icon union.
- WebInspector: real-layers via context (`DocumentLayersContext` + `SchemaLayers` fallback at
  the 7 Layers sites — schema views otherwise untouched; fixture trees remain when no rows
  supplied, so the chats-route Phase-C mount is unchanged). W2.2 `hydrated` now reaches all
  seven controllers. New props: `hydrated`, `layers`, `onSelectLayer`.
- Canvas publishes `WebArtifactCanvasControls.selectNode` via a `controlsRef` prop (threaded
  through ArtifactStage as `canvasControlsRef`) — layer-row click → postMessage into the
  iframe → frame echoes `select` → ordinary selection path.
- **Composition decision (flag for founder at the W2 demo):** while editing a real web doc,
  editor-surface docks WebInspector beside the canvas using the dummy's own editing
  arrangement (ruling R6 — inspector takes the conversation column; this chat-less route has
  only the dock) and the dummy's split grid template verbatim (`minmax(400px,480px)
  minmax(0,1fr)`). Not-editing stays full-width per W0.4. Inspector remounts per selected
  node (key) so hydration re-applies.
- **Browser-verified round-trip both directions** (live 3030 stack): canvas click → button
  schema + CTA row active; Headline row click → canvas outline moves + text schema;
  Subheadline shows REAL values (Size 18 from text-lg; center alignment pressed); rows =
  Hero/Headline/Subheadline/CTA/Features/Feature-grid only (depth-2 capped). Screenshot
  /tmp/w23-editing-dock.png. Gates 487/487, lint clean, build ✓. Servers stopped after.
- **W2 exit-gate status:** click→schema→real-values proven; the §2/§3 partition polish
  (padding 4→2, hidden sections, icon layout-only rendering) is W4's per the plan (each
  schema task applies its own §2 deltas). Founder demo/sign-off still to be given.

## W3.1 done — commit `da918933` (event seam grows write addressing)

`dispatchInspectorEvent(name, detail, addressing?)` — every inspector event detail now
carries `{selectionId, artifactId, documentVersion}` additively (legacy shape preserved when
absent; nulls = not-addressable, the W3.2 write adapter must IGNORE such events). All four
controller dispatch sites thread it; WebInspector passes an `addressing` prop to its seven
controllers; editor-surface supplies `{activeArtifactId, selection.node.id,
document.currentVersion}` (the W3.2 `base_version` source). 3 unit tests drive the exported
dispatcher against a captured window (no renderer needed). Gates 490/490, lint clean, build ✓.

## W3.2 done — commits `e19b8427` (adapter) + `4fc9f414` (wiring). **The platform writes through the engine.**

- `adapter/apply.ts` (13 TDD tests, harvested fixtures): §1 inverse maps — fontSize→ramp
  (out-of-ramp null), fontWeight, tokenTextColor (R2 tokens only; hex null), textAlign,
  padding.x/y→nearest SPACING_STEP (R3), textStyle→set_node_props text variant WITH content
  resent (props replace wholesale!), lineSpacing→leading. Unmapped → null.
- `use-web-manual-edits.ts` = verbatim port (designBffConfig; passive-effect refs). 409 →
  "Document moved on — reloaded." + quiet reload; 422 → first diagnostic inline; one
  in-flight (busyRef). **Undo/redo already in the port — W3.4 just binds the menu.**
- `use-inspector-writes.ts`: window listener on clue:inspector-property-change; W3.1 null
  contract enforced; page resolved by node membership; intent "inspector: <property>".
- Reload: write success → reloadNonce++ → doc refetch (fresh base_version) + canvas keyed
  remount (bridge nonce rotates); inspector key = node.id + currentVersion (re-hydration).
- Text schema §2 deltas (cited in place): Style (25) + Line spacing (26) selects; vertical
  alignment hidden (8); padding 2-axis with LOCAL DRAFT + blur/Enter commit (R3 — write path
  never sees keystrokes); size 13 dropped (§6(5)); ColorControl `onTokenChange` label
  emission (R2; hex stays visual-only). Note/error = one inline line under the header
  (`.inspectorStatusNote/Error` in chat-shell CSS) — the pre-W3.3 FLOOR, founder gate owns more.
- **Live-proven, persisted (doc v2→v5 in Postgres):** size 18→24 (text-2xl), theme Dark →
  text-dark (slate-300 replaced), padding 7→px-6 (snap) via Enter. Full-reload persistence
  verified. Gates 506/506, lint clean, build ✓. Servers stopped after.
- **Verification gotchas recorded:** browse `$B fill` does NOT trigger React controlled-input
  onChange in these custom inputs — use the native value setter + input event + keydown in one
  `$B js`. srcdoc grep checks must anchor to the NODE (cta's px-6 false-positived a sub check).
  The fixture embed 404s (`example.com/widget`) are benign external fetches.
- **Known W4.3-adjacent gap (recorded):** the theme tab's option list is the dummy's fixture
  palette (Primary/Secondary/Tertiary/Dark/Light/Subtle) — Dark/Light/Primary happen to be
  real web theme tokens; Tertiary/Subtle/Secondary are not (a pick writes an unstyled class,
  honest no-op visually). Real theme-token options need theme data — W4 color flow decision.

## W3.3 ruling + W3.4 done — commit `be3e45f1`. **Phase W3 code-complete; founder sign-off pending.**

- **W3.3 FOUNDER RULING (2026-08-18): inline only.** Save failures = the single note/error
  line under the inspector header; NO additional UI. Trade-off accepted on the record (can be
  missed / invisible when inspector closes). Plan task marked decided; contract §7 item 5
  updated (version-refused + publish-failure remain open). Do not grow the surface without a
  new ruling.
- **W3.4:** action-menu Undo ⌘Z / Redo ⇧⌘Z + window keydown shortcuts → the ported
  manual-edits controller's undo/redo (`clue:artifact-action-request` events, kind-guarded
  "web"; focused inputs keep native text undo; NOTE the hook's `document` prop shadows the
  global — listeners attach to window). `undoDepth`/`redoDepth` → native `disabled` threaded
  editor-surface→stage→header→menu (+ one `.artifactMenuItem:disabled` CSS rule — the dummy
  shipped none). History success → reload (fresh base_version) + canvas re-render.
- **Live-proven:** Redo born disabled; menu Undo reverted px-6 (v5→v6 in the engine, canvas
  re-rendered); ⇧⌘Z reapplied (v7); Redo re-disabled at empty stack. Gates 506/506, lint
  clean, build ✓. Servers stopped after.
- **W3 exit gate:** rows 4–7 + §2 additions live (row 4 via theme-tab token picks — real
  token option list still W4's color-flow decision), undo/redo live — FOUNDER BROWSER
  SIGN-OFF PENDING (relaunch recipe above).

## Remount defect fixed — commit (post-W3.4) `fix(part4): edits no longer remount…`

Founder observed every edit re-rendering the whole canvas + inspector (unlike the MVP).
Causes were two of our own keyed remounts: canvas key carried the reloadToken; inspector key
carried the document version. Fix = source semantics: quiet in-place srcdoc swap on the SAME
iframe (loading state only at per-document mount; `useWebRender(documentId, reloadToken)`),
inspector keyed on selected node only (accepted drift: engine-snapped values display as typed
until reselect), plus the source's render-rebuild selection sequence (resetSelection on reload
→ selectNode on the new frame's ready; canvas takes `selectedNodeId`). DOM-identity-marker
verified: same inspector root + iframe element across a write; open sections persist; outline
restored. LESSON for future W-work: never key-remount on write-cycle tokens — reserve keyed
remounts for identity changes (document id, node id).

## Gallery leg-derived feed — RATIFIED plan, parallel worktree (2026-08-18)

Founder ratified the gallery data feed as **leg-derived v1** (per-project via
design_leg→agent_thread join; workspace-wide REJECTED — cross-pollinates projects) with two
more rulings: card renders WITHOUT artwork (`imagePath`/`originRunId` go optional; no
placeholder imagery; thumbnails = future capture-pipeline work) and web docs only. Full plan:
`docs/superpowers/plans/2026-08-18-gallery-leg-derived-artifact-feed.md` — executes on a
SEPARATE worktree (`feature/gallery-leg-derived-feed`), merged back locally, while THIS
branch continues W4. Shared-file watch: `editor-surface.tsx` (gallery lane touches only the
artifacts feed + documentIds map). Unlocks (separate follow-up, not the worktree's scope):
the W0.5 Decision-2 route swap of `/projects/{id}/gallery`. Contract rules to be recorded in
apps/frontend/docs/api-contracts/projects.md by the worktree: creation surfaces must write
project linkage; the read is replaced wholesale by the future artifact registry.

## W2 + W3 gates SIGNED OFF; R6 dock ruling ratified (founder, 2026-08-18)

Founder verdicts, verbatim intent: **W2 passes and W3 passes** — both exit gates closed
(recorded in the W-plan at each gate). The W2.3 editing-dock composition is **ratified**:
R6 stands exactly as the dummy designed it (inspector takes over the conversation column),
with two behavioral clarifications now on the record at R6 in the Phase-C plan:
(1) **Edit-only entry** — the dock appears only via the Edit button while a specific
artifact is open, never any other trigger; (2) **send dismisses the dock** — on the chat
screen, sending a message to the agent closes the dock and restores the conversation
column; Edit reopens it. (2) is chats-route/chat-flow wiring (composer send event), NOT W4
scope — it binds whoever mounts editing on the chats route. The artifact route's chat-less
dock (W2.3) is the same arrangement transposed and is signed off with W2. W4 is fully
unblocked; still awaiting founder word on the proposed lane split (A: container/section/
canvas/icon/eye here; B: image+button worktree; C: rich-text+custom-component worktree)
and on pulling the shared theme-token feed forward as trunk substrate before the fan-out.

## W4.1 DONE — commit `e85c5e36` (radius facet family, contract §8 / ruling 14; 2026-08-18)

Executed under SDD (ledger: `.superpowers/sdd/2026-08-17-website-editor-integration/progress.md`).
Five facets (`radiusFacet` + tl/tr/bl/br) added to BOTH `webClassFacets.ts` copies —
byte-identical mirror verified independently by the reviewer. Suffix-as-value parse
(`rounded-lg`→"lg", `rounded-[8px]`→"[8px]"); arbitrary-px set; `RADIUS_SEGMENTS` guard
makes all-corners vs per-corner prefix-unambiguous both ways; variant tokens opaque via
makeFacet's central guard; facets also registered in the `webClassFacets` map (behavior-
neutral — no consumer iterates it). Gates: design-editor 149/149 + tsc clean; frontend
full suite 515/515 (runner is `tsx --test`, NOT vitest), lint, build green. Review: spec ✅,
Approved, zero Critical/Important. **Two W4.2 hand-off notes (in the ledger as deferred
minors):** (a) bare `rounded`/`rounded-tl` parses `null` — Shape hydrate must not render
null as 0 and then write `rounded-[0px]`; (b) all-corners `set` deliberately leaves
per-corner/side overrides in place (conservative §4 reading) — W4.2 needs a founder
micro-ruling: does "Radius (all)" clear per-corner overrides?

## W4.0 DONE — commit `cf228bc9` (theme-token feed; founder-ordered trunk substrate, 2026-08-18)

The ColorControl Theme tab now serves the document's REAL compiled theme
(`GET /documents/{id}/web/theme` → engine `fetchWebTheme` → `designBffConfig()` BFF →
`useWebTheme` hook → pure `buildThemeColorOptions` mapper → `ThemeColorsContext` →
optional `options` prop with fixture fallback). Text schema only; other schemas join in
their W4 lanes via the same context. Labels capitalize-first over lowercased token names
so `label.toLowerCase() === token` round-trips into apply.ts's `text-<token>` write.
`themeColorForToken` resolves the hydrated token → honest closed-state trigger swatch.
Fixture palette moved verbatim to `model/inspector-theme-colors.ts` (fallback contract
testable); hydrate's `tokenLabel` now imports the ONE shared rule. Gates 528/528 + lint +
build. **Browser-verified end to end:** 52 real tokens with real swatches; picked Accent →
`text-accent` written (other `text-*` utilities untouched — facet law held), persisted
through reload, trigger resolved `#06B6D4`, aria-pressed on the current token. Process:
Opus implemented; Fable reviewed INLINE (founder ruling 2026-08-18: no reviewer subagents,
ever — memory `opus-subabgents-fable-orchestrates` updated; typo aside, the slug is
`opus-subagents-fable-orchestrates`).
- **OPEN founder ruling — Theme-tab curation:** the real theme has 52 tokens incl.
  machine ramps (`palette-neutral/primary-50…950`) and structural roles (`surface-*`,
  `border-*`, `focus-ring`); the popover honestly lists all 52 (screenshot
  /tmp/w40-theme-popover.png). Options: keep all; filter `palette-*` out; or curated
  role subset per control (text controls → `text-*` roles + semantic base). Until ruled,
  all 52 stand.
- **LAUNCH RECIPE AMENDMENT (ops trap, cost this session a false alarm):** before
  `npm run dev -- --port 3030`, ALWAYS `lsof -nP -iTCP:3030 -sTCP:LISTEN` and kill any
  stale listener. A pre-commit next-server from an earlier run held 3030; the new launch
  died EADDRINUSE silently (log-only) and the browser exercised OLD code — the W4.0
  feature appeared "broken" while the code was fine. Same check applies to 8010/8030.
- Dev-doc note: the seeded subheadline now carries `text-accent` (cyan) from the verify.

## Brand-kit × onboarding lane — RATIFIED plan, parallel worktree (2026-08-18)

Founder ordered a fourth parallel lane: the design subsystem's SHIPPED brand-kit ingestion
pipeline (website/PDF/assets → versioned `design_brand_kit` rows behind a human approval
gate; theme compiled from kits — the W4.0 picker feed's upstream) integrates into
onboarding. Six rulings ratified (2026-08-12 defer-ruling superseded; auto-fire ONLY at
first-time provisioning, manual from the Brand-context screen otherwise; the dummy
`codex/brand-context-page` is the parity baseline with a HARD lift-only-these-files
constraint; approval stamps the kit on NEW documents at creation — never render-fallback;
vision assist ON by default; L2 BrandContextCard out). Plan (self-contained, both scout
inventories + the 36-file lift list baked in):
`docs/superpowers/plans/2026-08-18-brandkit-onboarding-integration.md` (`b649e292`).
Executes on worktree branch `feature/brandkit-onboarding-integration`; merged back locally.
Slice 4 has a deliberate founder UI gate (no dummy slot for ingest/approve affordances).
CLAUDE.md's stale "no versioned brand-kit payload" line fixed (`b9189131`).

## Gallery-feed lane MERGED — `5a532397` (2026-08-18)

`feature/gallery-leg-derived-feed` merged into this branch (founder-ordered). The gallery
now serves REAL per-project cards (leg-derived list read `GET /api/v1/projects/{id}/
design-artifacts` + mapper + artifact-page feed; artwork-free card frames). One conflict
(editor-surface.tsx imports — W4.0 theme hook vs the lane's ProjectArtifact type; kept
both). Union gates: frontend 546/546, lint, build; backend feed suite 9/9. Live-verified:
real card in the Gallery tab, click-through → canvas render. NOTE for W0.5 Decision 2:
the new gallery now HAS real data — but the standalone `/projects/{id}/gallery` route was
already retired to a compat redirect by Phase R, so that follow-on is moot; the chats-rail
gallery feed is the remaining consumer (recorded in the lane's contract notes). SECOND
stale-server incident during verify: a zombie design API held 8010 (earlier launch died
EADDRINUSE unnoticed) and began 500ing renders — the pre-launch port check is now proven
twice; treat it as mandatory for 3030/8030/8010 alike.

## W4 fan-out LAUNCHED (founder rulings F1–F3, 2026-08-18)

Founder ruled with standing no-reconfirm: **F1** three-lane split approved; **F2**
Radius-all CLEARS per-corner overrides (adapter-level, W4.2/lane B); **F3** theme tab
hides only `palette-*` ramps — landed on the trunk as W4.0b (`34ecdcff`, live-verified
30 options/zero palette) BEFORE the branch cut. Rulings recorded in the W-plan W4
preamble (`4f95b192`). Lane briefs committed (`ae8a8abb`):
`docs/superpowers/plans/2026-08-18-w4-lane-{b,c}-brief.md`. Branches cut at `ae8a8abb`:
`feature/w4-lane-b-image-button` (W4.2→W4.3; ports 3040/8040/8011; seeds own doc; merges
FIRST) and `feature/w4-lane-c-richtext-components` (W4.8→W4.7; ports 3050/8050/8012;
rebases after B, merges last). Lane A runs on the trunk workspace: W4.4→W4.5→W4.9→W4.6,
then W4.10 audit after both merges, then W5. Lane A owns the trunk doc `doc_31126…`.

## Next on THIS branch — W4 fan-out (awaiting founder lane ruling)

W4.1 done (above). W4.2–W4.9 fan out per the W-plan (each schema task applies its own §2
deltas, citing rulings); W4.10 keyboard audit last. PENDING founder: (1) the proposed lane
split — A here = W4.4/W4.5/W4.9/W4.6; B worktree = W4.2+W4.3; C worktree = W4.8+W4.7 —
and (2) whether the shared theme-token feed (real theme tokens in ColorControl) is pulled
forward as trunk substrate before the fan-out (it fronts W4.3/W4.4/W4.5 and fixes the W3
fixture-palette caveat). W2/W3 gates are SIGNED OFF (2026-08-18) — no longer pending.

## Next

- **W2** (read path): W2.1 real render in the artifact stage (sandboxed srcdoc iframe,
  per-render nonce, unbounded scroll container — drop the dummy's aspect-ratio letterbox);
  W2.2 selection bridge + inspector hydration adapter.
- Ad-side files (image-inspector, image-export-menu, use-image-export-controller, model/image-export) are in-tree but must stay unmounted/unwired through W1–W5 (founder scope: website editor only).
