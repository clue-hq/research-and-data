# Typography And Composition

Status: supported now, recognized but not lowered, and future scaffold.

## Supported Now

Current Lumen text support can produce useful previews when the agent stays
conservative:

- Use short headlines.
- Keep headline boxes wide enough for expected copy.
- Prefer `style($type.headline)` and `style($type.body)` when a Brand Kit is
  available.
- Use `hug` height for text likely to wrap, or make fixed-height boxes large
  enough for measured line height.
- Use `wrap_text(true)` on body copy and long headlines.
- Use `max_lines(...)` on ad headlines and compact cards so overflow is
  diagnosed early.
- Use `lh(...)` for hierarchy: tighter headlines such as `lh(1.05)` to
  `lh(1.15)`, relaxed body copy such as `lh(1.3)` to `lh(1.45)`.
- Use `ls(...)` sparingly; positive values can widen labels and increase
  overflow risk.
- Use `dir(rtl)` only when the content is truly right-to-left. Phase B records
  direction, but full bidi shaping remains future work.
- Keep body text at readable sizes.
- Avoid placing text partially outside parent frames.
- Use high contrast and simple hierarchy.

Good text box patterns:

```text
headline text "Let neurosurgeons focus on surgery." p(64,88) s(620,hug) style($type.headline) lh(1.08) wrap_text(true) max_lines(2)
body text "Insight Health handles calls, scheduling, and patient routing." p(64,240) s(600,hug) style($type.body) lh(1.35) wrap_text(true) max_lines(3)
cta_text text "Book a Demo" p(0,0) s(fill,hug) style($type.cta) max_lines(1)
```

Bad patterns:

```text
headline text "Very long headline..." p(40,40) s(300,24) font("Inter",64,800,left)
body text "Long paragraph..." p(40,120) s(300,24) font("Inter",18,400,left)
```

Those compile, but Phase B layout should flag overflow and the visual critic
should request a layout repair.

For Phase A visual quality, a reviewer should reject:

- clipped text
- text that crosses frame boundaries
- long lines that run off the page
- tiny unreadable supporting copy
- decorative type that reduces clarity

## Supported But Heuristic

Phase B supports line height, letter spacing, wrap, max lines, and text
direction in the scene contract and DSL. Measurement is deterministic and
shared by layout/export/diagnostics, but it is still heuristic. Do not treat it
as final browser/PDF font shaping.

## Future Scaffold

Future typography work should add:

- non-Latin and RTL shaping
- rich text spans
- print/PDF font embedding and subsetting
