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
  venv post-Part-II; same shared Postgres 55040/clue).
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

## Next

- **W2** (read path): W2.1 real render in the artifact stage (sandboxed srcdoc iframe,
  per-render nonce, unbounded scroll container — drop the dummy's aspect-ratio letterbox);
  W2.2 selection bridge + inspector hydration adapter.
- Ad-side files (image-inspector, image-export-menu, use-image-export-controller, model/image-export) are in-tree but must stay unmounted/unwired through W1–W5 (founder scope: website editor only).
