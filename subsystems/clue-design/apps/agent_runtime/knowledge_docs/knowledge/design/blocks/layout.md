# Lumen DSL Vetted Blocks — Layout & Structure

Pre-proportioned, pre-spaced structural blocks for the page shell: hero, header,
footer, divider, and section band. ASSEMBLE these — do not re-invent proportions
from primitives (that is what overcrowds designs and trips `LUMV0810`/`0903`/`0904`).

Every fenced `text` example below is **self-contained** (a `page` + one clipped
root `artboard` + the block + `#slot:` fixture lines) and was personally run
through `.context/p02-validate.py` returning `{"ok": true}`. The only warnings are
`LUMB0613`/`LUMB0614` (platform font not embeddable/subsettable) — environmental,
never failing. Geometry rules that make these pass (calibrated, not guessed):

- A **slotted** text node needs a fixed `s(W,H)` (width AND height) sized for its
  `worst_case` copy; `hug`/`s(fill,hug)` on a slotted node fails `LUMV0810`.
  Fixtures attach ONLY via a `#slot:<key> sample(...) worst_case(...)` line indented
  one level under the `page` — never as node properties.
- Width floors (platform type is large): `$type.subtitle` 2 words `ml(1)` ≥ 160;
  `$type.body.small` ~5-word sentence ≥ 220; a 5-6-word header needs `$type.headline`
  at W≥499 (`$type.title` will not wrap 5-6 words at that width).
- A4 portrait is `595 x 842 pt`. With `pad(48)` the content width is `499`; a
  full-bleed band laid in a `pad(0)` artboard is `595` wide and gets `499` of inner
  content width back from its own `pad(48)`. Size slotted text to that `499`.
- Center via an `al(x(c),y(c))` wrapper — there is no `align`/`valign`/`text_align`.
  A divider is a `rect` (`r s(fill,2) fill($border.subtle)`) — there is no `divider`
  node, and `$stroke.width.divider` is illegal inside `s(...)`.

---

## Hero (eyebrow + headline + subtitle + CTA)

**When to use:** the single focal message of a social square (1080×1080). One
eyebrow, one headline, one supporting sentence, one CTA — vertically centered with
`y(c)` and surrounded by `pad(96)` (~65% whitespace). This is the dominant region;
nothing competes with it.

**When to use / Content budget:** eyebrow 2-4 words `max_lines(1)`; headline 4-8
words `max_lines(2)` at `$type.headline` `lh(1.08)`; subtitle 6-25 words
`max_lines(3)` at `$type.body` `lh(1.4)`; CTA 2-3 words `max_lines(1)`. All four
text nodes are slotted with fixed boxes sized for worst_case: headline `888×200`,
subtitle `820×150`, eyebrow `888×40`. The CTA label is `s(fill,48)` inside a
fixed `s(340,72)` button (`fill($surface.inverse)` `rd($radius.button)`) and is
centered by the button's `al(h, x(c), y(c), …)`. Hero surface is `$surface.brand`;
the dark button sits on it as the focal action.

```text
page hero_square size(1080,1080,px)
  artboard al(v, x(s), y(c), g($space.stack.loose), pad(96)) p(0,0) s(fill,fill) fill($surface.brand) clip(true)
    content al(v, x(s), g($space.stack.default), pad(0)) p(0,0) s(888,hug)
      eyebrow text "FOR SPECIALTY CLINICS" p(0,0) s(888,40) style($type.eyebrow) wrap_text(true) max_lines(1) slot(campaign.eyebrow)
      headline text "Answer every patient call." p(0,0) s(888,200) style($type.headline) lh(1.08) wrap_text(true) max_lines(2) slot(campaign.headline)
      subtitle text "Insight Health handles intake." p(0,0) s(820,150) style($type.body) lh(1.4) wrap_text(true) max_lines(3) slot(offer.primary_message)
      cta al(h, x(c), y(c), pad(18,36)) p(0,0) s(340,72) fill($surface.inverse) rd($radius.button)
        cta_text text "Book a Demo" p(0,0) s(fill,48) style($type.cta) max_lines(1) slot(campaign.cta)
  #slot:campaign.eyebrow sample("FOR SPECIALTY CLINICS") worst_case("FOR HIGH-VOLUME SPECIALTY CLINICS")
  #slot:campaign.headline sample("Answer every patient call.") worst_case("Give your specialists their operating hours back.")
  #slot:offer.primary_message sample("Insight Health handles intake.") worst_case("Insight Health answers, qualifies, books the visit, and routes the rest to your team.")
  #slot:campaign.cta sample("Book a Demo") worst_case("Start Free Trial")
```

Validator proof:
```json
{ "ok": true, "stage": "preflight", "errors": [], "warnings": ["LUMB0613", "LUMB0614"] }
```

---

## Header (logo lockup left + contact/nav right)

