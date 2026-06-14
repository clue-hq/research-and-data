---
name: repair-design
description: Fix a compile, preflight, or visual diagnostic on an existing Lumen scene SURGICALLY — change only the named target, never re-author the scene or re-declare the page. Use for every repair iteration after the first compile.
---

# Repair a Design (Surgically)

A repair changes the **smallest thing that fixes the diagnostic** and nothing
else. The scene already exists; you are editing it, not rebuilding it.

## The one rule that matters most

**Never re-emit a `page …` line or an existing node id during a repair.** Doing so
is a repair *failure* — it raises `LUMA0200`/duplicate-id, and the partial deletes
that usually accompany a full rewrite can wipe the good scene off the canvas. A
compile/preflight/visual repair is **not** a whole-scene replacement.

If you catch yourself about to write `page page_a4 …` again, stop — you want a
modify line or a continuation instead.

## Choose the smallest actuator (in order)

1. **Modify line** — `#<node_id> prop(...)`. Best for changing a property on one
   existing node. `#instruction s(352,140) max_lines(6)` · `#card s(400,560)` ·
   `#headline font_size(22) lh(1.1)`.
2. **Layout cluster repair** — only when diagnostics name page/artboard bounds,
   parent containment, oversized background, or parent/child scale mismatch.
   Change only the diagnosed page/artboard/root/parent cluster and affected
   descendants. Allowed: p/s, fill/hug/fixed, auto-layout, padding, gap, wrap,
   root sizing, and converting a diagnosed background rect into page/artboard
   fill. Forbidden: page deletion, unrelated node deletion, unrelated
   slot/brand/asset edits, or whole-scene regeneration. See
   `knowledge/loop/layout-cluster-repair`.
3. **Structural directive** — `delete`, `parent`, `before`/`after`, `clone`,
   `replace`, `ungroup` (see `knowledge/lumen-dsl/directives`). For reordering,
   re-homing, duplicating, or swapping a subtree.
4. **Checked structured edit** — the `apply_structured_edit` tool with a `scope`.
   Use this for a precise edit on a *named* node when you want the engine to **fail
   closed** if the edit would touch anything else:
   ```json
   { "kind": "modify",
     "target": { "kind": "node", "id": "instruction" },
     "patch": { "kind": "node", "value": { "size": { "height": 140 } } },
     "scope": { "mode": "strict", "allowed": [{ "kind": "node", "id": "instruction" }] } }
   ```
5. **Continuation DSL** — only when you are *adding* new nested elements under an
   existing container. Indent them under the container; do not re-declare it.

Re-authoring the whole scene is the **last** resort, used only when the design
direction itself is wrong and the coordinator explicitly asked for a replacement.

## Repair by diagnostic kind

**Compile (`LUMD…`)** — fix the exact failing token on the failing line. Earlier
lines are already applied; emit only the corrected continuation/modify, not the
whole block. (`valign` → remove it; bad color → a valid color form; `rd(a,b,c,d)`
→ `rd(a)`.) See `knowledge/lumen-dsl/diagnostics`.

**Layout / fit (`LUMV0903`, `LUMV0810`, `LUMV0904`)** — the text genuinely doesn't
fit (measurement is real). Pick the *smallest* targeted change on the named node:
- give the box more height (`#instruction s(352,160)`) or `hug` it,
- raise `max_lines`,
- drop the font a point (`#instruction font_size(12)`),
- or make the *container* taller (`#card s(400,560)`) if several boxes are tight,
- or relax the slot's overflow policy (`#slot:appointment.instruction` to
  `shrink_font`/`wrap`) so real data fits.
Do **not** delete-and-recreate the card to do this.

**Page/artboard bounds or parent containment (`LUMV09xx` with page/root/parent
targets)** — use `layout_cluster`, not isolated text surgery. Examples:
- convert a diagnosed full-artboard `bg` rect into the root artboard `fill(...)`
  or a permitted `#page:page_id background(...)` modify line;
- resize/reposition the root/card and its dependent children together;
- use `#artboard s(fill,fill)` for root artboard frame size repairs instead of
  numeric page dimensions like `s(595,842)`;
- switch fixed child widths to `fill` inside the diagnosed parent.
Do **not** change unrelated content or page/export dimensions unless the
diagnostic targets page size.

**Brand governance (`LUMB…`)** — replace the raw value with the right `$token`
(`fill(#2463eb)` → `fill($surface.brand)`), not another raw value. See
`skills/brand-and-tokens`.

**Visual critique** — the reviewer names a target and a concrete repair. Apply it
to that target only, preserving the layout direction. If the critique is about a
missing concept, *add* it as a continuation; don't rebuild.

## Edit-surface guidance

The coordinator may pass an `allowed_edit_surface`. When it is `structured_ops`,
prefer `apply_structured_edit` with a `scope` (above). When it is `dsl`, emit the
smallest non-duplicating modify/continuation line. Treat any keyword hint as
advisory — a named `target.node_id` always means "edit that node, in place."

## Preserve the best draft

Even if a run can't reach acceptance, the last scene that compiled cleanly must
remain on the canvas. So: never let a repair attempt destroy a good scene. If a
structural change is risky, do it as a scoped `apply_structured_edit` (which fails
closed) rather than a delete-then-recreate DSL block.

## Self-check before handing off

- Did I avoid re-emitting `page …` and existing node ids? (If not, rewrite.)
- Did I change only the named target, immediate container, or explicitly
  diagnosed layout cluster?
- Is this the smallest edit that clears the diagnostic?
- For a precise named-node fix, did I consider `apply_structured_edit` + scope?
