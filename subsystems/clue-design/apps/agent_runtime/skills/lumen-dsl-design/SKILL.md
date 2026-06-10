---
name: lumen-dsl-design
description: Use when creating, repairing, reviewing, or explaining Lumen design artifacts with the Lumen DSL, including ABM artifacts, brand tokens, slots, compile diagnostics, SVG preview, and preflight repair loops.
---

# Lumen DSL Design

Use this skill to author Lumen designs through the current Lumen DSL. The goal
is to produce DSL that compiles cleanly into `Scene` operations, respects
Lumen's scene/operation/slot architecture, and creates useful brand-aligned
artifacts for the prompt -> DSL -> preflight -> SVG preview -> repair loop.

## Core Model

Lumen DSL is an authoring surface, not the canonical document model.

- `Scene` is the canonical runtime model.
- `Operation` is the canonical mutation/history surface.
- DSL text compiles into structured operations.
- DSL should create visual structure, describe layout, reference tokens, and
  assign lightweight slot marks.
- Rich configuration belongs in scene/document metadata, not in DSL.

Do not use DSL as the only source of truth for full Brand Kit configuration,
export profiles, full page metadata, slot validation fixtures, repeaters,
conditionals, font licensing, production asset storage, or ABM binding metadata.

## Required Reference Loading

Before nontrivial DSL work, ask the coordinator to load relevant excerpts from:

- `docs/dsl-compiler.md`
- `docs/agents-design-loop.md`
- `docs/preflight-pipeline.md`
- `reference_docs/ABM-Design-Engine-Temporary-Spec.md`
- `reference_docs/Brilliant-Reverse-Engineering-Report.md`
- `reference_docs/Brilliant-vs-Lumen-Product-Gap-Analysis.md` when present

## Lumen DSL Rules

The DSL is line-oriented and indentation-sensitive.

```text
line       = indent , ( checkpoint | comment | page | element | directive | modify )
indent     = { "  " }
checkpoint = "//" text
comment    = "#" text
page       = "page" id [ page_property* ] | "page(" id ")"
element    = kind id property* | id kind property*
directive  = verb "(" args ")"
modify     = "#" ref property*
```

Use exactly two spaces per indentation level. One visual element should occupy
one line. Parent-child structure is created by indentation. Only containers can
have children.

Containers:

```text
page
frame / fr
group / gr
autolayout / al
```

Leaf nodes cannot have children.

Supported element kinds:

```text
frame | fr
group | gr
autolayout | al
rect | r
ellipse | e | c
line | l
text | t
image | img
vector | v
svg
instance | inst
```

## Supported Properties

Use only supported properties:

```text
page page_id size(width,height,px|mm|in)
page page_id preset(a4|us_letter|linkedin_ad|envelope_dl,portrait|landscape)
p(x,y)
s(width,height)
fill(paint)
f[(paint_id,paint),...]
stroke(paint,width)
st[(stroke_id,paint,w(width)),...]
font("family",size,weight,align)
font_size(size)
font_weight(weight)
style($type.token)
lh(value)
ls(value)
tracking(value)
max_lines(count)
wrap_text(true|false)
dir(ltr|rtl|auto)
slot(key)
meta(slot="key")
asset(asset_id)
path("svg path data")
source(node_id)
rd(radius) / radius(radius)
o(opacity) / opacity(opacity)
rot(degrees) / rotation(degrees)
sk(x,y) / skew(x,y)
flip(x|y|both|none)
clip(true|false)
gap(value) / g(value)
pad(all) / pad(vertical,horizontal) / pad(top,right,bottom,left)
x(anchor) / y(anchor)
wrap(true|false)
grow(value)
to(x,y)
name("display name")
```

Prefer canonical `font(...)`, `lh(...)`, and `ls(...)` in new designs.
`font_size(...)`, `font_weight(...)`, and `tracking(...)` are compatibility
aliases for targeted repairs when a model has already drifted into common
design-tool language. `tracking(200)` is interpreted as design-tool tracking,
roughly `0.2em`, not `200px`.

Supported dimensions:

```text
number
hug
fill
fill(weight)
fill:weight
```

Supported paints:

```text
#RRGGBB
#AARRGGBB
$token.path
solid(color)
linear(angle,stop(color,position),...)
radial(stop(color,position),...)
```

Eight-digit DSL hex follows Brilliant/Flutter alpha-first syntax:

```text
#AARRGGBB
```

The compiler normalizes this into scene/export color order. Prefer six-digit
hex plus `o(opacity)` unless alpha is necessary.

## Token Guidance

Use token references when the design should be brand-resolved:

```text
fill($surface.brand)
stroke($surface.brand,$stroke.width.firm)
g($space.md)
pad($space.md)
rd($radius.md)
o($opacity.subtle)
style($type.headline)
font($type.headline)
```

