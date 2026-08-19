---
name: design-guidance
description: The brand-deployment grammar — how a brand USES its tokens (allocation, rhythm, posture, signature moments) and how to read a Creative Brief when the kit carries one. Sits between brand-and-tokens (the values) and create-website (the mechanics). Must-read for every website turn.
---

# Design Guidance — deploying a brand, not just its palette

Your design training carries hierarchy, balance, proportion, typography. The
sibling skills carry our mechanics: `create-website` owns the vocabulary,
class grammar, and copy rules; `brand-and-tokens` owns the token taxonomy;
`review-website` owns the ship bar. **This skill owns the layer between
them: the rules by which a real brand deploys its vocabulary** — where color
is allowed to live, how backgrounds sequence, what the buttons mean, when
scale may spike — and the contract for reading a per-brand **Creative
Brief** when the brand card carries one.

Two situations, one discipline:

- **The brand card carries a Creative Brief** (characterization, chromatic
  moment, palette application, background rhythm, postures, constraints,
  component recipes): the brief is the spec. Follow it literally; the rules
  below are the defaults for whatever the brief is silent about.
- **No brief** (kit-only, or the platform default theme): the rules below
  are the whole grammar. Derive the characterization yourself from the
  brand card's anchor words and hold to it as if it were briefed.

## The adherence ladder (binding, top wins)

1. The user's explicit request this turn.
2. The Creative Brief (follow literally when not overridden by 1).
3. The kit's tokens and theme variants (`brand-and-tokens`; the class
   grammar in `create-website`).
4. Your design instincts.

When 1 conflicts with 2–4: comply, and flag the deviation in one sentence in
your report — the director flags it in the finalize summary, the author in
its completion report back to the director. Never silently "improve" a brief
directive, and never refuse a user ask because the brief disagrees —
comply-and-flag is the whole protocol.

## Palette allocation — color has scopes, not just values

A brand is not a set of colors; it is a set of **permissions about where
each color may live**. Read (or assign) every palette entry one of these
scopes, and keep it there:

| Scope | Meaning | Typical carrier |
|---|---|---|
| **canvas** | the page's resting background | `bg-light` (or the brief's named canvas) |
| **ink** | headline/body foreground | `text-dark` / `text-primary`-as-text only if the brief says so |
| **accent-punctuation** | the saturated brand color as SIGNAL | button fills, icon color, check marks, link text, one highlighted word |
| **tinted-card** | a card surface tinted with brand color | `bg-primary/10`, one saturated card in a set |
| **closing-surface / statement band** | a full band in brand or dark color | at most where the rhythm calls for it |
| **motif** | a repeated small brand mark | logo tile, chip, badge |

The load-bearing rule: **accent is punctuation, not volume.** Within a
section, brand color lives on small surfaces; a restrained brand gets zero
to one brand-colored band per page, a heavy-brand-color identity two to
four — the brief's background rhythm decides, and when silent, default to
restrained. When siblings repeat (cards in a grid, steps in a row), they
share ONE background treatment; a tint applied to one sibling is a
deliberate chromatic moment (see below), not a styling accident. Tinted
brand color (`bg-primary/10`) is still brand color — allocate it, don't
scatter it.

**The chromatic brand moment.** Strong pages have ONE chromatic peak — the
single place the saturated brand color goes big (the one filled pricing
card, the statement band, the oversized accent numeral). Decide where the
peak is before authoring; everything else stays quiet so the peak reads.
Two peaks is zero peaks. The brief may name this moment explicitly
(`chromatic_moment`) — then it is not yours to move.

## Background rhythm — the page is a sequence

Think of the page as its background sequence before you think of sections:
`canvas → canvas → statement → canvas → footer-dark` is a design decision,
not an accident of authoring order. Rules when the brief is silent:

