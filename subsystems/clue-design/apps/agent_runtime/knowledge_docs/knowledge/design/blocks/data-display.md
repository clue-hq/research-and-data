# Lumen DSL Vetted Blocks — Data Display

Pre-proportioned, validator-passed building blocks for surfacing information:
cards, stat tiles, benefit rows/items, and a logo lockup. **Assemble** these
instead of inventing proportions from primitives — the sizing below is already
calibrated against the fixture-fit validator so the agent stops overcrowding and
stops failing `LUMV0810`/`LUMV0903`/`LUMV0904`.

Every fenced `text` example is a self-contained doc (`page` + one clipped root
`artboard` + the block + `#slot:` fixture lines) that **personally returned
`ok==true`** from `.context/p02-validate.py`. The only warnings are
`LUMB0613`/`LUMB0614` (platform font not embeddable/subsettable) — these are
environmental and never fail a block.

Universal rules these blocks bake in:

- **Slotted text node ⇒ definite width + HUG height** sized for the `worst_case`
  copy: `s(W,hug)`. `text_fit` uses the node's own line height, so hug heights
  validate for slotted nodes too — a fixed pixel height just reserves dead space.
  Keep the width definite and `wrap_text(true) + max_lines(N)`; let the height hug.
- Fixtures attach **only** via a `#slot:<key> sample("…") worst_case("…")` modify
  line indented one level under the `page` (never under the artboard, never as a
  node property).
- Tokens only — `$surface.*`, `$text.*`, `$type.*`, `$space.*`, `$radius.*`,
  `$border.*`. Colors are never bare numbers; `rd()` is one uniform radius.
- Center a *label's glyph* with `align(center)` (alias `text_align(center)`) on the
  text node — it sets horizontal text alignment independently of `style($type.x)`
  and renders the glyph centered (no hug-width needed). When the label sits in a
  taller centered container (`al(…, x(c), y(c))`), pair `align(center)` with a
  **hug height** (`s(fill,hug) align(center)`) so the container's `y(c)` centers
  the glyph-tall box. Do **not** use hug WIDTH for centering (trips `LUMV0902`).
  Leave left-aligned body/title text alone (keep it left / `x(s)`).

---

## Card

**When to use:** a single self-contained unit of content on a page surface — a
title with a short supporting paragraph — set on `$surface.card`. Reach for this
when one idea deserves a contained, slightly elevated region rather than living
loose on the page. One card is a secondary region; do not tile a page with cards.

**When to use / Content budget:** title ≤4 words `max_lines(2)` (`$type.headline`,
wraps where `$type.title` will not); body 12-25 words `max_lines(3)`
(`$type.body`). The 752pt body column clears the `$type.body` width floor — a
14-word `worst_case` fits in 3 lines at this width; do not push past ~15 words at
`max_lines(3)` or the fixture overflows (`LUMV0810`). Title and body are
left-aligned (`x(s)`), so they keep their definite width with **hug heights**
(`s(752,hug)`) — text heights hug, no dead space reserved. Card is
`pad($space.card.padding)` inside `rd($radius.card)`; title→body gap is
`$space.stack.default`.

```text
page card_demo size(1080,1080,px)
  artboard al(v, x(s), y(c), g($space.section), pad(96)) p(0,0) s(fill,fill) fill($surface.page) clip(true)
    card al(v, x(s), g($space.stack.default), pad($space.card.padding)) p(0,0) s(840,hug) fill($surface.card) rd($radius.card)
      card_title text "Automated patient intake" p(0,0) s(752,hug) style($type.headline) lh(1.12) wrap_text(true) max_lines(2) slot(card.title)
      card_body text "Insight Health answers, qualifies, and books the visit." p(0,0) s(752,hug) style($type.body) lh(1.4) wrap_text(true) max_lines(3) slot(card.body)
  #slot:card.title sample("Automated patient intake") worst_case("Automated patient intake")
  #slot:card.body sample("Insight Health answers, qualifies, and books the visit.") worst_case("Insight Health answers, qualifies, books the visit, and routes the rest to your team.")
```

Validator proof:
```json
{ "ok": true, "stage": "preflight", "errors": [], "warnings": ["LUMB0613", "LUMB0614"] }
```

---

