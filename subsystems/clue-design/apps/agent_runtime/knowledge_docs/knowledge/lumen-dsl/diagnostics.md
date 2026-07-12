# Lumen DSL — Diagnostic Code Map

A diagnostic is a contract: it names a code, often a target (node/page/slot), and
a suggested repair. Never ignore one; never re-emit the exact token a diagnostic
rejected. Repair from the failing line forward — earlier lines are preserved, the
failing line is dropped, later lines are discarded (cascade halt).

## Where a code comes from

| Family | Layer | Typical fix |
|--------|-------|-------------|
| `LUMA02xx` | Agent/coordinator guard | stop re-emitting an existing page |
| `LUMD02xx` | DSL parse (syntax/arity/value) | fix the failing token |
| `LUMD03xx` | DSL structure (indent/nesting) | fix indentation / move the line |
| `LUMD04xx` | DSL lowering (ids/refs) | fix the element |
| `LUMD06xx`/`LUMD07xx` | property applied to wrong target / not-yet-lowered | move the property or drop it |
| `LUMD09xx` | targeted edit (modify/replace/override) | fix the modify target/scope |
| `LUMV08xx`/`LUMV09xx` | layout & fit | resize/relayout text, slots, artboard bounds, or parent containment |
| `LUMB06xx`/`LUMB08xx` | brand governance | use the right `$token` |
| `LUME02xx` | export | run layout before export |

## High-frequency codes

| Code | Meaning | Repair |
|------|---------|--------|
| `LUMA0200` | repair re-declared an existing page | emit a continuation / modify line, or use structured ops — never re-`page` |
| `LUMD0206` | unknown element kind (often prose narration in a DSL block) | delete the line if it is narration; to target an existing page use `#page:<page_id> …`, not a bare page id |
| `LUMD0207` | delete/parent/clone/replace/`parent()` syntax error | fix the directive args |
| `LUMD0212` | unknown property name (e.g. `z_index`, `overflow` — CSS habits with no DSL equivalent) | remove it; there is no such property |
| `LUMD0219` | invalid color (bare number, malformed) | use `#RRGGBB`/`#AARRGGBB`/`$token`/`oklch`/`rgb(a)` |
| `LUMD0220` | `font(...)` arity | `font(family,size,weight,align)` or `font($type.x)` |
| `LUMD0222` | padding arity | `pad(a)` / `pad(v,h)` / `pad(t,r,b,l)` |
| `LUMD0230` | property arity mismatch | match the expected arity; `rd` takes **1 or 4** (`rd(r)` uniform / `rd(tl,tr,br,bl)` per-corner) |
| `LUMD0255` | value must be positive (e.g. `max_lines(0)`) or non-negative (a negative `rd` corner) | use a valid value; `0` IS a valid per-corner radius (square corner) |
| `LUMD0266` | malformed `glow(...)` (e.g. an x/y offset) | `glow(id?,#color,o(),blur(),spread())` — a glow is centered; use `shadow` for an offset |
| `LUMD0267` | malformed `blur(...)` | `blur(12)` or `blur(id?,r(12))` |
| `LUMD0268` | malformed `inner_shadow(...)` | mirror `shadow`: `inner_shadow(id?,#color,o(),x(),y(),blur(),spread())` |
| `LUMD0269` | `bleed(...)` wrong form/target | `bleed(true)` on a node (off-canvas intent) or `bleed(x,y,w,h)` on a page (print-bleed rect) |
| `LUMD0270` | `solid(color,opacity)` out of range or token misuse | opacity in `0..=1`; bake alpha into a `$token`, or use `#RRGGBBAA` |
| `LUMD0271` | unknown `case`/`text_transform` value | use `none`, `upper`/`uppercase`, `lower`/`lowercase`, or `title` |
| `LUMD0272` | malformed `[[…]]` rich-text span markers (nested `[[`, or an unclosed `[[`) | each run is one `[[…]]` range; runs cannot nest and every `[[` must close with `]]` (see `text.md`) |
| `LUMD0273` | empty or malformed `span(...)` — `span()` with no channel, or a non-call channel | give at least one channel: `span(fill(#hex))`, `span(fill($token))`, `span(weight(700))`, `span(underline(true))`, `span(strike(true))`; multiple channels are **comma-separated** |
| `LUMD0275` | unknown `valign(...)` value (e.g. `middle`) | use `top`, `center`, or `bottom` — `center`, never `middle`; no aliases |
| `LUMD0301/0302/0304` | indentation / over-nesting / leaf-with-children | two spaces per level; only containers nest |
| `LUMD0401` | duplicate node id | rename, or modify the existing node instead of re-declaring |
| `LUMD0403/0404/0405` | image/vector/instance missing required arg | add `asset(id)` / `path("…")` / `source(id)` |
| `LUMD0264` | `reconcile(target)` target missing or not a container | target a frame/group/autolayout node (the hint names the live containers); to fill an empty page use `#page:<page_id>` |
| `LUMD0901` | modify target does not exist | check the id with `inspect(view="page")`/`inspect(view="scene")` |
| `LUMD0903` | property not valid for that modify target | use a property the target supports |

