---
name: linkedin-banner
description: Author a LinkedIn cover image — 1584x396 for a personal profile banner, 1128x191 for a company page cover — as ambient brand canvas, with the profile-photo overlap allowance, a calm one-band composition, and the self-audit checklist. Use whenever the brief asks for a linkedin banner, linkedin cover, profile banner, company page cover, or a linkedin header.
required_decisions: banner_surface, positioning_line, brand_adherence
selection_policy: llm_selectable
---

# LinkedIn banner

This is not an ad. It is the wall behind someone's name. The platform draws the
profile photo, the name, the headline, and its own buttons on top of it, and the
viewer came to read those, not this. A banner earns its place by being a calm,
recognisable brand field that makes the person or company in front of it look
credible. The more it competes, the worse the whole profile reads.

## Composes with

This skill decides; the craft skills execute. Read beside it:

- `skills/brand-and-tokens` — role tokens, never guessed values.
- `skills/color-and-contrast` — which combination of those tokens actually
  reads. The on-color pairing law, and the shade decision.
- `skills/brand-imagery` — the kit-asset / generate / deliberately-none call.
  A quiet brand field beats a busy photo here almost every time.
- `skills/clarify-design-brief` — derive before you ask.

Pin these knowledge files into the frame payload instead of hunting for them
mid-run: `knowledge/design/layout-recipes` (the archetype canon),
`knowledge/design/foundations` (squint test, 60-30-10, contrast floors),
`knowledge/design-systems/logo-and-assets` (mark variants, minimum size,
clearspace), `knowledge/design/font-library`, and `knowledge/lumen-dsl/grammar`
+ `text`.

## Defaults & required decisions

Two surfaces, both plain pixel pages. These are the platform's published sizes.

| Surface | Page line | Layout bounds |
|---|---|---|
| Personal profile banner | `page linkedin_banner size(1584,396,px)` | 1584 x 396 pt |
| Company page cover | `page linkedin_cover size(1128,191,px)` | 1128 x 191 pt |

**When the brief does not say which, build the personal profile banner.**

**The profile photo overlaps the LEFT of a personal banner.** The round avatar
sits over the banner's lower-left and hangs below its bottom edge, and the name
block renders under it. So on a 1584 x 396 banner:

- Nothing that must be read goes **left of x = 480**.
- Nothing that must be read goes **below y = 300**.
- That leaves a reliable content box of **1040 x 236 pt**, reached with a root
  `pad(64,64,96,480)` (top, right, bottom, left).

**Those two allowances are deliberately generous.** The avatar well, its ring,
and the name block move with viewport width and app version, so a measured
figure would go stale. Over-reserving costs a strip of canvas. Under-reserving
puts the wordmark behind a face.

The company page cover has no avatar overlap, but it is cropped harder on narrow
screens. Keep content in the middle: root `pad(32,112)` gives a **904 x 127 pt**
box with a tenth of the width clear on each side.

Brand adherence: **strict** = kit tokens/faces/assets only · **balanced** = kit
defaults + limited complementary accents · **loose** = brand-inspired, kit
still recognizable. **Strict is the default here**, unlike an ad — a masthead
that is off-brand is simply wrong, and there is no offer to justify a liberty.

Before authoring, check the brief against this table. Each row maps 1:1 onto
`ClarificationQuestion`. If a material decision is missing, ask once — a single
batched `request_clarification` round. Otherwise proceed on the defaults and
call `record_gap(area="agent_protocol", …)` for each assumption you apply.
Derive answers before you ask: read the prompt, prior turns, the document, and
the brand card first (`skills/clarify-design-brief`).

| id | question | why_it_matters | options | default |
|---|---|---|---|---|
| `banner_surface` | Personal profile banner or company page cover? | The two sizes differ, and only the personal one loses its left side to the profile photo. | personal profile 1584x396 · company page 1128x191 | personal profile 1584x396 |
| `positioning_line` | What is the one line under the wordmark? | It is the only sentence the banner gets, so it has to be the standing claim, not a campaign message. | | the kit's tagline, or no line at all |
| `brand_adherence` | How tightly must this hold the kit? | It decides whether a non-kit display face is allowed. | strict · balanced · loose | strict |

## Concept plan gate (before any DSL)

No playbook here — a masthead has no argument to make. Before any DSL, write:

1. The **mark** — the logo asset id, or the wordmark text if there is no asset.
2. The **one line**, verbatim, ≤9 words, or the explicit decision to have none.
3. The **field** — which single surface treatment carries the background (solid
   paper, one brand gradient, one soft radial wash, or a quiet photo).
4. One sentence confirming the mark and the line sit inside the reliable box.

If the brief supplies a campaign message rather than a standing claim, say so
and use the standing claim instead. A banner outlives every campaign on it.

## Layout skeletons (pick one, name it in the direction)

An extreme strip cannot hold a stacked composition. 1584 x 396 is 4:1 and
1128 x 191 is nearly 6:1, so every skeleton below is **one horizontal band with
one alignment spine**.

1. **Right-field lockup** — the **vertical-poster** flattened into the reliable
   box. Root `al(v,x(s),y(c),g($space.stack.tight),pad(64,64,96,480))
   s(fill,fill) clip(true)`, two children: the wordmark `s(1040,hug)` and the
   positioning line `s(1040,hug) max_lines(1)`. The default choice.