**When to use:** the top band of a one-pager / letter. A `space_between`
(`x(sb)`) row: brand lockup pinned left, a single contact or nav line pinned
right, vertically centered with `y(c)`. Keep it visually subordinate to the hero
below it — small type, one line each, no card.

**When to use / Content budget:** wordmark ≤2 words `max_lines(1)` at
`$type.label` (the canonical brand-name role across the catalog; the standalone
**Logo lockup** uses larger `$type.title` only because it is a hero-scale identity
unit) in a `200`-wide box; contact ≤1 line `max_lines(1)` at `$type.body.small` in
a `220`-wide box (the body.small floor).
The logo mark is a fixed `s(40,40)` chip (`fill($surface.brand)`
`rd($radius.badge)`) with a 2-letter monogram centered by its own `al(x(c),y(c))`.
The outer row is fixed `s(499,hug)` (A4 `pad(48)` content width) so the
left/right ends resolve; the brand lockup is a fixed `s(260,hug)` so the
`x(sb)` split is stable.

```text
page header_page preset(a4,portrait)
  artboard al(v, x(s), g($space.section), pad(48)) p(0,0) s(fill,fill) fill($surface.page) clip(true)
    header al(h, x(sb), y(c), g($space.md), pad(0)) p(0,0) s(499,hug)
      brand al(h, x(s), y(c), g(12), pad(0)) p(0,0) s(260,hug)
        mark al(h, x(c), y(c), pad(0)) p(0,0) s(40,40) fill($surface.brand) rd($radius.badge)
          markt text "IH" p(0,0) s(fill,28) style($type.eyebrow) max_lines(1)
        wordmark text "Insight Health" p(0,0) s(200,32) style($type.label) wrap_text(true) max_lines(1) slot(account.name)
      contact text "hello@insighthealth.com" p(0,0) s(220,28) style($type.body.small) wrap_text(true) max_lines(1) slot(account.contact)
  #slot:account.name sample("Insight Health") worst_case("Insight Health")
  #slot:account.contact sample("hello@insighthealth.com") worst_case("hello@insighthealth.com")
```

Validator proof:
```json
{ "ok": true, "stage": "preflight", "errors": [], "warnings": ["LUMB0613", "LUMB0614"] }
```

---

## Footer (contact + legal, tinted band)

**When to use:** the closing band of a one-pager. A tinted card
(`fill($surface.muted)` `rd($radius.card)` `pad($space.card.padding)`) holding a
`space_between` top row (contact block left, one CTA right), a hairline `rect`
rule, and a fine-print legal line. Visually quiet — it closes the page, it does
not compete with the hero.

**When to use / Content budget:** company name ≤2 words `max_lines(1)`
`$type.label` (matches the Header wordmark and the composition logos); contact line ≤1 short line — but email + phone together exceeds
the body.small 1-line floor, so give it `max_lines(2)` with a `300×52` box;
legal ≤15 words `max_lines(2)` at `$type.legal`. The CTA is a compact fixed
`s(150,56)` button. The top row is fixed `s(467,hug)` (the card's inner width:
`499 − 2×16` card padding); contact column `300`, CTA `150` plus the `$space.md`
gap split by `x(sb)`. The rule is `r s(fill,2) fill($border.subtle)` — numeric
height, never `$stroke.width.divider` in `s(...)`.

```text
page footer_page preset(a4,portrait)
  artboard al(v, x(s), g($space.section), pad(48)) p(0,0) s(fill,fill) fill($surface.page) clip(true)
    footer al(v, x(s), g($space.stack.default), pad($space.card.padding)) p(0,0) s(499,hug) fill($surface.muted) rd($radius.card)
      top al(h, x(sb), y(c), g($space.md), pad(0)) p(0,0) s(467,hug)
        contact al(v, x(s), g(4), pad(0)) p(0,0) s(300,hug)
          cname text "Insight Health" p(0,0) s(300,30) style($type.label) wrap_text(true) max_lines(1) slot(account.name)
          cinfo text "hello@insighthealth.com  ·  (555) 012-3456" p(0,0) s(300,52) style($type.body.small) wrap_text(true) max_lines(2) slot(account.contact)
        cta al(h, x(c), y(c), pad(14,28)) p(0,0) s(150,56) fill($surface.inverse) rd($radius.button)
          ctat text "Get Started" p(0,0) s(fill,40) style($type.cta) max_lines(1) slot(campaign.cta)
      rule r p(0,0) s(fill,2) fill($border.subtle)
      legal text "© 2026 Insight Health, Inc. All rights reserved." p(0,0) s(467,28) style($type.legal) wrap_text(true) max_lines(2) slot(footer.legal)
  #slot:account.name sample("Insight Health") worst_case("Insight Health")
  #slot:account.contact sample("hello@insighthealth.com  ·  (555) 012-3456") worst_case("hello@insighthealth.com  ·  (555) 012-3456")
  #slot:campaign.cta sample("Get Started") worst_case("Get Started")
  #slot:footer.legal sample("© 2026 Insight Health, Inc. All rights reserved.") worst_case("© 2026 Insight Health, Inc. All rights reserved.")
```

