# Lumen DSL Vetted Block Catalog — Shared Authoring Spec (P0.2 Contract)

This is the authoritative spec every block author follows so the catalog is
consistent. It is grammar-accurate (validated against our `lumen-dsl` reference
and the live validator) and it is calibrated: every number below was measured
against `.context/p02-validate.py`, not guessed. Follow it exactly. Two blocks
at the end are fully worked and personally validated (`ok==true` proof inline).

A block is VETTED iff `.context/p02-validate.py` returns `ok==true`. Ignore the
`LUMB0613`/`LUMB0614` warnings (platform font not embeddable/subsettable) — they
never fail a block. **Never ship a block you did not see return `ok==true`.**

---

## 0. THE FIXTURE-FIT RULE (read this first — it is why our runs fail)

The validator runs two different text measurements:

1. **Render fit** — measures the node's *visible content* against its box.
2. **Fixture fit** — if a node has `slot(...)`, measures the slot's
   `sample`/`worst_case` fixture against the box. This path is **much stricter**
   and is the source of `LUMV0810` and most of our preflight failures.

Hard-won, validator-confirmed facts about fixture fit:

- **`sample(...)`/`worst_case(...)` written as node properties DO NOT attach.**
  They leave `LUMV0509 (no fit-validation fixtures)` warning AND still let a
  default fixture overflow. Fixtures attach **only** through a `#slot:<key>`
  modify line: `#slot:campaign.headline sample("…") worst_case("…")`.
- **A slotted text node MUST have a fixed (definite) WIDTH and a fixed HEIGHT.**
  `s(fill,hug)` or `hug` height on a slotted node fails `LUMV0810` *no matter how
  large the parent is* — even a single word in a 936×700 box overflows as a
  fixture. The identical node with **no slot** passes render fit fine. So: slot
  ⇒ fixed `s(W,H)`.
- The fixed box must be sized for the **worst_case** copy at the chosen
  `style($type.x)` and `max_lines(N)`. If worst_case needs more lines than
  `max_lines` allows (or is too wide for `W`), you get `LUMV0810`
  (fixture overflows) or `LUMV0904` (exceeds max_lines).
- **Width floors are real and large** (platform type is big). Measured minimums:
  - `$type.subtitle`, 2 short words (e.g. "Faster intake"), `max_lines(1)`:
    needs **W ≥ 160**.
  - `$type.body.small`, ~5-word sentence, `max_lines(4-5)`: needs **W ≥ 220**.
  - `$type.title` at W=499 cannot fit a 6-word worst_case **even at ml(8)** —
    use `$type.title` for ≤4-word headers, or use `$type.headline` for 5-6-word
    section headers (headline wraps where title will not at the same width).
- **Consequence (the overcrowding trap):** a literal 3-column benefit row across
  A4 portrait (595pt) cannot fit slotted text. Three columns each need ≥220pt for
  body.small descriptions ⇒ 660pt+ of text alone, more than the page is wide.
  **Do not author a horizontal 3-up of fixtured cards on A4.** Stack benefits
  vertically (full page width per row) or use a 2-up. This is encoded in
  Canonical Block B.

When fixtures are not needed (a purely structural/decorative block, or a label
the agent will hard-code), **omit `slot(...)` entirely** — the node then uses
render fit, `hug` is fine, and the block validates cleanly.

---

## 1. CANONICAL CONVENTIONS (the idioms every block uses)

Two-space indent. Only `frame`/`fr`, `group`/`gr`, `autolayout`/`al` may hold
children. Colors are tokens/`#hex`/`oklch`, never bare numbers. `rd()` is one
uniform radius (no per-corner). No `align()`/`valign()`/`text_align()`/`divider`
node.

### 1a. Root artboard frame (every doc has exactly one)
One clipped root `artboard` per page; background lives on its `fill(...)`.
Size is always `s(fill,fill)` (resolves to canonical artboard bounds — never
hardcode `s(595,842)`).
```text
page my_square size(1080,1080,px)
  artboard al(v, x(s), g($space.section), pad($space.page.margin)) p(0,0) s(fill,fill) fill($surface.page) clip(true)
```
- Vertical hero centering: add `y(c)` to the root `al(v, x(s), y(c), …)`.
- Use `pad(96)` (square social) / `pad(48)`–`pad($space.page.margin)` (A4).