## Card on a ground (elevated plate)

**When to use:** reach for this when the ad has a coloured or textured ground and
the message needs its own calm surface to sit on. The card gives the copy a light
plate so the ground can stay saturated. Use it when the reference ad you are
matching shows a rounded panel floating over a field. It carries the WHOLE message
— eyebrow, headline, support line, and one call to action — so it replaces the
loose centred stack rather than decorating it.

**When NOT to use:** do not use it when the ground is already plain paper. A card
on `$surface.page` is an invisible box with a shadow under it. Do not put a second
card beside it — two plates of equal weight kill the focal point. Do not lift it
with a hard dark shadow; the shadow reads as air under the plate, never as a drawn
outline.

**Content budget / geometry:** the card is `s(760,hug)` on a 1080² ground with
`pad(96)`, so it clears the ground on every side and the ground stays visible as a
frame. `pad(64)` inside the card leaves a `632pt` content column — size every
slotted text node to that width with a hug height. Eyebrow 1-3 words `max_lines(1)`;
headline 4-8 words `max_lines(2)` at `$type.headline`; support ≤12 words
`max_lines(3)` at `$type.body.small` (`$type.body` is tuned for the wider 820pt hero
column and crowds a 632pt card). One CTA, fixed `s(300,72)`, label `s(fill,hug)
align(center)`.

**The elevation:** `rd($radius.card)` for the corner and one soft
`shadow(card_lift, #000000, o(0.18), y(24), blur(56))`. The blur is scaled up from
the `skills/effects` card recipe (`o(0.12), y(8), blur(24)`) because that recipe is
tuned for a ~400pt card and this plate is 760pt wide — a small blur on a big plate
reads as a printed edge. **The shadow colour is a literal neutral, not a brand
hex:** the Brand Kit's token groups carry no `shadow.*` entries, so there is no
role to reference; use `#000000` at low opacity (ink) and never a brand colour.

```text
page card_on_ground size(1080,1080,px)
  artboard al(v, x(c), y(c), g($space.section), pad(96)) p(0,0) s(fill,fill) fill($surface.brand) clip(true)
    card al(v, x(s), y(c), g($space.stack.default), pad(64)) p(0,0) s(760,hug) fill($surface.card) rd($radius.card) shadow(card_lift, #000000, o(0.18), y(24), blur(56))
      eyebrow text "WEBINAR" p(0,0) s(632,hug) style($type.eyebrow) wrap_text(true) max_lines(1) slot(campaign.eyebrow)
      headline text "Close the quarter with fewer tools." p(0,0) s(632,hug) style($type.headline) lh(1.06) wrap_text(true) max_lines(2) slot(campaign.headline)
      support text "One workspace for pipeline, forecast, and the board deck." p(0,0) s(632,hug) style($type.body.small) lh(1.4) wrap_text(true) max_lines(3) slot(offer.primary_message)
      cta al(h, x(c), y(c), pad(18,36)) p(0,0) s(300,72) fill($surface.inverse) rd($radius.button)
        cta_text text "Save my seat" p(0,0) s(fill,hug) align(center) style($type.cta) max_lines(1) slot(campaign.cta)
  #slot:campaign.eyebrow sample("WEBINAR") worst_case("WEBINAR ON DEMAND")
  #slot:campaign.headline sample("Close the quarter with fewer tools.") worst_case("Close the quarter with fewer tools.")
  #slot:offer.primary_message sample("One workspace for pipeline, forecast, and the board deck.") worst_case("One workspace for pipeline, forecast, and the board deck.")
  #slot:campaign.cta sample("Save my seat") worst_case("Save my seat")
```

Validator proof:
```json
{ "ok": true, "stage": "preflight", "errors": [], "warnings": ["LUMB0613", "LUMB0614"] }
```

---

## Framed plate (a document inside a card)

**When to use:** show a report cover, a document, or a piece of artwork as an
**object**. The image sits inside the card with a visible margin on all four sides,
so the card reads as a frame around it. Reach for this when the artifact IS the
subject of the ad — a benchmark report, a guide, an issue of something.

**When NOT to use:** do not use it when the image is atmosphere rather than
subject; that ground belongs full-bleed behind the whole ad (see the
**Card on a washed ground** composition in `knowledge/design/blocks/patterns`). Do
not let the margin collapse to zero — an image touching the card edge stops looking
framed and starts looking mis-cropped. Do not frame a photograph of people this
way; a frame says "document".

