---
name: story-ad-9x16
description: Author a 1080×1920 vertical story ad end-to-end — the platform-chrome safe zones, the vertical composition ladder, type floors, and the self-audit checklist. Use whenever the brief asks for a story ad, reel ad, 9:16 creative, vertical social ad, or a full-screen mobile ad.
required_decisions: audience, offer_cta, tone, brand_adherence
selection_policy: llm_selectable
---

# Story ad — 9:16

A story plays full screen and it plays on a timer. The viewer decides in about
one second whether to hold or swipe. So the top third has to arrest, the middle
has to say the one thing, and the ask has to land before the frame ends. The
whole format is one vertical ladder read top to bottom.

## Composes with

This skill decides; the craft skills execute. Read beside it:

- `skills/brand-and-tokens` — role tokens, never guessed values.
- `skills/color-and-contrast` — which combination of those tokens actually
  reads. The on-color pairing law, and the shade decision.
- `skills/brand-imagery` — the kit-asset / generate / deliberately-none call.
- `skills/clarify-design-brief` — derive before you ask.

Pin these knowledge files into the frame payload instead of hunting for them
mid-run: `knowledge/design/layout-recipes` (the six-archetype canon),
`knowledge/design/foundations` (squint test, 60-30-10, contrast floors),
`knowledge/design/blocks/patterns` (validated big-canvas proportions),
`knowledge/design/font-library` (the display voices), `knowledge/images/placement`
(the scrim rule), and `knowledge/lumen-dsl/grammar` + `text`.

## Defaults & required decisions

- Surface: `page story size(1080,1920,px)`, which lays out as 1080 × 1920 pt.
  This exact line is in `knowledge/lumen-dsl/grammar`.
- Safe zones: give the root artboard `pad(250,96,340,96)` (top, right, bottom,
  left) `s(fill,fill) clip(true)`. That leaves an **888 × 1330 pt** content band.
- **Those top and bottom numbers are deliberately conservative platform-chrome
  allowances, not a measured spec.** Every story app paints its own avatar row,
  progress bar, caption, and swipe-up affordance over your frame. The exact
  heights move with each app version. Designing to a generous allowance costs a
  little canvas. Designing to a tight one gets the CTA covered.
- **Art may run full bleed. Words may not.** A photo, wash, or band is welcome
  edge to edge. Anything a viewer must READ or ACT ON stays inside the band.
- Side margin: 96pt is the default, matching every validated 1080-wide skeleton.
  **64pt is the hard side floor.**
- One ad = one audience, one promise, one ask. Kill every secondary message.
- Brand adherence: **strict** = kit tokens/faces/assets only · **balanced** = kit
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
| `audience` | Who is this story for? | One audience reads; three compete and none land. | | the kit's primary audience |
| `offer_cta` | What should they do next? | The ask fixes the CTA label and the whole close. | Request a demo · Read the case study · Start free | Request a demo |
| `tone` | Bold or conservative? | It picks the archetype, the type voice, and the contrast. | bold · conservative | bold |
| `brand_adherence` | How tightly must this hold the kit? | It decides whether a non-kit display face is allowed. | strict · balanced · loose | balanced |

## Concept plan gate (before any DSL)

Write in the direction: the **playbook** (product-as-hero / before-after /
typographic-manifesto / stat-proof / problem-solution / demonstration /
juxtaposition / visual-metaphor), the **headline** (verbatim), the **thumb-stop**
(what lands in the top third and why it stops a swipe), the **single focal
point**, the **type direction**, and the imagery decision.

Then say where each of the three beats sits: stop in the top third of the band,
the one idea in the middle, the ask in the lower third. If two beats want the
same zone, the strategy has two messages — cut one.

## Layout skeletons (pick one, name it in the direction)

Each is an archetype from `knowledge/design/layout-recipes` — recompose it, never
pour copy into the shell.

1. **Vertical ladder** — the **vertical-poster** stretched to the story band.
   Root `al(v,x(s),y(s),g($space.section),pad(250,96,340,96)) s(fill,fill)`. A hug
   `header s(888,hug)` pins to the top of the band, a `main s(888,fill) y(c)`
   absorbs the slack and centers the focal block, a hug `footer s(888,hug)` is
   pushed to the bottom of the band. The default choice when the kit's imagery is
   weak or adherence is strict.
2. **Full-bleed photo** — the **image-hero**. An `fr` root on
   `fill($surface.inverse)`, then in declaration order: `photo image asset(<id>)
   p(0,0) s(1080,1920)`, `scrim r p(0,0) s(1080,1920) fill($surface.inverse)
   o($opacity.scrim)`, then a `content al(v,x(s),y(sb),pad(250,96,340,96)) p(0,0)
   s(1080,1920)` holding a hug brand block and a hug copy block. The photo covers
   the whole 1920 including the chrome zones. The text does not.
