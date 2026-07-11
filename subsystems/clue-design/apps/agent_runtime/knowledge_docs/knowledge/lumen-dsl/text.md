# Lumen DSL — Text & Typography

Text is the most common source of overflow. Measurement is real (server-side
SkParagraph shaping over the bundled Inter), so a box that the compiler says is
too small genuinely is.

## Properties

| Property | Aliases | Meaning |
|----------|---------|---------|
| `text("…")` | `content` | the string content |
| `font("family",size,weight,align)` | — | full type spec; align ∈ `left`/`center`/`right`/`justify` |
| `font($type.x)` | — | one typography token (preferred when branded) |
| `style($type.x)` | `text_style` | typography role token (preferred when branded) |
| `align(left\|center\|right\|justify)` | `text_align` | horizontal alignment, standalone — pairs with `style($type.x)` (which carries no align) |
| `font_size(n)` / `font_size($type.size.x)` | `font-size` | size only — a raw number OR a size-step token (the token form is preferred; see below) |
| `font_weight(n)` | `font-weight` | alias — weight only |
| `lh(n)` | `line_height` | line height multiplier |
| `ls(n)` | `letter_spacing` | pixel letter spacing |
| `tracking(n)` | — | design-tool tracking; `tracking(200)` ≈ `0.2em`, not 200px |
| `wrap_text(bool)` | `text_wrap` | enable wrapping |
| `max_lines(n)` | `max` | cap line count (>0; else `LUMD0255`); overflow → `LUMV0904` |
| `dir(ltr|rtl|auto)` | `direction` | base direction |
| `case(upper\|lower\|title\|none)` | `text_transform` (also takes `uppercase`/`lowercase`) | display-time case transform; the stored content stays canonical; bad value → `LUMD0271` |
| `underline(bool)` | — | underline decoration |
| `strike(bool)` | `strikethrough` | strike-through decoration |
| `truncate(bool)` | `ellipsis` | end the cut line with `…` when `max_lines`/`wrap(false)` clips; inert (warns `LUMV0905`) if the text can never be cut |
| `para_spacing(n)` | `paragraph_spacing` | extra px of vertical gap at each `\n` paragraph break (≥ 0; negative → `LUMD0255`) |
| `span(fill(#hex\|$token), weight(n), underline(bool), strike(bool))` | — | style ONE `[[…]]` run of the content differently; **repeatable** — the Nth `span()` styles the Nth `[[…]]` run. Channels are **comma-separated**; give only the ones you want to override (each inherits the node otherwise). See "Rich-text spans" below |

Canonical vs alias: prefer `font(...)` / `style($type.x)` / `lh(...)` / `ls(...)`
in new designs. `font_size`/`font_weight`/`tracking` are compatibility aliases for
*targeted text repairs* when a model has drifted into CSS/design-tool language.

## Typography v1 — case, decoration, ellipsis, paragraph spacing

- **Case is display-only.** `case(upper)` uppercases at render time; the stored
  content string is never mutated, so a human editor still sees and edits the real
  words. Values `upper`/`lower`/`title`/`none`; the alias `text_transform(...)`
  additionally accepts `uppercase`/`lowercase`. Pair `case(upper)` with wide
  `tracking(...)` for an eyebrow/kicker — never on body copy (see
  `knowledge/design/typography-and-composition`).
- **Text strokes now render** (the old `LUME0214` "deferred to Typography v1" drop
  is retired). A `stroke(#hex,width)` on a text node draws a display-type outline —
  stroke behind fill, the convention design tools use to outline type. **First
  solid stroke only**: extra strokes, gradient stroke paint, and dashes on text
  advise `LUME0215` and are ignored. PDF export still cannot render text
  strokes/decoration — it degrades loudly (`LUME0421` decoration, `LUME0422`
  stroke); export SVG/PNG when you need them.