**Content budget / geometry:** the plate is a FIXED `s(720,880)` (not `hug`) so the
frame proportion is the design decision and does not drift with the caption length.
`pad(40)` is the frame margin; the inner panel is `s(640,600)`, which leaves exactly
40pt of card on the left and right (`720 − 2×40 = 640`). The caption column below is
the same 640 wide. Kicker 2-4 words `max_lines(1)`; title 4-7 words `max_lines(2)`.
The panel takes `rd($radius.md)` — a smaller radius than the card's
`rd($radius.card)`, so the frame reads as the outer object and the artwork as the
inner one.

**Placement is on the node, not the DSL line.** The `image` line carries only
`asset(cover_art)`; its `fit:cover` + focal point + alt are set on the node's
AssetPlacement by `asset(action="place")` (see `knowledge/images/placement`). Swap
`cover_art` for the generated or uploaded asset id.

```text
page framed_plate size(1080,1080,px)
  artboard al(v, x(c), y(c), g($space.section), pad(96)) p(0,0) s(fill,fill) fill($surface.muted) clip(true)
    plate al(v, x(c), y(s), g($space.stack.default), pad(40)) p(0,0) s(720,880) fill($surface.card) rd($radius.card) shadow(plate_lift, #000000, o(0.16), y(20), blur(48))
      panel image asset(cover_art) p(0,0) s(640,600) rd($radius.md)
      caption al(v, x(s), g($space.stack.tight), pad(0)) p(0,0) s(640,hug)
        kicker text "2026 BENCHMARK REPORT" p(0,0) s(640,hug) style($type.eyebrow) wrap_text(true) max_lines(1) slot(campaign.eyebrow)
        title text "How finance teams closed the gap." p(0,0) s(640,hug) style($type.headline) lh(1.06) wrap_text(true) max_lines(2) slot(campaign.headline)
  #slot:campaign.eyebrow sample("2026 BENCHMARK REPORT") worst_case("2026 BENCHMARK REPORT")
  #slot:campaign.headline sample("How finance teams closed the gap.") worst_case("How finance teams closed the gap.")
```

Validator proof:
```json
{ "ok": true, "stage": "preflight", "errors": [], "warnings": ["LUMB0613", "LUMB0614"] }
```

---

## Stat tile

**When to use:** spotlight one metric — a big number with a short label beneath
it. Use 1-3 of these in a row for social proof / outcomes; stop at three.

**When to use / Content budget:** value 1 short numeral/token `max_lines(1)`
(`$type.stat`); label ≤5 words `max_lines(2)` (`$type.caption`,
`$text.secondary` by default). The value box keeps a definite **356pt width**
with a **hug height** (`s(356,hug)`) so a `worst_case` like `"12,480"` (a count,
not just a percentage) still fits at `$type.stat` — slot the value as `stat.value`
and size the *width* for the *longest* realistic number; the height hugs (no dead
zone). Value and label are left-aligned (`x(s)`), so they stay left — no
`align(center)` here. The tile is `pad($space.card.padding)`; value→label gap is
`$space.stack.tight` (the label reads as a caption *belonging to* the number, so
keep them tight).

```text
page stat_demo size(1080,1080,px)
  artboard al(v, x(s), y(c), g($space.section), pad(96)) p(0,0) s(fill,fill) fill($surface.page) clip(true)
    tile al(v, x(s), g($space.stack.tight), pad($space.card.padding)) p(0,0) s(420,hug) fill($surface.card) rd($radius.card)
      stat_value text "98%" p(0,0) s(356,hug) style($type.stat) lh(1.0) wrap_text(true) max_lines(1) slot(stat.value)
      stat_label text "of calls answered in seconds" p(0,0) s(356,hug) style($type.caption) lh(1.3) wrap_text(true) max_lines(2) slot(stat.label)
  #slot:stat.value sample("98%") worst_case("12,480")
  #slot:stat.label sample("of calls answered in seconds") worst_case("of calls answered in seconds")
```

Validator proof:
```json
{ "ok": true, "stage": "preflight", "errors": [], "warnings": ["LUMB0613", "LUMB0614"] }
```