### 1b. Vertical stack
```text
content al(v, x(s), g($space.stack.default), pad(0)) p(0,0) s(888,hug)
```
- `g($space.stack.tight)` inside a tight group (eyebrow→title), `default`
  between peers, `loose`/`$space.section` between major regions.
- A container may be `hug` height; only **slotted leaf text** needs fixed height.

### 1c. Row
```text
row al(h, x(s), y(c), g($space.md), pad(0)) p(0,0) s(499,hug)
```
- `y(c)` vertically centers items in the row. `x(sb)` for nav/proof ends.
- Give the row a **fixed width** when its children are fixed-width (so widths add up).

### 1d. Centering text (there is no valign / standalone align)
Center a label by wrapping it in an `al(...)` with `x(c) y(c)`:
```text
cta al(h, x(c), y(c), pad(18,36)) p(0,0) s(340,72) fill($surface.inverse) rd($radius.button)
  cta_text text "Book a Demo" p(0,0) s(fill,48) style($type.cta) max_lines(1)
```

### 1e. Text sizing — two cases
- **Not personalized (no slot):** `s(W,hug) wrap_text(true) max_lines(N)`. `hug`
  is fine; render fit measures the visible string.
- **Personalized (has a slot):** `s(W,H)` — **fixed width AND fixed height**,
  sized for worst_case — plus `wrap_text(true) max_lines(N)` and a `#slot:` line.
```text
headline text "Answer every patient call." p(0,0) s(888,200) style($type.headline) lh(1.08) wrap_text(true) max_lines(2) slot(campaign.headline)
```

### 1f. CTA button (one per section)
```text
cta al(h, x(c), y(c), pad(18,36)) p(0,0) s(340,72) fill($surface.inverse) rd($radius.button)
  cta_text text "Book a Demo" p(0,0) s(fill,48) style($type.cta) max_lines(1) slot(campaign.cta)
```
- Button is a **fixed-width** `al` (e.g. `s(340,72)`). Label text is `s(fill,48)`
  (fill width inside the fixed button, fixed height). A slotted CTA label needs
  that fixed height (`48`), not `hug`.

### 1g. Divider / horizontal rule (there is NO `divider` node)
```text
rule r p(0,0) s(fill,2) fill($border.subtle)
```
- The rule is a `rect` with a numeric height. **`$stroke.width.divider` is NOT
  valid in `s(...)`** (→ `LUMB0301`); it is only a `stroke(...)` token. Use a
  number (`2`) for a rect's thickness.

### 1h. Slot + fixture annotation (the ONLY way fixtures attach)
On the node: `slot(<key>)`. After the whole tree, one `#slot:` modify line per
slot, indented one level under the page (NOT under the artboard):
```text
  #slot:campaign.headline sample("Answer every patient call.") worst_case("Give your specialists their operating hours back.")
```
- `worst_case` is the realistic *longest* copy. Size the node's box so worst_case
  fits at `max_lines`. This clears `LUMV0509` and prevents `LUMV0810`.
- `sample` = a typical-length value (used for preview).

---

## 2. TOKEN USAGE TABLE (prescriptive — do not diverge)