- **Single-line ellipsis** is `wrap_text(true) max_lines(1) truncate(true)` — the
  one surviving line ends with `…` when the copy overflows. `truncate` needs a cut
  point: with no `max_lines` and free wrapping it can never fire and warns
  `LUMV0905`. Truncation is **layout honesty, not a silencer** — when the copy
  actually gets cut, managed (agent-authored) text still reports the overflow
  (`LUMV0904` / `LUMV0903`) as an error, so fit the copy or raise `max_lines`;
  `truncate` is the graceful fallback for variable/slot content, not a way to cram
  oversized copy.
- **Paragraph spacing vs line-height.** `lh(...)` is rhythm *within* a paragraph;
  `para_spacing(n)` adds air *between* stanzas split on `\n`. Use both for a
  multi-stanza body (`lh(1.35) para_spacing(16)`); do not fake stanza gaps with
  empty lines.

## Rich-text spans — style a sub-range of ONE text node

A **span** styles part of a single text node differently — the moda **two-color
headline** (one accented phrase), a bolded keyword, one struck word. It is a
scalpel, not a rich-text editor.

- **Mark the runs in the content with `[[…]]`, then attach `span(...)`
  properties.** Each `[[…]]` pair is a run, in order; the Nth `span()` styles the
  Nth run. The markers are stripped from the stored content — the node stores the
  clean words (`"Every outage, mapped."`), so a human editor never sees the
  brackets. Markers are parsed **only when the element carries at least one
  `span()`** — without one, `[[` stays literal (existing scenes are untouched).

```text
headline text "Every [[outage]], mapped before it spreads." s(888,hug) font("Fraunces",76,600,left) fill(#0b3d2e) lh(1.03) wrap_text(true) max_lines(3) span(fill(#e11d48), weight(800))
```

  That renders "outage" in rose (`#e11d48`) at weight 800 while the rest stays the
  node's dark green — a **two-color, two-weight headline** from one node.

- **Channels are comma-separated inside `span(...)`**: `fill(#hex)` or
  `fill($token)`, `weight(n)`, `underline(bool)`, `strike(bool)` (alias
  `strikethrough`). Give only the channels you want to override — each unset
  channel inherits the node. `span(weight(800))` bolds a keyword with no color
  change; `span(fill($accent.primary))` recolors it with a kit token when branded.
  **A single channel needs no comma; multiple channels DO** —
  `span(fill(#e11d48), weight(800))`, never `span(fill(#e11d48) weight(800))`
  (the space form mis-parses the color → `LUMD0219`).
- **Repeat `span()` per run**, space-separated like any other properties:
  `… span(fill(#e11d48), weight(800)) span(weight(800)) span(underline(true))`
  styles three `[[…]]` runs in order.
- **Count mismatch is a warning, not an error** (`LUMD0274`): more `[[…]]` runs
  than `span()` → surplus runs render base; more `span()` than runs → extras are
  ignored. Author one `span()` per run.

**v1 limits (know them before you reach for a span):**

- Fill is **solid color or `$token` only** — no per-span gradients (a gradient
  span fill is rejected, `LUMV0906` on ops-injected spans).
- **No per-span family, size, letter-spacing, or line-height** — a span changes
  color / weight / underline / strike, nothing that would reflow line metrics.
- **`span()` only authors on a create line**, when the node is first written. It
  is **not** supported on a `#node` modify line (`LUMD0903`) — later span edits
  arrive as structured ops, which carry the spans directly.
- **A content edit CLEARS spans** (honesty): editing the text without also
  re-authoring `spans` drops them, because the old byte offsets would now point at
  the wrong characters. Undo restores the prior spans. Re-author the accent after
  a copy change.
- **`para_spacing` is not applied to spanned text in v1** (`LUMV0907` warning): a
  spanned node with `\n` stanzas and `para_spacing(n)` still hard-breaks the line
  but skips the extra paragraph gap. Split the stanzas into **separate** text
  nodes if you need both the spans and the gap.
- **PDF export renders base text only** — spans present degrade loudly
  (`LUME0424` advisory); the words render complete, the accent styling does not.
  Export SVG/PNG when the two-color headline must ship.

