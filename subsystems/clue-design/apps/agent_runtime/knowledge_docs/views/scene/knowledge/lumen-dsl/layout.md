# Lumen DSL — Layout, Sizing & Auto-Layout

Prefer **systematic** structure (auto-layout with consistent gaps) over hand-placed
`p(x,y)` coordinates. Hand placement is fine for a few absolute elements; it does
not survive content that varies by account/contact.

## Sizing tokens (the `s(w,h)` args)

| Token | Meaning |
|-------|---------|
| `<number>` | fixed canonical layout points (`pt`) |
| `hug` | size to fit content (use for text whose copy may vary) |
| `fill` | expand to fill the parent's available main-axis space |
| `fill(weight)` / `fill:weight` | weighted fill among siblings |
| `$token` | a `$space.*`/`$radius.*`-style dimension token |

Rules of thumb:
- Use `hug` height for any text that can wrap or vary.
- Use `fill` only inside a layout context that can resolve it (an `al` container,
  or a frame with a definite cross-axis).
- Keep text boxes **wide enough for the real copy**; a too-narrow box forces extra
  lines and triggers overflow (`LUMV0903`).
- Do not put `mm` or renderer-pixel thinking into child `p()`/`s()` values.
  Page/export declarations may use `px`, `mm`, `in`, or `pt`, but child geometry
  is authored in canonical layout points.

## Artboard-local layout

Page presets and explicit page sizes normalize into artboard layout bounds before
children are interpreted. The child coordinate space is always artboard-local or
parent-local:

- A4 portrait: about `595 x 842 pt`, with print metadata of `210mm x 297mm`.
- US Letter: `612 x 792 pt`, with print metadata of `8.5in x 11in`.
- `size(1080,1080,px)`: `1080 x 1080 pt`, with a `1080 x 1080 px` raster export
  default.
- `size(6,4,in)`: `432 x 288 pt`, with print metadata of `6in x 4in`.

Prefer one bounded root frame under each page/artboard:

```text
page page_a4 preset(a4,portrait)
  artboard al(v, x(s), g(18), pad(36)) p(0,0) s(fill,fill) fill($surface.page) clip(true)
```

If a page/artboard or parent-containment diagnostic appears, fix the diagnosed
layout cluster rather than shrinking one unrelated child. See
`knowledge/loop/layout-cluster-repair`.
For root artboard frame size repairs, use `s(fill,fill)` so the frame resolves
against the canonical artboard bounds instead of rounded print or stale raster
dimensions.

## Auto-layout

Put `al(...)` on an `autolayout`/`al` container. Children flow along the main
axis with a uniform gap.

```text
stack al(v, x(s), g(18), pad(24)) p(64,64) s(520,hug) fill($surface.card) rd($radius.lg)
  headline text "Pipeline-ready outreach" p(0,0) s(fill,hug) style($type.headline) wrap_text(true) max_lines(2)
  body     text "A concise, account-specific message." p(0,0) s(fill,hug) style($type.body) wrap_text(true) max_lines(3)
nav  al(h, x(sb), y(c), g(16), pad(24)) p(40,40) s(1000,hug)
cta  al(h, x(c),  y(c), pad(12,24))     p(64,860) s(220,56) fill($surface.inverse) rd($radius.md)
```

Auto-layout parts:

| Part | Values | Meaning |
|------|--------|---------|
| direction | `v` (column) · `h` (row) | main axis (unknown → `LUMD0244`) |
| `x(anchor)` | `s`/`start`, `c`/`center`, `e`/`end`, `sb`/`space_between`, `st`/`stretch` | the horizontal axis |
| `y(anchor)` | same set | the vertical axis |
| `g(n)` | number / `$space.*` | gap between children |
| `pad(a)` · `pad(v,h)` · `pad(t,r,b,l)` | 1/2/4 values | padding (other arities → `LUMD0222`) |
| `wrap(bool)` | | wrap to multiple lines |

`x` and `y` name the literal screen axes, not the roles "main" and "cross". Which
one distributes the children depends on the direction: in `al(v, …)` the main axis
is `y(…)` and `x(…)` aligns the cross axis; in `al(h, …)` it is the other way
round. Both default to `start`, so children pack toward the top-left and any
leftover space collects at the far end. Spend leftover space deliberately: don't
leave content packed at the top over an empty band, and don't inflate type sizes
or padding to fill the canvas.

Anchor cheat-sheet:
- `x(sb)` — nav / proof rows (push items to the ends).
- `x(c), y(c)` — centered buttons (this is how you center a label inside a button).
- `x(s)` — left-aligned content stacks.
- `stretch` — only on the cross axis, and only when the container has definite
  space on that axis.

## Vertical centering — `y(c)` for containers, `valign` for a text box

Two tools, two jobs — pick by what you are centering:

- **Centering children inside a container** → make the container an auto-layout and
  use `y(c)`. This lays out the container's *children* on the cross axis:

  ```text
  banner al(h, x(c), y(c), pad(0,24)) p(0,0) s(595,80) fill($surface.brand)
    title text "Appointment Reminder" p(0,0) s(fill,hug) style($type.headline) font("Inter",22,700,center)
  ```

- **Centering the copy inside a single text node's own fixed/fill-height box** →
  put `valign(top|center|bottom)` on the text node itself (see `text.md`). No
  auto-layout wrapper needed:

  ```text
  band text "Appointment Reminder" p(0,0) s(595,80) style($type.headline) align(center) valign(center)
  ```

  `valign` only bites when the box has vertical slack (fixed/fill height taller than
  the copy). On a **hug** height there is no slack and `valign` is a silent no-op —
  reach for the auto-layout `y(c)` form instead, or give the box a real height.
  `valign` never hides overflow (an overflowing box still emits `LUMV0903`).

Value is `center`, never `middle` (`valign(middle)` → `LUMD0275`). `text_align(...)`
is the alias for the **horizontal** `align(...)`, not a vertical knob.

## Backgrounds

Put the background **on the container frame** (`fill(...)`), not a separate
decorative rectangle, when the background belongs to that container. For a page
or artboard background in new DSL, use a single clipped root `artboard` frame
with `fill(...)`. Do not put `background(...)` on a `page ...` creation line,
and do not create loose oversized full-canvas `bg` rectangles.
