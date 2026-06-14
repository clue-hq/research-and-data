# Artboard Frame Authoring

Use this reference for every generated exportable artifact.

## Canonical Geometry

Lumen authoring uses canonical layout points (`pt`) for scene geometry:

- A4 portrait preset: about `595 x 842 pt` layout bounds, with print metadata
  of `210mm x 297mm`.
- US Letter: `612 x 792 pt`, with print metadata of `8.5in x 11in`.
- LinkedIn square: `1080 x 1080 pt`, with raster export defaulting to
  `1080 x 1080 px`.
- LinkedIn wide: `1200 x 628 pt`, with raster export defaulting to
  `1200 x 628 px`.
- Custom `6in x 4in`: `432 x 288 pt`, with print metadata of `6in x 4in`.

The agent should author only against layout bounds. Do not use `mm` for child
`p()` or `s()` values. Do not treat renderer pixels as scene coordinates.

## Root Structure

Preferred generated structure:

```text
page page_a4 preset(a4,portrait)
  artboard al(v,g(18),pad(36)) p(0,0) s(fill,fill) fill($surface.page) clip(true)
    card al(v,g(12),pad(18)) p(0,0) s(fill,hug) fill($surface.card) rd(12)
      ...
```

If page-level `background(...)` is supported for the current artifact, it is
also valid:

```text
page page_a4 preset(a4,portrait) background($surface.page)
  card al(v,g(12),pad(18)) p(48,96) s(499,hug) fill($surface.card) rd(12)
    ...
```

Do not create a separate top-level `bg` rectangle for the artboard background.
Only use a separate background-like node when it is a real layered visual object
inside the composition.

## Artboard-Local Coordinates

Children of an artboard are local to that artboard. A node at `p(24,24)` on an
A4 page is `24pt` from the artboard top-left, not `24mm` and not `24px` in the
renderer. Children of a card or stack are local to that parent.

Use parent-relative layout before absolute placement:

- `fill` for width/height that should use available parent space.
- `hug` for text or sections whose content can vary.
- `al(...)`, `pad(...)`, `g(...)`, and `wrap(true)` to keep child groups inside
  parent bounds.
- fixed point values only where the visual size is intentional.

## Anti-Patterns

Avoid these patterns in generated or repaired export-safe designs:

- A4 page plus child values authored as if the page were `210 x 297`.
- A4 page plus `bg s(595,842)` when export/viewBox still uses `210 x 297`.
- `card s(170,210)` with descendants still `s(400,...)`.
- loose top-level `bg`, `card`, or `header` nodes that exceed the artboard.
- switching from `px` to `mm` to make a preview look smaller.

If one parent is resized, inspect and update the affected descendants in the
same layout cluster.