## Auto-recovery warnings (never silent)

The compiler recovers from a handful of common near-misses instead of halting,
but it always says so with a warning. A warning is not an error — the block still
compiles — but treat it as a lint: author the clean form next time.

| Code | Meaning | What the parser did |
|------|---------|---------------------|
| `LUMD0259` | a bare known page id opened a top-level line (e.g. `page_x size(1080,1080,px)`) | normalized it to `#page:page_x …` and routed it through the page-modify path — write `#page:<page_id> …` explicitly |
| `LUMD0260` | a leading prose/narration line preceded the first DSL line in the block | skipped it as narration — DSL blocks contain only DSL; do not narrate inside a block |
| `LUMD0261` | a modify line swapped an image node to an asset the scene hasn't registered yet (e.g. `#hero_img asset(<kit id>)`) | swapped the leaf node's kind to that asset as a *dangling reference* (matching the declaration path) — the reference resolves when a brand kit or library registers the asset (auto-registered for kit assets); an unresolved reference warns `LUME0211` at export. A swap on a node *with children* does NOT degrade and still hard-fails |
| `LUMD0262` | a `reconcile(...)` block OMITTED a protected (seed-born / human) node | KEPT the node rather than removing it — omission never deletes human content. To remove it, add an explicit `delete(<id>)` inside the block |
| `LUMD0263` | a `reconcile(...)` block closed (info summary, never an error) | reports `N updated, N inserted, N removed, N moved, N kept-protected` for that container — the trace-visible record of what the diff applied |
| `LUMD0274` | a spanned text node has a different number of `[[…]]` runs than `span()` properties | rendered anyway: surplus runs render base, surplus `span()` are ignored — author one `span()` per `[[…]]` run, in order |

Bounds: `LUMD0260` skips at most 3 leading lines per block, and only when the
block still yields real DSL. A 4th consecutive narration line, or a block that is
*entirely* narration, halts with the original `LUMD0206` error — recovery never
lets a pure-prose block "succeed" empty.

## Layout & fit (the usual cause of "won't accept")

| Code | Meaning | Repair |
|------|---------|--------|
| `LUMV0902` | non-wrapping text overflows horizontally | `wrap_text(true)`, smaller style, or wider box |
| `LUMV0903` | text node exceeds available height | `hug` height, taller box, fewer lines, or smaller font |
| `LUMV0904` | text exceeds `max_lines` | raise `max_lines`, shorten copy, or enlarge the box (still fires **with** `truncate` — the ellipsis renders but the cut is still diagnosed) |
| `LUMV0905` | `truncate(true)` on freely wrapping text with no `max_lines` — the ellipsis can never fire | add `max_lines(n)` / `wrap(false)` to give it a cut point, or drop `truncate` |
| `LUMV0906` | an ops-injected rich-text span is invalid — out of bounds, off a UTF-8 char boundary, `start >= end`, unsorted, overlapping, or gradient-filled | keep span offsets in-bounds, char-aligned, `start<end`, sorted, non-overlapping, and solid/token-filled. DSL-authored `[[…]]` spans are valid by construction; this fires only on ops |
| `LUMV0907` | a text node combines rich-text spans with `paragraph_spacing` — the paragraph gap is **not** applied to spanned text in v1 (warning) | split the stanzas into separate text nodes, or drop the spans/`para_spacing` combination |
| `LUMV0810` | slot fixture overflows its text node | same box fixes, or set the slot overflow policy to `shrink_font`/`wrap` |
| `LUMV0509` | text slot has no fit-validation fixtures (warning) | add `sample`/`worst_case` so fit is tested against real-length data |
| `LUMV09xx page/artboard bounds` | node exceeds or starts outside the artboard | use a bounded `layout_cluster` repair on the diagnosed artboard/root/parent cluster |
| `LUMV09xx parent containment` | child exceeds a bounded parent or uses a different scale | resize/relayout the parent and affected descendants together |
| `LUMV09xx background-like rect` | top-level rect/frame mostly covers the artboard | convert it to page/artboard background fill when the diagnostic targets that cluster |

