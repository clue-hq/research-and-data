# Lumen DSL — Text & Typography

Text is the most common source of overflow. Measurement is real (server-side
SkParagraph shaping over the bundled Inter), so a box that the compiler says is
too small genuinely is.

## Properties

| Property | Aliases | Meaning |
|----------|---------|---------|
| `text("…")` | `content` | the string content |
| `font("family",size,weight,align)` | — | full type spec; align ∈ `left`/`center`/`right`/`justify` |
| `font($type.x)` | — | one typography token (preferred when branded) |
| `style($type.x)` | `text_style` | typography role token (preferred when branded) |
| `align(left\|center\|right\|justify)` | `text_align` | horizontal alignment, standalone — pairs with `style($type.x)` (which carries no align) |
| `font_size(n)` / `font_size($type.size.x)` | `font-size` | size only — a raw number OR a size-step token (the token form is preferred; see below) |
| `font_weight(n)` | `font-weight` | alias — weight only |
| `lh(n)` | `line_height` | line height multiplier |
| `ls(n)` | `letter_spacing` | pixel letter spacing |
| `tracking(n)` | — | design-tool tracking; `tracking(200)` ≈ `0.2em`, not 200px |
| `wrap_text(bool)` | `text_wrap` | enable wrapping |
| `max_lines(n)` | `max` | cap line count (>0; else `LUMD0255`); overflow → `LUMV0904` |
| `dir(ltr|rtl|auto)` | `direction` | base direction |

Canonical vs alias: prefer `font(...)` / `style($type.x)` / `lh(...)` / `ls(...)`
in new designs. `font_size`/`font_weight`/`tracking` are compatibility aliases for
*targeted text repairs* when a model has drifted into CSS/design-tool language.

`align(...)` is the horizontal alignment knob. Use it **standalone** alongside
`style($type.x)` — the style token carries no alignment — to center a label without
resizing its box: e.g. a numeral in a circle chip or a CTA label is
`style($type.cta) align(center)`. (It is also the 4th arg of `font(...)`.) To center
a label in a chip/button, the box does NOT need to hug the glyph — `align(center)`
centers the glyph within whatever width the box has. Vertical centering is an
auto-layout `y(c)` on the parent plus a hug height on the label (see `layout.md`);
there is no `valign`.

## Type-size scale — pick the step for the surface

A role (`style($type.headline)`) bakes in **one** size, tuned for a document-scale
page (A4 ≈ 595pt wide). On a much larger canvas (a 1080² social square, a wide
flyer) that same size is too small to dominate — the headline reads at the same
weight as a stat and the squint test fails. Fix it at the source: keep the role
for weight/color/line-height and **override the size with a step token**:

```
$type.size.xs=12  sm=14  md=16  lg=20  xl=24  2xl=32  3xl=36
$type.size.4xl=40 (hero)  5xl=48 (large hero)  6xl=64 (display)
$type.size.7xl=80  8xl=96  9xl=128  (oversize / display)
```

```text
# A4 / document scale — the role default is right, no override needed
headline text "Your appointment is confirmed." s(fill,hug) style($type.headline) lh(1.08) wrap_text(true) max_lines(2)

# 1080² social hero — same role, but step the size up so it dominates
headline text "Meet Magic-Doc." s(fill,hug) style($type.headline) font_size($type.size.7xl) lh(1.08) wrap_text(true) max_lines(2)
```

The step token resolves to a fixed value regardless of canvas (no auto-scaling —
a human editor can resize it freely), and it wins over the role's default size.
**Rules of thumb** (canvas-independent): one element dominates per artifact; the
hero is ~2–3× body; a stat/secondary value must read *visibly smaller* than the
hero (don't let `$type.stat`, 48, rival a 56 headline — step the headline to
64–80 on a big canvas). See `knowledge/design/foundations`.

## Patterns that fit

```text
headline text "Let neurosurgeons focus on surgery." p(64,88) s(620,hug) style($type.headline) lh(1.08) wrap_text(true) max_lines(2)
body     text "Insight Health handles calls, scheduling, and patient routing." p(64,240) s(600,hug) style($type.body) lh(1.35) wrap_text(true) max_lines(3)
cta_text text "Book a Demo" p(0,0) s(fill,hug) style($type.cta) max_lines(1)
```

- `hug` height so the box grows with the copy.
- Box **wide enough** for the real sentence.
- `wrap_text(true)` on anything that can vary.
- `max_lines(...)` so overflow is diagnosed early rather than clipping silently.
- `lh` for hierarchy: tight headlines (`1.05`–`1.15`), relaxed body (`1.3`–`1.45`).

## Patterns that overflow

```text
headline text "Very long headline that cannot fit" p(40,40) s(300,24) font("Inter",64,800,left)
body     text "A long paragraph forced into a tiny fixed box" p(40,120) s(300,24) font("Inter",18,400,left)
```

A fixed `24px` height with a 64px font, or a paragraph in a narrow box, will fail
fit validation (`LUMV0903 exceeds available height`, `LUMV0810 fixture overflows`).
The fix is small and targeted: widen/heighten the box, raise `max_lines`, drop the
font a point, or switch the slot's overflow policy to shrink/wrap. **Do not redesign
the whole scene to fix one box** — see `skills/repair-design`.
