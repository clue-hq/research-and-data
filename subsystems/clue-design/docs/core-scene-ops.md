# Core Scene/Ops Engine

This workstream hardens `lumen-core` from a contract shape into a reusable scene and operation engine.

## Boundary

This branch owns:

- deterministic scene snapshots
- atomic operation application
- checked operation application with validation diagnostics
- read/query helpers for pages, nodes, slots, parents, descendants, bound nodes, and export profiles
- native and `wasm32-unknown-unknown` compatibility

This branch does not own:

- DSL parsing
- Taffy/layout solving
- React-Konva rendering
- SVG/PNG/PDF export implementation
- FastAPI/persistence
- agent orchestration
- conditional evaluation or repeater cloning

## Operation APIs

- `apply_operation` and `apply_operations` apply to a draft scene and only commit when all operations succeed.
- `apply_operation_checked` and `apply_operations_checked` additionally validate the resulting draft and reject it when validation contains errors.
- Validation warnings are returned in `OperationReport` and do not block checked application.

Use checked application for editor, API, and agent boundaries that need to preserve a structurally valid scene. Use raw application only for controlled construction, migrations, tests, or tooling that intentionally needs to inspect invalid intermediate contract states.

