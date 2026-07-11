# Layout Recipes — the Archetype Canon

This is the **canonical home for the six design archetypes**. An archetype is a
*composition skeleton*, not a template: it fixes the structural move (how the
canvas is divided and what dominates), and you recompose it for the brief — you
do **not** swap copy into a fixed shell. `skills/create-design` teaches the
choose-archetype-first protocol and points here for the skeletons; nothing
duplicates them.

All positions and sizes in child `p()`/`s()` are canonical layout points (`pt`),
local to the containing artboard or parent. Physical print units and raster pixel
targets belong to the page/export declaration, not to child geometry.

Every skeleton below was **mechanically validated** (compiles with zero blocking
diagnostics, preflights clean on platform-default tokens, exports a non-black
PNG with no tofu). They are written in the **no-kit concrete-hex form** with
faces from the curated library (`knowledge/design/font-library`). With a Brand
Kit, swap the hex for `$surface.*`/`$text.*` tokens and `font("Family",…)` for
`style($type.*)` — the *structure* is what carries over.

## Choose the archetype first

Read the brief, then pick the structural move that fits the message — before you
write any DSL. Do **not** default to the vertical poster; it is ONE of six.

| Archetype | The move | Reach for it when |
|---|---|---|
| vertical-poster | `al(v)` header / centered main / footer | a single statement or quote, editorial calm, no photo |
| split-panel | `al(h)` root: image column + content column | you have a photo AND a message that both deserve half the canvas |
| numeral-hero | one giant display numeral dominates; caption beside/below | a single metric IS the story (uptime, speed, scale, savings) |
| image-hero | `fr` root: full-bleed image + scrim + overlaid text | the photo is the emotional payload and text rides on top of it |
| banded | stacked full-width bands, alternating surfaces | multiple beats (claim → proof stats → CTA) that want rhythm |
| emblem | centered plate/badge overlapping a field or photo | a stamp/seal/credential tone; anniversaries, launches, awards |

Two designs of the **same** archetype for **different** briefs should still look
different (different surface treatment, type voice, crop). Two designs of
different archetypes should never be confusable.

## Surface-treatment vocabulary (orthogonal to archetype)

Treatments are how the ground reads; pick one per design and pair it with the
archetype. These are the intended palette of moves — none are clichés when
brand-derived (see `knowledge/design/foundations`, "Avoid the AI clichés"):

- **Solid paper** — one flat brand surface. The quiet default; lets type carry.
- **Brand gradient field** — `fill(linear(angle, stop($c1,0), stop($c2,1)))`
  between two *brand* colors (never a stock blue→purple). Directional energy.
- **Soft radial wash** — `fill(radial(stop($c_light,0), stop($c_dark,1)))` so the
  light center feels like a spotlight, not a decorative blob. The minimal-luxury
  look. Two ways to bleed it: a **full-frame rect** exactly the frame size (falloff
  runs to the edges, no warning), or a genuinely **off-canvas shape tagged
  `bleed(true)`** — an oversized/overhanging shape that declares its intent and
  downgrades the `LUMV0801` overflow error to a warning (without the flag, an
  oversized shape is a hard error). Use the off-canvas form when the geometry (an
  ellipse, a rotated band) truly overhangs the edge; see `skills/effects`.
- **Shadowed plate/card** — a rounded surface lifted off the field with
  `shadow(...)`. The emblem's home; also lifts a single stat or quote.

Each archetype below names the treatments that suit it.

## The six archetypes

### 1 — vertical-poster

The classic idiom, kept as ONE option (not the default). `al(v)` root: a hug
header pinned top, a `fill`-height `main` that CENTERS the focal block, a hug
footer pushed to the bottom — so free space reads as symmetric margin, never a
dead band (see `foundations`, "Distribute the canvas").

- **Suits:** solid paper, soft radial wash. **Constructs:** size-stepping, one
  alignment spine, generous margin.
- **Type:** a display voice for the headline (Fraunces / Bricolage Grotesque /
  Playfair for elegance) over Inter/Hanken body; a mono eyebrow (Space Mono)
  reads as "field report", not a tinted pill. Set the eyebrow with `case(upper)
  tracking(200)` (author the words in natural case — the transform is display-only,
  the content stays editable); reserve uppercase + wide tracking for this one
  kicker line, never the body.

