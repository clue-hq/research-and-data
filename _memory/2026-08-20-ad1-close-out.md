# 2026-08-20 — Phase AD1 COMPLETE: the scene-engine substrate is extracted, vendored, and proven

Branch `integration/frontend-design-part-iv-v4`, commits `3d8ff650..902f7e34` (+ this note).
Plan: `docs/superpowers/plans/2026-08-20-ad-editor-integration-execution-plan.md`. Ledger:
`.superpowers/sdd/2026-08-20-ad-editor-integration-execution-plan/progress.md`.

## What AD1 shipped

| Task | Commits | What landed |
|---|---|---|
| AD1.1 | `3d8ff650` | Vendor pipeline: canvaskit-wasm pinned exact `0.41.1`; `copy-design-vendor.mjs` scene section → `public/vendor/{canvaskit,wasm,fonts}` on predev/prebuild(/pretest per Ruling 13). Real wasm built: 813,150 B gz vs 3,145,728 budget, stamp `7b992f8c6ec8`. |
| AD1.2 | `3570639a` | Both bundler configs — webpack `resolve.fallback` AND turbopack `resolveAlias` (the risk was real: `Can't resolve 'fs'` at canvaskit.js:157). Stub: `engine/scene/empty-module.ts`. Both proven load-bearing by negative control. |
| AD1.3 | `80235c61`, `d8460bbc` | Tier A: 13 pure-core modules byte-identical + recursive no-env-reads guard + 134 tests (fix round added 2 plan-omitted test files). tsconfig target → ES2020 (Ruling 11). |
| AD1.4 | `a200b80c` | Tier B: 7 modules (6 identical; renderAdapter = deletions-only D7 Konva-prune, now in-file-marked). Workspace viewport pair landed here (Ruling 8 reorder). |
| AD1.5 | `06989503`, `e710abc2`, `933a4c8d` | Tier C: editQueue/documentStore/structuredEdits/exportRunner/assetLibrary/wasmEngine on `DesignEditorConfig`; env reads retired; `activateWasmCore({apiBaseUrl required, wasmBaseUrl?})`; wasm default `/vendor/wasm`; Ruling 12 — all fetch defaults are the receiver-safe `defaultDesignFetch`. |
| AD1.6 | `bbadfe3e`, `851f0238` | Canvaskit runtime (loadCanvasKit w/ `/vendor/*` defaults, drawDescriptors, skiaMeasurements, imageCache) + Ruling-8 movers (renderDiagnostics, kitFonts, libraryFonts) + node wasm loader + **the exit-gate smoke: recomputed lumen-core stamp == artifact `engine_commit` (`7b992f8c6ec8`)**; all 43 artifact/font-gated cases executed. `pretest` vendor hook (Ruling 13). |
| AD1.7 | `93f1c172` | D8 passthrough: `GET /api/clue/design-public/asset-store/{64-hex}` — headerless, GET-only, regex-locked, streams, allowlists content-type+cache-control; 503 when `LUMEN_API_BASE_URL` unset. `DESIGN_PUBLIC_BFF_PREFIX` exported (unconsumed until AD2.3). |
| AD1.8 | `902f7e34` + this | Exit gate + whole-phase review (exit contract MET) + fix wave: injectable `fetchImpl` for exportRunner/structuredEdits/assetLibrary (9 module-global sites — trap-the-global tests per module), assetStoreBytesUrl origin-not-prefix note, renderAdapter D7 marker. |

End state: **33 scene modules** (engine/scene/ + canvaskit/), **378 scene tests**, suite **1274/1274**,
lint 0 errors, build green, root `make check` = only the 5 documented pre-existing reds (3×
pilot_budget_controls, 1× unified_agent_gate_migration, 1× o3_account_deep_behavior — zero backend
paths in the phase diff). Browser regression checks clean after every sub-slice (gstack browse,
dev on :3032).

## The two invariants, machine-enforced
1. **The slice owns no ambient configuration** — recursive no-env-reads guard (+ `localhost:8000` /
   `X-Workspace-Id` residue grep, proven non-vacuous); every transport is injectable, defaulting to
   `defaultDesignFetch`; zero `editorConfig`/`lumenFetch` residue.
2. **The browser only talks to our origin** — authenticated BFF for everything workspace-gated;
   the D8 passthrough for content-addressed public bytes; passthrough tests lock the header vacuum
   (`[...headers.keys()] == []`).

## What AD2 must know
- `activateWasmCore` REQUIRES `apiBaseUrl` (pass `designBffConfig().apiBaseUrl`; handshake hits
  `/build-info` through the BFF). `loadWasmModule` defaults to `/vendor/wasm`; `loadCanvasKit` to
  `/vendor/canvaskit` + `/vendor/fonts/Inter-*.ttf`.
- **Asset bytes:** build passthrough URLs by string-concat (`${DESIGN_PUBLIC_BFF_PREFIX}/asset-store/${digest}`)
  — NEVER pass the prefix to `assetStoreBytesUrl` (it's `new URL`-based; origin only; noted in-file).
- Fonts: `/font-library` + `/assets/{id}/bytes` are workspace-gated → authenticated BFF via
  injected fetchImpl (kitFonts/libraryFonts already take `{apiBaseUrl, fetchImpl}`).
- `imageCache`'s default fetcher is a deliberate free-call `fetch` (receiver-safe, injectable via
  `options.fetcher`, URLs arrive complete from `resolveUrl`).
- The wasm-gated tests run everywhere `pretest` can vendor artifacts; toolchain-less machines skip
  them with a logged note (fail-soft by design; the runtime handshake owns the hard guarantee).
- Deferred minors + rulings 8–13 live in the ledger; FINE-DEFERRED triage from the final review:
  stale Konva comments (M1), fixture cmp-guard candidate for AD5 (M3), passthrough drops upstream
  ACAO + X-Request-Id (M4 — widen only with a ruling), pretest rebuild cost on Rust drift is the
  intended anti-drift behavior (M5), turbopack alias stubs bare fs/path/crypto app-wide (M6),
  libraryFonts.test unused-var lint warning (AD1.6 cosmetic).
- Dev server may still be running on :3032; seeded ad doc `doc_ad0auditscene0000000000000001`
  awaits AD2 (see the AD0 close-out for stack/login traps).
