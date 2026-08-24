---
name: effects
description: Apply Lumen special effects — drop shadows, glow, layer blur, inner shadow, extended strokes (dash, cap, join, align), and gradients — plus per-corner radius and fill opacity, with the exact grammar and the accepted CSS-style aliases. Use when a design needs elevation, focal emphasis, depth, inset surfaces, decorative borders, or color transitions.
---

# Special Effects — Shadows, Glow, Blur, Inner Shadow, Strokes, Gradients

Effects are part of the paint/effects contract. Keep them tasteful and, in branded
designs, tokenized. Get the grammar exactly right — the parser is strict but
accepts a few CSS-style aliases models reach for.

## The effect stack

Drop shadow, **glow**, **layer blur**, and **inner shadow** are all `effects` on a
node — they stack, each carries an **addressable id**, and a modify line **upserts
by id** (same id edits in place, new id appends). Compose order: layer blurs apply
to the node first, the shadow/glow stack merges beneath the blurred result, inner
shadows draw over it clipped to its alpha. Remove one by id on a modify line:

```text
#card remove_effect(shadow_soft)
```

**Text strokes are not rendered** (deferred to Typography v1). A text node carrying
`stroke(...)` still exports, but both exporters emit the loud advisory `LUME0214`
and drop the stroke — emulate an outline with a duplicate offset text layer, or
wait for Typography v1. (Shape strokes render fully — see *Extended strokes*.)

## Drop shadows — elevation

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
- A malformed shadow → `LUMD0257`.

A soft elevation recipe for a card:
```text
card fr p(97,196) s(400,460) fill(#ffffff) rd(16) shadow(#000000, o(0.12), y(8), blur(24))
```

## Glow — focal emphasis on a dark field

An **outer** glow — a centered, offset-free halo that dilates by `spread` and
softens by `blur`, merged beneath the source. There is **no x/y** (a glow is
centered; use `shadow(...)` for an offset — `glow(...,x(),y())` → `LUMD0266`).

```text
# id? then COLOR, then named channels — same channel style as shadow, minus x/y:
glow(#7c3aed, o(0.8), blur(24), spread(4))
glow(numeral_halo, #f5a020, o(0.5), blur(56), spread(2))   # optional leading id
```

- Channels: `o(opacity)`, `blur(radius)`, `spread(s)`. Malformed → `LUMD0266`
  (hint: `glow(glow_soft,#7c3aed,o(0.8),blur(24),spread(4))`).
- **When to use:** a display numeral or wordmark that has to carry a **dark**
  canvas — the "living type" move, where the number reads as lit rather than
  printed. Pick a glow color from the type's own gradient (a warm halo under warm
  digits), not a generic white bloom.
- **When NOT to use:** glow is focal — reserve it for the ONE hero element on a
  dark field. Glow on every card, on body text, or on a light surface is neon
  clutter, the exact cliché the critic gates. Not a substitute for elevation
  (that's a shadow) or depth (that's blur).

A dark-field numeral hero with a warm halo (validated):
```text
numeral text "3.2s" p(0,0) s(888,hug) font("Archivo Black",300,400,left) fill(linear(120, stop(#f5d020,0), stop(#f5380a,1))) glow(numeral_halo, #f5a020, o(0.5), blur(56), spread(2)) lh(0.92) max_lines(1)
```

## Layer blur — depth and backdrop washes

A gaussian blur of the node's **own** rendering. Two forms — a bare shorthand and
the id + radius channel:

```text
blur(12)                 # auto id, radius 12
blur(blur_soft, r(12))   # optional id, r(...) radius channel
```

- Malformed → `LUMD0267` (hint: `blur(12) or blur(blur_soft,r(12))`).
- **When to use, sparingly:** a **backdrop wash** — a single soft color orb behind
  the content that reads as depth, not a decorative blob. Blur the backdrop shape,
  never the foreground type. One washed shape per design; it is atmosphere, not an
  element.
- **When NOT to use:** blurring content the reader needs (headlines, logos,
  photos), or stacking several blurred shapes into mush. Backdrop-blur /
  glassmorphism (blurring *what is behind* a node) is not in v1 — this blurs the
  node itself.

A blurred backdrop orb behind a headline (validated):
```text
orb e p(520,120) s(520,520) fill(radial(stop(#3b5bdb,0), stop(#0b1120,1))) blur(72)
```

## Inner shadow — pressed and inset surfaces

The exact mirror of `shadow(...)`, but the shadow falls **inward** and `spread`
erodes inward — the surface reads as recessed:

```text
inner_shadow(#000000, o(0.4), x(0), y(4), blur(8), spread(0))
inner_shadow(inner_soft, #000000, o(0.4), x(0), y(4), blur(8), spread(0))   # optional id
```

- Same channels as `shadow` (`o`, `x`, `y`, `blur`, `spread`); the CSS positional
  alias works too. Malformed → `LUMD0268`
  (hint: `inner_shadow(inner_soft,#000000,o(0.4),x(0),y(4),blur(8),spread(0))`).