`align(...)` is the horizontal alignment knob. Use it **standalone** alongside
`style($type.x)` — the style token carries no alignment — to center a label without
resizing its box: e.g. a numeral in a circle chip or a CTA label is
`style($type.cta) align(center)`. (It is also the 4th arg of `font(...)`.) To center
a label in a chip/button, the box does NOT need to hug the glyph — `align(center)`
centers the glyph within whatever width the box has. Vertical centering is an
auto-layout `y(c)` on the parent plus a hug height on the label (see `layout.md`);
there is no `valign`.

## Type-size scale — pick the step for the surface

A role (`style($type.headline)`) bakes in **one** size, tuned for a document-scale
page (A4 ≈ 595pt wide). On a much larger canvas (a 1080² social square, a wide
flyer) that same size is too small to dominate — the headline reads at the same
weight as a stat and the squint test fails. Fix it at the source: keep the role
for weight/color/line-height and **override the size with a step token**:

```
$type.size.xs=12  sm=14  md=16  lg=20  xl=24  2xl=32  3xl=36
$type.size.4xl=40 (hero)  5xl=48 (large hero)  6xl=64 (display)
$type.size.7xl=80  8xl=96  9xl=128  (oversize / display)
```

```text
# A4 / document scale — the role default is right, no override needed
headline text "Your appointment is confirmed." s(fill,hug) style($type.headline) lh(1.08) wrap_text(true) max_lines(2)

# 1080² social hero — same role, but step the size up so it dominates
headline text "Meet Magic-Doc." s(fill,hug) style($type.headline) font_size($type.size.7xl) lh(1.08) wrap_text(true) max_lines(2)
```

The step token resolves to a fixed value regardless of canvas (no auto-scaling —
a human editor can resize it freely), and it wins over the role's default size.
**Rules of thumb** (canvas-independent): one element dominates per artifact; the
hero is ~2–3× body; a stat/secondary value must read *visibly smaller* than the
hero (don't let `$type.stat`, 48, rival a 56 headline — step the headline to
64–80 on a big canvas). See `knowledge/design/foundations`.

## Patterns that fit

```text
headline text "Let neurosurgeons focus on surgery." p(64,88) s(620,hug) style($type.headline) lh(1.08) wrap_text(true) max_lines(2)
body     text "Insight Health handles calls, scheduling, and patient routing." p(64,240) s(600,hug) style($type.body) lh(1.35) wrap_text(true) max_lines(3)
cta_text text "Book a Demo" p(0,0) s(fill,hug) style($type.cta) max_lines(1)
```

- `hug` height so the box grows with the copy.
- Box **wide enough** for the real sentence.
- `wrap_text(true)` on anything that can vary.
- `max_lines(...)` so overflow is diagnosed early rather than clipping silently.
- `lh` for hierarchy: tight headlines (`1.05`–`1.15`), relaxed body (`1.3`–`1.45`).

### Text over an image

A headline or label placed **over a photo** must sit on a **scrim** and use an inverse
fill so it stays legible on a busy image: `style($type.headline) fill($text.inverse)`
over a sibling scrim rect (`fill($surface.inverse) o($opacity.scrim)`). Declaration order
is image → scrim → text. See the scrim idiom in `grammar.md` and
`knowledge/images/placement`; legibility-over-image is a hard imagery-critic gate.

## Patterns that overflow

```text
headline text "Very long headline that cannot fit" p(40,40) s(300,24) font("Inter",64,800,left)
body     text "A long paragraph forced into a tiny fixed box" p(40,120) s(300,24) font("Inter",18,400,left)
```

A fixed `24px` height with a 64px font, or a paragraph in a narrow box, will fail
fit validation (`LUMV0903 exceeds available height`, `LUMV0810 fixture overflows`).
The fix is small and targeted: widen/heighten the box, raise `max_lines`, drop the
font a point, or switch the slot's overflow policy to shrink/wrap. **Do not redesign
the whole scene to fix one box** — see `skills/repair-design`.
