---
name: tools
description: Use when choosing an available tool for a scene design step or recovering from a tool refusal.
---

# Scene tools

Use only tools registered for the current agent. Use inspect/view for evidence,
validate_creative_direction for the shared direction, checked compile/asset tools
for construction, preflight_design and render_preview for current artifacts, and
finalize_run only after the required review. Delegate only when the configured
runtime exposes and calls for delegation.

All registered skills and shared resources remain available on demand during
composition, review and later revision. Read files via their
delivered virtual paths. Do not call an imagined knowledge
loader, export API or image-edit command. Tool descriptions define argument
schemas; `knowledge/lumen-dsl/*` defines DSL syntax. Asset/reference mechanics
live in `knowledge/scene/components.md` and `knowledge/scene/references.md`.
Run dependent writes, preflight and rendering sequentially; independent reads
may batch. A refusal is evidence to repair the named issue, never permission to
bypass the seam or report success.
