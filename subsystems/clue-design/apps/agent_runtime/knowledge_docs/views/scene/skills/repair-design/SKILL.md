---
name: repair-design
description: Use when a compiled scene has a preflight, visual or request-satisfaction defect, or an existing design needs a scoped edit.
---

# Repair the coherent failing part

Read the actual current diagnostics/critique and inspect the implicated geometry.
Change the smallest coherent part that fully fixes the failure; recompose that
part when tiny adjustments cannot solve the reading order or density. Preserve
successful unrelated content and the user's chosen sources.

Anchor the repair to the current saved scene, not a remembered template. Separate
the properties the user wants changed from those already approved. A spacing
repair changes measure, gap or position; it must not silently rebind a typography
role, reset a corner radius or restyle a neighboring component. Inspect existing
bindings and effective values before editing. Prefer property-level `modify`
operations when the structure is already sound. Reapplying `style($type.<role>)`
can change several effective fields at once even if the words remain unchanged.
If a subtree really needs reconciliation, retain its unrelated existing fields
and compare them with the saved baseline afterward.

For a requested color match, inspect the actual target and current rendered
colors using the scene and pinned kit's active mode. A token named `cream`,
`accent` or `primary` is not evidence of its appearance. When the requested
target already exists in this scene, reuse its correct color binding where
appropriate; preserve the target's typography and other properties. Compare
the affected resolved values before and after, then inspect the composite.
Keeping the same rejected value and describing it differently is not a repair.
If the target is unavailable, name the gap instead of claiming an exact match.
This does not authorize recoloring authentic logo/product pixels or changing the
workspace's Brand Kit globally. `brand-and-tokens` owns palette selection.

When moving support closer to a headline, inspect measured text lines and
reflow dependent positions using `knowledge/scene/components.md`. Preserve the
approved headline treatment; assess both optical grouping and comfortable type
size in the current full preview and placement proxy. A narrower gap alone does
not rescue unreadable text.

Use compile_dsl_block with modify lines for properties or reconcile for a
container's intended subtree. Do not re-declare an existing page; page edits use
`#page:<id>`. Node IDs remain unique. Omitted human content is protected; deleting
it requires an explicit directive. `knowledge/lumen-dsl/directives.md` owns exact
syntax and `knowledge/loop/layout-cluster-repair.md` covers bounds failures.

Keep the shared creative direction current when copy, evidence or source choices
change; validate the revised record with its revision reason before using it.
Record the repair delta once in the active round, then preflight, render and
view the new scene. Check the requested change and preserved properties against
the baseline; disclose any remaining mismatch instead of calling it resolved.
An old acceptance cannot certify a repaired artifact.
