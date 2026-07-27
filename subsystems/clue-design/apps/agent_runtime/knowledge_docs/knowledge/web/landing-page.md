# Recipe: Landing Page

The section grammar and hard rules for a product landing page. A recipe is a
business contract, not a style guide — the create-website skill owns HOW to
author; this owns WHAT a landing page must contain and must never do.

## Required section order

1. **header** — brand name or logo left; 2–4 text nav items (anchor links to
   sections); primary CTA right. On phone: logo + CTA only.
2. **hero** — overline (category, e.g. "AI medical scribe"), h1 with the
   value proposition (`display` variant), one supporting paragraph, primary +
   secondary CTA pair. Optional single hero image.
3. **social proof strip** — ONLY with real, verifiable customer names/logos
   from the brand kit or brief. No real proof → OMIT the section entirely.
4. **features** — h2 + 3 (or 6) cards: icon, h3, one concrete sentence each.
5. **how-it-works** — h2 + 3 numbered steps, one line each. Omit if the brief
   gives no process to describe.
6. **final CTA band** — statement background (`bg-dark` or `bg-primary`),
   h2 restating the value, the primary CTA.
7. **footer** — brand name, 2–4 links, © line with the current year.

Optional between 4 and 6: a product-shot band (one generated product image),
an FAQ (h3 question + p answer pairs). Never two imagery bands adjacent.

## Hard rules (violations are defects, not taste)

- **Never invent facts**: no made-up statistics, customer counts, quotes,
  testimonials, awards, compliance claims beyond the brief. If the brief
  says "HIPAA", you may say "HIPAA"; you may not add "SOC 2".
- **Real links only**: CTAs point to the brand's real domain (from the brand
  kit source or the brief) or to `#section` anchors. Never guess deep paths
  (`/pricing`, `/signup`) unless given. Unverifiable → use an anchor or omit
  the element.
- **One primary CTA destination**, reused verbatim in header, hero, and the
  final band. Secondary CTAs are anchors (`#features`, `#how-it-works`).
- **CTA variants**: `primary` and `secondary`/`outline` only. `ghost`/`link`
  are for footer/nav-adjacent links.
- **Sibling parity**: feature cards all use icons or all use images, same
  size, same structure. Never mix.
- **Never reuse an image** in two places on the page.
- **Copy**: concrete verbs over adjectives; one idea per sentence; no
  emojis; no em-dashes; sentence case everywhere except the brand name.
