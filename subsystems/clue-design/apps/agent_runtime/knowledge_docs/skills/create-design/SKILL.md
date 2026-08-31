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
   + `knowledge/design/foundations` (the taste rubric — one dominant element,
   hero-size-per-surface, whitespace-as-margin, anti-cliché)
   + `knowledge/design/layout-recipes` (**the archetype canon** — the six
   composition skeletons you choose from FIRST)
   + `knowledge/design/artboard-frame-authoring` + the **vetted block catalog**
   (`knowledge/design/blocks/*` — pinned automatically)
   + `knowledge/images/decide` (whether the surface needs an image at all, and which
   mechanism) + `knowledge/design/font-library` (the always-loadable type voices);
   add `skills/brand-and-tokens` + the design-systems files when a Brand
   Kit is in play; `knowledge/images/prompts` + `knowledge/images/placement` when the
   design uses imagery; `skills/effects` for the exact shadow/stroke/gradient grammar.
2. **Pin the surface.** Match the requested artifact exactly:
   `page story size(1080,1920,px)` for a story, `preset(a4,portrait)` for a
   one-pager. These commands normalize to canonical `pt` artboard layout bounds:
   A4 is about `595 x 842 pt`, US Letter is `612 x 792 pt`, and a 1080 square
   social artboard is `1080 x 1080 pt`. Keep child coordinates artboard-local
   or parent-local. Never fake a square ad as a square frame inside an A4 page.
3. **Decide branded vs neutral.** With an effective Brand Kit, use `$tokens`
   (`$surface.*`, `$type.*`, `$space.*`, `$radius.*`). Without one, use concrete
   hex values — and make a deliberate TYPE-VOICE call from the curated font
   library (`knowledge/design/font-library`): pick a display voice + a workhorse
   that match the brief's tone and name the choice in your notes. Defaulting
   every no-kit surface to `font("Inter",…)` is a missed decision — Inter is the
   fallback, not the voice. Library families load by exact name with listed
   weights, e.g. `font("Bricolage Grotesque",72,800,left)` for the hero,
   `font("Inter",17,400,left)` for support copy.

## Choose the archetype first

Before any DSL, pick the **composition archetype** that fits the brief from the
canon in `knowledge/design/layout-recipes` — the six are vertical-poster,
split-panel, numeral-hero, image-hero, banded, emblem. Each names the structural
move (how the canvas divides, what dominates), the surface treatments that suit
it, and the type voice. **Archetypes are skeletons — recompose, don't reskin.**
Do NOT pick one shell and pour copy into its slots: choose the move that serves
*this* message, then build it for *this* content. Defaulting every brief to the
vertical poster is the single failure the canon exists to break — if the brief
invites a photo, a dominant metric, or editorial rhythm, use the archetype that
delivers it.

Then declare, in your notes: the archetype, the surface treatment (solid paper /
brand gradient field / soft radial wash / shadowed plate), and the imagery
decision (kit asset / generate / deliberately none — see `knowledge/images/decide`).

## Working from references (when the user attached them)

When the run has references, `reference-brief.md` exists in the workspace (the
Director wrote it by looking at every reference). **Read it FIRST — before you
choose an archetype or treatment.** References can be ANY kind of image: a photo,
an illustration, a busy poster, a typography specimen, a 3D render, a screenshot,
a texture. There is no default "what a reference looks like."

The discipline is the same whatever the image class:

1. **Adopt the DEFINING qualities the brief names — not just the palette.** The
   brief states the qualities that actually define these references: form
   vocabulary, edge character, density, palette role, texture, mood, composition
   rhythm. Build the design so those qualities are visible in the render. If the
   references are a brutalist type poster, the defining quality might be raw
   scale, tight tracking and hard left rag; if a soft atmospheric field, it might
   be low saturation and edges that fade to nothing; if a product photo, it might
   be a specific light and negative-space rhythm. Perceive what is THERE.
