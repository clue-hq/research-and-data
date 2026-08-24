# 2026-08-23 — Render fidelity first

## Scope

Implement only the first requested design-editor feature: make browser rendering honor the document's pinned Brand Kit, surface font degradation, preserve the deterministic Inter fallback across browser/server, and strengthen fresh-generation image-byte readiness coverage.

## Implementation state

- The platform editor now requests `/brand-kits/{id}/versions/{version}` for document-pinned kits. The unversioned latest route remains only for the synthetic platform-default fallback.
- Both scene loading and editing-session vocabulary/palette loading key Brand Kit state by `id@version`, so a document pinned to v6 cannot silently consume v9.
- Brand font and library font face load/registration failures now flow into renderer diagnostics. A kit that declares a family with zero faces emits an explicit deterministic-Inter degradation diagnostic and does not fetch or fabricate font bytes.
- The canvas exposes those diagnostics through the existing banner surface and a diagnostic-count data attribute. Font registration still invalidates the token generation, which reruns Skia measurement.
- Fresh-generation regressions now prove durable bytes survive engine-cache deletion before the document's first canvas load and that the browser image cache replaces its initial null placeholder after one fetch/decode.
- A server export regression proves a zero-face declared family reports `LUMS0100` and falls back to bundled Inter.

## Verification so far

- Focused frontend unit tests: 45 passed, 0 failed (`documentStore`, `kitFonts`, `libraryFonts`, and renderer-banner suites).
- Focused server zero-face export regression: passed.
- Focused fresh-generation custody regression: passed.
- `git diff --check`: passed.
- Raw `tsc --noEmit` is not a clean standalone gate in this checkout: it reports existing test-shim/test typing failures in unrelated brand-context, web-document, WASM-handshake, and existing mock-heavy tests. No production-source type error was identified in that run. Use the repository's normal lint/build gates for the final signal.
- The first draft of the server fallback test used preflight, but preflight deliberately does not surface whole-family resolution diagnostics. The regression was corrected to use PNG export, the path that actually shapes/rasterizes and emits `LUMS0100`.

## Remaining before close

- Review the final diff and commit the coherent slice locally. Do not push.

## Closing verification

- Focused platform render-fidelity tests: 53/53 passed (exact Brand Kit route, kit/library diagnostics including unexpected CanvasKit registration throws, `document.fonts`, image-cache decode/replace, banner presentation).
- Real CanvasKit suites: 44/44 passed, including bundled Inter face registration, unknown-family-to-Inter equivalence, real kit-face registration before/after provider init, Skia measurement, real image pixels, text painting/alignment, and token paint resolution.
- Server API regressions passed: zero-face PNG export reports `LUMS0100` with Inter; fresh-generation persistence makes the document and durable bytes observable in the right order even after deleting the engine cache.
- Typography export parity passed for vector PDF, flattened PDF, and headless-Chromium SVG against the Skia PNG truth.
- Live known banner `doc_9e93c1e08c395f57b5efc67d687c8314`: document pins `brand_kit_ing_813df4f30f2d429a853dbccae2277a5a@6`; the exact endpoint returns 200 while latest is v9. Both currently declare `sohne-var` with zero faces. The hero digest returns 200 with all 682,376 JPEG bytes. Non-persisting document export returned status `ok`, the same v6 scene ref, explicit `sohne-var` → Inter diagnostics, 547,980 PNG bytes, and 80,412 colors (not flat).
- Live fresh generated ad `doc_da2edcb80acf5078be5fae5870741401`: generated digest returns 200 with 474,667 JPEG bytes. Non-persisting document export returned status `ok`, 702,457 PNG bytes, and 26,383 colors (not flat).
- Full frontend gate passed: design-system build; 2,005 tests; ESLint with zero errors (two pre-existing unused-helper warnings in `canvasOperations.ts`); Next production build and TypeScript validation.
- `git diff --check` passed.
- Live authenticated canvas automation was attempted through the existing Chrome session, but the extension timed out twice during local navigation and reset its connection. Do not claim a captured browser-canvas pass. The code exposes `data-scene-text-measurement="skia"` and `data-scene-font-diagnostics`, and the real CanvasKit/browser-facing test lanes above cover those mechanisms; a manual authenticated browser check remains useful after checkout.
- Standalone Ruff over the two long design-API test modules is not a valid clean baseline here: it reports numerous pre-existing import/type issues throughout those files. The focused pytest cases are green; no unrelated cleanup was made.
