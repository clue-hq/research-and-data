# Authoring & Repair Loop

The coordinator runs a controlled, deterministic loop. Every scene change flows
through DSL compilation or checked core operations — there is no Python-side scene
mutation.

## The loop

1. Load knowledge before authoring (mandatory brand/design-system knowledge for
   branded tasks).
2. Ask the DSL author for one coherent block (`skills/create-design`).
3. Compile the block (`compile_dsl_block`).
4. Repair compile diagnostics before continuing (`skills/repair-design`).
5. Run preflight (`preflight_design`).
6. Repair preflight diagnostics before preview acceptance.
7. Export previews (`export_preview_bundle`).
8. Validate preview bytes/metadata; never review an invalid artifact.
9. Embed the preview for the reviewer (`get_latest_preview_for_critique`).
10. Ask the visual reviewer to inspect the render (`skills/visual-review`).
11. Persist the critique (`submit_visual_critique`); pass it **verbatim** to the
    author via `create_repair_request`.
12. Stop only on acceptance, max iterations, or a deterministic tool failure.

## Repairs are surgical, not rewrites

Preflight and visual diagnostics that name a node/page/slot are **targeted
repairs**. Fix that target (or its immediate container) and nothing else:

- Prefer a checked structured operation (`apply_structured_edit` with a `scope`)
  for a precise edit on a named node — it fails closed if the edit would touch
  anything else.
- If repairing via DSL, use a `#id` modify line or a small continuation. **Do not
  recreate an existing page or reinsert existing node ids.** Duplicate page/node
  ids are a repair *failure*, not a successful revision (`LUMA0200`).

Full guidance: `skills/repair-design` and `knowledge/lumen-dsl/directives`.

## Layout cluster repairs

Some geometry diagnostics cannot be fixed by touching one text node. If preflight
names an artboard/page-bounds failure, a background-like top-level rect, a child
that exceeds its parent, or a parent/child unit-scale mismatch, use the bounded
`layout_cluster` policy:

- target only the diagnosed page/artboard, root frame, parent, and affected
  descendants;
- allow p/s, fill/hug/fixed, auto-layout, padding, gap, wrap, root cluster sizing,
  and conversion of a diagnosed background rect into the artboard/page fill;
- prohibit page deletion, unrelated node deletion, unrelated slot/brand/asset
  edits, and whole-scene regeneration.

Load `knowledge/loop/layout-cluster-repair` before attempting this repair class.

## Don't lose a good design

A run that ends without acceptance still surfaces the best scene that compiled
cleanly as an inspectable draft. So a repair must never destroy a good scene to
chase a fix — that is exactly why destructive "delete everything and re-`page`"
blocks are forbidden. When a structural change is risky, do it as a scoped checked
edit, not a delete-then-recreate.

## Debug previews

A preview may be exported from a scene that still has preflight errors, for human
inspection only (`export_preview_bundle(debug_only=True)`). It must show computed
layout geometry when the solver produced it, but it does **not** satisfy final
acceptance.

## What "done" means

Done is reviewer acceptance — not a clean compile, not a passing preflight, not a
successful export. Do not claim success before preview-based review accepts the
output.