Validator proof:
```json
{ "ok": true, "stage": "preflight", "errors": [], "warnings": ["LUMB0613", "LUMB0614"] }
```

---

## Divider (horizontal rule via rect)

**When to use:** to separate two regions. There is NO `divider` node (`LUMD0206`)
— a rule is a `rect` (`r`) with a numeric thickness: `r s(fill,2)
fill($border.subtle)`. Two forms are shown: a plain full-width rule, and a
labeled rule (rule + centered word + rule) for an "OR"-style break.

**When to use / Content budget:** the rule thickness is the literal number `2`
inside `s(fill,2)` — `$stroke.width.divider` is a `stroke(...)` token only and is
rejected inside `s(...)` (`LUMB0301`). The label in the labeled form is a short,
hard-coded structural word (e.g. "OR") so it carries NO `slot(...)` (render fit
applies; `hug`/fixed is fine) — give it a fixed `s(60,28)` box centered in an
`al(h, x(c), y(c), …)` between two `r s(fill,2)` rules so the word sits in the gap.

```text
page divider_page preset(a4,portrait)
  artboard al(v, x(s), g($space.section), pad(48)) p(0,0) s(fill,fill) fill($surface.page) clip(true)
    above text "Trusted by specialty clinics nationwide." p(0,0) s(499,hug) style($type.body) lh(1.4) wrap_text(true) max_lines(2)
    rule r p(0,0) s(fill,2) fill($border.subtle)
    labeled al(h, x(c), y(c), g($space.md), pad(0)) p(0,0) s(499,hug)
      l_left r p(0,0) s(fill,2) fill($border.subtle)
      l_text text "OR" p(0,0) s(60,28) style($type.eyebrow) max_lines(1)
      l_right r p(0,0) s(fill,2) fill($border.subtle)
    below text "Talk to our team about a pilot." p(0,0) s(499,hug) style($type.body) lh(1.4) wrap_text(true) max_lines(2)
```

Validator proof:
```json
{ "ok": true, "stage": "preflight", "errors": [], "warnings": ["LUMB0613", "LUMB0614"] }
```

---

## Section band (full-width tinted band wrapper)

**When to use:** wrap a region in a full-bleed tinted band to set it apart from
the page (e.g. a pilot/CTA section). The artboard is `pad(0)` so the band runs
edge to edge (`s(fill,hug)` = 595 wide on A4); the band supplies its own
`pad($space.section)` (use `pad(48)` for a predictable `499` inner width) and a
soft `fill($surface.brand.subtle)`. It holds an eyebrow + a header + one body
paragraph — one focal idea per band.

**When to use / Content budget:** eyebrow 2-4 words `max_lines(1)`; section header
4-6 SHORT words `max_lines(2)` at `$type.headline` (NOT `$type.title`, which will
not wrap 5-6 words at `499`); body 6-12 words `max_lines(3)` at `$type.body`
`lh(1.4)`. All slotted text is sized to the `499` inner width — eyebrow `499×32`,
title `499×140`, body `499×120`. Keep the header tight: at `499`/`ml(2)` the
headline fits ~6 short words; a denser 6-word string (long words back to back) can
tip to a 3rd line and fail `LUMV0810` — stay at or below 6 short words, or raise to
`max_lines(2)` with a taller `499×160` box.

```text
page band_page preset(a4,portrait)
  artboard al(v, x(s), g($space.section), pad(0)) p(0,0) s(fill,fill) fill($surface.page) clip(true)
    band al(v, x(s), g($space.stack.default), pad(48)) p(0,0) s(fill,hug) fill($surface.brand.subtle)
      eyebrow text "PILOT PROGRAM" p(0,0) s(499,32) style($type.eyebrow) wrap_text(true) max_lines(1) slot(section.eyebrow)
      title text "Try it on your busiest week." p(0,0) s(499,140) style($type.headline) lh(1.12) wrap_text(true) max_lines(2) slot(section.title)
      body text "Run a two-week pilot and measure booked visits." p(0,0) s(499,120) style($type.body) lh(1.4) wrap_text(true) max_lines(3) slot(section.body)
  #slot:section.eyebrow sample("PILOT PROGRAM") worst_case("PILOT PROGRAM")
  #slot:section.title sample("Try it on your busiest week.") worst_case("Try it on your busiest week.")
  #slot:section.body sample("Run a two-week pilot and measure booked visits.") worst_case("Run a two-week pilot and measure booked visits.")
```

Validator proof:
```json
{ "ok": true, "stage": "preflight", "errors": [], "warnings": ["LUMB0613", "LUMB0614"] }
```
