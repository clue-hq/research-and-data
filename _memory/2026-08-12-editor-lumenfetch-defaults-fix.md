# 2026-08-12 — Editor lumenFetch defaults fix (O4 seam, Part A)

Branch `integration/frontend-design-part-ii`. Fixes the standalone design editor's 401s
against the strict O4 workspace seam (found in the 2026-08-11 post-merge live run; recorded —
with two factual errors, now corrected in place — in
`2026-08-11-frontend-design-integration-merge.md`).

## What was wrong (root cause, established from git)

- `documentStore.ts` (8 fetchers) and `brandHub.ts` (4 fetchers) defaulted
  `fetchImpl = fetch` — headerless — while every design-API route they hit is
  workspace-gated (401 `workspace.header_required`). Both modules predate the seam
  (created 2026-07-04/06); correct when written.
- The D2.5A migration (`09eff3a0`, 2026-08-08) flipped 13 engine modules to `lumenFetch` and
  its commit message claims "adopted by every API-calling module" — false. The enumeration
  was grep-shaped: the 13 migrated files all contain the token `fetch(`; the two missed files
  contain only the parenless default `= fetch`. `webDocuments.ts` survived only because an
  unrelated frontend-practices-rule-8 fix (`f1f7a242`, 2026-07-27) had rewritten its default
  into a wrapper containing `fetch(`. Oversight, not deferral: no TODO, no debt-table row,
  no doc mention anywhere.
- Nothing could catch it: every vitest suite injects `fetchImpl` (the default is dead code to
  the tests), Pattern-A suites stub global `fetch` (which `lumenFetch` calls through), tsc
  can't see it (`fetch`/`lumenFetch` are type-identical), `npm run lint` is hex-guard + tsc
  only, and CI (`make check`) runs zero editor checks.

## What changed (TDD: red 12 → green 12)

- NEW `apps/editor/src/engine/__tests__/workspaceHeaderDefaults.test.ts` — calls all 12
  exported fetchers WITHOUT `fetchImpl` and asserts `X-Workspace-Id` reaches the wire.
  Watched fail 12/12 on the pre-fix tree (header `null`), pass 12/12 after.
- `documentStore.ts` / `brandHub.ts`: import `lumenFetch`, all 12 defaults flipped
  (`replace_all "fetchImpl = fetch"` → `lumenFetch`); module headers now state the seam rule.
- `editorConfig.ts`: comment-only — the `lumenFetch` JSDoc was mis-attached (a second doc
  block sat between it and the declaration, so IDE hover showed nothing); moved to the
  declaration.

## Verification

- Editor suite: 12 new pass; **zero new failures**. NOTE: 26 pre-existing failures
  (`EditorApp.test.tsx` 25 — missing `[data-testid="canvas-selection"]`, a jsdom DOM-shell
  issue, no network involvement — and `EditorAppWasm.test.tsx` 1) fail **identically on the
  pre-change tree** (proven via `git stash` A/B). Not touched; owner: design subsystem.
- `npm run lint` (hex guard + tsc) clean.
- Browser-verified live (frontend-practices rule 5; servers from the 2026-08-11 run, Next dev
  hot-reload): `/` → `GET /brand-kits` 200; **Add artboard → `POST /documents` 200, URL
  adopts `?document=doc_fb4e2d…`; reload → `GET /documents/{id}` 200 + artboard renders**
  (the exact previously-dead save→load round-trip); unknown id → **404 not 401** (transport
  passed the seam); `/brand` → 200 with the genuine empty state, no error pill; `/new` →
  brand-kits 200 + web/templates 200. Trap for future headless drivers: the artboard creator
  has TWO buttons named "Add artboard" — the first is the disclosure toggle; the submit is
  the last one.

## Follow-ups (agreed plan, NOT yet done)

