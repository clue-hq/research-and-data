# Contract Foundation

This phase establishes the shared contract that parallel workstreams can build against.

The implementation follows the Brilliant-derived principles captured in `reference_docs/Brilliant-Reverse-Engineering-Report.md`:

- stable explicit IDs for addressable entities
- shallow, structured scene graph
- operations as the mutation surface
- structured diagnostics with stable codes
- visual syntax/DSL as an authoring projection, not the only source of truth
- token and slot metadata as machine-readable design semantics

## Canonical Split

- `Scene` is the canonical runtime model.
- `Operation` is the canonical mutation/history model.
- DSL will compile into operations later.
- Renderer/editor implementations are adapters over the scene model.
- Export workers implement `ExportAdapter`; they do not invent their own scene API.

## Foundation Guarantees

The contract foundation now includes:

- explicit stable IDs for documents, pages, nodes, paints, slots, assets, brand kits, template revisions, and operations
- page/artboard, node, slot, export-profile, and document metadata shapes
- structured update operations for document metadata, page settings, node geometry/content/styles, slots, brand refs, and export profiles
- finalization as a validation-gated operation that freezes the current template revision
- validation for embedded ID mismatches, duplicate parents, cycles, missing references, slot scope targets, and export profile sanity
- native Rust tests and `wasm32-unknown-unknown` compile compatibility

## Conditionals And Repeaters

Conditionals and repeaters are represented in the slot contract but are not operational in this phase.

For now they are metadata that can be validated structurally:

- a conditional slot must define an expression and empty-state behavior
- a repeater slot must define item-count constraints and a template node
- operational semantics for evaluation, cloning, hiding, and reflow remain a later design decision

This lets other workstreams proceed without prematurely freezing the full personalization/runtime behavior.
