---
name: review-website
description: Visual review of a rendered website at desktop/tablet/phone widths — the checklist, what blocks shipping, and how to report actionable issues.
---

# Review a Website Page

You are shown full-page screenshots of the SAME page at three widths —
1440 (desktop), 768 (tablet), 375 (phone). Judge what is actually in the
pixels; never assume the markup is right because it should be.

## The checklist — run it at every width

1. **Overflow & clipping** — any horizontal scrollbar, text escaping its
   container, cards colliding, content cut at the viewport edge.
2. **Hero** — headline readable in ≤2 lines at 1440 (≤4 at 375), visible
   CTA above the fold, imagery not crushing the copy on narrow widths.
3. **Images & icons** — every image renders (no missing/blank boxes), no
   distorted aspect ratios, sibling cards visually uniform (same icon size,
   same image treatment).
4. **CTAs** — primary CTA present in header, hero, and closing band; buttons
   look like the brand's buttons (not restyled ad hoc).
5. **Rhythm** — one consistent content max-width; section paddings even;
   band backgrounds alternate deliberately; nothing floats half-styled.
6. **Type hierarchy** — exactly one h1; sizes step down monotonically;
   overlines/eyebrows smaller than body, not shouting.
7. **Contrast** — body text clearly readable on its band (dark-on-light or
   inverse-on-dark); no mid-gray-on-gray, no accent-on-accent.
8. **Phone-specific (375)** — header still usable (logo + CTA visible, no
   overlapping links), grids collapsed to one column, tap targets not
   crowded, no tiny (<14px-equivalent) body text.
9. **Brand coherence** — palette and type feel like the brand card, accent
   color used as signal (links, highlights) not flood fill.

## Interactive states (when the page has components)

State captures accompany the width screenshots — the same page with a dialog
open or the accordions expanded (`view` lists them alongside the previews).
Judge interactive states from pixels with the same discipline as widths:

10. **Dialog** — opens centered over a dimmed backdrop; content readable and
    on-brand at 1440 AND 375; the close control visible; the page behind it
    not reflowed. A CTA wired to a missing dialog is a dead CTA — blocking.
11. **Accordion** — expanded items show real content with no overflow;
    summary rows read as tappable at 375; nothing double-renders.
12. **Marquee** — the strip shows no gap or pile-up at either edge in the
    base screenshots; content is legible at the pace implied by its length.
13. **Wiring** — every command button targets a dialog that exists (a
    LUMW0018 diagnostic is a blocking issue, same as a broken link).
14. **Nav menu (375)** — the expanded capture shows every nav link readable
    in the dropdown panel; the hamburger is visible in the base 375 shot;
    at 1440 the links render inline, no hamburger.
15. **Tabs** — the selected-tab capture shows the panel actually switched
    (different content than the default tab); tab labels short enough not
    to wrap into a second row at 375.
16. **Carousel** — slides sized so a peek of the next slide is visible at
    the viewport edge (affordance); arrows not overlapping content
    illegibly.
17. **Embeds** — a calendly embed has explicit height (not collapsed to a
    sliver); inside a dialog it fits without double scrollbars at 375. An
    embed showing the missing-content placeholder is blocking.

## Brand expression — the anchor check

You receive the director's **brand anchor** (2–3 creative-director words,
e.g. "clinical calm precision"). Your job is structural, not vibes:

- Point at ONE concrete element in the pixels that would only make sense
  for THIS characterization — a composition choice, a type move, an image
  treatment. If you cannot, report the advisory issue **"brand expression
  generic"** and name the band that most needs the anchor.
- Squint-test heuristics, at 1440: does one element clearly dominate each
  band (hierarchy)? does the weight balance left/right feel deliberate? do
  edges align to a consistent grid? are there 1–2 intentional color
  moments rather than accent spread everywhere?
- Trace the contrast chain: body text on band background, button label on
  button fill, **logo on its band** (a dark logo on a dark band is a
  blocking miss — no class fixes it), muted text still ≥ readable.

## Imagery — the decision check

Your brief carries the director's **imagery decision**: per band, place a
real asset / generate one / deliberately none-with-a-reason. Judge the
render against it, the same way you judge the anchor.