2. **Split field** — the **split-panel** archetype, and the one skeleton that
   uses the covered zone on purpose. Root `al(h,x(s),y(s),g(0),pad(0))`: a
   `media fr p(0,0) s(480,396) clip(true)` carrying the brand field, then a
   `panel al(v,x(s),y(c),g(12),pad(64,64,96,64)) p(0,0) s(1104,396)` holding the
   wordmark and the line in a 976 x 236 box. The avatar lands on the media
   column, which is exactly why that column holds texture and never words.
3. **Quiet field, mark only** — the **emblem** archetype stripped back. One
   surface treatment across the whole banner and the mark alone, placed in the
   reliable box. Reach for this when the positioning line is not settled, when
   adherence is strict and the kit has no approved tagline, or on the 191pt-tall
   company cover where a second line crowds the strip.

## Type

- Wordmark: `style($type.title) font_size($type.size.5xl)` (48) on the personal
  banner, `font_size($type.size.3xl)` (36) on the company cover. If the kit has
  no title role, use `style($type.headline)` with the same size override.
- Positioning line: `style($type.body) font_size($type.size.xl)` (24) on the
  personal banner, `font_size($type.size.md)` (16) on the company cover.
  `max_lines(1)`, `wrap_text(true)`, ≤9 words.
- **`$type.size.md` (16) is the floor.** A banner renders small on a phone.
- **Never step to `$type.size.7xl` (80) here.** A 396pt-tall strip cannot hold an
  80pt line plus a mark plus air, and the platform crops the top and bottom on
  narrow screens. The big steps belong to the 1080-class canvases.
- Kit faces first, and on a masthead that rule is nearly absolute. A library
  display face is allowed for the wordmark only when the kit ships no wordmark
  asset and adherence is not strict — **Anton**, **Bebas Neue** (caps only),
  **Archivo Black**, **Bricolage Grotesque**, **Syne**; exact name, listed
  weights (`knowledge/design/font-library`). One voice, not two. Banned:
  defaulting to `font("Inter",…)` as a decision, and any family off the library
  list (Arial/Helvetica/Roboto/Open Sans do not resolve).

## No CTA, and why

- **Nothing on a banner is clickable.** A button shape is a lie: the viewer taps
  it, nothing happens, and the brand looks broken. Do not draw a filled pill, an
  outlined pill, or an underlined "link".
- **No offer copy.** No "Book a demo", no discount, no deadline. Those belong on
  an ad. They date the profile the moment the campaign ends.
- A URL in small type is fine as a fact, set at `style($type.caption)`, never
  styled to look pressable.

## Brand & assets

- **On a saturated brand ground, text is `$text.inverse`.** Dark ink belongs on
  `$surface.page`, `$surface.card`, or `$surface.brand.subtle`, never on
  `$surface.brand`. This format wants a calm field, so `$surface.brand.subtle`
  is often the better ground here anyway. See `skills/color-and-contrast`.
- Prefer the real mark over a typeset wordmark. Bind through slots
  (`slot(account.logo)`) with asset roles (`logo.primary` / `logo.reversed`),
  never an invented asset id. Pick the variant that suits the field's lightness.
- **Look at every asset before you place it** — `view("asset:<asset_id>")`.
  Reject crops with baked-in text and check the mark's shape against its box.
- Logo minimum height is **48pt**, or the kit's declared minimum size if larger,
  plus the kit's clearspace. On a 396pt band a mark below 48pt disappears.
- Image slots are born with a default policy; if an inherited document raises
  `LUMV0820`, one line clears it — `#slot:account.logo image_policy(fit=cover,
  focal_x=0.5, focal_y=0.35)` — never delete the slot.
- If a photo carries the field, it must be quiet: low contrast, no faces, no
  text in the image. Text over a photo ALWAYS gets a scrim beneath it
  (`fill($surface.inverse) o($opacity.scrim)`) on a dark artboard.

## Self-audit checklist

Score each test **0–2** into `critique.json` (the `VisualCritique` shape), and
only **after looking at the render** — never from geometry alone. Write it up
like this:

- One `acceptance_notes` line per test: `"<test-name>: <score> — <why>"`.
- Every score below 2 also becomes an `issues[]` entry. Name the test in
  `message`, give a `target` and a `suggested_repair`, and use the category
  shown in parentheses below.
- Any `0` on tests 1–7 means `accepted=false`.

Score with facts and measurements against the named test, never with adjectives.
Write "wordmark starts at x=520" or "the line measures 3.1:1 against the field",
not "looks clean" or "feels balanced". A weak design passes an adjective and
fails a measurement, which is exactly why the measurement is the score.

1. `photo-overlap-clear` — on a personal banner nothing that must be read sits left of x=480 or below y=300. (`clipping`)
2. `single-band-composition` — one horizontal band, one alignment spine, no stacked composition on a 4:1 strip. (`visual_balance`)
3. `no-cta-pretence` — no button shape, no pressable-looking element, no offer or deadline copy. (`request_satisfaction`)
4. `wordmark-at-real-scale` — the mark is ≥48pt tall, or the kit's declared minimum if larger, and carries no cropped baked-in text. (`asset_use`)
5. `one-line-budget` — a mark plus at most one line of ≤9 words, and nothing else. (`typography`)
6. `calm-contrast` — the line measures ≥ 4.5:1 against its field, and the field does not fight the platform chrome drawn over it. (`contrast`)
7. `on-color-pairing` — every text/ground and plate/ground pair reads cleanly.
   Dark ink on a saturated brand ground scores 0, and so does spending the
   full-strength brand color as BOTH the ground and the accent. (`contrast`)
8. `brand-adherence-followed` — the chosen level actually holds (tokens, faces, assets). (`brand_fit`)

## Override

Explicit user instructions beat every rule above. Record each override with
`record_gap`.
