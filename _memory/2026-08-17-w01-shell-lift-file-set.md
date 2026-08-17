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

## Next

- **W1** (engine + hosting foundation): W1.1 extract web engine slice behind injected config
  (no `process.env`, guard test); W1.2 authenticated BFF proxy `/api/clue/design/[...path]`
  (stamps X-Workspace-Id server-side; pattern: existing `/api/clue/[...path]` proxy); W1.3
  artifact→document read seam (contract-gap review with founder if no linkage row exists);
  W1.4 vendor asset script for `tailwind-browser.js`.
- Ad-side files (image-inspector, image-export-menu, use-image-export-controller, model/image-export) are in-tree but must stay unmounted/unwired through W1–W5 (founder scope: website editor only).
