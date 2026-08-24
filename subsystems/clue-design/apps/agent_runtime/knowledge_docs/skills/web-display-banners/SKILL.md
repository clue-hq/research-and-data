---
name: web-display-banners
description: Author the standard IAB display family in one place — leaderboard 728×90, billboard 970×250, mpu 300×250, half-page 300×600, skyscraper 160×600, mobile 320×50 — with per-size type floors, edge clearance, and one legible message. Use whenever the brief asks for a display banner, web banner, display ad, banner ad, leaderboard, or a skyscraper.
required_decisions: banner_size, offer_cta, brand_adherence
selection_policy: llm_selectable
---

# Web display banners

A display banner is small, it is surrounded by someone else's page, and it gets
a fraction of a glance. It can carry exactly three things: who it is from, one
offer, and one action. Everything in this skill exists to keep those three
legible at the unit's real pixel size. A fourth thing does not make the banner
richer. It makes all four unreadable.

## Composes with

This skill decides; the craft skills execute. Read beside it:

- `skills/brand-and-tokens` — role tokens, never guessed values.
- `skills/brand-imagery` — the kit-asset / generate / deliberately-none call.
  On a banner the answer is usually **deliberately none**: below 300 × 250 there
  is no room for a photo that reads, and a shrunken one reads as noise.
- `skills/clarify-design-brief` — derive before you ask.

Pin these knowledge files into the frame payload instead of hunting for them
mid-run: `knowledge/design/foundations` (squint test, 60-30-10, contrast
floors), `knowledge/design/blocks/actions` (the validated button structure),
`knowledge/design/layout-recipes` (the archetype canon),
`knowledge/design/font-library` (the display voices), and
`knowledge/lumen-dsl/grammar` + `text`.

## The surface command

Every banner is an arbitrary pixel size, so it is a plain
`page <id> size(w,h,px)` line. Example: `page banner_mpu size(300,250,px)`.

- **No preset applies.** `preset(...)` accepts only `a4`, `us_letter`,
  `linkedin_ad`, `envelope_dl`, and `custom` — none of them is a display unit.
  Reach for `size(w,h,px)` and nothing else.
- The page id is a label you choose, not a fixed surface kind. Name it for the
  unit (`banner_mpu`, `banner_leaderboard`) so the document reads clearly.
- A `px` page's canonical bounds are numerically 1:1 with its px size, so a
  300 × 250 px page is a 300 × 250 pt artboard and the same numbers go into
  `size(...)` and into child geometry.
- Give the root artboard `s(fill,fill) clip(true)` with the background on its
  `fill(...)`. Never hardcode the root size.

## Defaults & required decisions

**When the brief does not name a size, build the MPU 300 × 250.** It is the
most widely placed unit and the one that carries a real message.

The family, with the edge clearance and root padding for each:

| Unit | Size | Root pad | Content box |
|---|---|---|---|
| Leaderboard | 728 × 90 | `pad(10)` | 708 × 70 |
| Billboard | 970 × 250 | `pad(10)` | 950 × 230 |
| MPU (medium rectangle) | 300 × 250 | `pad(10)` | 280 × 230 |
| Half-page | 300 × 600 | `pad(10)` | 280 × 580 |
| Wide skyscraper | 160 × 600 | `pad(8)` | 144 × 584 |
| Mobile leaderboard | 320 × 50 | `pad(5)` | 310 × 40 |

These are the published IAB standard sizes. The clearance is 8–10pt on every
unit except 320 × 50, which gets 4–6pt because it has no height to spare.

**Why the clearance exists:** ad networks draw a thin border around a display
unit on the publisher's page. Content pushed flush to the edge collides with
that border and reads as clipped, even though nothing overflowed.

Brand adherence: **strict** = kit tokens/faces/assets only · **balanced** = kit
defaults + limited complementary accents · **loose** = brand-inspired, kit
still recognizable.