- **Part B — DONE 2026-08-12 (same branch, follow-up commit).** Delivered:
  (1) `subsystems/clue-design/scripts/check_editor_bare_fetch.mjs` — hex-guard clone flagging
  the global fetch in BOTH token shapes (`fetch(` call AND `= fetch`/`?? fetch` value — the
  shape split that caused the escape) plus `globalThis|window|self.fetch`; `typeof fetch`
  stays legal (probe, not transport); comment-stripped scan of `apps/editor/src/**/*.ts(x)`
  excluding tests; allowlist = editorConfig / runEventStream / canvaskit/imageCache /
  canvaskit/loadCanvasKit / wasmEngine, each justified in-script AND at the site
  (wasmEngine's missing why-exempt comment added). Proven both ways: clean tree exit 0;
  planted 4-shape scratch file → exit 1 naming it. Wired as second link in
  `npm run lint` (+ standalone `lint:fetch`).
  (2) `workspaceHeaderDefaults.test.ts` extended 12→18: one wiring pin per remaining
  Pattern-B module (webDocuments ×2, libraryFonts w/ memo reset, kitFonts w/ one-face kit,
  editQueue constructor default via enqueue→idle) + one Pattern-A representative
  (brandGovernance, direct-lumenFetch path). Pins proven able to fail by mutation check
  (flipped one webDocuments default → exactly that pin failed → restored).
  (3) `docs/frontend-practices.md` rule 8a added — the workspace-header convention now
  exists in the canonical doc, naming both enforcement layers and the open `<img src>` hole.
  Full-module enumeration in the dynamic suite is deliberately NOT done — the static guard
  owns enumeration; the pins own per-module wiring proof.
- **`<img src>` 401 class — RESOLVED 2026-08-12 (founder-ratified: extend `/asset-store/{digest}`
  content-addressing).** Full trail in `2026-08-12-asset-img-serving-and-editor-ci.md`. Summary:
  the API stamps `media.thumbnail.digest` at the DTO boundary (`public_asset_record` in
  `lumen_api/main.py`, applied at all 8 record-returning sites; ref parsing stays server-owned
  via `location_digest`); the editor gained `publicAssetBytesUrl`/`publicAssetThumbnailUrl` +
  `fetchAssetRecord` (engine/assetLibrary) and the cached id→record resolver hook
  `useAssetPreviewUrl` (hooks/); all NINE `<img>` surfaces swapped (the audit's 8 + a missed
  `AssetPreviewImage`, whose registry-onError dance is retired); the registry URL builders
  (`assetBytesUrl`/`assetThumbnailUrl`, in assetLibrary AND brandHub AND brandLibrary's
  wrappers) are DELETED so the class is unrepresentable; `sceneAssetBytesUrl`'s digest-less
  fallback now returns null (imageCache models null = skipped load) closing the latent 401
  inside the imageCache exception. Browser-verified live end-to-end (uploaded asset →
  brand kit referencing it → kit logos/images/picker + editor Assets panel all render from
  `/asset-store/{digest}` 200, one deduped `GET /assets/{id}` 200 via lumenFetch, zero 401s;
  headerless `curl /asset-store/{digest}` 200). Residual unchanged: R-D4-7 —
  `/asset-store/{digest}` still resolves across tenants; Part-IV auth owns serving policy.
- `docs/frontend-practices.md` predates the seam — the workspace-header rule exists nowhere
  in the canonical doc; add it (+ the guard) when Part B lands.
- Editor CI — RESOLVED 2026-08-12: the editor's original gate
  (`subsystems/clue-design/.github/workflows/conformance.yml`, job browser-wasm-core) had been
  DEAD since the subtree merge (GitHub only runs root `.github/`). Ported to
  `.github/workflows/editor-checks.yml` (root): paths-filtered on `subsystems/clue-design/**`,
  runs npm ci → wasm build+budget → `npm run lint` (hex + lumenFetch guards + tsc) → vitest
  with the two documented pre-existing red files excluded (loud header comment; removing the
  excludes is part of fixing those 26) → production build. The old subsystem-level
  conformance.yml is left untouched as history (its rust/api jobs are a separate porting
  decision). Details in `2026-08-12-asset-img-serving-and-editor-ci.md`.
- 26 pre-existing editor test failures above (now also pinned as CI exclusions — fixing them
  deletes the two `--exclude` flags in editor-checks.yml).