```text
page linkedin_square size(1080,1080,px)
  artboard al(v,x(s),y(s),g(40),pad(96)) p(0,0) s(fill,fill) fill(#f4f1ea) clip(true)
    header al(h,x(sb),y(c),g(12),pad(0)) p(0,0) s(888,hug)
      brand text "NORTHWIND" p(0,0) s(500,hug) font("Space Grotesk",22,700,left) fill(#0b3d2e) max_lines(1)
      tag text "FIELD REPORT" p(0,0) s(320,hug) font("Space Mono",15,400,right) fill(#6b7280) align(right) max_lines(1)
    main al(v,x(s),y(c),g(24),pad(0)) p(0,0) s(888,fill)
      over text "grid intelligence" p(0,0) s(888,hug) font("Space Mono",16,400,left) fill(#c2410c) case(upper) tracking(200) max_lines(1)
      headline text "Every outage, mapped before it spreads." p(0,0) s(888,hug) font("Fraunces",76,600,left) fill(#0b3d2e) lh(1.03) wrap_text(true) max_lines(3)
      body text "Northwind watches ten thousand substations and routes crews to the fault in seconds." p(0,0) s(760,hug) font("Inter",21,400,left) fill(#374151) lh(1.4) wrap_text(true) max_lines(3)
    footer al(h,x(sb),y(c),g(16),pad(0)) p(0,0) s(888,hug)
      cta al(h,x(c),y(c),pad(18,34)) p(0,0) s(240,64) fill(#0b3d2e) rd(999)
        cta_text text "See the map" p(0,0) s(fill,hug) align(center) font("Inter",18,600,center) fill(#f4f1ea) max_lines(1)
      url text "northwind.grid" p(0,0) s(300,hug) font("Space Mono",15,400,right) fill(#6b7280) align(right) max_lines(1)
```

**Two-color headline (the moda span move).** Accent ONE phrase of the headline
with a `[[…]]` run + `span(...)` — one accent per headline, never a rainbow. Raw
hex when unbranded, a kit token when branded:

```text
# raw-hex accent (no kit)
headline text "Every [[outage]], mapped before it spreads." p(0,0) s(888,hug) font("Fraunces",76,600,left) fill(#0b3d2e) lh(1.03) wrap_text(true) max_lines(3) span(fill(#e11d48), weight(800))
# kit-token accent (branded — the token resolves at apply)
headline text "Every [[outage]], mapped before it spreads." p(0,0) s(888,hug) style($type.headline) fill($text.primary) lh(1.03) wrap_text(true) max_lines(3) span(fill($accent.primary), weight(800))
```

Channels inside `span(...)` are **comma-separated**; drop the color for a
weight-only emphasis (`span(weight(800))`). See `lumen-dsl/text.md`.

### 2 — split-panel

`al(h)` root divides the canvas into a full-bleed **image column** and a
**content column**. The vertical seam is the composition. Give the image column
~40–45% and let the content column breathe with its own padding.

- **Suits:** a photo (or brand gradient field as the image stand-in) beside solid
  paper. **Constructs:** `al(h)` root, cover-fit image, two-zone rhythm.
- **Type:** display headline in the content column; keep the image column type-free
  except a small badge.

The image column here uses a **brand gradient field as a stand-in** so the
skeleton validates with no asset store. In a real build, replace the `media`
frame's `fill(...)` with a placed photo:
`photo image asset(<asset_id>) p(0,0) s(456,1080)` (fit:cover + focal point —
see `knowledge/images/placement`).

```text
page linkedin_square size(1080,1080,px)
  artboard al(h,x(s),y(s),g(0),pad(0)) p(0,0) s(fill,fill) fill(#ffffff) clip(true)
    media fr p(0,0) s(456,1080) fill(linear(155, stop(#0b3d2e,0), stop(#177a5b,1))) clip(true)
      badge al(h,x(c),y(c),pad(9,16)) p(40,40) s(96,40) fill(#f4c430) rd(999)
        badge_text text "NEW" p(0,0) s(fill,hug) align(center) font("Space Mono",14,400,center) fill(#0b3d2e) max_lines(1)
    panel al(v,x(s),y(c),g(22),pad(80,64)) p(0,0) s(624,1080)
      over text "PATIENT FLOW" p(0,0) s(496,hug) font("Space Mono",16,400,left) fill(#c2410c) max_lines(1)
      headline text "Half the wait. Same front desk." p(0,0) s(496,hug) font("Fraunces",60,600,left) fill(#0b3d2e) lh(1.05) wrap_text(true) max_lines(3)
      body text "Meridian routes every arrival to the right room the moment they check in." p(0,0) s(496,hug) font("Inter",20,400,left) fill(#374151) lh(1.4) wrap_text(true) max_lines(3)
      cta al(h,x(c),y(c),pad(18,34)) p(0,0) s(220,62) fill(#0b3d2e) rd(999)
        cta_text text "Book a demo" p(0,0) s(fill,hug) align(center) font("Inter",18,600,center) fill(#ffffff) max_lines(1)
```

