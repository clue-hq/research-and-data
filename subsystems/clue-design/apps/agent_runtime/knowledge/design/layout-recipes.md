# Lumen Layout Recipes

Status: supported now, recognized but not lowered, and future scaffold.

## Supported Now

Use these conservative recipes for product-quality ABM artifacts.

### Square Social Ad

Use a single clear message, one CTA, and generous margins. Keep text away from
edges and avoid oversized typography until preview validation confirms the page
is actually square.

Recommended structure:

- page
- background frame
- message stack
- CTA pill or button
- brand/offer proof point
- optional simple vector/shape motif

### A4 One-Pager Section

Use sections with clear vertical rhythm. Make headings shorter than the
available text box and use `hug` height for body copy.

### Email Hero

Use a compact header, a large headline, one supporting sentence, and a CTA.
Avoid detailed small text because current preview/export quality is not meant
for final email-client rendering.

### Direct Mail Header/Postcard

Use print-safe margins, visible brand block, recipient/account slot, and a
single concrete reason to respond. Avoid complicated pagination in Phase A.

## Recognized But Not Lowered

Some alignment and distribute behaviors are parsed or planned but not fully
available to agents yet. If the model needs center/end/space-between semantics,
prefer explicit positions or record a layout gap.

## Future Scaffold

Future layout docs should include:

- responsive/variant recipes
- repeater/conditional regions
- dense stat/table modules
- multi-page brochures
- pagination rules
- editorial grid systems