The DSL compiler lowers token references into scene token carriers where a
precise field exists. Brand Kit resolution and fallback behavior happen in
preflight.

Avoid ambiguous token forms where the scene contract has no precise carrier:

```text
font("Inter",$type.size.heading,700,left)
```

Prefer:

```text
style($type.headline)
```

## Slot Guidance

Slots are lightweight semantic annotations in DSL. Use them for future ABM
binding points.

Good slot keys:

```text
contact.full_name
contact.title
account.name
account.logo
account.industry
campaign.headline
campaign.cta
offer.primary_message
research.key_insight
sender.signature
```

Example:

```text
headline text "A sharper plan for patient acquisition" p(24,24) s(420,hug) style($type.headline) slot(campaign.headline)
logo img asset(account_logo) p(24,260) s(96,48) slot(account.logo)
```

Do not encode rich slot behavior in DSL. Required/optional status, overflow
policy, samples, fit policy, repeaters, and conditionals belong in slot
metadata and runtime validation.

## Layout Guidance

Prefer shallow semantic structure. Use frame fills for backgrounds rather than
decorative background rectangles when the background is part of a container.

Good:

```text
hero fr p(24,24) s(480,220) fill(#ffffff) rd(16)
  headline text "Plan" p(24,24) s(420,hug) font("Inter",54,800,left)
```

Use `autolayout` / `al` when sibling spacing should be systematic:

```text
page linkedin_square size(1080,1080,px)
  stack al(v,g(16),pad(24),x(s)) p(64,64) s(560,hug) fill($surface.card) rd($radius.lg)
    headline text "Pipeline-ready outreach" p(0,0) s(fill,hug) style($type.headline) lh(1.08) wrap_text(true) max_lines(2)
    body text "A concise account-specific message." p(0,0) s(fill,hug) style($type.body) lh(1.35) wrap_text(true) max_lines(3)
```

Use `hug` for text height when content may vary. Use `fill` only when parent
layout can resolve it. Keep text boxes wide enough for the actual copy. Use
`x(sb)` for row distribution, `x(c),y(c)` for centered buttons, and
`wrap_text(true)` for any text that could vary by account/contact.

## Directives

Currently supported lowering:

```text
delete(node_id)
parent(node_id,parent_id[,index])
parent(node_id,page:page_id[,index])
```

Parsed or recognized but not production-lowered in the current compiler:

```text
before(...)
after(...)
clone(...)
replace(...)
ungroup(...)
undo(...)
redo(...)
ds(...)
#target property...
svg(icon:name)
solid(color,o(opacity))
stroke cap/position tuple extras
```

Do not rely on unsupported constructs in final generated DSL. Use structured
operations or state the limitation.

## Diagnostic And Repair Behavior

The compiler uses cascade halt:

- lines before the failing line may be preserved
- the failing line is not applied
- lines after the failing line are discarded
- diagnostics use stable `LUMD...` codes
- repair should continue from the failed line, not rewrite the entire design
  unless the design direction is wrong

When repairing an existing scene, do not emit an existing `page ...` line again
unless the coordinator explicitly asks for a full replacement. Do not reinsert
existing node IDs as new elements. If diagnostics identify a target node, page,
or slot, repair only that target or its immediate container and preserve
unrelated nodes.

When using `DslCompileSession`, preserve session context across repair blocks.
Do not reset the session unless starting a new design or a structured operation
edit intentionally invalidates DSL parser context.

## Design Quality Checklist

Before finalizing DSL, check:

- IDs are stable, descriptive, and unique.
- Indentation uses two spaces only.
- Leaf nodes have no children.
- Containers are meaningful and not empty.
- Text has explicit size and typography.
- Text that may vary uses `hug` height or enough fixed space.
- Slot keys are semantic and stable.
- Brand-sensitive values use tokens when a Brand Kit is expected.
- Concrete fallback values are acceptable when no Brand Kit is available.
- Fills belong on frames when they are backgrounds.
- Layout spacing is systematic, not random.
- No unsupported directives are used.
- The output is small enough for compile diagnostics and repair.

## Agent Behavior

When asked to create a Lumen design:

1. Return DSL first unless the coordinator asks for explanation.
2. Keep DSL syntactically conservative.
3. Prefer supported compiler semantics over aspirational syntax.
4. Use slots for ABM placeholders.
5. Use token references for brand-aligned variants.
6. Use concrete colors/type only when no Brand Kit is available.
7. After compile/preflight diagnostics, repair the smallest failing block.
8. Never silently ignore diagnostics.
9. Do not mutate scene semantics directly from DSL beyond supported operations.
10. If visual preview is available, use review feedback to repair spacing,
    hierarchy, contrast, clipping, overflow, and slot fit before declaring the
    design complete.
