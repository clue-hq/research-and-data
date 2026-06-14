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
| `LUMD0207` | delete/parent/clone/replace/`parent()` syntax error | fix the directive args |
| `LUMD0212` | unknown property name (e.g. `valign`) | remove it; there is no such property |
| `LUMD0219` | invalid color (bare number, malformed) | use `#RRGGBB`/`#AARRGGBB`/`$token`/`oklch`/`rgb(a)` |
| `LUMD0220` | `font(...)` arity | `font(family,size,weight,align)` or `font($type.x)` |
| `LUMD0222` | padding arity | `pad(a)` / `pad(v,h)` / `pad(t,r,b,l)` |
| `LUMD0230` | property arity mismatch (e.g. `rd(a,b,c,d)`) | match the expected arity; `rd` takes 1 |
| `LUMD0255` | value must be positive (e.g. `max_lines(0)`) | use a positive value |
| `LUMD0301/0302/0304` | indentation / over-nesting / leaf-with-children | two spaces per level; only containers nest |
| `LUMD0401` | duplicate node id | rename, or modify the existing node instead of re-declaring |
| `LUMD0403/0404/0405` | image/vector/instance missing required arg | add `asset(id)` / `path("…")` / `source(id)` |
| `LUMD0901` | modify target does not exist | check the id with `summarize_page`/`summarize_scene` |
| `LUMD0903` | property not valid for that modify target | use a property the target supports |

## Layout & fit (the usual cause of "won't accept")

| Code | Meaning | Repair |
|------|---------|--------|
| `LUMV0902` | non-wrapping text overflows horizontally | `wrap_text(true)`, smaller style, or wider box |
| `LUMV0903` | text node exceeds available height | `hug` height, taller box, fewer lines, or smaller font |
| `LUMV0904` | text exceeds `max_lines` | raise `max_lines`, shorten copy, or enlarge the box |
| `LUMV0810` | slot fixture overflows its text node | same box fixes, or set the slot overflow policy to `shrink_font`/`wrap` |
| `LUMV0509` | text slot has no fit-validation fixtures (warning) | add `sample`/`worst_case` so fit is tested against real-length data |
| `LUMV09xx page/artboard bounds` | node exceeds or starts outside the artboard | use a bounded `layout_cluster` repair on the diagnosed artboard/root/parent cluster |
| `LUMV09xx parent containment` | child exceeds a bounded parent or uses a different scale | resize/relayout the parent and affected descendants together |
| `LUMV09xx background-like rect` | top-level rect/frame mostly covers the artboard | convert it to page/artboard background fill when the diagnostic targets that cluster |

These are measured with real text shaping — when fit fails, it genuinely doesn't
fit. Fix the *specific* node for ordinary text/slot overflow. For page/artboard
bounds or parent-containment diagnostics, use `knowledge/loop/layout-cluster-repair`
instead of repeatedly shrinking unrelated text nodes. Do not re-author the scene.

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
