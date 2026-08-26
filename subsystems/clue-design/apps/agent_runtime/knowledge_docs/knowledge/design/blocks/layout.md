# Lumen DSL Vetted Blocks — Layout & Structure

Pre-proportioned, pre-spaced structural blocks for the page shell: hero, header,
footer, divider, and section band. ASSEMBLE these — do not re-invent proportions
from primitives (that is what overcrowds designs and trips `LUMV0810`/`0903`/`0904`).

Every fenced `text` example below is **self-contained** (a `page` + one clipped
root `artboard` + the block + `#slot:` fixture lines) and was personally run
through `.context/p02-validate.py` returning `{"ok": true}`. The only warnings are
`LUMB0613`/`LUMB0614` (platform font not embeddable/subsettable) — environmental,
never failing. Geometry rules that make these pass (calibrated, not guessed):

- A **slotted** text node needs a fixed `s(W,…)` width sized for its `worst_case`
  copy; its **height hugs** (`s(W,hug)`) — `text_fit` now uses the node's own line
  height, so hug heights validate for slotted nodes and reserve no dead space.
  Fixtures attach ONLY via a `#slot:<key> sample(...) worst_case(...)` line indented
  one level under the `page` — never as node properties.
- Width floors (platform type is large): `$type.subtitle` 2 words `ml(1)` ≥ 160;
  `$type.body.small` ~5-word sentence ≥ 220; a 5-6-word header needs `$type.headline`
  at W≥499 (`$type.title` will not wrap 5-6 words at that width).
- A4 portrait is `595 x 842 pt`. With `pad(48)` the content width is `499`; a
  full-bleed band laid in a `pad(0)` artboard is `595` wide and gets `499` of inner
  content width back from its own `pad(48)`. Size slotted text to that `499`.
- Centered labels use `align(center)` + a hug height. A centered container
  (`al(…, x(c), y(c))`) centers the text BOX, but a left-anchored glyph in a box
  wider than itself hugs the left edge — so the text node itself needs
  `align(center)` (alias `text_align(center)`), which sets `text-anchor=middle`
  independently of `style($type.x)`. Keep the label fill-width or a fixed width (do
  NOT use hug WIDTH — it trips `LUMV0902`) and let `align(center)` center the glyph;
  pair it with a hug HEIGHT (`s(fill,hug)`) so the container's `y(c)` centers the
  glyph-tall box. This is how you center a label in a button/chip/cell. Leave
  left-aligned body/title text alone (no `align`).
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
text nodes are slotted with a fixed worst_case WIDTH and a hug HEIGHT: headline
`888×hug`, subtitle `820×hug`, eyebrow `888×hug` — text heights hug so no dead
space is reserved. The eyebrow/headline/subtitle are left-aligned (`x(s)` column),
so they carry no `align`. The CTA label is `s(fill,hug) align(center)` inside a
fixed `s(340,72)` button (`fill($surface.inverse)` `rd($radius.button)`): the
button's `al(h, x(c), y(c), …)` centers the hug-height label box, and
`align(center)` centers the glyph within it. Hero surface is `$surface.brand`;
the dark button sits on it as the focal action.