These are measured with real text shaping — when fit fails, it genuinely doesn't
fit. Fix the *specific* node for ordinary text/slot overflow. For page/artboard
bounds or parent-containment diagnostics, use `knowledge/loop/layout-cluster-repair`
instead of repeatedly shrinking unrelated text nodes. Do not re-author the scene.

`LUMV0801` (node exceeds parent bounds) **downgrades to a warning** on a node
tagged `bleed(true)` — declared off-canvas intent, not a fix-me (see
`skills/effects`). Export semantics: on digital exports content outside the
page is not exported; on PRINT exports with bleed, content inside the page's
bleed box IS exported — edge-touching print art is REQUIRED to extend there
(see `knowledge/export/print-geometry`).

## Typography v1 render/export advisories

Text case/decoration/ellipsis/paragraph-spacing/strokes are supported (see
`text.md`). What each surface can and cannot carry is diagnosed loudly, never
dropped in silence:

| Code | Meaning | Repair |
|------|---------|--------|
| `LUME0214` | **RETIRED** in Typography v1 — text strokes now render (single solid stroke, outline behind fill). No longer emitted. | none; a single solid text stroke is supported |
| `LUME0215` | a text node has >1 stroke, a gradient stroke paint, or a dashed stroke — only the first **solid** stroke renders; the extras are ignored | use a single solid text stroke; gradient/dash/multi-stroke text outlines are out of scope |
| `LUME0421` | **legacy-stub only** (see `LUME0426` note below) — PDF export cannot render text `underline`/`strike` | not emitted on server exports; if seen, export SVG/PNG for text decoration |
| `LUME0422` | **legacy-stub only** — PDF export cannot render a text stroke | not emitted on server exports; if seen, export SVG/PNG for text strokes |
| `LUME0423` | **legacy-stub only** — PDF export renders only the first fill for a multi-fill text node | not emitted on server exports; if seen, use a single text fill for PDF |
| `LUME0424` | **legacy-stub only** — PDF export cannot render rich-text spans | not emitted on server exports; if seen, export SVG/PNG for span styling |
| `LUME0425` | **legacy-stub only** — PDF export cannot render `italic` (block or span) | not emitted on server exports; if seen, export SVG/PNG for italics |
| `LUME0426` | server PDF export ran the **raster-flattened baseline** (`LUMEN_PDF_RENDERER=flattened`): pages paint through the same Skia renderer as PNG and embed as images — full fidelity, but text is not selectable (advisory) | none — comparison-baseline mode only; the default is the vector renderer (`LUME0427`) |
| `LUME0427` | server PDF export is **vector** (Skia PDF backend, the default): live selectable text with embedded subset fonts, vector shapes and gradients; effects PDF cannot express (blur, shadow) rasterize locally at the profile dpi (advisory, always emitted on server PDF exports) | none — this is the expected mode; do NOT avoid PDF for spans/effects/italics. The `LUME0421`–`LUME0425` limitations apply only to the legacy portable vector writer, which server exports no longer use |
| `LUMS0104` | the font family has no face at the requested weight; the shaper snapped to the nearest one (advisory — snapping is correct, the silence was the bug) | add a face at that weight to the `fonts/` set for exact fidelity, or pick a weight the family ships |
| `LUMS0105` | the resolved family/weight has no **italic** face; the shaper rendered the **upright** face instead (advisory — no synthetic skew, snapping is correct; the silence would be the bug) | pick a family/weight that ships an italic cut (see `knowledge/design/font-library` Italics column), or drop the `italic` — display families have no italics by design |

## Brand governance

| Code | Meaning |
|------|---------|
| `LUMB0804` | raw/off-brand color where a token belongs |
| `LUMB0805` | raw typography where a `type.*` token belongs |
| `LUMB0806` | raw spacing/radius/stroke/opacity |
| `LUMB0807` | logo on a disallowed background |
| `LUMB0811` | print/direct-mail transparency violation |
| `LUMB0813`–`LUMB0815` | Brand Kit compatibility breakage |

Repair these by choosing the right `$token`, not by swapping one raw value for
another. See `skills/brand-and-tokens` and `knowledge/design-systems/brand-validation`.
