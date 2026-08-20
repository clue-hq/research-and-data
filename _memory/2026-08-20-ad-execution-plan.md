# 2026-08-20 — Ad-editor integration: execution plan authored (AD0–AD5, task-level)

## What happened
Founder asked for a fully specified, discrete implementation plan now that all rulings are
closed. Three parallel Opus scouts harvested exact interface facts (frontend precedent, scene
engine internals, backend seams); synthesis written as
**`docs/superpowers/plans/2026-08-20-ad-editor-integration-execution-plan.md`** — ~28 tasks
across AD0–AD5 with exact files, verbatim interface signatures, per-task TDD steps, gate
register (G-A…G-G), dependency graph, and a verified traps register. The 2026-08-19 plan is
marked SUPERSEDED-for-execution (stays as the study record).

## Load-bearing scout facts folded into the plan (verified 2026-08-20)
- **Transparent-background PNG export does NOT exist server-side — definitive.** The rasterizer
  paints unconditional opaque white (`lumen-skia/src/render.rs:207-212`), regression-locked by
  `raster_export.rs::empty_page_rasters_as_white_paper_not_black`; no options struct reaches the
  rasterizer. Contract §8's conditional candidate is now a live founder decision (plan Gate G-E);
  until ruled, the checkbox is not rendered (removed at AD0.4).
- **D8 precision:** only `/asset-store/{digest}` is public/headerless upstream (hand-attached
  ACAO *, immutable cache, no deps). `/font-library` and `/assets/{id}/bytes` 401 without
  `X-Workspace-Id` → they ride the existing authenticated BFF (the web precedent already does
  this at `hydrate.ts:304`). The plan's AD1.7 passthrough is GET-only, regex-locked to
  `asset-store/<64-hex>`.
- **Engine slice:** 60 React-free modules, 5-tier dependency graph, exactly 4 env reads to
  retire (editorConfig ×2 + wasmEngine flag fns ×2). `editorConfig.ts` is deleted in extraction;
  everything else is already `{apiBaseUrl, fetchImpl}`-parameterized. Konva exclusion = 3
  `konva*Props` exports pruned from renderAdapter + `effectsRenderParity.test` not ported (D7).
- **Gallery widening is exactly 4 edits** (`design_leg_wiring.py:437,458` + `router.py:1044` +
  docstrings); the wire `kind` enum already admits "ad"; frontend reconstruction
  (`type==="website"?web:ad`) needs zero mount changes once `toProjectArtifact` maps ad →
  `type:"canvas"`, no collateralType (inferred decision, recorded in AD2.1 — confirm with
  founder in passing).
- **No seed script exists** for scene docs; platform tests use the DAL
  (`create_document(doc_kind="scene")` + a design_leg row) — AD2.2 builds the seed + harvests
  fixtures (W2.2 provenance pattern).
- Traps pinned: `persist_preflight:false` on editor exports (server default bumps the version
  behind the editQueue); CornerRadii order TL,TR,**BR**,BL; Dimension literals lowercase snake,
  `hug` has no value key; render the engine's relaid snapshot never the raw server scene;
  editQueue halts on any rejection until `resync()`; zoom clamp [0.1,2.0]; stamp scope is
  lumen-core only; `tsx --test` = `.test.ts` only; no-env-reads guard is non-recursive → the
  scene slice gets its own recursive sibling (also greps `localhost:8000`/`X-Workspace-Id`
  residue).
- **No browser→FastAPI grep-guard test actually exists** in apps/frontend (the law is enforced
  behaviorally by `route.test.ts` + eslint) — the old plan's claim was wrong; the scene
  no-env-reads sibling covers the slice.

## Open / next
- **G-G:** co-founder must commit+push the 23-file dummy delta; hash goes in the contract header
  slot → AD0 unblocks. AD1 can start now.
- **Gate G-E (founder):** authorize the small transparency engine change or rule the checkbox
  out of v1. Evidence is complete either way.
- Mockup queue G-A…G-F scheduled during AD1 (handles/outline, palette-departure note, focal
  dot, banner wordings, print extras). Canvas name/dims chrome joins G-A if the dummy delta
  carries no CSS for it (AD2.3 item 7).
- Turbopack-dev canvaskit fallback is a flagged unknown (AD1.2 step 2) — record the outcome.
