---
name: tools
description: Use when choosing an available tool for a scene design step or recovering from a tool refusal.
---

# Scene tools

Use only tools actually registered for your role. The director inspects/views,
delegates via task, validates the creative direction and finalizes; it does not
compile. The author uses compile_dsl_block, asset, fetch_logo, inspect/view,
validate_binding_set and preflight_design; in the fast loop it also renders.
The reviewer has inspect/view and filesystem tools only.

Read files via their delivered virtual paths. Do not call an imagined knowledge
loader, export API or image-edit command. Tool descriptions define argument
schemas; `knowledge/lumen-dsl/*` defines DSL syntax. Asset/reference mechanics
live in `knowledge/scene/components.md` and `knowledge/scene/references.md`.
Run dependent writes, preflight and rendering sequentially; independent reads
may batch. A refusal is evidence to repair the named issue, never permission to
bypass the seam or report success.