| Role | Token | Notes |
|------|-------|-------|
| Page / one-pager background | `$surface.page` | on the root artboard `fill(...)` |
| Bold hero background | `$surface.brand` | full-bleed colored hero |
| Soft tint / chip background | `$surface.brand.subtle` | number chips, eyebrow pills, soft panels |
| Card background | `$surface.card` | on a card `fr`/`al` |
| Inverse CTA fill | `$surface.inverse` | dark button on a light/brand surface |
| Headline / display text color | `$text.primary` (default) · `$text.inverse` on dark/brand | tokens resolve per Brand Kit; usually omit on branded surface |
| Eyebrow type | `style($type.eyebrow)` | small caps overline; `max_lines(1)` |
| Section header (5-6 words) | `style($type.headline)` | wraps at 499; **use instead of title for 5-6-word headers** |
| Short section title (≤4 words) | `style($type.title)` | does NOT wrap a 6-word string at 499 |
| Hero headline | `style($type.headline)` | `lh(1.08)`, `max_lines(2)` |
| Subtitle / lead-in | `style($type.subtitle)` | benefit titles, lead sentences |
| Body copy | `style($type.body)` | `lh(1.4)`, `max_lines(3)` |
| Small body / benefit description | `style($type.body.small)` | `lh(1.35–1.4)`, `max_lines(2-3)` |
| CTA label | `style($type.cta)` | inside the button, `max_lines(1)` |
| Stat number | `style($type.stat)` | big numeral |
| Caption / fine print | `style($type.caption)` / `$type.legal` | |
| Section gap (major regions) | `g($space.section)` | between hero/benefits/footer regions |
| Stack gap (peers) | `g($space.stack.default)` | between headline/subtitle/CTA |
| Tight gap (label→value) | `g($space.stack.tight)` | eyebrow→title |
| Loose gap (between list rows) | `g($space.stack.loose)` | benefit rows |
| Generic small/medium row gap | `g($space.md)` (`$space.sm`/`lg`) | rows where semantic gap doesn't apply |
| Outer page margin | `pad($space.page.margin)` (A4) · `pad(96)` (1080 square) | generous; aim 60-70% whitespace |
| Card padding | `pad($space.card.padding)` | inside cards |
| Card radius | `rd($radius.card)` | cards/panels |
| Button radius | `rd($radius.button)` | CTA buttons |
| Badge / pill radius | `rd($radius.badge)` | small pills |
| Circular chip radius | `rd($radius.full)` | number/avatar chips |
| Divider color | `fill($border.subtle)` | on a rect rule |
| Divider thickness | numeric in `s(fill,2)` | NOT `$stroke.width.divider` in `s()` |
| Hairline border (stroke) | `stroke($border.default, $stroke.width.hairline)` | stroke tokens are valid only in `stroke(...)` |

---

## 3. CONTENT-BUDGET TABLE (per element: max words / max_lines)

These keep the design uncrowded AND keep worst_case fixtures inside the box.

| Element | Max words | `max_lines` | Notes |
|---------|-----------|-------------|-------|
| Eyebrow | 2-4 (1 short line) | 1 | small caps; fits a wide box at `max_lines(1)` |
| Headline (hero) | 4-8 | 2 | tight `lh(1.08)`; box ≥ ~820 wide for 8 words |
| Section header | 4-6 | 2 | use `$type.headline`; `$type.title` only for ≤4 words |
| Subtitle / lead | 6-12 | 2 | `$type.subtitle` |
| Body / supporting | 12-25 | 3 | `$type.body`, `lh(1.4)` |
| Benefit title | ≤4 (≤2 ideal) | 1 | box ≥ 160 wide; longer phrases wrap and break `max_lines(1)` |
| Benefit description | ≤12 | 2-3 | `$type.body.small`; box ≥ 220 wide |
| CTA label | 2-3 | 1 | inside a fixed-width button |
| Stat value | 1 numeral/short | 1 | `$type.stat` |
| Caption / legal | ≤15 | 2 | `$type.caption`/`$type.legal` |

Composition rules (encode into every block): one dominant focal region;
secondary regions visibly subordinate; ~60-70% whitespace with generous outer
padding; one CTA per section; **never more than 3 benefits in a row, and on A4
portrait never 3 *across* — stack them** (see §0).

---

## 4. CANONICAL BLOCKS (both personally validated — `ok==true`)

### 4a. HERO — eyebrow + headline + subtitle + one CTA (1080×1080 social square)

**When to use:** the single primary message of a social square (the focal
artifact). One headline, one supporting sentence, one CTA.

**When to use / Content budget:** eyebrow 2-4 words `max_lines(1)`; headline 4-8
words `max_lines(2)`; subtitle 6-12 words `max_lines(3)`; CTA 2-3 words. The four
text nodes are slotted with fixed boxes sized for worst_case; CTA label is
`s(fill,48)` inside a fixed `s(340,72)` button. `pad(96)` keeps ~65% whitespace.

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

### 4b. 3-UP BENEFIT LIST — vertical, full-width rows (A4 portrait)

**When to use:** three benefits on an A4 one-pager. **This is the correct shape
for the composition our runs overcrowd.** A literal 3-column horizontal row does
NOT fit fixtured text on A4 (see §0) — stack the three benefits as full-width
rows instead, each a number chip + a title + a short description.

