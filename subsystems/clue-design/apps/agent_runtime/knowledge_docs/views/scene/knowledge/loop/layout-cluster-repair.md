# Layout Cluster Repair

Use this reference when preflight or visual review reports page/artboard bounds,
parent containment, oversized background, or unit-scale mismatch diagnostics.

Ordinary text-fit diagnostics are still surgical node repairs. A
`layout_cluster` repair is a bounded exception for geometry failures where one
node cannot be fixed safely without its parent or dependent descendants.

## When To Use

Use `layout_cluster` when diagnostics indicate:

- a top-level node exceeds or starts outside the artboard bounds;
- a background-like rect/frame mostly covers the artboard and should become the
  page/artboard background fill;
- a child exceeds a bounded frame, auto-layout frame, clipped container, or root
  artboard;
- parent and child sizes use inconsistent scales, such as a `400pt` child inside
  a `170pt` card after only the parent was resized.

Do not use it just because a single text box overflows. For `LUMV0903`,
`LUMV0904`, or `LUMV0810` on one text node, prefer a normal modify-only repair.

## Allowed Bounded Changes

Within the diagnosed artboard/root/parent cluster, the repair may:

- modify `p(...)` and `s(...)`;
- change `fill`, `hug`, fixed values, and weighted fill;
- adjust existing auto-layout frames with `g(...)`, `pad(...)`, `x(...)`, and
  `y(...)`;
- enable text wrapping with `wrap_text(true)` and update `max_lines(...)` on
  affected text nodes;
- resize the affected parent;
- resize the root artboard frame with `s(fill,fill)` when the root frame should
  match the exportable artboard bounds;
- convert a diagnosed background-like rect into a page/artboard fill when the
  repair request grants that permission;
- update affected descendant sizes after a parent changes size.

## Prohibited Changes

Even in `layout_cluster`, do not:

- delete the page;
- delete unrelated nodes;
- change unrelated slots, Brand Kit tokens, logos, assets, or copy;
- regenerate the whole scene;
- change page/export dimensions unless the diagnostic targets page size itself;
- hardcode numeric root artboard frame sizes such as `s(595,842)`, `s(612,792)`,
  or stale raster dimensions after a resize;
- use `mm` or renderer pixels for child coordinates.

## DSL Shape

Prefer modify lines when possible:

```text
#artboard s(fill,fill) fill($surface.page) clip(true)
#card p(48,96) s(499,hug) g(16) pad(24)
#header s(fill,hug)
#divider s(fill,1)
#headline s(fill,hug) wrap_text(true) max_lines(3)
```

For root artboard frame sizing, prefer `s(fill,fill)`. It resolves against the
canonical page/artboard bounds for A4, Letter, social sizes, and custom
mm/in/px surfaces, avoiding rounded print dimensions or stale raster values.

Do not write `#node al(...)` in a repair. `al(...)` is creation syntax for an
auto-layout element line, not a supported modify-line property. Do not write
`#node wrap(...)` either; container wrap is not lowered for node modify lines.
Use `wrap_text(true)` for text nodes, and use `g(...)`, `pad(...)`, `x(...)`,
and `y(...)` to adjust an existing auto-layout frame.

When conversion from a background rect to an artboard fill cannot be expressed as
a safe modify-only DSL block, use a checked structured edit with a scope that
contains only the diagnosed artboard/root/background cluster.