---

## Benefit row (3-up)

**When to use:** three peer benefits *across* a **wide** surface (1080 square or
wider). This is the disciplined horizontal 3-up. **Do not author a 3-across row on
A4 portrait** — at 595pt the three description columns cannot clear the body-text
width floor and you get guaranteed `LUMV0810`; on A4, stack benefits as full-width
rows (use **Benefit item** repeated) instead.

**When to use / Content budget:** title ≤2 words `max_lines(1)` (`$type.subtitle`,
≥160pt box); description **≤6 words** `max_lines(3)` (`$type.body.small`). This is
the key discipline encoded here: at the narrow ~280pt column width of a 3-up,
descriptions MUST be terse — a 10-word description overflows `LUMV0810` even at
`max_lines(6)`. Keep them to a single short phrase. Geometry: 1080 square,
`pad(96)` ⇒ 888pt content; three `s(280,…)` cells + two `g(24)` gaps = 888 exactly.
Titles and descriptions are left-aligned (`x(s)`) and keep their 280pt width with
**hug heights** (`s(280,hug)`) — text heights hug, no dead space. Title→desc gap
is `$space.stack.tight`. If you need richer descriptions, switch to a stacked
layout of **Benefit item** rows (wide columns fit long copy).

```text
page benefit_row_demo size(1080,1080,px)
  artboard al(v, x(s), y(c), g($space.section), pad(96)) p(0,0) s(fill,fill) fill($surface.page) clip(true)
    row al(h, x(s), y(s), g(24), pad(0)) p(0,0) s(888,hug)
      c1 al(v, x(s), g($space.stack.tight), pad(0)) p(0,0) s(280,hug)
        c1t text "Faster intake" p(0,0) s(280,hug) style($type.subtitle) lh(1.15) wrap_text(true) max_lines(1) slot(benefit.1.title)
        c1d text "Route every call in seconds." p(0,0) s(280,hug) style($type.body.small) lh(1.4) wrap_text(true) max_lines(3) slot(benefit.1.desc)
      c2 al(v, x(s), g($space.stack.tight), pad(0)) p(0,0) s(280,hug)
        c2t text "Less busywork" p(0,0) s(280,hug) style($type.subtitle) lh(1.15) wrap_text(true) max_lines(1) slot(benefit.2.title)
        c2d text "Reminders sent automatically." p(0,0) s(280,hug) style($type.body.small) lh(1.4) wrap_text(true) max_lines(3) slot(benefit.2.desc)
      c3 al(v, x(s), g($space.stack.tight), pad(0)) p(0,0) s(280,hug)
        c3t text "Happier patients" p(0,0) s(280,hug) style($type.subtitle) lh(1.15) wrap_text(true) max_lines(1) slot(benefit.3.title)
        c3d text "Shorter waits, clearer steps." p(0,0) s(280,hug) style($type.body.small) lh(1.4) wrap_text(true) max_lines(3) slot(benefit.3.desc)
  #slot:benefit.1.title sample("Faster intake") worst_case("Faster intake")
  #slot:benefit.1.desc sample("Route every call in seconds.") worst_case("Route every call in seconds.")
  #slot:benefit.2.title sample("Less busywork") worst_case("Less busywork")
  #slot:benefit.2.desc sample("Reminders sent automatically.") worst_case("Reminders sent automatically.")
  #slot:benefit.3.title sample("Happier patients") worst_case("Happier patients")
  #slot:benefit.3.desc sample("Shorter waits, clearer steps.") worst_case("Shorter waits, clearer steps.")
```

Validator proof:
```json
{ "ok": true, "stage": "preflight", "errors": [], "warnings": ["LUMB0613", "LUMB0614"] }
```

---

## Benefit item

**When to use:** a single icon/number + title + description unit, full width. This
is the row primitive to **stack vertically** when you have 2-4 benefits and want
real descriptions (the correct shape for A4 portrait, where a 3-across row cannot
fit body text — see Benefit row above). Repeat it inside a
`al(v, g($space.stack.loose))` list.