- Alternate deliberately between the canvas token and the card/muted
  surface (`create-website`'s band-alternation rule); insert at most one
  statement band (`bg-dark`/brand) where the argument peaks.
- A single-canvas brand (everything on one background) differentiates
  sections **compositionally, not chromatically** — spacing, scale, and
  structure change; the background does not. Do not fake variety with
  tinted bands the brand would never use.
- Cards sit ON the canvas; never stack a card-colored full section against
  the canvas without a card boundary — surface roles do not blur.
- The brief's `background_rhythm` (a sequence plus ratio, e.g. "1 dark
  sliver : 20 cream") is followed as given — reproduce the ratio's spirit,
  not a mechanical copy of section counts.

## Buttons are brand-identity components

A brand's button — its radius, padding, border, fill, label color, weight —
carries identity the way the wordmark does. Our theme already renders
`data-button="primary|secondary|outline|ghost|link"` as the brand's real
buttons; that is why `create-website` forbids restyling them. The deployment
etiquette this skill adds:

- **Placement over override.** The default move is to choose a section
  background the button's own variants read against — primary on canvas,
  outline/ghost on a statement band. Ask "which variant works here?" before
  ever asking "how do I recolor this?".
- A recolor is the last resort, reached only when the band's background is
  fixed by the composition AND no variant reads against it — and then only
  with theme tokens, inheriting the variant's shape untouched. Never
  recolor a button for visual interest.
- When the brief carries **component recipes** (the measured shape of the
  brand's real buttons/cards, in token names), use them verbatim — a recipe
  came from the brand's actual site and outranks your instinct.
- `link` buttons are prose, not chrome: they may take copy-fitting styling
  (tracking, underline) where the primary shape may not.

## Typographic posture — read it, then hold it

A brand has a typographic posture: case (sentence-case vs uppercase-tracked
labels), scale temperament (restrained vs stadium), signature moves (a
two-color headline split, an accent-colored numeral, an eyebrow ritual).
Read it from the brief (`typographic_posture`) or infer it from the kit's
type roles — then hold it page-wide:

- The theme's type ramp is the voice; headings land styled with zero
  classes (`create-website`). Posture decisions are about deployment:
  which variant where, what case, which single word carries accent color.
- **Stat-numeric accent:** when the brand's signature is an accent-colored
  metric (the brief will say so), the numeral MUST carry the accent token —
  a neutral stat number on such a brand reads as generic SaaS.
- **The signature moment:** at most ONE section per page may exceed the
  ramp — the stadium headline, the oversized hero number — and only where
  the brief designates it (`signature_compositions` marked STRONG/SINGLE).
  Everywhere else, strict variant discipline. No brief, no spike.
- Uppercase tracked text is a chip/eyebrow garnish, never body posture,
  unless the brief says the brand shouts.

## Imagery posture — the brief decides the diet

Photography-led, product-UI-led, text-forward, or abstract: the posture
(brief `imagery_posture`, else the brand card) sets the image DIET for the
whole page, not per-section whims. `create-website` owns the mechanics
(generate-then-reference, sibling uniformity, one hero image); this skill
adds the deployment rule: when the posture says text-only for a section
type, **omit imagery rather than decorate** — restraint (space, type, one
anchor) beats a filler visual every time. Product-UI briefs compose UI from
the vocabulary as a system across the page (create-website's Design-guidance
item on composable primitives); photography briefs without library assets
lead with type rather than shipping placeholder rectangles.

## Constraints are law, not mood

A brief's `constraints[]` are hard rules harvested from the brand's real
presence ("mint is the sole saturated color", "navy never as a mid-page
background", "exactly one filled card per tier row", "never flatten the
logo lockup"). Treat each as a lint you run over your own draft before
finalizing; the reviewer receives the same constraints and will report a
violation as a defect, not a taste note. When a user ask collides with a
constraint, the ladder applies: comply with the user, flag the collision.

## The pre-ship ritual (authoring-side QA)

Run the same three checks the reviewer will — as the author, before
reporting success back to the director; as the director, before
`finalize_web_run` (that tool is yours alone):

1. **Characterization recheck.** Re-read the anchor (brief's
   characterization, else your own 2–3 words). Point — literally, to a
   section id — at one element that would only make sense for THIS brand.
   Cannot? The page is generic: push the allocation, the chromatic moment,
   or the signature composition until it isn't.
2. **Squint pass.** Blur the text mentally at 1440: one dominant element
   per band; weight deliberate; edges on a shared grid; one or two color
   moments, not spread. Squint failures are structural — fix before polish.
3. **Chain trace.** Every band: background token → text token → button
   variant → logo variant all read together; the contrast rules in
   `review-website` are the bar.

## What this skill deliberately does NOT contain

The node vocabulary, class grammar, diagnostics, components, and repair
loop (`create-website`); the token taxonomy and mode rules
(`brand-and-tokens`); the review checklist (`review-website`); the recipe
grammar (`knowledge_docs/knowledge/web/landing-page.md`, `abm-page.md`).
When this skill and a sibling seem to conflict, the sibling owns its layer:
mechanics beat deployment advice mechanically (a class the grammar rejects
is rejected no matter what this skill implies), and this skill governs
which mechanically-valid choice the brand permits.