- **When to use:** a **pressed well** for a stat or input-like surface (a value
  seated *into* the field), or a subtle top-inner darkening as a photo **vignette**.
  A small downward `y` with a soft `blur` sells "inset".
- **When NOT to use:** on floating cards or buttons that should read as *raised* —
  that's a drop shadow. Don't stack inner + drop on the same surface hoping for
  "depth"; pick one physical story.

A pressed value well (validated):
```text
well al(v,x(c),y(c),g(6),pad(56,64)) p(0,0) s(888,320) fill(#d8d2c4) rd(28) inner_shadow(well_inset, #000000, o(0.35), x(0), y(6), blur(18), spread(0))
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
`stroke($border.default, $stroke.width.card)`. (Strokes render fully on shapes;
**text** strokes are dropped with `LUME0214` — see *The effect stack*.)

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

### The soft radial wash (minimal-luxury surface treatment)

A radial gradient from a lighter brand tone at the center to a darker one at the
edge reads as a lit field, not a flat fill. Stops accept `#RRGGBBAA` alpha, so you
can fade a tint into a base surface:

```text
# light center bleeding into a dark brand field:
field r p(0,0) s(1080,1080) fill(radial(stop(#177a5b,0), stop(#06231a,1)))
# a translucent tint wash over an existing surface (alpha stops):
wash r p(0,0) s(1080,1080) fill(radial(stop(#f5d02033,0), stop(#f5d02000,1)))
```

**Two ways to make the wash bleed — pick by intent:**

1. **Full-frame rect** — a rect *exactly* the frame size (`s(1080,1080)` on a
   1080² root). The falloff runs to the canvas edges, so the bright center reads as
   a spotlight, not a contained circle. Nothing bleeds off-canvas, no warning.
2. **True off-canvas bleed** — an oversized shape that actually extends past the
   frame, tagged `bleed(true)`. This declares off-canvas intent and **downgrades**
   the `LUMV0801` parent-bounds error to a warning ("off-canvas extent declared as
   bleed; content outside the page is not exported"). Without `bleed(true)` an
   oversized shape is a hard `LUMV0801` error — this flag is the only sanctioned
   way to bleed a shape past the page.

An off-canvas spotlight ellipse (validated — preflights with the LUMV0801 warning,
not an error):
```text
wash e p(-280,-280) s(1640,1640) fill(radial(stop(#1f8a66,0), stop(#06231a,1))) bleed(true)
```

Use the full-frame form when you want a lit field that fills the surface; use
`bleed(true)` when the shape's geometry (an ellipse, a rotated band) genuinely
overhangs the edge. Either way this is the opposite of the cliché — NOT a small
low-opacity circle drifting behind content (see `knowledge/design/foundations`).
Reserve it for numeral-hero, image-hero, and emblem fields
(`knowledge/design/layout-recipes`).

## Per-corner radius

`rd(...)` takes **1 or 4** arguments:

```text
rd(16)                 # uniform radius (number or $radius.* token)
rd(40, 40, 12, 12)     # per-corner, CSS clockwise from top-left: tl, tr, br, bl
```

- Four-arg order is **top-left, top-right, bottom-right, bottom-left** (CSS
  clockwise). Any other arity → `LUMD0230`
  (hint: `rd(8) for a uniform radius or rd(tl,tr,br,bl) for per-corner radii`).
- **Corner values are ≥ 0** — `0` is a square corner, so `rd(12,12,0,0)` rounds
  only the top (the tab/welded-card idiom). Negative values are rejected with
  `LUMD0255`. Uniform `rd($radius.*)` tokens still resolve; per-corner takes raw
  numbers.

A card with generous top corners and tight bottom corners (validated):
```text
card al(v,x(s),y(c),g(14),pad(56,56)) p(0,0) s(888,440) fill(#ffffff) rd(40,40,12,12) shadow(#000000, o(0.12), y(14), blur(36))
```

## Fill opacity — `solid(color, opacity)`

`solid(...)` takes an optional second argument that multiplies into the color's
alpha — no separate scrim node needed:

```text
fill(solid(#ffffff))            # opaque
fill(solid(#ffffff, 0.5))       # bare-number opacity
fill(solid(#f5d020, o(0.16)))   # o(...) / opacity(...) form — both accepted
```

- Opacity must be in `0..=1`; out of range, an unreadable hex, or a token color
  (bake the alpha into the token instead) → `LUMD0270`
  (hint: `solid(#ffffff) or solid(#ffffff,0.5)`).
- Multiplies onto any hex/oklch alpha the color already carries; the paint stays a
  plain solid, so exports are unchanged. Use it for a **translucent tint or plate**
  that lets the field show through, instead of a separate overlay rect.

A translucent plate over a radial field (validated):
```text
plate al(v,x(c),y(c),g(16),pad(64,64)) p(140,340) s(800,400) fill(solid(#ffffff, 0.92)) rd(32)
```