3. **Numeral hero** — the **numeral-hero**. One number carries the top two
   thirds, the caption and CTA sit below it. The size ramp tops out at
   `$type.size.9xl` (128), so step it raw: `style($type.display) font_size(300)
   lh(0.92) max_lines(1)`. Only with a number from the brief or kit, and keep it
   to four glyphs or fewer (`3.2s`, `99.99%`, `40M`) so it holds the 888 column.

## Type

- Headline: `style($type.headline) font_size($type.size.7xl)` (80) — or
  `$type.display` when the kit ships a distinct display role. **Floor
  `$type.size.6xl` (64)**; the role default 56 does not dominate 1080.
  ≤7 words, `max_lines(3)`, `lh(1.04)`, `wrap_text(true)`.
- Body: ≤140 chars at `style($type.body)` on an `s(820,hug)` box, and at least
  **22pt**. That is one step above the general 1080-wide skeletons' 19–21pt,
  because a phone downscales the canvas hard. If the kit's body role lands
  smaller, step up with `font_size($type.size.xl)` (24).
- CTA label: ≤4 words, `style($type.cta) align(center)`, inside an
  `s(fill,hug)` text node.
- Kit faces first. A library display face may carry the headline when the kit
  voice is too neutral to stop a swipe and adherence is not strict — **Anton**,
  **Bebas Neue** (caps only), **Archivo Black**, **Bricolage Grotesque**; exact
  name, listed weights (`knowledge/design/font-library`). One display voice plus
  one workhorse. Banned: defaulting the headline to `font("Inter",…)` (Inter is
  the fallback, not a voice) and any family off the library list
  (Arial/Helvetica/Roboto/Open Sans do not resolve).
- Headline and visual are ONE idea. If the headline still works pasted on a
  different image, rework the pair. Never caption the image.

## Brand & assets

- **On a saturated brand ground, text is `$text.inverse`.** Dark ink belongs on
  `$surface.page`, `$surface.card`, or `$surface.brand.subtle`, never on
  `$surface.brand`. A full-bleed brand field fills this whole format, so this is
  the pairing that decides whether the ad reads. See `skills/color-and-contrast`.
- Logo or wordmark at real scale — **≥48pt height**, or the kit's declared
  minimum size if larger. Put it in the header block, inside the band, never in
  the top chrome zone where the avatar row lands. Bind through slots
  (`slot(account.logo)`) with asset roles (`logo.primary` / `logo.reversed`),
  never an invented asset id.
- **Look at every asset before you place it** — `view("asset:<asset_id>")`.
  A 9:16 crop is brutal: check that the subject survives a tall frame and that
  the crop carries no baked-in text.
- Image slots are born with a default policy; if an inherited document raises
  `LUMV0820`, one line clears it — `#slot:account.logo image_policy(fit=cover,
  focal_x=0.5, focal_y=0.35)` — never delete the slot.
- Text over a photo ALWAYS gets a scrim beneath it (`fill($surface.inverse)
  o($opacity.scrim)`) on a dark artboard. Ornament never competes with the focal
  point: confine a pattern or wash to a strip, quadrant, or radial corner.

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
Write "headline is 6 words at 80pt" or "CTA measures 3.1:1 against its surface",
not "looks clean" or "feels balanced". A weak design passes an adjective and
fails a measurement, which is exactly why the measurement is the score.

1. `single-focal-point` — squint: one mass, one landing spot. (`hierarchy`)
2. `safe-zone-clearance` — every word, logo, and CTA sits inside the 888 × 1330 band; art may bleed past it, text may not. (`clipping`)
3. `thumb-stop-in-the-top-third` — something arresting lands in the first third of the band, not below the fold of attention. (`hierarchy`)
4. `headline-budget` — ≤7 words, ≥64pt, and NOT a caption of the image. (`typography`)
5. `cta-legibility` — CTA readable at phone scale; ≥ 4.5:1 against its surface. (`contrast`)
6. `distinctive-asset-at-real-scale` — logo/wordmark ≥48pt; no asset with cropped baked-in text. (`asset_use`)
7. `on-color-pairing` — every text/ground and plate/ground pair reads cleanly.
   Dark ink on a saturated brand ground scores 0, and so does spending the
   full-strength brand color as BOTH the ground and the accent. (`contrast`)
8. `brand-adherence-followed` — the chosen level actually holds (tokens, faces, assets). (`brand_fit`)

## Override

Explicit user instructions beat every rule above. Record each override with
`record_gap`.
