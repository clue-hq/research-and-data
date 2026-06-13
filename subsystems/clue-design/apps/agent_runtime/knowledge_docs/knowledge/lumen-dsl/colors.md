# Lumen DSL — Colors & Paint

Every color argument (fills, strokes, shadows, gradient stops) accepts the same
forms. **A color is never a bare number** (`fill(4)` → `LUMD0219 invalid color`).

## Color forms

| Form | Example | Notes |
|------|---------|-------|
| 6-digit hex | `#00897b` | opaque |
| 8-digit hex (alpha-first input) | `#19000000` | input is `#AARRGGBB`; stored canonical `#RRGGBBAA` (here `#00000019`, ~10% black) |
| Brand token | `$surface.brand` | resolved by preflight against the effective Brand Kit |
| oklch | `oklch(0.72,0.14,250,1)` | `l,c,h` and optional alpha (3–4 args; else `LUMD0218`) |
| CSS rgb / rgba | `rgb(0,137,123)` · `rgba(0,0,0,0.10)` | compatibility alias, lowered to hex; channels 0–255 or `NN%`, alpha 0–1 |

Prefer `$tokens` in branded designs, then 6-digit hex, then `#AARRGGBB`/`rgba`
for translucency. `oklch` is available when you need perceptual control.

## Translucency

Two equivalent ways to dim a fill:

```text
fill(#00000019)        # alpha baked into the color (#RRGGBBAA, ~10% black)
fill(#000000) o(0.1)   # opaque color + node opacity
```

For a *shadow* the alpha rides in the color, e.g. `shadow(#000000, o(0.12), …)`
or `shadow(0,8,24,#1f000000)`.

## Gradients

```text
fill(linear(135, stop(#ffffff,0), stop(#e7f0ef,1)))
fill(radial(stop(#ffffff,0), stop(#0b3d2e,1)))
```

- `linear(angle, stop(color,pos), …)` — angle in degrees, ≥1 stop (`LUMD0239`).
- `radial(stop(color,pos), …)` — ≥1 stop (`LUMD0240`).
- Each stop is `stop(color, position)` with `position` in `0..1` and `color` in
  any form above. A bare number as a stop color → `LUMD0219`.

## Fill stacks and strokes

```text
panel fr s(400,200) f[(#ffffff),(linear(180,stop(#ffffff00,0),stop(#00000010,1)))]
divider r s(400,1) fill(#e0e0e0)
card fr s(400,200) fill(#ffffff) stroke(#111827,2)
```

- `f[...]` is an ordered fill stack (bottom→top); each entry is `paint` or
  `(id,paint)`. Empty tuple → `LUMD0213`.
- Basic stroke is `stroke(color,width)`. For dashes/caps/joins/alignment see
  `skills/effects` and the extended stroke grammar.

## Common slips (now accepted as aliases — but the canonical form is preferred)

- `rgba(0,0,0,0.10)` → accepted (lowered to `#0000001a`). Prefer `$token` or
  `#AARRGGBB` in new work.
- A trailing `rgba(...)` inside a positional shadow is recognized as the shadow
  color: `shadow(0,4,24,rgba(0,0,0,0.10))` compiles.
