---
name: effects
description: Apply Lumen special effects — drop shadows, extended strokes (dash, cap, join, align), and gradients — with the exact grammar and the accepted CSS-style aliases. Use when a design needs elevation, decorative borders, or color transitions.
---

# Special Effects — Shadows, Strokes, Gradients

Effects are part of the paint/effects contract. Keep them tasteful and, in branded
designs, tokenized. Get the grammar exactly right — the parser is strict but
accepts a few CSS-style aliases models reach for.

## Drop shadows

Two accepted forms; both compile to the same drop shadow:

```text
# Canonical — COLOR FIRST, then named channel args:
shadow(#000000, o(0.18), x(0), y(8), blur(24), spread(0))
shadow(shadow_soft, #000000, o(0.12), y(8), blur(24))   # optional leading effect id

# CSS box-shadow positional — color LAST, leading bare numbers are x,y,blur[,spread]:
shadow(0, 8, 24, #1f000000)
shadow(0, 4, 24, rgba(0,0,0,0.10))
```

- Channels: `o(opacity)`, `x(dx)`, `y(dy)`, `blur(radius)`, `spread(s)`; omitted
  channels default (opacity 1, offsets/blur/spread 0).
- For translucency, bake alpha into the color (`#AARRGGBB` or `rgba`), e.g. a soft
  card shadow is `shadow(#000000, o(0.12), y(8), blur(24))` or `shadow(0,8,24,#1f000000)`.
- A malformed shadow → `LUMD0257`. Remove one shadow by id on a modify line:
  `#card remove_effect(shadow_soft)`.

A soft elevation recipe for a card:
```text
card fr p(97,196) s(400,460) fill(#ffffff) rd(16) shadow(#000000, o(0.12), y(8), blur(24))
```

## Extended strokes

```text
# Basic:
divider r s(400,1) stroke(#e0e0e0, 1)

# Extended (optional id, then paint, then named options):
panel fr s(400,200) stroke(stroke_border, #111827, w(1), dash(6,4), cap(round), join(round), align(inside))
```

| Option | Values | Notes |
|--------|--------|-------|
| `w(width)` / bare number | number / `$stroke.width.*` | width (required) |
| `dash(on,off,…)` | numbers | dash pattern |
| `cap(...)` | `butt`, `round`, `square` | line ends |
| `join(...)` | `miter`, `round`, `bevel` | corner joins |
| `align(...)` | `center`, `inside`, `outside` | stroke alignment to the path |

Bad option value/arity → `LUMD0256`; the basic two-arg form
`stroke(color,width)` keeps working unchanged. In branded designs use
`stroke($border.default, $stroke.width.card)`.

## Gradients

Gradients are *paints*, usable anywhere a color is (fills, stroke paint, etc.):

```text
hero fr s(1080,1080) fill(linear(135, stop($surface.brand,0), stop($surface.brand.subtle,1)))
chip r   s(120,120)  fill(radial(stop(#ffffff,0), stop(#0b3d2e,1)))
```

- `linear(angle, stop(color,pos), …)` — angle in degrees, ≥1 stop.
- `radial(stop(color,pos), …)` — ≥1 stop.
- Each `stop(color, position)` has `position` in `0..1` and any color form. A bare
  number as a stop color → `LUMD0219`. See `knowledge/lumen-dsl/colors`.

## Not an alias — per-corner radius

`rd(...)` is a **single uniform radius**. `rd(12,12,0,0)` (round only the top) is
**not supported** (→ `LUMD0230`) and the renderer squares non-uniform corners
anyway. If a design needs top-only rounding today, use a uniform `rd(...)` and
accept rounded bottom corners, or record a gap — do not try to fake it.
