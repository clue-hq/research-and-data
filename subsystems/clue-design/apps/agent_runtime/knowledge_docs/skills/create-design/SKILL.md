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
   `knowledge/lumen-dsl/grammar` + `knowledge/lumen-dsl/text`
   + `knowledge/design/artboard-frame-authoring` + the **vetted block catalog**
   (`knowledge/design/blocks/*` — pinned automatically); add `skills/brand-and-tokens`
   + the design-systems files when a Brand Kit is in play;
   `skills/effects` for shadows/special strokes/gradients.
2. **Pin the surface.** Match the requested artifact exactly:
   `page story size(1080,1920,px)` for a story, `preset(a4,portrait)` for a
   one-pager. These commands normalize to canonical `pt` artboard layout bounds:
   A4 is about `595 x 842 pt`, US Letter is `612 x 792 pt`, and a 1080 square
   social artboard is `1080 x 1080 pt`. Keep child coordinates artboard-local
   or parent-local. Never fake a square ad as a square frame inside an A4 page.
3. **Decide branded vs neutral.** With an effective Brand Kit, use `$tokens`
   (`$surface.*`, `$type.*`, `$space.*`, `$radius.*`). Without one, concrete hex /
   `font("Inter",…)` values are fine.

## How to compose

- **Start from the vetted block catalog** (`knowledge/design/blocks/`, loaded for
  every design task). Pick the full-artifact composition in `blocks/patterns.md`
  that matches the requested surface (social square / A4 / landscape / postcard) —
  it is already correctly proportioned, spaced, and validator-passed. Swap copy
  through its `#slot:` lines, and swap in component blocks (`layout.md`,
  `actions.md`, `data-display.md`) as needed. **Do not invent proportions from
  primitives** — that is what overcrowds layouts and fails preflight. See
  `blocks/README.md` for the index, the shared token choices, and the content budget.
- **Respect the content budget** (`blocks/README.md`): headline 4–8 words /
  `max_lines(2)`, body 12–25 words / `max_lines(3)`, benefit title ≤4 words,
  benefit description ≤12 words; one CTA per section; never more than 3 benefits in
  a row, and never 3 across on a portrait page. If content exceeds the budget, drop
  it or stack vertically — never shrink type or cram more in.
- **Structure with auto-layout**, not hand coordinates, whenever spacing should be
  systematic. A vertical `al(v, x(s), g(…), pad(…))` stack for content; a
  horizontal `al(h, x(c), y(c), …)` for buttons and proof rows.
- **One clear message, one CTA, generous margins.** Keep text off the edges.
- **Text**: `hug` height for anything that can vary, `wrap_text(true)` on body and
  long headlines, `max_lines(…)` so overflow is caught early, boxes **wide enough**
  for the real copy. Headlines tight (`lh 1.05–1.15`), body relaxed (`1.3–1.45`).
- **Center a label in a button/chip/circle** by adding `align(center)` to the text
  and a hug height: `... text "Book a Demo" s(fill,hug) style($type.cta) align(center)`,
  inside a both-axes-centered container `al(h, x(c), y(c), …)`. `align(center)`
  centers the glyph horizontally; never use a hug WIDTH for this (it trips `LUMV0902`).
  `style($type.x)` carries no alignment, so always pair it with `align(...)` when
  the text must be centered.
- **Backgrounds** belong on the container frame's `fill(...)`, not a separate rect.
  For export-safe pages, put the background on a clipped root `artboard` frame
  with `fill(...)`. Do not put `background(...)` on a `page ...` creation line,
  and do not draw a loose oversized `bg` rectangle.
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
  artboard al(v, x(s), g(28), pad(72)) p(0,0) s(fill,fill) fill($surface.brand) clip(true)
    content al(v, x(s), g(28), pad(0)) p(0,0) s(560,hug)
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
- Child `p()`/`s()` values are canonical `pt`, never `mm` and never renderer
  pixels; physical/raster units stay in the page/export declaration.
- Background is a page/artboard/root-frame fill, not a loose full-canvas `bg`
  rectangle.
- Every variable text box uses `hug`/enough space + `wrap_text` + realistic
  `max_lines`.
- Slots are semantic and on every personalizable element.
- Branded values use tokens; raw values only when no Brand Kit exists.
- No invented properties; no unsupported syntax.