```text
page hero_square size(1080,1080,px)
  artboard al(v, x(s), y(c), g($space.stack.loose), pad(96)) p(0,0) s(fill,fill) fill($surface.brand) clip(true)
    content al(v, x(s), g($space.stack.default), pad(0)) p(0,0) s(888,hug)
      eyebrow text "FOR SPECIALTY CLINICS" p(0,0) s(888,hug) style($type.eyebrow) wrap_text(true) max_lines(1) slot(campaign.eyebrow)
      headline text "Answer every patient call." p(0,0) s(888,hug) style($type.headline) lh(1.08) wrap_text(true) max_lines(2) slot(campaign.headline)
      subtitle text "Insight Health handles intake." p(0,0) s(820,hug) style($type.body) lh(1.4) wrap_text(true) max_lines(3) slot(offer.primary_message)
      cta al(h, x(c), y(c), pad(18,36)) p(0,0) s(340,72) fill($surface.inverse) rd($radius.button)
        cta_text text "Book a Demo" p(0,0) s(fill,hug) align(center) style($type.cta) max_lines(1) slot(campaign.cta)
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
a `220`-wide box (the body.small floor); both wordmark and contact use a hug
height (`s(200,hug)`, `s(220,hug)`).
The logo mark is a fixed `s(40,40)` chip (`fill($surface.brand)`
`rd($radius.badge)`) with a 2-letter monogram: the chip's own `al(x(c),y(c))`
centers the label box, and the monogram is `s(fill,hug) align(center)` so the
glyph sits dead-center.
The outer row is fixed `s(499,hug)` (A4 `pad(48)` content width) so the
left/right ends resolve; the brand lockup is a fixed `s(260,hug)` so the
`x(sb)` split is stable.

```text
page header_page preset(a4,portrait)
  artboard al(v, x(s), g($space.section), pad(48)) p(0,0) s(fill,fill) fill($surface.page) clip(true)
    header al(h, x(sb), y(c), g($space.md), pad(0)) p(0,0) s(499,hug)
      brand al(h, x(s), y(c), g(12), pad(0)) p(0,0) s(260,hug)
        mark al(h, x(c), y(c), pad(0)) p(0,0) s(40,40) fill($surface.brand) rd($radius.badge)
          markt text "IH" p(0,0) s(fill,hug) align(center) style($type.eyebrow) max_lines(1)
        wordmark text "Insight Health" p(0,0) s(200,hug) style($type.label) wrap_text(true) max_lines(1) slot(account.name)
      contact text "hello@insighthealth.com" p(0,0) s(220,hug) style($type.body.small) wrap_text(true) max_lines(1) slot(account.contact)
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
the body.small 1-line floor, so give it `max_lines(2)` with a `300`-wide hug-height
box; legal ≤15 words `max_lines(2)` at `$type.legal`. All three of these are
left-aligned text in `x(s)` columns, so their heights hug and they carry no
`align`. The CTA is a compact fixed `s(150,56)` button whose label is
`s(fill,hug) align(center)` — the button's `al(h, x(c), y(c), …)` centers the
hug-height box and `align(center)` centers the glyph. The top row is fixed
`s(467,hug)` (the card's inner width:
`499 − 2×16` card padding); contact column `300`, CTA `150` plus the `$space.md`
gap split by `x(sb)`. The rule is `r s(fill,2) fill($border.subtle)` — numeric
height, never `$stroke.width.divider` in `s(...)`.

```text
page footer_page preset(a4,portrait)
  artboard al(v, x(s), g($space.section), pad(48)) p(0,0) s(fill,fill) fill($surface.page) clip(true)
    footer al(v, x(s), g($space.stack.default), pad($space.card.padding)) p(0,0) s(499,hug) fill($surface.muted) rd($radius.card)
      top al(h, x(sb), y(c), g($space.md), pad(0)) p(0,0) s(467,hug)
        contact al(v, x(s), g(4), pad(0)) p(0,0) s(300,hug)
          cname text "Insight Health" p(0,0) s(300,hug) style($type.label) wrap_text(true) max_lines(1) slot(account.name)
          cinfo text "hello@insighthealth.com  ·  (555) 012-3456" p(0,0) s(300,hug) style($type.body.small) wrap_text(true) max_lines(2) slot(account.contact)
        cta al(h, x(c), y(c), pad(14,28)) p(0,0) s(150,56) fill($surface.inverse) rd($radius.button)
          ctat text "Get Started" p(0,0) s(fill,hug) align(center) style($type.cta) max_lines(1) slot(campaign.cta)
      rule r p(0,0) s(fill,2) fill($border.subtle)
      legal text "© 2026 Insight Health, Inc. All rights reserved." p(0,0) s(467,hug) style($type.legal) wrap_text(true) max_lines(2) slot(footer.legal)
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
hard-coded structural word (e.g. "OR") so it carries NO `slot(...)` — give it a
fixed-width hug-height box with `align(center)` (`s(60,hug) align(center)`)
centered in an `al(h, x(c), y(c), …)` between two `r s(fill,2)` rules: the wrapper
centers the box and `align(center)` centers the glyph so the word sits in the gap.

```text
page divider_page preset(a4,portrait)
  artboard al(v, x(s), g($space.section), pad(48)) p(0,0) s(fill,fill) fill($surface.page) clip(true)
    above text "Trusted by specialty clinics nationwide." p(0,0) s(499,hug) style($type.body) lh(1.4) wrap_text(true) max_lines(2)
    rule r p(0,0) s(fill,2) fill($border.subtle)
    labeled al(h, x(c), y(c), g($space.md), pad(0)) p(0,0) s(499,hug)
      l_left r p(0,0) s(fill,2) fill($border.subtle)
      l_text text "OR" p(0,0) s(60,hug) align(center) style($type.eyebrow) max_lines(1)
      l_right r p(0,0) s(fill,2) fill($border.subtle)
    below text "Talk to our team about a pilot." p(0,0) s(499,hug) style($type.body) lh(1.4) wrap_text(true) max_lines(2)
