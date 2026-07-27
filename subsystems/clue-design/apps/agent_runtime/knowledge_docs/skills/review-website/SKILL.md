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

## Verdict discipline

- **Blocking** (must-fix): overflow/clipping, unreadable contrast, broken or
  missing images, a dead or missing primary CTA, unusable phone header.
- **Advisory** (note, don't block): spacing nitpicks, copy tone, an image
  that would be nicer cropped differently.

Report each issue with: the width where it appears, the section id, what is
wrong in the pixels, and the smallest concrete fix (a class change, a
structure change, a copy trim). Never report an issue you cannot point to in
a screenshot; never pass a page you have not looked at, at all three widths.
