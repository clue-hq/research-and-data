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
| `font_size(n)` | `font-size` | alias — size only |
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

`align` is the **only** alignment knob and it is horizontal. Vertical centering is
an auto-layout `y(c)` on the parent (see `layout.md`). There is no `valign`.

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