### 3 — numeral-hero

A single display numeral is the hero — **≥2× the headline size**, dominating the
canvas (Brilliant reference: the number runs 3–6× body). A caption row beside or
below carries the context. The numeral is the squint-test winner; everything else
is deliberately quiet.

- **Suits:** dark solid paper (numeral pops) or a soft wash. A **gradient text
  fill** on the numeral (`fill(linear(...))`) + optional shadow is the signature.
  On a **dark** field, a **glow** on the numeral is the moda "Living Type" move —
  the number reads as lit, not printed. Add `glow(id, #warm, o(0.5), blur(56),
  spread(2))` to the `numeral` line, pulling the halo color from the numeral's own
  gradient (a warm halo under warm digits). Glow is focal — the ONE hero element,
  never on the caption or on a light field (see `skills/effects`).
  **Constructs:** display type, gradient text fill, glow on a dark field, `al(h)`
  caption sub-group.
- **Type:** an impact face for the numeral — **Archivo Black / Anton / Bricolage
  Grotesque** for no-kit; a kit display role otherwise. Keep the numeral short
  (`3.2s`, `99.99%`, `40M`) so it never overflows its box — check `font_gaps` in
  the brand card for glyph coverage of `%`, `×`, `/` before committing.

```text
page linkedin_square size(1080,1080,px)
  artboard al(v,x(s),y(c),g(4),pad(96)) p(0,0) s(fill,fill) fill(#0d0d0f) clip(true)
    label text "RESPONSE TIME, MEASURED" p(0,0) s(888,hug) font("Space Mono",18,400,left) fill(#9ca3af) max_lines(1)
    numeral text "3.2s" p(0,0) s(888,hug) font("Archivo Black",300,400,left) fill(linear(120, stop(#f5d020,0), stop(#f5380a,1))) lh(0.92) max_lines(1)
    caption al(h,x(s),y(c),g(18),pad(0)) p(0,0) s(888,hug)
      bar r p(0,0) s(5,72) fill(#f5380a)
      capcol al(v,x(s),y(c),g(4),pad(0)) p(0,0) s(760,hug)
        cap_h text "Median first-response, last quarter" p(0,0) s(760,hug) font("Space Grotesk",24,600,left) fill(#f4f1ea) lh(1.15) wrap_text(true) max_lines(2)
        cap_b text "Across 40 million alerts, no on-call paged after midnight." p(0,0) s(760,hug) font("Inter",18,400,left) fill(#9ca3af) lh(1.4) wrap_text(true) max_lines(2)
```

An accent span in the **caption headline** ties the words to the numeral — pull the
accent from the numeral's own warm gradient (a hex here, `$accent.*` when branded):

```text
cap_h text "Median [[first-response]], last quarter" p(0,0) s(760,hug) font("Space Grotesk",24,600,left) fill(#f4f1ea) lh(1.15) wrap_text(true) max_lines(2) span(fill(#f5a020), weight(800))
```

### 4 — image-hero

`fr` (free) root so children stack by **declaration order = z-order**: the image
fills the frame, a **scrim** sits on top, the text block rides over the scrim,
bottom-anchored. This is the only archetype that puts text directly on a photo —
so the scrim rule is non-negotiable (`knowledge/images/placement`).

- **Suits:** a full-bleed photo; the artboard is a **dark surface**
  (`fill($surface.inverse)` / a dark hex) so brand type tokens resolve to LIGHT
  ink over the scrim, and the dark fill is the fallback if the image fails.
  **Constructs:** `fr` root, overlap by declaration order, scrim.
- **Type:** a confident display headline in light ink; keep body short. Close with
  at most **one** underlined text CTA (`underline(true)`) as the single accent.

The `photo` here is a **radial-wash stand-in** so the skeleton validates without
an asset store. In a real build, replace it with
`photo image asset(<asset_id>) p(0,0) s(1080,1080)` (fit:cover + focal).

```text
page linkedin_square size(1080,1080,px)
  artboard fr p(0,0) s(fill,fill) fill(#0b3d2e) clip(true)
    photo r p(0,0) s(1080,1080) fill(radial(stop(#1f8a66,0), stop(#06231a,1)))
    scrim r p(0,0) s(1080,1080) fill(#05140e) o(0.55)
    content al(v,x(s),y(e),g(18),pad(96)) p(0,0) s(1080,1080)
      over text "CASE STUDY" p(0,0) s(880,hug) font("Space Mono",16,400,left) fill(#a7f3d0) max_lines(1)
      headline text "Calmer clinics, faster triage." p(0,0) s(880,hug) font("Fraunces",72,600,left) fill(#f4f1ea) lh(1.05) wrap_text(true) max_lines(3)
      body text "Meridian answered every after-hours call at Cedar Valley and cut readmissions by a third." p(0,0) s(820,hug) font("Inter",21,400,left) fill(#d1fae5) lh(1.4) wrap_text(true) max_lines(3)
      cta_link text "Read the case study" p(0,0) s(880,hug) font("Inter",18,600,left) fill(#f4f1ea) underline(true) max_lines(1)
```