```

Validator proof:
```json
{ "ok": true, "stage": "preflight", "errors": [], "warnings": ["LUMB0613", "LUMB0614"] }
```

---

## Divider — zone rule inside a card (weight and inset)

**When to use:** one surface is carrying two different KINDS of content and the gap
alone is not reading as a break — a message above, proof or contact detail below.
The rule is the same `rect` primitive as the page divider above; what changes is
that it lives INSIDE a card and separates zones rather than page regions.

**When NOT to use:** do not reach for a rule first. More space between the two zones
is the quieter fix and is usually the right one — a rule is what you add after the
space has failed. Do not use more than one rule per surface. Do not make it thick or
dark; a rule you notice is a rule that is competing with the message.

**Weight:** `1` is the hairline and `2` is the visible rule; both are literal numbers
inside `s(fill,W)`. `$stroke.width.divider` is a `stroke(...)` token and is rejected
inside `s(...)` (`LUMB0301`) — that is the same trap the page divider above warns
about. Colour it `$border.subtle`, never `$border.strong`: a zone break is a whisper.

**Inset:** the rule is `s(fill,1)` and it is a direct child of the card, so it spans
the card's CONTENT width and stops at the card's own `pad(56)` on both sides. That
inset is what makes it read as a zone rule instead of a band across the artboard —
do NOT hang it off the artboard or size it to the full 888. The zones on either side
are `s(776,hug)` groups (`888 − 2×56`), so the rule and the copy share one left edge.

```text
page zone_divider size(1080,1080,px)
  artboard al(v, x(c), y(c), g($space.section), pad(96)) p(0,0) s(fill,fill) fill($surface.page) clip(true)
    card al(v, x(s), y(c), g($space.stack.default), pad(56)) p(0,0) s(888,hug) fill($surface.card) rd($radius.card)
      message al(v, x(s), g($space.stack.tight), pad(0)) p(0,0) s(776,hug)
        headline text "Forecast in the same place you sell." p(0,0) s(776,hug) style($type.headline) lh(1.06) wrap_text(true) max_lines(2) slot(campaign.headline)
        support text "Pipeline, coverage, and commit in one view." p(0,0) s(776,hug) style($type.body.small) lh(1.4) wrap_text(true) max_lines(2) slot(offer.primary_message)
      zone_rule r p(0,0) s(fill,1) fill($border.subtle)
      proof al(h, x(sb), y(c), g($space.md), pad(0)) p(0,0) s(776,hug)
        proof_text text "Used by 4,000 finance teams" p(0,0) s(500,hug) style($type.caption) wrap_text(true) max_lines(1) slot(proof.line)
        url text "example.com" p(0,0) s(240,hug) align(right) style($type.caption) wrap_text(true) max_lines(1) slot(account.url)
  #slot:campaign.headline sample("Forecast in the same place you sell.") worst_case("Forecast in the same place you sell.")
  #slot:offer.primary_message sample("Pipeline, coverage, and commit in one view.") worst_case("Pipeline, coverage, and commit in one view.")
  #slot:proof.line sample("Used by 4,000 finance teams") worst_case("Used by 4,000 finance teams")
  #slot:account.url sample("example.com") worst_case("example.com")
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
`lh(1.4)`. All slotted text is sized to the `499` inner WIDTH with a hug HEIGHT —
eyebrow `499×hug`, title `499×hug`, body `499×hug` — so heights hug and reserve no
dead space. These are left-aligned in the `x(s)` band column, so they carry no
`align`. Keep the header tight: at `499`/`ml(2)` the headline fits ~6 short words;
a denser 6-word string (long words back to back) can tip to a 3rd line and fail
`LUMV0810` — stay at or below 6 short words, or raise to `max_lines(2)` (the hug
height grows to fit).

```text
page band_page preset(a4,portrait)
  artboard al(v, x(s), g($space.section), pad(0)) p(0,0) s(fill,fill) fill($surface.page) clip(true)
    band al(v, x(s), g($space.stack.default), pad(48)) p(0,0) s(fill,hug) fill($surface.brand.subtle)
      eyebrow text "PILOT PROGRAM" p(0,0) s(499,hug) style($type.eyebrow) wrap_text(true) max_lines(1) slot(section.eyebrow)
      title text "Try it on your busiest week." p(0,0) s(499,hug) style($type.headline) lh(1.12) wrap_text(true) max_lines(2) slot(section.title)
      body text "Run a two-week pilot and measure booked visits." p(0,0) s(499,hug) style($type.body) lh(1.4) wrap_text(true) max_lines(3) slot(section.body)
  #slot:section.eyebrow sample("PILOT PROGRAM") worst_case("PILOT PROGRAM")
  #slot:section.title sample("Try it on your busiest week.") worst_case("Try it on your busiest week.")
  #slot:section.body sample("Run a two-week pilot and measure booked visits.") worst_case("Run a two-week pilot and measure booked visits.")
```

Validator proof:
```json
{ "ok": true, "stage": "preflight", "errors": [], "warnings": ["LUMB0613", "LUMB0614"] }
```