Before authoring, check the brief against this table. Each row maps 1:1 onto
`ClarificationQuestion`. If a material decision is missing, ask once — a single
batched `request_clarification` round. Otherwise proceed on the defaults and
call `record_gap(area="agent_protocol", …)` for each assumption you apply.
Derive answers before you ask: read the prompt, prior turns, the document, and
the brand card first (`skills/clarify-design-brief`).

| id | question | why_it_matters | options | default |
|---|---|---|---|---|
| `banner_size` | Which display unit is this? | The unit fixes the page size, the type floor, and how much copy fits. | leaderboard 728x90 · billboard 970x250 · mpu 300x250 · half-page 300x600 · skyscraper 160x600 · mobile 320x50 | mpu 300x250 |
| `offer_cta` | What should the reader do next? | The ask is the whole close, and its label is the banner's loudest element. | See the demo · Get the guide · Start free | See the demo |
| `brand_adherence` | How tightly must this hold the kit? | It decides whether a non-kit display face is allowed. | strict · balanced · loose | balanced |

## Concept plan gate (before any DSL)

A banner has no room for a playbook. The gate is smaller and harder. Before any
DSL, write three strings and one sentence:

1. The **brand string** — the wordmark text, or the logo asset id.
2. The **one line** — verbatim, at the word count the chosen unit allows.
3. The **CTA label** — verbatim, ≤3 words, starting with a verb.
4. One sentence saying all three fit the content box at the type floors below.

If the one line needs a second sentence to make sense, it is not a banner
message. Shorten it or ask.

## Layout skeletons (pick one, name it in the direction)

Three shapes cover the whole family. Each compresses an archetype from
`knowledge/design/layout-recipes`. Recompose it. Never pour copy into the shell.

1. **Rectangle stack** — the **vertical-poster** compressed. For MPU, half-page,
   and billboard. Root `al(v,x(s),y(sb),g(12),pad(10)) s(fill,fill)`, three
   children: a hug wordmark row, a hug headline, a fixed CTA button. On the MPU:
   wordmark `s(280,hug)`, headline `s(280,hug)` at 24 `max_lines(3) lh(1.1)`,
   CTA `al(h,x(c),y(c),pad(8,16)) s(150,40)`. On the half-page the same three
   children run at headline 32 and CTA `s(200,48)`.
2. **Strip row** — the **banded** archetype turned on its side. For the two
   leaderboards. Root `al(h,x(sb),y(c),g(12),pad(10)) s(fill,fill)`, three
   children left to right: wordmark, one line, CTA button. On 728 × 90:
   wordmark `s(140,hug)`, message `s(396,hug)` at 20 `max_lines(2)`, CTA
   `s(140,52)`. Those sum to 676 of the 708 available, so 32pt of slack
   distributes between them. On 320 × 50 the same row runs `pad(5) g(5)` with
   wordmark `s(70,hug)`, message `s(150,hug)` at 14, CTA `s(78,30)` — 298 of 310.
3. **Tower stack** — the **vertical-poster** at 144pt wide, for the skyscraper.
   Root `al(v,x(s),y(sb),g(12),pad(8)) s(fill,fill)`: wordmark `s(144,hug)`
   `max_lines(2)`, headline `s(144,hug)` at 20 `max_lines(5) lh(1.15)`, CTA
   `s(144,44)`. At 144pt a line holds about four short words — write for that.

## Type

**Banners invert the usual rule.** On a 1080 canvas you step the headline UP
because the role default is too small. On a banner you step it DOWN:
`$type.headline` defaults to 56, which is taller than half an MPU. Keep the role
for weight and color and override the size every time.

