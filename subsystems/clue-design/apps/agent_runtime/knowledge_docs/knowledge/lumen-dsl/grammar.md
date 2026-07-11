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
- Units: `px`, `mm`, `in`/`inch`, `pt` (unknown → `LUMD0252`). Dimensions must
  be positive (`LUMD0251`). `size(...)` needs all three args (`LUMD0250`).
  New page commands normalize to canonical `pt` artboard bounds while preserving
  the requested source/export size.
- Presets are shortcuts only. **Never fake a square ad as a square frame inside an
  A4 page** — set the page size.
- Child `p()`/`s()` values are authored in canonical layout points and are
  artboard- or parent-local. Do not use physical `mm` or renderer pixels for
  child coordinates.

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
| `p(x,y)` | 2 | position in canonical layout points (`pt`), local to the parent/artboard |
| `s(w,h)` / `s(w,h,unit)` | 2–3 | size in canonical layout points; `w`/`h` are a number, `hug`, `fill`, `fill(weight)`, `fill:weight`, or `$token` |
| `rd(r)` / `radius(r)` | **1 or 4** | `rd(r)` uniform (number or `$radius.*`); `rd(tl,tr,br,bl)` per-corner, CSS clockwise from top-left — corners are **≥ 0** (`0` = square corner; negative → `LUMD0255`), bad arity → `LUMD0230` |
| `bleed(true\|false)` | 1 | node off-canvas intent; downgrades the `LUMV0801` overflow error to a warning (distinct from the 4-arg page print-bleed `bleed(x,y,w,h)`) — misuse → `LUMD0269` |
| `o(a)` / `opacity(a)` | 1 | node opacity |
| `rot(deg)` / `rotation(deg)` | 1 | rotation |
| `sk(x,y)` / `skew(x,y)` | 2 | skew |
| `flip(axis)` | 1 | `x`/`horizontal`, `y`/`vertical`, `both`/`xy`, `none` |
| `clip(bool)` | 1 | clip children |

Paint and effects (see `colors.md` and `skills/effects`):

| Property | Meaning |
|----------|---------|
| `fill(paint)` | single fill |
| `fill(solid(#hex,0.5))` / `fill(solid(#hex,o(0.5)))` | fill with opacity multiplied into the color alpha (both arg orders; out-of-range/token misuse → `LUMD0270`) |
| `f[(id,paint),(paint),…]` | ordered fill stack |
| `background(paint)` / `bg(paint)` | page/container background |
| `stroke(paint,width)` or extended `stroke(id?,paint,w(),dash(),cap(),join(),align())` | stroke; on **text** it renders as a display-type outline (stroke behind fill, first **solid** stroke only — extras advise `LUME0215`; PDF can't, `LUME0422`) |
| `shadow(color,o(),x(),y(),blur(),spread())` or `shadow(x,y,blur[,spread],color)` | drop shadow (elevation) |
| `glow(id?,#color,o(),blur(),spread())` | outer glow — centered, **no x/y** (`glow(...,x())` → `LUMD0266`) |
| `blur(12)` or `blur(id?,r(12))` | layer blur of the node's own rendering (malformed → `LUMD0267`) |
| `inner_shadow(id?,color,o(),x(),y(),blur(),spread())` | inset shadow, mirrors `shadow(...)` (malformed → `LUMD0268`) |

Text (see `text.md`):

`text("…")`/`content`, `font("family",size,weight,align)` or `font($type.x)`,
`font_size(n)` or `font_size($type.size.x)` (step token overrides the role's
default size for big canvases — see `text.md`), `font_weight`, `style($type.x)`,
`align(left|center|right|justify)`
(standalone horizontal align; pairs with `style($type.x)`), `lh`, `ls`, `tracking`,
`wrap_text(bool)`, `max_lines(n)`, `dir(ltr|rtl|auto)`,
`case(upper|lower|title|none)` (alias `text_transform`, also `uppercase`/`lowercase`;
bad value → `LUMD0271`), `underline(bool)`, `strike(bool)` (alias `strikethrough`),
`truncate(bool)` (alias `ellipsis`; inert with no cut point → `LUMV0905`),
`para_spacing(n)` (alias `paragraph_spacing`; ≥ 0, negative → `LUMD0255`),
`span(fill(#hex|$token), weight(n), underline(bool), strike(bool))` — style one
`[[…]]` run of the content; **comma-separated channels**, repeatable (Nth `span()`
→ Nth `[[…]]` run). Markers parse only when a `span()` is present; empty span() →
`LUMD0273`, malformed markers → `LUMD0272`, run/span count mismatch → `LUMD0274`
(warning). Create-line only — a `span()` on a `#node` modify line is `LUMD0903`
(ops carry span edits). See `text.md`.

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

## Images, icons & the scrim idiom

Three ways to put a picture on a surface — pick by content (see `knowledge/images/decide`):

| Kind | DSL | Lowers to | Use for |
|------|-----|-----------|---------|
| raster image | `image asset(id)` / `img(id)` | `Image{asset_id,alt}` | a generated/uploaded photo, product, texture |
| library icon | `svg(icon:name)` | `Vector` (viewBox-fit, recolorable) | iconographic marks — `knowledge/images/icons` |
| hand vector  | `vector path("…")` / `v(…)` | `Vector` (node-local coords) | a bespoke path you author by hand |

**Fit / focal / alt are placement, not DSL leaf props.** An `image` line carries only
`asset(id)` (+ geometry/`slot`). The *cover/contain/crop fit*, the *focal point*, and the
*alt text* live on the node's **AssetPlacement**, attached by the agent's
`asset(action="place")` tool (or the editor's image inspector) — the same canonical
`place_asset_in_node` / `place_asset_in_slot` ops a human edit issues. So the DSL author **composes the frame +
image + scrim structure**; the placement is set on the node, not typed as a property on
the `image` line (`fit(...)`/`focal(...)` are not DSL properties). The default is
**`fit:cover` + a sensible focal point**; aspect comes from the *frame*, never stretch.

### The scrim idiom — text over an image is ALWAYS scrimmed

The blessed pattern is a **clipped frame holding the image, a sibling scrim rect, then the
text** — declaration order is z-order (image, scrim, text). The scrim is a semi-transparent
rect between the image and the text so the headline stays legible on a busy photo. Use
`$opacity.scrim` (0.56) or `$opacity.overlay` (0.88); a dark scrim (`$surface.inverse`)
under light text (`$text.inverse`). This is the single most common imagery failure the
critic gates — never put text on a photo without it.

**Give the frame `fill($surface.inverse)` (a dark surface).** Brand tokens resolve relative
to their container's surface, so a dark frame is what makes `$text.inverse` / the `$type.*`
roles resolve to **light** ink over the scrim — on a light (`$surface.page`) frame the same
tokens resolve dark and the headline vanishes against the photo. It is also the fallback
colour if the image fails to load.

```text
frame fr p(0,0) s(1080,1350) clip(true) rd($radius.card) fill($surface.inverse)
  photo image asset(hero_photo) p(0,0) s(1080,1350)          # cover-fit + focal set by asset(action="place")
  scrim r p(0,0) s(1080,1350) fill($surface.inverse) o($opacity.scrim)
  caption text "Faster triage, calmer clinics" p(64,1120) s(936,180) style($type.headline) fill($text.inverse) wrap_text(true) max_lines(2)
```

When the text sits on its own solid band instead of on the photo, **no scrim is needed** —
see `knowledge/images/placement` (Idiom B) and the image-bearing block in
`knowledge/design/blocks/patterns`. For prompt-craft see `knowledge/images/prompts`.

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
