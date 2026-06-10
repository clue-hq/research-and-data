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
page page_square size(1080,1080,px)
  hero fr p(32,32) s(520,260) fill($surface.card) rd($radius.lg)
    headline text "A focused message" p(24,24) s(460,hug) style($type.headline) wrap_text(true) max_lines(2) slot(campaign.headline)
    body text "Support copy." p(24,112) s(440,hug) style($type.body) wrap_text(true) slot(offer.primary_message)
```

Custom page dimensions are supported. Use `size(width,height,unit)` whenever
the user specifies an output ratio or exact surface:

```text
page linkedin_square size(1080,1080,px)
page story_ad size(1080,1920,px)
page print_page preset(a4,portrait)
```

Presets are shortcuts only. Do not fake a square ad by drawing a square frame
inside an A4 page.

Auto-layout anchors are supported:

```text
nav al(h,x(sb),y(c),g(16),pad(24)) p(40,40) s(1000,hug)
stack al(v,x(s),g(18),pad(40)) p(64,64) s(520,hug)
button al(h,x(c),y(c),pad(12,24)) p(64,860) s(220,56)
```

For text, use explicit fit controls when copy length matters:

```text
headline text "Let neurosurgeons focus on surgery." p(64,88) s(620,hug) style($type.headline) lh(1.08) wrap_text(true) max_lines(2)
body text "Insight Health handles calls, scheduling, and patient routing." p(64,240) s(600,hug) style($type.body) lh(1.35) wrap_text(true) max_lines(3)
```

Canonical typography syntax is preferred:

```text
headline text "Message" p(64,88) s(620,hug) font("Inter",42,700,left) lh(1.08) ls(0.2)
```

Compatibility aliases are accepted for common model slips, especially in
targeted repairs:

```text
headline text "Message" p(64,88) s(620,hug) font_size(42) font_weight(700) tracking(120)
```

`tracking(...)` uses design-tool tracking units when the value is large:
`tracking(200)` becomes roughly `0.2em` letter spacing. Prefer `ls(...)` for
explicit pixel letter spacing in new compositions.

## Repair Rules

When repairing an existing scene:

- Do not emit an existing `page ...` line again unless the repair request says
  the coordinator is replacing the whole scene.
- Do not reinsert existing node IDs as new elements.
- If diagnostics name a node/page/slot target, repair only that target or its
  immediate container.
- If the repair request recommends `structured_ops`, use checked operations
  through the coordinator when possible. If the current authoring step only
  allows DSL, return the smallest non-duplicating DSL continuation and preserve
  current page dimensions.

## Recognized But Not Lowered

The compiler recognizes some future syntax and warns instead of silently
dropping it:

- richer edit directives such as `before`, `after`, `clone`, and `replace`
- some paint/effect tuple extras
- granular tokenized font-size fields where no precise carrier exists

If a repair needs one of these, do not invent Python-side mutation. Record a
gap or use checked structured operations when the target is exact.

## Future Scaffold

Future DSL work should add:

- richer targeted edit directives
- reusable component instances
- chart/table primitives
- rich text spans and typography controls beyond line height, letter spacing,
  wrap, max lines, and direction
- safer asset acquisition and image-generation directives
