# Typography And Composition

Status: supported now, recognized but not lowered, and future scaffold.

## Supported Now

Current Lumen text support can produce useful previews when the agent stays
conservative:

- Use short headlines.
- Keep headline boxes wide enough for expected copy.
- Prefer `style($type.headline)` and `style($type.body)` when a Brand Kit is
  available.
- Use `hug` height for text likely to wrap.
- Keep body text at readable sizes.
- Avoid placing text partially outside parent frames.
- Use high contrast and simple hierarchy.

For Phase A visual quality, a reviewer should reject:

- clipped text
- text that crosses frame boundaries
- long lines that run off the page
- tiny unreadable supporting copy
- decorative type that reduces clarity

## Recognized But Not Lowered

The engine does not yet have product-grade line-height, letter-spacing,
hyphenation, bidi/RTL shaping, rich spans, or final print metrics. Do not rely
on the model to visually guess these perfectly.

## Future Scaffold

Future typography work should add:

- line-height and letter-spacing DSL fields
- robust text measurement and fitting
- non-Latin and RTL shaping
- rich text spans
- print/PDF font embedding and subsetting

