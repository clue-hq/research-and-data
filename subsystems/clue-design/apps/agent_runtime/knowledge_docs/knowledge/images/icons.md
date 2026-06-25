---
assumes: images/decide
---
# Imagery — Icons (the reliable vector path)

For anything **iconographic** — feature rows, checklists, step markers, bullet accents,
directional cues — reach for a **library icon**, not `asset(action="generate_image")`. A curated vector is
reliable, crisp at any size, and recolors to brand; a model garbles small flat marks. This
is the `icon → library` branch of `knowledge/images/decide`.

## How to place an icon

Use `svg(icon:NAME)` as the element kind, size the node, and recolor with a `fill(...)`
token (every icon is a filled shape, so `fill` is the color):

```text
mark svg(icon:check) p(0,0) s(28,28) fill($surface.brand)
```

- **Size the node** (`s(W,H)`) — the icon scales uniformly to fit and centers in the box.
  No need to match a 24px source; a `s(48,48)` node renders a 48px icon.
- **Recolor with `fill($color.* / $surface.* / $text.*)`** — keep icons on one brand color,
  not a rainbow. For an icon sitting on a brand surface, use `fill($text.inverse)`.
- **One consistent icon style per surface.** Don't mix an icon row with a generated
  illustration; pick the library for the whole set so they read as a family.
- **Icon + label** pattern: a small horizontal `al(h, x(s), y(c), g(...))` row with the icon
  then a text label; repeat for a feature/checklist/step row.

## Available icons (Slice 0 curated set)

Geometric / markers: `circle`, `dot`, `square`, `diamond`, `triangle-up`, `play`, `star`,
`heart`, `bolt`.
Status / actions: `check`, `x`, `plus`, `minus`.
Directional (block arrows): `arrow-right`, `arrow-left`, `arrow-up`, `arrow-down`.

An unknown name fails compile (`LUMD0703`) and the error lists the valid options — pick the
closest shipped icon (e.g. `check` for "done", `bolt` for "fast", `star` for "featured",
`arrow-right` for "next"/"learn more") rather than inventing a name. The set is curated and
extensible; richer pictograms (calendar, shield, users…) arrive in a later slice.

## When NOT to use an icon

- A **photo/portrait/product** that must be seen → `asset(action="generate_image")` (see `images/decide`).
- A **logo** → a brand `logo.*` / `asset.*` token, never `svg(icon:...)`; for the logo
  roles + allowed-surface rules see `knowledge/design-systems/logo-and-assets`.
- Pure **decoration that adds no meaning** → drop it; whitespace beats clutter.
