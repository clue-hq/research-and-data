# Canonical Preflight Pipeline

This document defines the Phase 3.5 stitching path used before Phase 4 agents, API persistence, and asset workflows consume generated designs.

`Scene` remains the canonical document model. DSL is an authoring projection into `Operation` batches. Brand kits, layout, and export are adapter stages around the scene contract.

## Pipeline Order

The canonical authoring path is:

```text
DSL source
  -> compile_dsl / DslCompileSession
  -> apply checked operations to Scene
  -> validate_scene
  -> attach brand kit ref when missing
  -> validate_brand_kit
  -> resolve_scene_tokens
  -> layout_scene
  -> apply computed geometry operations
  -> export preview through an export adapter
```

The core helper for the middle stages is:

```rust
preflight_scene(scene, Some(&brand_kit), PreflightOptions::default())
```

`lumen-core` intentionally does not call exporters. Preview export is composed by passing `PreflightResult.scene` to an export adapter, for example `lumen-export`'s SVG adapter.

## Stop Rules

Use these rules consistently:

- DSL parse/lower errors stop immediately. Preserve valid operations before the cascade halt for agent repair loops.
- Checked operation application errors stop before validation, brand resolution, layout, or export.
- Scene validation errors stop before brand resolution and layout.
- Tokenized scenes without a supplied brand kit stop before layout. Concrete non-token scenes may preflight without a brand kit.
- Brand-kit validation errors stop before token resolution.
- Token-resolution errors stop before layout and export. Warnings may continue.
- Layout errors stop before computed geometry is applied. Warnings may still be returned for preview decisions.
- Export errors belong to the export adapter and should not mutate the scene.

## Token Carrier Boundary

The DSL compiler preserves token references only where the scene contract has a precise carrier:

- size dimensions: `Dimension::Token`
- fills and color stops: `Color::Token` or `Paint::Token`
- stroke width: `Stroke.width_token`
- corner radius: `CornerRadii.token`
- opacity: `Node.opacity_token`
- auto-layout gap and all-edge padding: `AutoLayoutProps.gap_token` and `AutoLayoutProps.padding_token`
- full text styles: `TextNode.style_token`

The brand resolver owns catalog lookup, aliases, mode selection, fallback policy, unit checks, and materialization into concrete scene values. The DSL compiler must not guess unsupported token semantics into unrelated fields.

## Brand Reference Handling

DSL does not own rich document metadata. During preflight, `PreflightOptions::attach_brand_ref_if_missing` defaults to `true`, so a scene with no brand-kit ref gets a checked `SetBrandKitRef` operation before token resolution.

If a scene already references a different brand kit/version, preflight does not override it. The brand resolver emits a diagnostic and stops token materialization.

Preflight does not silently invent a brand kit. Callers should choose the effective brand kit before preflight:

```text
uploaded/client brand kit
  -> generated brand kit
  -> organization/client default brand kit
  -> platform_default_brand_kit()
```

If a scene has token carriers and the caller passes `None`, preflight emits `LUMP0300` and stops before layout/export. If the scene is fully concrete and has no token carriers, `None` is valid.

The platform fallback lives in:

```rust
platform_default_brand_kit()
```

The fixture is `crates/lumen-core/fixtures/brand_kits/platform_default.json`. It is intentionally explicit so downstream API/agent code can distinguish "user/client brand" from "platform fallback".

## Layout And Computed Geometry

`preflight_scene` runs `layout_scene` after token resolution so tokenized dimensions, spacing, typography, radius, opacity, and stroke values are concrete before layout.

When layout has no errors, preflight applies `UpdateNode { computed: Set(...) }` operations to the scene. Exporters and editor adapters should prefer `computed.layout_bounds`/`computed.render_bounds` for layout-sized nodes when present.

## Export Preview

Preview export is deliberately outside `lumen-core`:

```rust
let preflight = preflight_scene(scene, Some(&brand_kit), PreflightOptions::default());
if !preflight.has_errors() {
    export_adapter.export(&preflight.scene, &request)?;
}
```

This keeps the Rust core usable for native and WASM targets while allowing SVG/PNG/PDF adapters to evolve independently.

## Phase 4 Implications

`agents/design-loop-v0` should call this pipeline before rendered critique so the screenshot represents brand-resolved, layout-computed output.

`api/persistence-v0` should persist the canonical scene snapshot and operation history, not a separate preflight model.

`assets/pipeline-v0` should populate asset refs and metadata before preflight when generated or uploaded images are required by the scene.
