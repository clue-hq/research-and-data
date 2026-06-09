# Lumen DSL Authoring Guide

Status: supported now, recognized but not lowered, and future scaffold.

## Supported Now

Lumen DSL is a compact authoring surface that compiles into canonical scene
operations. The scene and operation log are the source of truth.

Use DSL for initial composition and small repairs:

- explicit page IDs
- stable node IDs
- two-space indentation
- one visual element per line
- shallow containers
- semantic slots
- concrete colors or brand token references
- `hug` text height when copy may vary
- `fill` dimensions only inside layout contexts that can resolve them

Supported common lines:

```text
page page_a4 preset(a4,portrait)
  hero fr p(32,32) s(520,260) fill($surface.card) rd($radius.lg)
    headline text "A focused message" p(24,24) s(460,hug) style($type.headline) slot(campaign.headline)
    body text "Support copy." p(24,112) s(440,hug) style($type.body) slot(offer.primary_message)
```

For square ads or custom sizes, prefer an explicit page-size form once the DSL
supports it. Until then, use supported presets and record a product gap when a
requested aspect ratio cannot be expressed faithfully.

## Recognized But Not Lowered

The compiler recognizes some future syntax and warns instead of silently
dropping it:

- richer edit directives such as `before`, `after`, `clone`, and `replace`
- some alignment anchors
- some paint/effect tuple extras
- granular tokenized font-size fields where no precise carrier exists

If a repair needs one of these, do not invent Python-side mutation. Record a
gap or use checked structured operations when the target is exact.

## Future Scaffold

Future DSL work should add:

- explicit arbitrary page dimensions
- richer targeted edit directives
- reusable component instances
- chart/table primitives
- richer text spans and typography controls
- safer asset acquisition and image-generation directives