| Unit | Headline | Body | CTA label |
|---|---|---|---|
| Billboard 970 × 250 | `$type.size.4xl` (40) | `$type.size.md` (16) | `$type.size.md` (16) |
| Half-page 300 × 600 | `$type.size.2xl` (32) | `$type.size.sm` (14) | `$type.size.sm` (14) |
| MPU 300 × 250 | `$type.size.xl` (24) | `$type.size.sm` (14) | `$type.size.sm` (14) |
| Leaderboard 728 × 90 | `$type.size.lg` (20) | none | `$type.size.sm` (14) |
| Skyscraper 160 × 600 | `$type.size.lg` (20) | none | `$type.size.sm` (14) |
| Mobile 320 × 50 | `$type.size.md` (16) | none | `$type.size.xs` (12) |

- **`$type.size.xs` (12) is the hard floor on every unit.** Nothing goes below
  it, including legal lines. If a string will not fit at 12, cut the string.
- **The three smallest units are type-only.** Leaderboard, skyscraper, and
  mobile carry a wordmark, one line, and a CTA. No body paragraph, no photo, no
  stat row. Smaller surfaces carry less content, not the same content smaller.
- Give every text node `wrap_text(true)` and a real `max_lines(n)` so overflow
  is diagnosed at compile instead of clipping in the browser.
- Kit faces first. A library display face may carry the headline when adherence
  is not strict — **Anton**, **Bebas Neue** (caps only), **Archivo Black**,
  **Bricolage Grotesque**; exact name, listed weights
  (`knowledge/design/font-library`). One display voice plus one workhorse.
  Banned: defaulting to `font("Inter",…)` as a decision, and any family off the
  library list (Arial/Helvetica/Roboto/Open Sans do not resolve).

## The CTA

- **The CTA is a button shape, always.** Use the validated structure from
  `knowledge/design/blocks/actions` at banner scale: a fixed-size
  `al(h,x(c),y(c),pad(...))` container with `fill($surface.inverse)` and
  `rd($radius.button)`, holding one label node sized `s(fill,hug) align(center)`
  at `style($type.cta)`. Never give the label a hug WIDTH — that trips
  `LUMV0902`.
- **The CTA is the highest-contrast element on the frame.** Not the headline,
  not the logo. If the eye lands anywhere else first, raise the button's
  contrast or lower everything around it.
- **The label is an action.** "See the demo", "Get the guide", "Start free",
  "Book a call". Never "Learn more", never "Click here", never "Read on" — they
  name no outcome, so they buy no clicks.

## Self-audit checklist

Score each test **0–2** into `critique.json` (the `VisualCritique` shape), and
only **after looking at the render** — never from geometry alone. Write it up
like this:

- One `acceptance_notes` line per test: `"<test-name>: <score> — <why>"`.
- Every score below 2 also becomes an `issues[]` entry. Name the test in
  `message`, give a `target` and a `suggested_repair`, and use the category
  shown in parentheses below.
- Any `0` on tests 1–6 means `accepted=false`.

Score with facts and measurements against the named test, never with adjectives.
Write "message is 5 words at 20pt" or "CTA measures 3.1:1 against its surface",
not "looks clean" or "feels balanced". A weak design passes an adjective and
fails a measurement, which is exactly why the measurement is the score.

1. `single-message` — brand, one offer, one action, and nothing else on the frame. (`hierarchy`)
2. `edge-clearance` — 8–10pt clear on all four sides (4–6pt on 320 × 50); nothing clipped. (`clipping`)
3. `type-floor-held` — every string at or above the floor for this unit, and nothing below 12pt. (`typography`)
4. `cta-is-the-contrast-peak` — the CTA is the loudest element and measures ≥ 4.5:1 against its surface. (`contrast`)
5. `cta-copy-is-an-action` — a verb and an outcome, never "Learn more". (`request_satisfaction`)
6. `wordmark-legible` — the brand reads at the unit's real pixel size, not just zoomed in. (`asset_use`)
7. `brand-adherence-followed` — the chosen level actually holds (tokens, faces, assets). (`brand_fit`)

## Override

Explicit user instructions beat every rule above. Record each override with
`record_gap`.
