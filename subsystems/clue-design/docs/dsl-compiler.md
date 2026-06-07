# DSL Compiler

This workstream adds a Blueprint-inspired authoring language for agents and humans.

The DSL is not the document source of truth. `Scene` remains the canonical runtime model, and `Operation` remains the canonical mutation/history surface. DSL text compiles into structured operations.

## Boundary

This branch owns:

- normalization of line-based DSL text
- parsed AST types for pages, elements, directives, target-reference modify lines, and visual properties
- structural parser diagnostics with line spans
- cascade halt on the first parse/lowering error
- partial operation output before the halt
- lowering supported create lines into `AddPage` and `InsertNode`
- lowering lightweight `slot(...)` and `meta(slot="...")` annotations into `UpsertSlot` and `BindNodeToSlot`
- lowering `delete(...)` and `parent(...)` into core operations
- native and `wasm32-unknown-unknown` compatibility through `lumen-core`

This branch does not own:

- making DSL the persisted document format
- rich page/export/brand/slot metadata in DSL
- Taffy layout solving
- token resolution or brand-kit semantics
- conditional/repeater runtime behavior
- modify-line lowering
- clone/replace/ungroup/before/after/undo/redo lowering
- render-preview critique or agent orchestration

## Compiler Pipeline

The exposed entry points are:

- `normalize_dsl(source)` for stable text normalization.
- `parse_dsl(source)` for AST and diagnostics without operation lowering.
- `compile_dsl(source)` for AST plus operations.
- `compile_dsl_into_scene(source, scene)` for checked application through the core operation engine.

The pipeline follows the Brilliant-derived shape:

```text
source text
  -> normalize
  -> parse typed lines
  -> validate local grammar/tree rules
  -> lower supported semantics to operations
  -> apply through checked core operations when requested
```

Diagnostics use `Phase::Dsl`, stable `LUMD...` codes, and one failing line span. Unsupported constructs are errors, not silent ignores.

## Grammar Contract

The grammar is intentionally terse but not toy-sized. It covers the important Blueprint grammar surface captured in the reverse-engineering report, then lowers only the subset that has stable scene/operation semantics today.

Line types:

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

Containers:

```text
page
frame / fr
group / gr
autolayout / al
```

Leaf nodes cannot have children.

Supported properties:

```text
p(x,y)
s(width,height)
fill(paint)
f[(paint_id,paint),...]
stroke(paint,width)
st[(stroke_id,paint,w(width)),...]
font("family",size,weight,align)
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
token(...) / ds(...) / color(...)
```

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

Supported colors:

```text
#RRGGBB
#AARRGGBB
$token.path
oklch(l,c,h)
oklch(l,c,h,a)
```

Supported directives:

```text
delete(node_id)
parent(node_id,parent_id[,index])
parent(node_id,page:page_id[,index])
```

Parsed but not lowered in this branch:

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

These are represented in the AST or parser and produce explicit DSL diagnostics instead of being silently ignored. That preserves the language surface without inventing operation semantics before the relevant workstreams.

## Brilliant-Inspired Rules

- One visual element per line.
- Stable explicit IDs are required for nodes, pages, paints, slots, and assets.
- Two-space indentation only.
- Indentation creates parent/child structure.
- Containers only: `page`, `frame/fr`, `group/gr`, and `autolayout/al`.
- Leaf nodes cannot have children.
- Diagnostics point to one failing line.
- Cascade halt stops at the first failing parse or lowering line.
- Valid operations before the halt are preserved.
- Comments beginning with `//` are checkpoints.
- `#target ...` lines are target-reference modify syntax; plain `# comment` lines are comments.
- Rich page/export/brand/slot configuration stays in scene JSON and operations.

## Lowering Notes

Creation lines lower directly into `Operation::InsertNode` under the parent implied by indentation. Page lines lower into `Operation::AddPage`.

Slot annotations derive deterministic slot IDs using `slot_` plus a stable sanitized suffix from the slot key. Example:

```text
slot(campaign.headline) -> slot_campaign_headline
```

Image, vector, and instance required references may come from either kind-call arguments or properties:

```text
logo img asset(account_logo)
icon vector path("M0 0L16 16Z")
copy instance source(card)
```

Token syntax is parsed but unresolved. The compiler emits warnings for design-system token declarations/properties because actual token resolution belongs to `brand-kit/tokens-v0`.

## Fixtures

DSL fixtures live under:

```text
crates/lumen-core/fixtures/dsl
```

Current fixture coverage includes:

- valid brochure-style ABM layout
- broad Blueprint-inspired language surface
- invalid indentation
- invalid leaf-child nesting
- invalid slot key
- unsupported directive cascade halt

## Downstream Implications

`engine/slots-layout` can consume the slot annotations and scene output but should own fit, overflow, conditionals, repeaters, and layout behavior.

`brand-kit/tokens-v0` should consume parsed token syntax and scene paint/style tokens but should own token catalogs and resolution.

`agents/design-loop-v0` can use `compile_dsl` for agent-authored create blocks and can rely on precise line diagnostics plus partial operation preservation for repair loops.