The trailing `cta_link` is the **one** underlined accent — a text CTA in light ink,
deliberate emphasis, not link-blue and not repeated. Underline exactly one element
per design (a CTA, one word); never underline headlines or body copy.

### 5 — banded

Stacked full-width **bands** with alternating surfaces — a claim band, a proof
band (stats), a footer band — so the design has editorial rhythm instead of one
flat field. Use `g(0)` on the root so bands touch; give ONE band `fill` height
(it absorbs slack) and the others fixed heights.

- **Suits:** two brand surfaces alternating (a dark claim band, a bright proof
  band). **Constructs:** multiple surface fills, vertical rhythm, a stat row.
- **Type:** display headline in the claim band; impact numerals in the proof band.

```text
page linkedin_square size(1080,1080,px)
  artboard al(v,x(s),y(s),g(0),pad(0)) p(0,0) s(fill,fill) fill(#f4f1ea) clip(true)
    band_top al(v,x(s),y(c),g(14),pad(80,72)) p(0,0) s(1080,fill) fill(#0b3d2e)
      over text "QUARTERLY BRIEF" p(0,0) s(936,hug) font("Space Mono",16,400,left) fill(#a7f3d0) max_lines(1)
      headline text "The grid held. Here is the proof." p(0,0) s(936,hug) font("Fraunces",66,600,left) fill(#f4f1ea) lh(1.04) wrap_text(true) max_lines(2)
    band_mid al(h,x(sb),y(c),g(24),pad(48,72)) p(0,0) s(1080,300) fill(#f4c430)
      stat_a al(v,x(s),y(c),g(2),pad(0)) p(0,0) s(280,hug)
        a_num text "99.99%" p(0,0) s(280,hug) font("Archivo Black",52,400,left) fill(#0b3d2e) lh(1.0) max_lines(1)
        a_lab text "Uptime" p(0,0) s(280,hug) font("Inter",16,500,left) fill(#0b3d2e) max_lines(1)
      stat_b al(v,x(s),y(c),g(2),pad(0)) p(0,0) s(280,hug)
        b_num text "3.2s" p(0,0) s(280,hug) font("Archivo Black",52,400,left) fill(#0b3d2e) lh(1.0) max_lines(1)
        b_lab text "Median response" p(0,0) s(280,hug) font("Inter",16,500,left) fill(#0b3d2e) max_lines(1)
      stat_c al(v,x(s),y(c),g(2),pad(0)) p(0,0) s(280,hug)
        c_num text "40M" p(0,0) s(280,hug) font("Archivo Black",52,400,left) fill(#0b3d2e) lh(1.0) max_lines(1)
        c_lab text "Alerts handled" p(0,0) s(280,hug) font("Inter",16,500,left) fill(#0b3d2e) max_lines(1)
    band_bot al(h,x(sb),y(c),g(16),pad(36,72)) p(0,0) s(1080,148) fill(#0b3d2e)
      url text "northwind.grid" p(0,0) s(400,hug) font("Space Mono",15,400,left) fill(#a7f3d0) max_lines(1)
      cta al(h,x(c),y(c),pad(16,30)) p(0,0) s(220,60) fill(#f4c430) rd(999)
        cta_text text "Read the brief" p(0,0) s(fill,hug) align(center) font("Inter",17,600,center) fill(#0b3d2e) max_lines(1)
```

### 6 — emblem

A centered **plate** (rounded rect or ellipse) lifted off a field or photo with a
soft `shadow(...)`, content centered ON the plate. The overlap of plate over
field is the composition; the shadow sells the depth. Reads as a stamp, seal, or
credential.

- **Suits:** a soft radial field behind a light plate. **Constructs:** overlap,
  plate, shadow, centered stack.
- **Type:** a display serif (Fraunces / Playfair / Instrument Serif) centered on
  the plate reads as "crafted"; a mono seal line ("EST. 2019") above it.