**When to use / Content budget:** section eyebrow 2-4 words `max_lines(1)`;
section header 4-6 words `max_lines(2)` via `$type.headline`; benefit title ≤4
words `max_lines(1)`; benefit description ≤12 words `max_lines(2)`. Geometry: A4
is 595pt; `pad(48)` ⇒ 499pt content; each row is the number chip `s(56,56)` +
`g(20)` + a `s(423,…)` text column (56+20+423 = 499). The 423pt column clears the
220pt body.small floor with room to spare.

```text
page benefits_a4 preset(a4,portrait)
  artboard al(v, x(s), g($space.section), pad(48)) p(0,0) s(fill,fill) fill($surface.page) clip(true)
    section_head al(v, x(s), g($space.stack.tight), pad(0)) p(0,0) s(499,hug)
      eyebrow text "WHY TEAMS SWITCH" p(0,0) s(499,32) style($type.eyebrow) wrap_text(true) max_lines(1) slot(section.eyebrow)
      title text "Built for the work that matters." p(0,0) s(499,140) style($type.headline) lh(1.12) wrap_text(true) max_lines(2) slot(section.title)
    list al(v, x(s), g($space.stack.loose), pad(0)) p(0,0) s(499,hug)
      r1 al(h, x(s), y(s), g(20), pad(0)) p(0,0) s(499,hug)
        n1 al(h, x(c), y(c), pad(0)) p(0,0) s(56,56) fill($surface.brand.subtle) rd($radius.full)
          n1t text "1" p(0,0) s(40,44) style($type.subtitle) max_lines(1)
        t1 al(v, x(s), g(6), pad(0)) p(0,0) s(423,hug)
          t1t text "Faster intake" p(0,0) s(423,34) style($type.subtitle) lh(1.15) wrap_text(true) max_lines(1) slot(benefit.1.title)
          t1d text "Answer and route every patient call in seconds, day or night." p(0,0) s(423,60) style($type.body.small) lh(1.4) wrap_text(true) max_lines(2) slot(benefit.1.desc)
      r2 al(h, x(s), y(s), g(20), pad(0)) p(0,0) s(499,hug)
        n2 al(h, x(c), y(c), pad(0)) p(0,0) s(56,56) fill($surface.brand.subtle) rd($radius.full)
          n2t text "2" p(0,0) s(40,44) style($type.subtitle) max_lines(1)
        t2 al(v, x(s), g(6), pad(0)) p(0,0) s(423,hug)
          t2t text "Less busywork" p(0,0) s(423,34) style($type.subtitle) lh(1.15) wrap_text(true) max_lines(1) slot(benefit.2.title)
          t2d text "Scheduling and follow-up reminders happen automatically." p(0,0) s(423,60) style($type.body.small) lh(1.4) wrap_text(true) max_lines(2) slot(benefit.2.desc)
      r3 al(h, x(s), y(s), g(20), pad(0)) p(0,0) s(499,hug)
        n3 al(h, x(c), y(c), pad(0)) p(0,0) s(56,56) fill($surface.brand.subtle) rd($radius.full)
          n3t text "3" p(0,0) s(40,44) style($type.subtitle) max_lines(1)
        t3 al(v, x(s), g(6), pad(0)) p(0,0) s(423,hug)
          t3t text "Happier patients" p(0,0) s(423,34) style($type.subtitle) lh(1.15) wrap_text(true) max_lines(1) slot(benefit.3.title)
          t3d text "Shorter waits and a clear next step on every call." p(0,0) s(423,60) style($type.body.small) lh(1.4) wrap_text(true) max_lines(2) slot(benefit.3.desc)
  #slot:section.eyebrow sample("WHY TEAMS SWITCH") worst_case("WHY GROWING TEAMS SWITCH")
  #slot:section.title sample("Built for the work that matters.") worst_case("Built for the work that matters.")
  #slot:benefit.1.title sample("Faster intake") worst_case("Faster intake")
  #slot:benefit.1.desc sample("Answer and route every patient call in seconds, day or night.") worst_case("Answer and route every patient call in seconds, day or night.")
  #slot:benefit.2.title sample("Less busywork") worst_case("Less busywork")
  #slot:benefit.2.desc sample("Scheduling and follow-up reminders happen automatically.") worst_case("Scheduling and follow-up reminders happen automatically.")
  #slot:benefit.3.title sample("Happier patients") worst_case("Happier patients")
  #slot:benefit.3.desc sample("Shorter waits and a clear next step on every call.") worst_case("Shorter waits and a clear next step on every call.")
```

