---
name: linkedin-square-ad
description: Author a 1080×1080 LinkedIn feed ad end-to-end — concept plan, layout skeleton, type scale, brevity budgets, and the self-audit checklist. Use whenever the brief asks for a linkedin ad, feed ad, square social ad, or 1:1 paid social creative.
required_decisions: audience, offer_cta, tone, brand_adherence
selection_policy: llm_selectable
---

# LinkedIn Square Ad

An ad interrupts a scroll. In the first second the viewer must register, in
order: something worth stopping for → who it's from → the one idea → what to
do. Every rule below serves that ordering; clarity earns the seconds after.

## Composes with

This skill decides; the craft skills execute. Read beside it:

- `skills/brand-and-tokens` — role tokens, never guessed values.
- `skills/brand-imagery` — the kit-asset / generate / deliberately-none call.

Pin these knowledge files into the frame payload instead of hunting for them
mid-run: `knowledge/design/layout-recipes` (the six-archetype canon),
`knowledge/design/blocks/patterns` (validator-passed 1080² blocks),
`knowledge/design/foundations` (squint test, 60-30-10, contrast floors), and
`knowledge/lumen-dsl/grammar` + `text` (the size ramp).

## Defaults & required decisions

- Surface: `page linkedin_square size(1080,1080,px)`, which lays out as
  1080 × 1080 pt. Give the root artboard `pad(96) s(fill,fill) clip(true)`.
  The validated margin is 96pt. **64pt is the hard safe-margin floor.** The
  content column between the default margins is 888pt wide.
- One ad = one audience, one promise, one ask. Kill every secondary message.
- Brand adherence: **strict** = kit tokens/faces/assets only · **balanced** = kit
  defaults + limited complementary accents · **loose** = brand-inspired, kit
  still recognizable.

Before authoring, check the brief against this table. Each row maps 1:1 onto
`ClarificationQuestion`. If a material decision is missing, ask once — a single
batched `request_clarification` round. Otherwise proceed on the defaults and
call `record_gap(area="agent_protocol", …)` for each assumption you apply.
Derive answers before you ask: read the prompt, prior turns, the document, and
the brand card first (`skills/clarify-design-brief`). Asking about something
derivable is a failure.

| id | question | why_it_matters | options | default |
|---|---|---|---|---|
| `audience` | Who is this ad for? | One audience reads; three compete and none land. | | the kit's primary audience |
| `offer_cta` | What should they do next? | The ask fixes the CTA label and the whole close. | Request a demo · Read the case study · Start free | Request a demo |
| `tone` | Bold or conservative? | It picks the archetype, the type voice, and the contrast. | bold · conservative | bold |
| `brand_adherence` | How tightly must this hold the kit? | It decides whether a non-kit display face is allowed. | strict · balanced · loose | balanced |

## Concept plan gate (before any DSL)

Write in the direction: the **playbook** (product-as-hero / before-after /
typographic-manifesto / stat-proof / problem-solution / demonstration /
juxtaposition / visual-metaphor / category-reversal / if-then), the **headline**
(verbatim), the **single focal point**, the **type direction**, and the imagery
decision. One-sentence test: "For [audience], [brand] is the [category] that
[single claim]" — if the claim needs two sentences the strategy is broken; ask,
don't design.

## Layout skeletons (pick one, name it in the direction)

Each is an archetype from `knowledge/design/layout-recipes` — recompose it, never
pour copy into the shell.

1. **Split-panel** — `al(h)` root: media `s(456,1080)` + panel `s(624,1080)
   pad(80,64)`, copy column 496pt. Media stays 40–45% so the panel breathes; a
   50/50 square reads as two half-ads. The photo must survive a hard square crop.
2. **Full-bleed statement** — the **vertical-poster** on an inverted surface
   (`fill($surface.inverse)`), type IS the hero, no photo: hug header /
   `s(888,fill) y(c)` main / hug footer. Use when kit imagery is weak or adherence
   is strict. Proportions: `blocks/patterns` "Full-canvas poster".
3. **Stat block** — the **numeral-hero**: one number at **≥300pt** carries the
   frame, everything else deliberately quiet. The ramp tops out at
   `$type.size.9xl` (128), so step it raw: `style($type.display) font_size(300)
   lh(0.92) max_lines(1)`. Only with a number sourced from the brief or kit, kept
   short (`3.2s`, `99.99%`, `40M`).

## Type

- Headline: `style($type.headline) font_size($type.size.7xl)` (80) — or
  `$type.display` when the kit ships a distinct display role. **Floor
  `$type.size.6xl` (64)**; the role default 56 does not dominate 1080. ≤7 words,
  `max_lines(2)`, `lh(1.04)`, `wrap_text(true)`.
- Body: ≤160 chars at `style($type.body)` (the wide-square role), and at least
  **22pt**. That is one step above the general 1080² skeletons' 19–21pt, because
  the feed downscales the canvas. If the kit's body role lands smaller, step up
  with `font_size($type.size.xl)` (24).
- CTA label: ≤4 words, `style($type.cta) align(center)`, inside a `s(fill,hug)`
  text node.
- Kit faces first. A library display face may carry the headline when the kit
  voice is too neutral to stop a scroll and adherence is not strict — **Anton**,
  **Bebas Neue** (caps only), **Archivo Black**, **Bricolage Grotesque**; exact
  name, listed weights (`knowledge/design/font-library`). One display voice + one
  workhorse; two display faces fight. Banned: defaulting the headline to
  `font("Inter",…)` (Inter is the fallback, not a voice) and any family off the
  library list (Arial/Helvetica/Roboto/Open Sans do not resolve).
- Headline and visual are ONE idea: if the headline still works pasted on a
  different image, rework the pair. Never caption the image.

## Brand & assets

- Logo or wordmark at real scale — **≥48pt height**, or the kit's declared
  minimum size if larger; an eyebrow line is not a substitute. Bind through slots
  (`slot(account.logo)`) with asset roles (`logo.primary` / `logo.reversed`),
  never an invented asset id.
- **Look at every asset before you place it** — `view("asset:<asset_id>")`.
  Reject crops with baked-in text; check the mark's shape against its frame.
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
- Any `0` on tests 1–6 means `accepted=false`.

Score with facts and measurements against the named test, never with adjectives.
Write "headline is 6 words at 80pt" or "CTA measures 3.1:1 against its surface",
not "looks clean" or "feels balanced". A weak design passes an adjective and
fails a measurement, which is exactly why the measurement is the score.

1. `single-focal-point` — squint: one mass, one landing spot. (`hierarchy`)
2. `first-second-ordering` — stop → who → idea → act is legible in that order. (`hierarchy`)
3. `headline-budget` — ≤7 words, ≥64pt, and NOT a caption of the image. (`typography`)
4. `cta-thumbnail-legibility` — CTA readable at thumbnail scale; ≥ 4.5:1 against its surface. (`contrast`)
5. `distinctive-asset-at-real-scale` — logo/wordmark ≥48pt; no asset with cropped baked-in text. (`asset_use`)
6. `safe-margins` — all four margins clear, nothing clipped, no dead or zero-size nodes. (`clipping`)
7. `brand-adherence-followed` — the chosen level actually holds (tokens, faces, assets). (`brand_fit`)

## Override

Explicit user instructions beat every rule above. Record each override with
`record_gap`.