```text
page linkedin_square size(1080,1080,px)
  artboard fr p(0,0) s(fill,fill) fill(radial(stop(#177a5b,0), stop(#06231a,1))) clip(true)
    plate al(v,x(c),y(c),g(16),pad(72,72)) p(140,270) s(800,540) fill(#f4f1ea) rd(40) shadow(#000000, o(0.35), y(24), blur(60))
      seal text "EST. 2019" p(0,0) s(656,hug) align(center) font("Space Mono",15,400,center) fill(#c2410c) max_lines(1)
      headline text "Built for the field." p(0,0) s(656,hug) align(center) font("Fraunces",64,600,center) fill(#0b3d2e) lh(1.05) wrap_text(true) max_lines(2)
      body text "Ten years of crews, storms, and substations — one platform that keeps the lights on." p(0,0) s(600,hug) align(center) font("Inter",19,400,center) fill(#374151) lh(1.4) wrap_text(true) max_lines(3)
      cta al(h,x(c),y(c),pad(16,32)) p(0,0) s(220,60) fill(#0b3d2e) rd(999)
        cta_text text "Meet Northwind" p(0,0) s(fill,hug) align(center) font("Inter",17,600,center) fill(#f4f1ea) max_lines(1)
```

## Fitting variable copy — truncation & stanza spacing

When a card or slot carries **variable-length** body copy you can't fully control,
arm `truncate(true)` alongside `max_lines(n)` so an overrun ends the last visible
line with `…` instead of clipping mid-glyph. Truncation is layout **honesty**, not
a licence to cram: if the copy actually gets cut, layout still reports the overflow
(`LUMV0904`) — prefer rewriting the copy to fit, and keep `truncate` as the graceful
fallback. For a multi-stanza body, keep line-height and paragraph air distinct:
`lh(...)` inside a paragraph, `para_spacing(n)` between stanzas split on `\n`.

```text
card al(v,x(s),y(s),g(12),pad(40)) p(0,0) s(888,420) fill(#ffffff) rd(24)
  title text "Field note" p(0,0) s(808,hug) font("Space Grotesk",26,700,left) fill(#0b3d2e) max_lines(1)
  body text "Northwind watches ten thousand substations across four regions and routes the nearest crew to a developing fault within seconds, long before the outage can cascade into neighbouring feeders and take down the wider grid." p(0,0) s(808,hug) font("Inter",19,400,left) fill(#374151) lh(1.4) wrap_text(true) max_lines(3) truncate(true)
```

## Surfaces & presets (the page mechanics, orthogonal to archetype)

Any archetype can render on any surface — these are the page-declaration facts.
Pin the surface to the requested artifact exactly; never fake a square ad as a
square frame inside an A4 page.

- **Square social** — `page linkedin_square size(1080,1080,px)` → `1080 x 1080 pt`
  layout bounds (all six skeletons above use this).
- **A4 one-pager** — `preset(a4,portrait)` → ~`595 x 842 pt` (export metadata can
  still say `210mm x 297mm`; author against the point bounds). Use the SAME
  archetype idioms — wrap the body in a `s(W,fill)` `main` between a hug header and
  hug footer so the footer pins to the page bottom (see `foundations`).
- **US Letter** — `page letter size(8.5,11,in)` → `612 x 792 pt`; print margins in
  points (`36–54pt`) via root-frame padding, not a margin rectangle.
- **Landscape / LinkedIn wide** — `page linkedin_wide size(1200,628,px)` →
  `1200 x 628 pt`; split-panel and image-hero suit wide surfaces especially well.
- **Email hero / postcard** — compact header, one large headline, one line, one
  CTA; print-safe margins and a recipient/account slot for direct mail.

### Alignment patterns

- `x(s)`/`x(c)`/`x(e)` start/center/end on the physical x axis; `x(sb)` distributes
  a row (nav / proof / footer). `y(c)` vertically centers row children (buttons).
- For columns, `y(sb)` distributes vertical space when the container has a definite
  height — use it for **exactly two** anchored blocks (header top + footer bottom);
  with 3+ light blocks it scatters into dead bands (`foundations`).
- `stretch` only on the cross axis when the container has definite space.

## Repair implications

If preflight reports an artboard-bounds or parent-containment problem, do not
repair only the most visible text node. The correct fix is often a bounded
`layout_cluster` repair: adjust the diagnosed parent/root frame and affected
descendants together (p/s, fill/hug/fixed sizing, g/pad/x/y, text wrapping, or
converting a background-like rect into the diagnosed artboard/root fill). When the
root artboard frame itself must match the exportable surface, use `s(fill,fill)`
rather than hardcoded page dimensions.

## Future scaffold

Responsive/variant recipes, repeater/conditional regions, dense stat/table
modules, multi-page brochures, pagination rules, editorial grid systems.
