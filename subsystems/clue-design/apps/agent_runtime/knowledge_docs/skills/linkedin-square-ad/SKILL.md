---
name: linkedin-square-ad
description: Use whenever the brief asks for a linkedin ad, feed ad, square social ad, or 1:1 paid social creative.
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
- `skills/color-and-contrast` — which combination of those tokens actually
  reads, using resolved colors and the actual image beneath the text.
- `skills/brand-imagery` — the kit-asset / generate / deliberately-none call.
- `skills/clarify-design-brief` — derive before you ask.

Pin these knowledge files into the frame payload instead of hunting for them
mid-run: `knowledge/design/layout-recipes` (the six-archetype canon),
`knowledge/design/blocks/patterns` (validator-passed 1080² blocks),
`knowledge/design/blocks/actions` (the validated button structure),
`knowledge/design/foundations` (squint test, 60-30-10, contrast floors), and
`knowledge/lumen-dsl/grammar` + `text` (the size ramp).

## Defaults & required decisions

- Surface: `page linkedin_square size(1080,1080,px)`, which lays out as
  1080 × 1080 pt. Start with `pad(96) s(fill,fill) clip(true)` for an inset layout; use a
  separate full-bleed artwork layer when the reference calls for it. Keep required
  copy and marks inside at least 64pt safe margins unless the brief specifies
  another safe area. Composition, proportions and alignment follow the message
  and reference, not a mandatory 888pt column.
  Author it in your FIRST compile, before any imagery or logo — a pageless
  scene registers nothing.
- One ad = one audience and one central message. Include an ask only when the
  brief calls for one; an awareness statement can end with the brand.
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

## Composition from the message and reference

When references are attached, read `skills/reference-conditioned-ads` and look
at the pixels. Preserve the relevant hierarchy, relative type/logo scale, field
proportions, tonal depth and imagery treatment while adapting the supplied copy.

The split-panel, vertical-poster and numeral-hero recipes in
`knowledge/design/layout-recipes` are examples, not an exhaustive menu or a
required shell. Choose or combine layout primitives around the actual idea:
editorial typography, a product stage, a source review card, a device composition,
a diagram, or an image-led statement may need different geometry. Numbers and
reviews require approved source content; a visual reference alone is no evidence
for a new claim. Do not force a left-image/right-copy split or a fixed CTA size.

The direction is a compact handoff: exact copy, selected source asset IDs,
reference observations, layer ownership, intended geometry and generated-artwork
requirements. Give the author the exact direction-file path and these essentials
inline. Reuse inspected assets instead of searching the whole catalog again.

## Type

- **Text height is always hug.** Write `s(W,hug)` or `s(fill,hug)`; never a
  fixed height on a text node — the box stops following the copy and the editor
  outlines empty space. Widths may be fixed or fill.
- Headline: keep the kit's appropriate display or headline face. Start around
  `style($type.display) font_size($type.size.7xl)` and adapt width, line breaks
  and size to the real copy. Preserve user-supplied copy even when longer than
  a generic brevity budget. For 1080 output, aim for at least 64pt resolved type
  unless the reference or brief justifies another scale.
- Body and CTA: choose explicit legal size tokens alongside their own roles,
  for example `style($type.body) font_size($type.size.xl)` and
  `style($type.cta) font_size($type.size.xl)`. Aim for at least 24pt resolved
  size, preferably larger when space permits, then read them at 360px feed size.
- The pinned kit may normalize its size ladder. Token names do not guarantee
  base-ramp numbers. Inspect resolved node sizes after preflight; a raw numeric
  font size can be replaced by role binding. Check headline, support AND CTA.
- Build the native CTA using `knowledge/design/blocks/actions`: a separate
  filled container with `al(h,x(c),y(c),pad(20,40))`, `rd($radius.button)` and
  one native label with `s(fill,hug) align(center)`. Choose the plate's explicit
  width/height to fit its measured label and intended padding. Its `y(c)` centers
  the label box; `align(center)` centers the glyphs. Preserve both. Do not use a
  hug-width label (`LUMV0902`). A large plate cannot rescue a tiny label.
- Omit the CTA when the brief calls for awareness without one; do not invent an
  extra action to satisfy a default recipe.
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

- Select foregrounds from actual approved colors using
  `skills/color-and-contrast`. A saturated brand surface may need dark or light
  text depending on its luminance. A token name is not a contrast verdict.