2. **`view("reference:<n>")` the sources** and judge the match by looking, never
   from metadata. When you `generate_image` this turn, the references are fed to
   the model as automatic style conditioning — you do NOT need to describe their
   look in the prompt (that's redundant); prompt the subject and let the attached
   references carry the style.
3. **Never regress to house vocabulary.** The single failure this section exists
   to break: reducing a reference to a couple of hex values and then composing in
   the loop's *default* style — the vertical-poster reflex, the eyebrow pill, the
   confetti blob. The soft-wash recreation case is the canon example: references
   were reduced to a palette and the output came back as scattered hard-edged
   blobs in the house style ("no problems detected" — because nobody checked
   fidelity). That is ONE instance of a general trap; the trap is *palette-only
   reduction*, and it applies to every image class, not just washes or gradients.
4. **The brief still governs, and the kit still owns identity.** The user's prompt
   overrides any incidental quality of a reference. And where a reference conflicts
   with the brand kit, the KIT wins on identity — colors, fonts, logo — while the
   reference supplies composition and mood. `reference-brief.md` says which is
   which for this turn; follow it.

The reviewer will judge `reference_fidelity` against these same qualities, so a
design that ignored them will not pass.

## How to compose

- **Build the chosen archetype's skeleton** (`knowledge/design/layout-recipes`) and
  fill it with the vetted component blocks (`knowledge/design/blocks/` — `layout.md`,
  `actions.md`, `data-display.md`), which are already correctly proportioned and
  validator-passed. **Do not invent proportions from primitives** — that is what
  overcrowds layouts and fails preflight. See `blocks/README.md` for the index,
  shared token choices, and the content budget. The archetype fixes the *structure*;
  the blocks supply well-proportioned *parts* — neither is a copy-swap template.
- **Respect the content budget** (`blocks/README.md`): headline 4–8 words /
  `max_lines(2)`, body 12–25 words / `max_lines(3)`, benefit title ≤4 words,
  benefit description ≤12 words; one CTA per section; never more than 3 benefits in
  a row, and never 3 across on a portrait page. If content exceeds the budget, drop
  it or stack vertically — never shrink type or cram more in.
- **Structure with auto-layout**, not hand coordinates, whenever spacing should be
  systematic. A vertical `al(v, x(s), g(…), pad(…))` stack for content; a
  horizontal `al(h, x(c), y(c), …)` for buttons and proof rows.
- **One clear message, one CTA, generous margins.** Keep text off the edges.
- **Distribute the canvas — no dead bands.** The root artboard is fixed-height
  (`s(fill,fill)`), so claim the vertical space: put the focal block in a
  `fill`-height region that centers it (`main al(v, x(s), y(c), …) s(W,fill)`) with a
  hug header above and a hug footer below — the region absorbs the slack so header
  pins top, footer bottom, content centers. Use `y(sb)` ONLY for two anchored blocks;
  with 3+ light regions it scatters into dead bands. Never start-stack everything and
  leave the bottom empty, and never add an empty spacer frame. See
  `knowledge/design/foundations` (Distribute the canvas).
- **Text**: `hug` height for anything that can vary, `wrap_text(true)` on body and
  long headlines, `max_lines(…)` so overflow is caught early, boxes **wide enough**
  for the real copy. Headlines tight (`lh 1.05–1.15`), body relaxed (`1.3–1.45`).
- **Center a label in a button/chip/circle** by adding `align(center)` to the text
  and a hug height: `... text "Book a Demo" s(fill,hug) style($type.cta) align(center)`,
  inside a both-axes-centered container `al(h, x(c), y(c), …)`. `align(center)`
  centers the glyph horizontally; never use a hug WIDTH for this (it trips `LUMV0902`).
  `style($type.x)` carries no alignment, so always pair it with `align(...)` when
  the text must be centered.
- **Step the hero size to the surface (one element must dominate).** `$type.headline`
  bakes in 56pt, tuned for A4 — keep it on A4/postcard. A large canvas is much bigger, so
  the same 56 won't dominate and the headline ends up rivaling a `$type.stat` (48). Keep the
  role for weight/color but step the SIZE with a token: `style($type.headline)
  font_size($type.size.6xl)` (64) on a landscape flyer, `font_size($type.size.7xl)` (80) on
  a 1080² square. Steps run `$type.size.xs`(12)…`9xl`(128); the size is fixed (no
  auto-scaling — editor-safe). The hero should read visibly larger than any stat/secondary
  value (squint test: one thing dominates). See `knowledge/design/foundations`.
- **Width inside a padded container: use `fill`, don't hand-compute.** A text or
  child box inside a frame with `pad(P)` has only `parentWidth − 2·P` available, so
  a hand-typed fixed width (e.g. `s(467,…)` inside a `s(499,…) pad(24)` card → only
  451 available) overflows the padding and wraps wrong. Give such text `s(fill,hug)`
  and let the layout size it to the real available width.
- **Slotted text reserves its worst case.** A slot-bound text node is fit-checked
  against its `worst_case` fixture, so give it `wrap_text(true)` + a realistic
  `max_lines(N)` and a `hug` height (the engine reserves the wrapped worst-case
  height). Set `sample`/`worst_case` to real-length copy; if the worst case can't
  fit in `max_lines`, raise `max_lines` or widen the box — don't shrink the font.
- **Backgrounds** belong on the container frame's `fill(...)`, not a separate rect.
  For export-safe pages, put the background on a clipped root `artboard` frame
  with `fill(...)`. Do not put `background(...)` on a `page ...` creation line,
  and do not draw a loose oversized `bg` rectangle.
- **Imagery decision, every turn.** Make an explicit imagery call — kit asset,
  generate, or deliberately none — and record it (`skills/brand-imagery`; whether the
  surface earns one: `knowledge/images/decide`). Kit-first: read the card's `images`
  inventory and `view()` candidates before generating. Place by filling a frame with
  `fit:cover` + a focal point (aspect from the frame, never stretched). When text sits
  over an image, emit a scrim BENEATH the text — a `r`/`fr` with
  `fill($surface.inverse) o($opacity.scrim)` and light `$text.inverse` text — or move
  the text onto its own surface. See `knowledge/images/placement`.
- **Surface treatments & effects are normal vocabulary, not decoration.** A
  brand-derived gradient field (`fill(linear(angle, stop($c1,0), stop($c2,1)))`),
  a soft radial wash (`fill(radial(...))` on a full-frame rect, or an off-canvas
  shape tagged `bleed(true)` — the minimal-luxury look), a gradient text fill (and,
  on a dark field, a `glow(...)`) on a hero numeral, a shadowed plate lifting a stat
  or emblem (`shadow(...)`), an inset well (`inner_shadow(...)`), a blurred backdrop
  orb (`blur(...)`) — all are first-class moves. Derive the colors from the brand (never a stock blue→purple), keep them
  tokenized in branded designs, and let the archetype tell you which treatment
  suits it. Exact grammar: `skills/effects` (incl. the soft-wash recipe).
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

## Skeleton — one of six

Below is the **vertical-poster** archetype: fixed-height root, hug header pinned
top, a **`fill`-height `main` that centers the focal block**, hug footer pushed to
the bottom — no dead bands. It is ONE of the six canon skeletons; the other five
(split-panel, numeral-hero, image-hero, banded, emblem) live in
`knowledge/design/layout-recipes`, each mechanically validated. Pick by the brief,
not by habit.

```text
page linkedin_square size(1080,1080,px)
  artboard al(v, x(s), y(s), g(40), pad(96)) p(0,0) s(fill,fill) fill($surface.page) clip(true)
    header al(h, x(s), y(c), g(12), pad(0)) p(0,0) s(888,hug)
      logo text "Insight Health" p(0,0) s(400,hug) style($type.label) wrap_text(true) max_lines(1) slot(account.name)
    main al(v, x(s), y(c), g(20), pad(0)) p(0,0) s(888,fill)
      kicker   text "PRODUCT LAUNCH" p(0,0) s(888,hug) style($type.eyebrow) wrap_text(true) max_lines(1) slot(campaign.eyebrow)
      headline text "Answer every call." p(0,0) s(888,hug) style($type.headline) font_size($type.size.7xl) lh(1.04) wrap_text(true) max_lines(2) slot(campaign.headline)
      body     text "Insight Health answers, qualifies, and books visits for your front desk." p(0,0) s(820,hug) style($type.body) lh(1.4) wrap_text(true) max_lines(3) slot(offer.primary_message)
    footer al(h, x(sb), y(c), g(16), pad(0)) p(0,0) s(888,hug)
      cta al(h, x(c), y(c), pad(18,36)) p(0,0) s(300,72) fill($surface.brand) rd($radius.button)
        cta_text text "Book a Demo" p(0,0) s(fill,hug) align(center) style($type.cta) max_lines(1) slot(campaign.cta)
      url text "insighthealth.ai" p(0,0) s(320,hug) style($type.caption) align(right) wrap_text(true) max_lines(1) slot(account.url)
  #slot:account.name sample("Insight Health") worst_case("Insight Health Systems")
  #slot:campaign.eyebrow sample("PRODUCT LAUNCH") worst_case("PRODUCT LAUNCH")
  #slot:campaign.headline sample("Answer every call.") worst_case("Answer every call.")
  #slot:offer.primary_message sample("Insight Health answers, qualifies, and books visits for your front desk.") worst_case("Insight Health answers, qualifies, and books visits for your front desk.")
  #slot:campaign.cta sample("Book a Demo") worst_case("Book a Demo")
  #slot:account.url sample("insighthealth.ai") worst_case("insighthealth.ai")
```

## Finish

Return **DSL only** (no fences/prose). Then the coordinator compiles it. If
anything fails, switch to `repair-design` — keep this design's direction and fix
the smallest failing piece.

## Self-check before handing off

- IDs stable, descriptive, unique — DOCUMENT-GLOBAL, across ALL pages: on
  multi-page output (variant concepts), suffix ids per page
  (`headline_a`/`headline_b`); a repeated id rejects the whole block (LUMD0401).
  Two-space indentation. Leaf nodes childless.
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
