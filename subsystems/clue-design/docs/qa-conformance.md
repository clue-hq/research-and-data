# QA Conformance

This branch owns contract conformance for the Design Engine foundation. Its job is to keep the shared `scene + operations + slots` surface stable enough for editor, export, agent, API, DSL, layout, and asset workstreams to consume without inventing parallel semantics.

## Fixture Ownership

Conformance fixtures are contract artifacts. They should represent durable scene shapes and validation expectations, not implementation details from a particular renderer, editor, or export engine.

Current fixture groups:

- `minimal_scene.json`: the smallest valid page/artboard and semantic text slot.
- `conformance/valid_multi_page_slots.json`: multi-page print/ad document with grouped text/logo slots and export profiles.
- `conformance/invalid_tree_reference.json`: structural tree/reference violations.
- `conformance/invalid_slot_export.json`: slot and export-profile validation violations.
- `visual_regression/manifest.json`: runnable export visual-regression skeleton cases.

When a shared contract changes, update the fixture and the expected diagnostic-code assertions together. Do not silently weaken invalid fixture assertions just to make downstream work pass.

## Boundary Rules

- Rust `lumen-core` remains the source of design semantics.
- Renderer, editor, export, and agent tests should consume `Scene`, `Operation`, slot, renderer, and export contract types directly.
- Mock adapter tests in this branch prove the contract shape; concrete Konva, SVG, PNG, PDF, browser, and agent-runtime behavior belongs in the corresponding adapter workstream.
- Visual regression is intentionally a runnable skeleton here until a concrete export renderer exists. The ignored test target is run explicitly in CI so future export code has a stable plug-in point.

## Required Checks

Run these from the design-engine repo root:

```bash
cargo fmt --check
cargo test
cargo test --test visual_regression -- --ignored
cargo check --target wasm32-unknown-unknown
```

CI should keep native tests and wasm compatibility visible on every pull request that touches the shared contract.