- Keep the authentic logo as its own image layer with undistorted proportions,
  sized for the composition and the kit's declared minimum. Use actual asset
  roles (`logo.primary` / `logo.reversed`), never an invented asset id. Prefer a
  recognizable wordmark/lockup to a favicon when the reference identifies the
  brand by name. Match its visual weight and choose a compatible ground.
  A standalone logo image is editable without a personalization slot. When
  scaling requires `slot(account.logo)`, supply its required placeholder/sample
  and a `fit=contain` policy matching the real source alpha; opaque assets
  cannot satisfy `preserve_transparency=true`. Preserve existing bound slots.
- **Look at every asset before you place it** — `view("asset:<asset_id>")`.
  Authentic product screenshots may contain source UI text. Keep their bytes
  intact; use contain or a deliberate crop that preserves meaningful content.
  Main campaign text remains native; a finished ad bitmap is not the editable
  composition. Logos, source UI, generated artwork and text are separate layers.
- When generated variants are requested, follow `skills/generative-imagery`:
  produce, view and retain the requested distinct assets. An existing screenshot
  or flat ground does not fulfill that requirement.
- Website section frequency, CSS classes and website button scales govern WebDoc
  work. This Scene ad follows its own brief and reference composition.
- Image slots are born with a default policy; if an inherited document raises
  `LUMV0820`, one line clears it — `#slot:account.logo image_policy(fit=cover,
  focal_x=0.5, focal_y=0.35)` — never delete the slot.
  This is modify-line syntax, not a universal logo crop: choose contain when
  cover would clip the actual mark, and verify the whole mark remains visible.
- Put copy on a genuinely quiet image region or an approved plate/scrim.
  Check local contrast and visual hierarchy. Artwork may occupy the whole frame
  when it supports the reference; its visual weight must serve the message.

## Self-audit checklist

Score each test **0–2** into `critique.json` (the `VisualCritique` shape), and
only **after looking at the render** — never from geometry alone. Write it up
like this:

- One `acceptance_notes` line per test: `"<test-name>: <score> — <why>"`.
- Every score below 2 also becomes an `issues[]` entry. Name the test in
  `message`, give a `target` and a `suggested_repair`, and use the category
  shown in parentheses below.
- Any `0` on tests 1–8 means `accepted=false`.

Score with facts and measurements against the named test, never with adjectives.
Write "headline is 6 words at 80pt" or "CTA measures 3.1:1 against its surface",
not "looks clean" or "feels balanced". A weak design passes an adjective and
fails a measurement, which is exactly why the measurement is the score.

1. `single-focal-point` — squint: one mass, one landing spot. (`hierarchy`)
2. `first-second-ordering` — the focal idea, brand and any required action read clearly; awareness may omit an action. (`hierarchy`)
3. `headline-budget` — supplied copy preserved, resolved size and line breaks readable at feed size. (`typography`)
4. `cta-thumbnail-legibility` — resolved label size and ≥4.5:1 contrast read at 360px; note omitted-by-brief when absent. (`contrast`)
5. `distinctive-asset-at-real-scale` — authentic mark/UI intact, correct proportions, requested generated variants viewed and retained. (`asset_use`)
6. `safe-margins` — required copy and marks stay clear; intentional artwork bleed is allowed; no dead or zero-size nodes. (`clipping`)
7. `no-collisions` — no text runs into another text block, a button, or an image
   edge. (`overflow`)
8. `on-color-pairing` — every resolved text/ground and plate/ground pair reads
   cleanly; judge local contrast and hierarchy, not semantic color names. (`contrast`)
9. `brand-adherence-followed` — the chosen level actually holds (tokens, faces, assets). (`brand_fit`)

Test 7 is an EYES test and cannot be scored from geometry. The engine measures a
line of text as exactly font size times line height, so tight leading shrinks the
measured box in step with the text and the spill it causes is never reported.
A scene can preflight perfectly clean while a headline sits on top of the body
copy. Look at the render, and name both node ids when you find a pair. Try
more line height, more gap, or fewer words only when the brief permits rewriting.
Otherwise preserve supplied copy and adjust width, layout or size within the
readable scale. Do not hide collisions by making required text illegibly small.

## Override

Explicit user instructions beat every rule above. Record each override with
`record_gap`.