- **Delivered?** A band the decision said would carry an asset, showing no
  image in the pixels, is a reportable issue against that section id.
- **The brand's mark.** A branded page shows its brand's real logo — in the
  header at minimum. No logo anywhere is blocking, not advisory: it is the
  single clearest sign the page does not belong to this company. A drawn or
  typeset stand-in for a logo the kit actually ships is the same miss.
- **Brand-generic imagery.** Look at each image and ask whether it could sit
  unchanged on any competitor's site. If yes, report **"imagery
  brand-generic"** and name the band — the same shape of finding as "brand
  expression generic", and advisory unless it also breaks a brief
  `constraint`.
- **Unjustified absence.** A page with no imagery at all is correct when the
  brief's imagery posture is text-forward and the composition earns it
  through primitives (a stat wall, a dashboard scaffold, an editorial
  stack). It is a finding when the page is simply bare — flat bands of type
  with no composed content and no reason given. Say which it is; do not
  score restraint as failure or bareness as restraint.
- **Placeholders.** A flat grey rectangle where an image belongs is a
  generation that failed, not a design choice. Blocking.

## When a Creative Brief reaches you

Some brands carry a per-brand **Creative Brief** (characterization, chromatic
moment, background rhythm, postures, `constraints`) — it reaches you in the
brand card or quoted in the director's brief. When one is present it is the
spec the page was built to, so two extra checks apply:

- **`constraints` are review criteria, not taste.** Each one is a hard rule
  harvested from the brand's real presence ("mint is the sole saturated
  color", "navy never as a mid-page background"). Read them, then look for
  each in the pixels: a violation is a reportable **defect** — name the
  constraint, the width, and the section id — never softened to a
  preference. A deviation the user's own request forced is the director's to
  reconcile: report what you see, plainly, and let them.
- **Geometry that contradicts the brand's measured shape** — a control radius
  unlike the brand's other controls, an elevation heavier than the brand's real
  shadows, a card whose padding or a band whose vertical rhythm ignores the
  spacing the brief measured. The page's shape is supposed to come from the
  kit; where the pixels say otherwise, say so. This one is an **ADVISORY** note
  in the Verdict-discipline sense below — never blocking, and NOT a
  `constraints` defect (unless a constraint names that geometry itself, in
  which case the bullet above governs). You are judging pixels, not classes, so
  report what the shape looks like beside the brand's own, and let the author
  find the class.
- **Background rhythm** — compare the page's actual band sequence against
  the brief's `background_rhythm` (a sequence plus a ratio, e.g. "1 dark
  sliver : 20 cream"). Judge the ratio's spirit, not a mechanical section
  count: a page that floods brand color where the brief says restraint, or
  drops the statement band entirely, has missed the rhythm. With no brief,
  the checklist's own Rhythm item is the bar.

## Personalization check (1:1 account pages)

When your brief names a target account, additionally verify in the pixels:

- **No template fallback text** where the account's own content belongs — a
  generic company name ("Acme", the template's example account) in a
  headline, eyebrow, or CTA that should carry the target's name is blocking.
- **The account's logo actually renders** (not the template's placeholder
  logo, not a blank box) wherever the page co-brands.
- **Quoted, not adopted**: the page stays in the seller's palette and type;
  the target appears as name + logo. Any band restyled to the target's
  colors is blocking.
- An account-gated band that shows empty or half-populated content (a peer
  strip with one lonely logo, an empty proof band) is blocking — it should
  have been omitted instead.

## Verdict discipline

- **Blocking** (must-fix): overflow/clipping, unreadable contrast, broken or
  missing images, a dead or missing primary CTA, unusable phone header.
- **Advisory** (note, don't block): spacing nitpicks, copy tone, an image
  that would be nicer cropped differently, and geometry that contradicts the
  brand's measured shape (the Creative Brief section's bullet — a brand-shape
  note is always advisory, however wrong the radius looks).

Report each issue with: the width where it appears, the section id, what is
wrong in the pixels, and the smallest concrete fix (a class change, a
structure change, a copy trim). Never report an issue you cannot point to in
a screenshot; never pass a page you have not looked at, at all three widths.
