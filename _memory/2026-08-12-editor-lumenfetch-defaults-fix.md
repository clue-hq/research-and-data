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

- **Part B (approved in discussion, awaiting go):** `check_editor_bare_fetch.mjs` guard
  cloned from `scripts/check_editor_hex.mjs` (allowlist: `editorConfig.ts`,
  `runEventStream.ts`, `canvaskit/imageCache.ts`, `canvaskit/loadCanvasKit.ts`,
  `wasmEngine.ts` + add the missing why-exempt comment there), wired into `npm run lint`.
- **`<img src>` 401 class (NOT fixable by lumenFetch):** `GET /assets/{id}/bytes|thumbnail`
  are workspace-gated but consumed as `<img src>` at 8 component sites (KitLogoPicker,
  KitLogosSection, KitImagesSection, AssetBrowserPanel, ImageInspectorSection ×2,
  WebAssetDrawer, WebBatchDialog) — browsers can't attach headers to `<img>`. Needs an API
  surface decision (extend `/asset-store/{digest}` content-addressing vs token carrier vs
  `/w/{ws}/` path scope). Same class D7 solved for SSE. Related: `assetLibrary.
  sceneAssetBytesUrl` falls back to `/assets/{id}/bytes` for digest-less assets → latent 401
  inside the sanctioned imageCache exception.
- `docs/frontend-practices.md` predates the seam — the workspace-header rule exists nowhere
  in the canonical doc; add it (+ the guard) when Part B lands.
- Editor has no CI at all (`make check` is Python-only) — belongs to Step-2/week-one hygiene.
- 26 pre-existing editor test failures above.
