# Phase 4 Integration

This branch stitches the Phase 4 workstreams into one system:

- `agents/design-loop-v0`
- `api/persistence-v0`
- `assets/pipeline-v0`

The goal is not to add production storage, model providers, or byte-level asset
resolution. The goal is to prove that the contracts work together.

## Proven Flow

The integrated V0 flow is:

```text
Agent edit / asset tool
  -> canonical core operations
  -> checked scene application
  -> asset registry and placement semantics
  -> canonical preflight
  -> preview export
  -> visual critic request
  -> DTO summaries
  -> API persistence / history / snapshots / template revisions
```

## Cross-Workstream Proofs

`crates/lumen-agent/tests/phase4_integration.rs` proves:

- an agent asset tool can return asset registry and placement operations
- those operations apply through checked core semantics
- strict asset validation passes for registered asset placements
- real SVG preview export runs after preflight
- the visual critic receives a usable preview
- agent DTO operation summaries include asset operation kinds

`crates/lumen-api-helper/tests/helper_cli.rs` proves:

- FastAPI's Rust helper bridge can deserialize and apply asset operations
- returned scenes preserve `Scene.assets`, image node refs, and placement metadata

`apps/api/tests/test_api.py` proves:

- API operation routes persist asset-bearing scenes
- operation history stores asset operations in order
- snapshots preserve asset registry and placement state
- template revisions preserve asset registry and placement state
- metadata-only `/asset-metadata` records coexist with canonical `Scene.assets`

`apps/editor/src/engine/__tests__/operations.test.ts` proves:

- editor-side contracts can represent asset operations
- local editor operation handling can upsert assets and place them into nodes
- asset removal is rejected while a node still references the asset

## Boundary

`preflight_scene` remains the canonical scene/brand/token/layout preflight path.
It does not resolve asset bytes. Strict asset validation is a separate explicit
boundary for flows that expect concrete assets before preview/export.

SVG/PDF/PNG export still does not resolve image bytes in V0. SVG export emits an
image placeholder with `data-lumen-asset-id` and a warning. A future export
resolver should turn `AssetId` references into concrete bytes or vector/font
payloads.