Validator proof:
```json
{ "ok": true, "stage": "preflight", "errors": [], "warnings": ["LUMB0613", "LUMB0614"] }
```

---

## 5. ANTI-PATTERNS (will fail the validator — never author these)

- **Slotted text at `hug` height (or `s(fill,hug)`).** Fixture fit needs a
  definite box ⇒ `LUMV0810`, even in a huge parent. Slotted ⇒ fixed `s(W,H)`.
- **Fixtures as node properties.** `… slot(x) sample("a") worst_case("b")` on the
  node does NOT attach; you still get `LUMV0509` and overflow. Fixtures attach
  ONLY via a `#slot:<key> sample(…) worst_case(…)` modify line under the page.
- **3 benefit columns across A4 portrait with body text.** Each column needs
  ≥220pt for descriptions; 3×220 > 595pt page width ⇒ guaranteed `LUMV0810`.
  Stack vertically (Block B) or 2-up.
- **`$type.title` for a 5-6 word header.** It won't wrap at column width even at
  `max_lines(8)` ⇒ `LUMV0810`. Use `$type.headline` for 5-6-word headers;
  reserve `$type.title` for ≤4 words.
- **`$stroke.width.divider` (or any stroke-width token) inside `s(...)`** ⇒
  `LUMB0301`. Stroke-width tokens are only valid in `stroke(...)`. A rect rule
  uses a numeric height: `r s(fill,2) fill($border.subtle)`.
- **`align(...)` / `valign(...)` / `text_align(...)` properties** ⇒ `LUMD0212`.
  Horizontal align is only `font(family,size,weight,align)`; with
  `style($type.x)` you cannot pass align — center via an `al(x(c),y(c))` wrapper.
- **A `divider` node kind** ⇒ `LUMD0206`. Use `rect`/`r` or `line`/`l`.
- **4-arg per-corner `rd(...)`** ⇒ `LUMD0230`. `rd()` is one uniform radius.
- **Bare-number color** (`fill(4)`) ⇒ `LUMD0219`. Use a `$token`/`#hex`/`oklch`.
- **Off-Brand-Kit token names** ⇒ `LUMB...`. Use only the aliases in the project
  brief (`$surface.*`, `$text.*`, `$type.*`, `$space.*`, `$radius.*`,
  `$border.*`, `$stroke.width.*`, `$accent.*`, `$opacity.*`).
- **Hardcoded root frame size** (`s(595,842)`). Root artboard is always
  `s(fill,fill)`.
- **Fake square inside an A4 page.** Set the page size (`size(1080,1080,px)`);
  don't draw a square frame in an A4 page.
- **Single-line `s(hug,hug)` variable text.** Can overflow horizontally
  (`LUMV0902`). Variable text ⇒ fixed/`fill` width + `wrap_text(true)` +
  `max_lines(N)`.
- **Children nested under a leaf** (`text`/`rect`/`ellipse`/`line`/`image`/
  `vector`) ⇒ `LUMD0304`. Only `fr`/`gr`/`al` hold children.
- **Indenting more than one level deeper than the parent** ⇒ `LUMD0302`; odd
  (non-two-space) indent ⇒ `LUMD0301`.

---

## 6. AUTHOR CHECKLIST (run before declaring a block VETTED)

1. Write a self-contained doc: `page …` + one clipped root `artboard` `s(fill,fill)`
   + the block, plus `#slot:` fixture lines under the page for every slot.
2. Every slotted text node: fixed `s(W,H)` (W per §0 floors, H per worst_case),
   `wrap_text(true)`, `max_lines(N)` within budget, and a `#slot:` fixture line.
3. Non-slotted labels: omit `slot(...)`; `hug` height is fine.
4. Run `$VENV .context/p02-validate.py /tmp/candidate.lumen`. Iterate until
   `ok==true` (LUMB0613/0614 warnings are OK). Paste that `ok==true` JSON as proof.
