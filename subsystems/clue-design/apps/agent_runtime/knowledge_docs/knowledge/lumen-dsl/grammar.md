# Lumen DSL — Grammar Reference

The compact, precise reference for the Lumen DSL surface. DSL text compiles into
canonical `Scene` operations. It is line-oriented and indentation-sensitive.

## Line shapes

```
line       = indent , ( checkpoint | comment | page | element | directive | modify )
indent     = { "  " }                 # exactly two spaces per level
checkpoint = "//" text                # labeled history anchor
comment    = "#"  text                # ignored (note: a leading "#ref" is a modify line, not a comment)
page       = "page" id [ page_property* ]
element    = id kind property*  |  kind id property*    # either order
directive  = verb "(" args ")"        # delete / parent / clone / replace / ungroup / …
modify     = "#" ref property*        # targeted edit of an existing object
```

Rules: two spaces per indent level (`LUMD0301`); never indent more than one level
deeper than the parent (`LUMD0302`); only containers may hold children
(`LUMD0304`); `page` lines must be top-level (`LUMD0305`).

## Page header

```text
page page_a4 preset(a4,portrait)          # preset(name, orientation?)
page story size(1080,1920,px)             # size(width, height, unit)
```

- Presets: `a4`, `us_letter`, `linkedin_ad`, `envelope_dl`, `custom`
  (unknown → `LUMD0223`). Orientation: `portrait` | `landscape` (unknown →
  `LUMD0224`); A4/Letter default portrait, ad/envelope default landscape.
- Units: `px`, `mm`, `in`/`inch` (unknown → `LUMD0252`). Dimensions must be
  positive (`LUMD0251`). `size(...)` needs all three args (`LUMD0250`).
- Presets are shortcuts only. **Never fake a square ad as a square frame inside an
  A4 page** — set the page size.

## Node kinds

Containers (may have children): `frame`/`fr`, `group`/`gr`, `autolayout`/`al`.
Leaves (no children, `LUMD0304` if nested): `rect`/`r`, `ellipse`/`e`/`c`,
`line`/`l`, `text`/`t`, `image`/`img`, `vector`/`v`, `svg`, `instance`/`inst`.

```text
hero fr p(0,0) s(595,160) fill(#ffffff) rd(16)
  title text "Welcome" p(24,24) s(440,hug) font("Inter",28,700,left)
```

Unknown kind → `LUMD0206`. Duplicate node id → `LUMD0401`. Node outside a
page/container → `LUMD0402`. `image` needs `asset(id)` (`LUMD0403`); `vector`
needs `path("…")` (`LUMD0404`); `instance` needs `source(id)` (`LUMD0405`).

## Property catalogue

Geometry and box:

| Property | Arity | Meaning |
|----------|-------|---------|
| `p(x,y)` | 2 | position (px) |
| `s(w,h)` / `s(w,h,unit)` | 2–3 | size; `w`/`h` are a number, `hug`, `fill`, `fill(weight)`, `fill:weight`, or `$token` |
| `rd(r)` / `radius(r)` | **1** | uniform corner radius — **4-arg per-corner is NOT supported** (→ `LUMD0230`) |
| `o(a)` / `opacity(a)` | 1 | node opacity |
| `rot(deg)` / `rotation(deg)` | 1 | rotation |
| `sk(x,y)` / `skew(x,y)` | 2 | skew |
| `flip(axis)` | 1 | `x`/`horizontal`, `y`/`vertical`, `both`/`xy`, `none` |
| `clip(bool)` | 1 | clip children |

Paint and effects (see `colors.md` and `skills/effects`):

| Property | Meaning |
|----------|---------|
| `fill(paint)` | single fill |
| `f[(id,paint),(paint),…]` | ordered fill stack |
| `background(paint)` / `bg(paint)` | page/container background |
| `stroke(paint,width)` or extended `stroke(id?,paint,w(),dash(),cap(),join(),align())` | stroke |
| `shadow(color,o(),x(),y(),blur(),spread())` or `shadow(x,y,blur[,spread],color)` | drop shadow |

Text (see `text.md`):

`text("…")`/`content`, `font("family",size,weight,align)` or `font($type.x)`,
`font_size`, `font_weight`, `style($type.x)`, `lh`, `ls`, `tracking`,
`wrap_text(bool)`, `max_lines(n)`, `dir(ltr|rtl|auto)`.

Auto-layout (on `al` containers; see `layout.md`):

`al(v|h, x(anchor), y(anchor), g(gap), pad(...), grow(n), wrap(bool))` where
anchor ∈ `start`/`s`, `center`/`c`, `end`/`e`, `space_between`/`sb`,
`stretch`/`st`.

Slots / ABM (see `knowledge/design-systems`):

`slot(key)`, `label("…")`, `required(bool)`, `placeholder("…")`, `sample("…")`,
`worst_case("…")`, `bind(node)`, `unbind(node)`.

Assets / vectors: `asset(id)`, `path("…")`, `source(node)`, `to(x,y)` (line end).

Any other property name → `LUMD0212 unknown property`. A property used on the
wrong node kind warns (e.g. `font(...)` on a non-text node → `LUMD0601`).

## Two ways to change an existing scene

1. **Continuation** — append new nested element lines under an existing container
   (do not re-declare the page).
2. **Modify line** — `#<ref> prop(...)` edits an existing object in place. Refs:
   `#node_id`, `#page:id`, `#slot:key`, `#asset:id`, `#export:name`, `#document`.
   ```text
   #headline s(440,hug) font_size(22)      # resize + shrink one node
   #card s(400,520)                        # make the card taller to fix overflow
   ```

See `directives.md` for modify/delete/parent/clone/replace and
`diagnostics.md` for the full code map.