**When to use / Content budget:** title ≤4 words `max_lines(1)` (`$type.subtitle`);
description ≤16 words `max_lines(3)` (`$type.body.small`). Because the copy column
is full-width (792pt here), it clears the body-text floor with room to spare — so
descriptions can be a full sentence, unlike the cramped 3-up. Title and
description are left-aligned (`x(s)`) with **hug heights** (`s(792,hug)`) — text
heights hug, no dead space. The leading chip is a fixed `s(72,72)` `rd($radius.full)`
on `$surface.brand.subtle`; its glyph is centered with `align(center)` + a hug
height (`s(fill,hug) align(center)`) so the chip's `x(c), y(c)` centers the
glyph-tall box (swap the `"1"` for a number, initial, or a `vector`/`svg` icon).
Chip→copy gap is `$space.md`; title→desc gap is `$space.stack.tight`.

```text
page benefit_item_demo size(1080,1080,px)
  artboard al(v, x(s), y(c), g($space.section), pad(96)) p(0,0) s(fill,fill) fill($surface.page) clip(true)
    item al(h, x(s), y(s), g($space.md), pad(0)) p(0,0) s(888,hug)
      icon al(h, x(c), y(c), pad(0)) p(0,0) s(72,72) fill($surface.brand.subtle) rd($radius.full)
        glyph text "1" p(0,0) s(fill,hug) style($type.title) align(center) max_lines(1)
      copy al(v, x(s), g($space.stack.tight), pad(0)) p(0,0) s(792,hug)
        item_title text "Answer every call" p(0,0) s(792,hug) style($type.subtitle) lh(1.15) wrap_text(true) max_lines(1) slot(benefit.title)
        item_desc text "Insight Health picks up day or night, qualifies the patient, and books the visit automatically." p(0,0) s(792,hug) style($type.body.small) lh(1.4) wrap_text(true) max_lines(3) slot(benefit.desc)
  #slot:benefit.title sample("Answer every call") worst_case("Answer every call")
  #slot:benefit.desc sample("Insight Health picks up day or night, qualifies the patient, and books the visit automatically.") worst_case("Insight Health picks up day or night, qualifies the patient, and books the visit automatically.")
```

Validator proof:
```json
{ "ok": true, "stage": "preflight", "errors": [], "warnings": ["LUMB0613", "LUMB0614"] }
```

---

## Logo lockup

**When to use:** a brand identity row — a mark next to a wordmark — for a header,
footer, or proof region. The wordmark is the place to slot a personalized account
name.

**When to use / Content budget:** wordmark ≤3 words `max_lines(1)` (`$type.title`,
*not* `$type.headline` — title is the right scale for a wordmark and stays robust
for longer account names: a 23-char `worst_case` like `"Riverside Medical Group"`
fits at the 480pt-wide box). The wordmark is left-aligned (`x(s)`) and keeps its
480pt width with a **hug height** (`s(480,hug)`) — text height hugs, no dead space.
The mark is a fixed `s(64,64)` chip on `$surface.brand` with `rd($radius.md)`; its
glyph is centered with `align(center)` + a hug height (`s(fill,hug) align(center)`)
so the chip's `x(c), y(c)` centers the glyph-tall box (swap `"IH"` for an
`image asset(...)` logo or a `vector`/`svg` mark). The row is `y(c)` so mark and
wordmark are vertically centered; mark→wordmark gap is `$space.sm` (a lockup reads
as one unit, so keep the gap tight).

```text
page logo_demo size(1080,1080,px)
  artboard al(v, x(s), y(c), g($space.section), pad(96)) p(0,0) s(fill,fill) fill($surface.page) clip(true)
    lockup al(h, x(s), y(c), g($space.sm), pad(0)) p(0,0) s(560,hug)
      mark al(h, x(c), y(c), pad(0)) p(0,0) s(64,64) fill($surface.brand) rd($radius.md)
        mark_glyph text "IH" p(0,0) s(fill,hug) style($type.subtitle) align(center) max_lines(1)
      wordmark text "Insight Health" p(0,0) s(480,hug) style($type.title) lh(1.0) wrap_text(true) max_lines(1) slot(account.name)
  #slot:account.name sample("Insight Health") worst_case("Riverside Medical Group")
```

Validator proof:
```json
{ "ok": true, "stage": "preflight", "errors": [], "warnings": ["LUMB0613", "LUMB0614"] }
```
