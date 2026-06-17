# Design Foundations

Core judgment for every build — the taste rubric the visual critic scores against.
Load this for every design task. For DSL syntax see `knowledge/lumen-dsl/grammar`
+ `text`; for ready-made proportions see `knowledge/design/blocks`.

## Before you build

Read the intent. A vague prompt is the user evaluating you — deliver one tight,
impressive piece. A specific product prompt — clarity and usability come before
style. Either way, commit to a system first: a surface, 3–6 token roles with one
brand color, a type scale, a spacing rhythm. Then decide the ONE focal point and
the personality. Assemble from `blocks/` — don't invent proportions per run.

## Composition — one thing dominates

- **One dominant region per artifact.** Every screen needs a single element the
  eye lands on first; everything else is visibly subordinate (smaller, lighter,
  lower contrast). **Squint test:** if you blur the design and nothing pops, the
  hierarchy has failed — raise the contrast or the size gap.
- **Scale the hero to the surface.** Type sizes are fixed values, not
  canvas-relative — so the same `$type.headline` (56) that dominates an A4 page is
  lost on a 1080² canvas. Keep the role, step the size with a token:
  `font_size($type.size.6xl)` (64) for a landscape flyer, `7xl` (80) for a 1080²
  square (see `knowledge/lumen-dsl/text`). The hero must read **visibly larger than
  any `$type.stat` (48) or secondary value** — a stat that rivals the headline
  inverts the hierarchy.
- **Jump rule.** A heading is ~150–200% of body; the hero is ~2–3× body. Build
  hierarchy with **size + weight + color together**, not one alone.
- **Whitespace is margin, not gaps.** Aim for ~60–70% empty space, but it must
  read as generous margin *around a coherent block* — not as dead bands trapped
  *between* scattered elements. Then ask what to remove.
- **One alignment spine.** Pick a left (or center) edge and align everything to it;
  a single consistent spine reads as intentional. Don't mix left- and center-
  alignment in the same column. One CTA per section.
- **Information on surfaces over boxes.** Favor type/color hierarchy over boxing
  everything in cards; favor asymmetry and scale contrast over grid-like sameness.

## Distribute the canvas — no dead bands

A tall canvas with light content fails when the agent **start-stacks** everything
(empty bottom, "reads truncated") or spreads it with `y(sb)` so each region floats
alone (two empty bands, "disconnected strips"). Free space must read as *margin
around an anchored block*, never as gaps *between* stranded strips. The root
`artboard` is already a fixed-height frame (`s(fill,fill)`), so free vertical space
is real and must be claimed — by **alignment + a `fill`-height region**, never a
filler element.

- **Never make an empty spacer frame.** Express free space with sizing/alignment.
- **`y(sb)` (space-between) is for exactly TWO anchored blocks** (header top + footer
  bottom). With 3+ light blocks it scatters the slack into dead bands — don't.
- **The poster idiom (one focal block on a big canvas):** a `fill`-height content
  region absorbs the slack and centers its content; the header pins top and the
  footer is pushed to the bottom. Verified: header `y=96`, footer `y=944`, hero
  centered `y=500` on a 1080² canvas.
  ```text
  artboard al(v, x(s), y(s), g($space.section), pad(96)) s(fill,fill)
    header ...                       s(888,hug)          # pins top
    main   al(v, x(s), y(c), ...)    s(888,fill)         # ABSORBS slack, centers
      <eyebrow / headline / subtitle / proof — the focal block>
    footer al(h, x(sb), y(c), ...)   s(888,hug)          # pushed to bottom
  ```
- **Decision rule for light content on a big canvas** — choose by block count, never
  by manufacturing filler copy:
  - **One focal block** → put it in a `s(W,fill)` / `s(fill,fill)` region with `y(c)`;
    the empty area becomes symmetric margin.
  - **Two anchored blocks** (header/footer) → `y(sb)` on the fixed-height parent.
  - **A genuinely long page** → stack sections with a small inter-section gap and let
    each section own its vertical `pad()`; a focal middle region can still be `fill`.
- **Never strand a header alone over a void, and never leave the bottom of a
  fixed-height page empty.** If the body doesn't reach the page bottom, give it a
  `fill`-height region (stretch) or center it with `y(c)`. If the artifact genuinely
  lacks content for its surface (e.g. an appointment card with no date/time/location),
  add the real missing content — that is the honest fill, not a spacer.

## Color & contrast

- **60-30-10:** one dominant surface (~60%), one secondary (~30%), one accent
  (~10%). The accent is the brand color — reserve it for the focal point / CTA.
- **Legibility is non-negotiable:** body text ≥ 4.5:1 against its surface, large
  text ≥ 3:1 (WCAG AA). Token resolution already corrects text color for its
  surface, but don't place a low-contrast accent as body copy.

## Avoid the AI clichés

- **Eyebrows:** the tinted pill above the headline is the #1 tell. Vary it — a
  plain overline, a short accent rule + label, or none. Reserve the pill for a
  genuine status badge ("NOW IN BETA").
- **Color:** skip blue→purple gradients, neon-on-dark, all-white-with-one-safe-
  accent, and low-opacity circles drifting behind sections.
- **Layout:** avoid three equal cards in a row as the default answer; avoid
  centering everything; avoid a lonely small headline stranded in a sea of white.
  If you've seen the move in three AI designs, drop it.

## Content budget (keeps it uncrowded — and keeps worst_case fixtures in the box)

Eyebrow 2–4 words; headline 4–8 words `max_lines(2)`; subtitle 6–13 words
`max_lines(3)`; body 12–25 words; benefit title ≤2 words; benefit description ≤12
words; one CTA label 2–3 words; stat = one numeral + ≤2-word label. If content
exceeds the budget, **drop it or stack vertically — never shrink type or cram more
in.** Smaller surfaces carry *less* content, not the same content smaller.
