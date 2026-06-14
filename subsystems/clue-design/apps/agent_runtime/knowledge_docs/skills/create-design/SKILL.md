---
name: create-design
description: Compose a brand-new Lumen design artifact from a prompt — choose the page surface, structure with auto-layout, write conservative compiling DSL, and mark ABM slots. Use for the first authoring pass, before any repair.
---

# Create a Design From Scratch

Author one coherent DSL block that compiles cleanly and reads as a real,
brand-aligned artifact. This is the *first* pass only — fixing diagnostics is
`repair-design`.

## Before you write

1. **Load knowledge** for the task (see `AGENT.md` §4): always
   `knowledge/lumen-dsl/grammar` + `knowledge/design/layout-recipes`; add
   `skills/brand-and-tokens` + the design-systems files when a Brand Kit is in
   play; add `knowledge/lumen-dsl/text` for text-heavy pieces;
   `skills/effects` for shadows/special strokes/gradients.
2. **Pin the surface.** Match the requested artifact exactly:
   `page story size(1080,1920,px)` for a story, `preset(a4,portrait)` for a
   one-pager. These commands normalize to canonical artboard layout bounds;
   keep child coordinates page-relative. Never fake a square ad as a square
   frame inside an A4 page.
3. **Decide branded vs neutral.** With an effective Brand Kit, use `$tokens`
   (`$surface.*`, `$type.*`, `$space.*`, `$radius.*`). Without one, concrete hex /
   `font("Inter",…)` values are fine.

## How to compose

- **Structure with auto-layout**, not hand coordinates, whenever spacing should be
  systematic. A vertical `al(v, x(s), g(…), pad(…))` stack for content; a
  horizontal `al(h, x(c), y(c), …)` for buttons and proof rows.
- **One clear message, one CTA, generous margins.** Keep text off the edges.
- **Text**: `hug` height for anything that can vary, `wrap_text(true)` on body and
  long headlines, `max_lines(…)` so overflow is caught early, boxes **wide enough**
  for the real copy. Headlines tight (`lh 1.05–1.15`), body relaxed (`1.3–1.45`).
- **Backgrounds** belong on the container frame's `fill(...)`, not a separate rect.
- **Shadows/strokes/gradients**: keep them tasteful and tokenized; see
  `skills/effects`.
- **Mark ABM slots** on every element a campaign would personalize:
  `slot(contact.full_name)`, `slot(account.logo)`, `slot(campaign.headline)`,
  `slot(offer.primary_message)`. Add `sample("…")`/`worst_case("…")` on text slots
  so fit validation tests real-length data (avoids `LUMV0509`).

## Size the content to the box (this prevents the common failure)

Text fit is measured for real. A dense card that packs a header + several
label/value pairs + a paragraph into a small fixed card **will** overflow
(`LUMV0903`/`LUMV0810`). Before finalizing:

- Give long paragraphs enough height (or `hug`) and a realistic `max_lines`.
- If the content is dense, make the card taller rather than shrinking every box.
- Prefer one `worst_case` fixture per text slot and eyeball that it still fits.

## Skeleton

```text
page linkedin_square size(1080,1080,px)
  bg fr p(0,0) s(1080,1080) fill($surface.brand)
    content al(v, x(s), g(28), pad(0)) p(72,88) s(560,hug)
      headline text "Let neurosurgeons focus on surgery." p(0,0) s(fill,hug) style($type.headline) lh(1.08) wrap_text(true) max_lines(2) slot(campaign.headline)
      body     text "Insight Health handles calls, scheduling, and patient routing." p(0,0) s(fill,hug) style($type.body) lh(1.35) wrap_text(true) max_lines(3) slot(offer.primary_message)
      cta al(h, x(c), y(c), pad(14,28)) p(0,0) s(220,56) fill($surface.inverse) rd($radius.md)
        cta_text text "Book a Demo" p(0,0) s(fill,hug) style($type.cta) max_lines(1) slot(campaign.cta)
```

## Finish

Return **DSL only** (no fences/prose). Then the coordinator compiles it. If
anything fails, switch to `repair-design` — keep this design's direction and fix
the smallest failing piece.

## Self-check before handing off

- IDs stable, descriptive, unique. Two-space indentation. Leaf nodes childless.
- Page surface matches the request exactly.
- Every variable text box uses `hug`/enough space + `wrap_text` + realistic
  `max_lines`.
- Slots are semantic and on every personalizable element.
- Branded values use tokens; raw values only when no Brand Kit exists.
- No invented properties; no unsupported syntax.
