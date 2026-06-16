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

- **Slotted text node ⇒ fixed `s(W,H)`** (definite width AND height) sized for the
  `worst_case` copy. `hug`/`s(fill,hug)` on a slotted node fails `LUMV0810`. Plain
  containers may stay `hug`; only the slotted leaf text needs a fixed box.
- Fixtures attach **only** via a `#slot:<key> sample("…") worst_case("…")` modify
  line indented one level under the `page` (never under the artboard, never as a
  node property).
- Tokens only — `$surface.*`, `$text.*`, `$type.*`, `$space.*`, `$radius.*`,
  `$border.*`. Colors are never bare numbers; `rd()` is one uniform radius.
- Center a label by wrapping it in `al(x(c), y(c))` — there is no `valign`/`align`.

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
`max_lines(3)` or the fixture overflows (`LUMV0810`). Card is `pad($space.card.padding)`
inside `rd($radius.card)`; title→body gap is `$space.stack.default`.

```text
page card_demo size(1080,1080,px)
  artboard al(v, x(s), y(c), g($space.section), pad(96)) p(0,0) s(fill,fill) fill($surface.page) clip(true)
    card al(v, x(s), g($space.stack.default), pad($space.card.padding)) p(0,0) s(840,hug) fill($surface.card) rd($radius.card)
      card_title text "Automated patient intake" p(0,0) s(752,120) style($type.headline) lh(1.12) wrap_text(true) max_lines(2) slot(card.title)
      card_body text "Insight Health answers, qualifies, and books the visit." p(0,0) s(752,200) style($type.body) lh(1.4) wrap_text(true) max_lines(3) slot(card.body)
  #slot:card.title sample("Automated patient intake") worst_case("Automated patient intake")
  #slot:card.body sample("Insight Health answers, qualifies, and books the visit.") worst_case("Insight Health answers, qualifies, books the visit, and routes the rest to your team.")
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
`$text.secondary` by default). The value box is fixed (`356×120`) so a `worst_case`
like `"12,480"` (a count, not just a percentage) still fits at `$type.stat` —
slot the value as `stat.value` and size for the *longest* realistic number. The
tile is `pad($space.card.padding)`; value→label gap is `$space.stack.tight` (the
label reads as a caption *belonging to* the number, so keep them tight).

```text
page stat_demo size(1080,1080,px)
  artboard al(v, x(s), y(c), g($space.section), pad(96)) p(0,0) s(fill,fill) fill($surface.page) clip(true)
    tile al(v, x(s), g($space.stack.tight), pad($space.card.padding)) p(0,0) s(420,hug) fill($surface.card) rd($radius.card)
      stat_value text "98%" p(0,0) s(356,120) style($type.stat) lh(1.0) wrap_text(true) max_lines(1) slot(stat.value)
      stat_label text "of calls answered in seconds" p(0,0) s(356,80) style($type.caption) lh(1.3) wrap_text(true) max_lines(2) slot(stat.label)
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
Title→desc gap is `$space.stack.tight`. If you need richer descriptions, switch to
a stacked layout of **Benefit item** rows (wide columns fit long copy).

```text
page benefit_row_demo size(1080,1080,px)
  artboard al(v, x(s), y(c), g($space.section), pad(96)) p(0,0) s(fill,fill) fill($surface.page) clip(true)
    row al(h, x(s), y(s), g(24), pad(0)) p(0,0) s(888,hug)
      c1 al(v, x(s), g($space.stack.tight), pad(0)) p(0,0) s(280,hug)
        c1t text "Faster intake" p(0,0) s(280,40) style($type.subtitle) lh(1.15) wrap_text(true) max_lines(1) slot(benefit.1.title)
        c1d text "Route every call in seconds." p(0,0) s(280,90) style($type.body.small) lh(1.4) wrap_text(true) max_lines(3) slot(benefit.1.desc)
      c2 al(v, x(s), g($space.stack.tight), pad(0)) p(0,0) s(280,hug)
        c2t text "Less busywork" p(0,0) s(280,40) style($type.subtitle) lh(1.15) wrap_text(true) max_lines(1) slot(benefit.2.title)
        c2d text "Reminders sent automatically." p(0,0) s(280,90) style($type.body.small) lh(1.4) wrap_text(true) max_lines(3) slot(benefit.2.desc)
      c3 al(v, x(s), g($space.stack.tight), pad(0)) p(0,0) s(280,hug)
        c3t text "Happier patients" p(0,0) s(280,40) style($type.subtitle) lh(1.15) wrap_text(true) max_lines(1) slot(benefit.3.title)
        c3d text "Shorter waits, clearer steps." p(0,0) s(280,90) style($type.body.small) lh(1.4) wrap_text(true) max_lines(3) slot(benefit.3.desc)
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
descriptions can be a full sentence, unlike the cramped 3-up. The leading chip is
a fixed `s(72,72)` `rd($radius.full)` on `$surface.brand.subtle` with a centered
glyph (swap the `"1"` for a number, initial, or a `vector`/`svg` icon). Chip→copy
gap is `$space.md`; title→desc gap is `$space.stack.tight`.

```text
page benefit_item_demo size(1080,1080,px)
  artboard al(v, x(s), y(c), g($space.section), pad(96)) p(0,0) s(fill,fill) fill($surface.page) clip(true)
    item al(h, x(s), y(s), g($space.md), pad(0)) p(0,0) s(888,hug)
      icon al(h, x(c), y(c), pad(0)) p(0,0) s(72,72) fill($surface.brand.subtle) rd($radius.full)
        glyph text "1" p(0,0) s(48,52) style($type.title) max_lines(1)
      copy al(v, x(s), g($space.stack.tight), pad(0)) p(0,0) s(792,hug)
        item_title text "Answer every call" p(0,0) s(792,48) style($type.subtitle) lh(1.15) wrap_text(true) max_lines(1) slot(benefit.title)
        item_desc text "Insight Health picks up day or night, qualifies the patient, and books the visit automatically." p(0,0) s(792,120) style($type.body.small) lh(1.4) wrap_text(true) max_lines(3) slot(benefit.desc)
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
fits at the 480pt box). The mark is a fixed `s(64,64)` chip on `$surface.brand`
with `rd($radius.md)` and a centered glyph (swap `"IH"` for an `image asset(...)`
logo or a `vector`/`svg` mark). The row is `y(c)` so mark and wordmark are
vertically centered; mark→wordmark gap is `$space.sm` (a lockup reads as one unit,
so keep the gap tight).

```text
page logo_demo size(1080,1080,px)
  artboard al(v, x(s), y(c), g($space.section), pad(96)) p(0,0) s(fill,fill) fill($surface.page) clip(true)
    lockup al(h, x(s), y(c), g($space.sm), pad(0)) p(0,0) s(560,hug)
      mark al(h, x(c), y(c), pad(0)) p(0,0) s(64,64) fill($surface.brand) rd($radius.md)
        mark_glyph text "IH" p(0,0) s(48,52) style($type.subtitle) max_lines(1)
      wordmark text "Insight Health" p(0,0) s(480,56) style($type.title) lh(1.0) wrap_text(true) max_lines(1) slot(account.name)
  #slot:account.name sample("Insight Health") worst_case("Riverside Medical Group")
```

Validator proof:
```json
{ "ok": true, "stage": "preflight", "errors": [], "warnings": ["LUMB0613", "LUMB0614"] }
```
