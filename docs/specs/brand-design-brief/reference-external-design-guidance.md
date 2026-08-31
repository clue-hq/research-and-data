# Design Guidance

Your design training carries most of this — hierarchy, balance, proportion, typography. This skill fills in what's specific to our editor, our brands, and our asset formats.

Assets span pages, slide decks, emails, ads, and one-pagers. Most examples use page grammar; asset-specific sections are labeled.

## Anchor in brand characterization

Before building, characterize the brand in 2–3 words — the shorthand a creative director would use ("commanding minimalism with surgical color", "warm practical confidence with handcrafted detail", "clinical precision with data-first hierarchy", "energetic editorial with bold type as image"). Every spacing, color, and imagery decision flows from this anchor. If swapping the logo would let the section fit any company's site, the anchor isn't showing up — push palette allocation, scale, and spacing until it does.

Squint at every section before shipping. Blur the text and name: weight balanced or lopsided? hierarchy dominant or competing? alignment shared or ragged? color 1–2 intentional moments or scattered? Squint-test failures are load-bearing — fix before refining details.

## The Brand

The Creative Brief is the personality. The tokens are the vocabulary. Rules below each block describe how to USE them.

**Company:** insighthealth.ai

### Creative Brief

### Brand Character
Calm, clinical, and optimistic — a healthcare-tech voice that pairs trustworthy navy ink with a single energetic mint accent on a warm cream canvas. Restrained scale, generous whitespace, soft-rounded shapes.

### Chromatic Brand Moment
A vivid mint-green pill-card (≈ #1fd39a) standing out as the "popular" tier within a row of cream cards on warm off-white — the saturated mint block surrounded by quiet cream is the brand's signature chromatic punch.

### Signature Compositions
- **[STRONG]** Mint-green (≈ #1fd39a) soft-glow pill buttons with a faint outer halo, used as primary CTAs (segments 1, 2, 3).
- **[STRONG]** Pricing/tier row of 4 rounded cards where exactly one card flips from cream-with-mint-text to saturated mint-fill with white type (segment 3) — the flagship chromatic moment.
- **[STRONG]** Subtle mint accent system: mint check-marks, mint 5-star row, mint tag chip ("DEVELOPED BY DOCTORS" on pale mint ≈ #d6f7ea), mint logo-mark tile (segments 1, 3).
- **[SINGLE]** Anchor composition pairing oversized navy headline (left) with a full-bleed clinician photograph (right) overlaid by a floating white rounded label card ("Scribe / AI AGENT") (segment 1).
- **[SINGLE]** Product-UI mock: white rounded panel containing chat bubbles, an audio-waveform strip in mint, and a mint brain glyph — primitives composed into a simulated agent interface (segment 1).

### Palette Application
- Warm cream off-white (≈ #fdf8ec) — **canvas** across all segments.
- Deep navy (≈ #14213d) — **ink** for headlines/body; **closing-surface** scope: only the slim top announcement bar.
- Vivid mint green (≈ #1fd39a) — **accent-punctuation** (buttons, checks, stars, links, highlighted tier text); **tinted-card** (the one saturated pricing card); **motif** (logo-mark tile).
- Pale mint (≈ #d6f7ea) — **tinted-card** (small pill chip fill).
- White (≈ #ffffff) — **tinted-card** (pricing cards, product-UI mock surface, floating labels).
- Muted slate-grey (≈ #6b7280) — secondary **ink** for body copy and struck-through prices.

### Background Rhythm
Sequence: thin navy bar (≈ #14213d) → warm cream (≈ #fdf8ec) → cream → cream → cream. Ratio ≈ 1 navy sliver : 20 cream. Anchor = cream canvas with photographic right-half and floating white UI card; closing = cream canvas (single-canvas brand — differentiation is compositional, not chromatic). The mint pricing card is the page's chromatic peak, not a section background.

### Typographic Posture
Mixed-case throughout, sentence-style headlines, restrained-to-substantial scale (large but never edge-bleeding). Repeating pattern: navy headline paired with a mint-colored sub-label or price (two-color split: navy heading + mint numeric/keyword). Small uppercase tracked labels appear sparingly inside chips ("DEVELOPED BY DOCTORS", "POPULAR"). No terminal-period or italic-accent motif observed.

### Imagery Posture
Photography-led + product-UI-heavy. Imagery slots observed: (1) full-bleed clinician portrait at the anchor — **full-bleed creative content**; (2) chat/waveform agent interface — **product-UI mock** composed from primitives; (3) circular testimonial headshot — **full-bleed creative content** in a rounded frame; (4) small monochrome compliance badges (HIPAA, SOC2) — **labeled content card**. Imagery is conspicuously absent from pricing and mid-page trust copy, which lean type-only.

### Constraints
- Mint green is the sole saturated color — use it for CTAs, checks, highlight chips, and at most one saturated tinted-card per composition; do not introduce a second competing accent hue.
- Navy lives only as ink and the slim top announcement strip; never use navy as a full mid-page section background.
- Pricing/tier compositions must single out exactly one card with the saturated mint fill; the others remain white-on-cream — the contrast is the signature.
- Never flatten the mint logo-tile + navy wordmark lockup to a single color.
- Canvas is uniformly warm cream; do not stack a pure-white section against cream without a card boundary (cards are white, sections are cream).

**The brief is the spec.** When any rule in this skill conflicts with an explicit brief directive, the brief wins. Rules below are defaults for when the brief is silent. Read the brief, characterize the brand in 2-3 words, then translate directives literally: "white / neutral / light" = `bg-light`, "dark" = `bg-dark`, "brand-colored / accent" = `bg-primary` or `bg-secondary`. If the brief calls for hero decoration (gradients, shapes, atmospheric photography), build it. If it bans a treatment, don't reintroduce it.

**Use the brief's Component Recipes verbatim** (when provided). If the brief gives an exact className for a pill, card, stat, or CTA band, use it — don't invent a new shape. The recipes came from the brand's actual site.

**Signature Moment.** The brief may identify ONE section per page where the brand goes bigger than its variants — stadium-scale headline, 128px hero number, oversized editorial display. In that ONE designated section, you may use the concrete `text-[...]` class the brief provides. Strict variant discipline everywhere else. If the brief says "no signature scale," stay within variants throughout.

### Palette

**Colors** (use as `bg-{token}`, `text-{token}`, `border-{token}`):
- **primary**: #30d8a7 (Primary)
- **secondary**: #139e85 (Secondary)
- **tertiary**: #231d40 (Tertiary)
- **dark**: #231d40 (Dark)
- **light**: #fffcf4 (Light)
- **mint-highlight**: #93ffdf (Mint Highlight)
- **soft-lavender**: #a8a8f9 (Soft Lavender)
- **white**: #ffffff (White)

**Only these colors.** Every color decision comes from the palette above. Forbidden patterns:
- Tailwind color scales (`red-500`, `blue-600`, `gray-200`).
- Arbitrary hex (`bg-[#FF0000]`).
- CSS color names (`bg-red`, `text-white`).
- Invented token names that look palette-like but aren't above (`text-light-purple-accent`, `bg-warm-beige`). If it's not in the Palette list, it doesn't exist.

Opacity on palette tokens (`bg-primary/10`, `border-dark/10`) is allowed — but tinted brand colors are still brand color, not neutral. Apply tints consistently across siblings.

**Color as hierarchy.** Defer to the Creative Brief's Background Rhythm when given. Otherwise: most sections are neutral (`bg-light` or `bg-dark`); brand-colored backgrounds are moments the characterization calls for — zero-to-one for restrained brands, two-to-four for heavy-brand-color identities. Within a section, brand color lives on small surfaces (button fills, icon color, accent text, borders) — punctuation, not volume. When elements repeat in a set, they share one background treatment.

**Contrast.** Dark bg → `text-light`. Light bg → `text-dark` (or omit). Set text color at the container level so children inherit. A `bg-white` card inside a dark section needs its own `text-dark`.

**Image backgrounds require a scrim** (see `node-architecture` Scrim pattern for the exact node structure). Prefer solid backgrounds for text-heavy sections — use a split layout if you'd put a paragraph over a photo.

### Text Variants

**Text Variants:**
- **body**: text-xl font-normal leading-[28px]
- **heading1**: text-[51.2px] font-normal leading-[61.44px]
- **heading2**: text-5xl font-normal leading-[57.6px]
- **heading3**: text-[32px] font-semibold leading-[38.4px]
- **heading4**: text-xl font-semibold leading-6
- **overline**: text-sm font-semibold leading-[22.4px] tracking-wider

**Typography comes from variants.** The theme owns font-family, size, weight, and line-height. Differentiate by switching variants, not restyling. Override only color (`text-primary`, `text-dark`), tracking (`tracking-tight`), alignment, case (`uppercase`), and decoration (`underline`) via className — not family, size, or weight (not on quotes, pull-quotes, callouts, or wordmarks).

**Permitted escapes:** inline semantic emphasis (`font-semibold` or `italic` on a `<span>` inside running copy) and the brief's ONE designated Signature Moment, which may use `text-[Xpx]` to reach stadium/display scale.

### Button Variants

**Button Variants:**
- **primary**: bg: bg-[#30d8a7], text: text-[#231d40], padding: py-3 px-6, radius: rounded-full, border: border-0
- **secondary**: bg: bg-transparent, text: text-[#139e85], padding: py-3 px-6, radius: rounded-full, border: border border-[#139e85]
- **link**: text: text-[#139e85]

**The button is a brand-identity component, not a raw UI primitive.** Its shape AND its color — padding, corner radius, border, font weight, bg, text — carry the brand the same way the wordmark does. A primary button from one brand should never be mistakable for another's. The Button Variants block above shows the brand's actual `radius`, `padding`, `border`, `bg`, and `text` values — trust them. Adding `rounded-full`, `rounded-xl`, `rounded-none`, `px-*`, `py-*`, `border-*`, `bg-*`, or `text-*` classes installs a different brand on top of theirs, even when your instinct says it looks better.

**Color overrides are a last resort, not a first move.** The default placement is to choose a section background the variant's own colors work against. Before overriding, ask: is there a primary/secondary pairing that reads against this section without any className? Usually yes — that's the correct answer. Reach for an override only when (a) the section background is fixed by the composition (hero with `backgroundSrc`, brand-colored band that must stay that color for the palette rhythm) AND (b) neither primary nor secondary works as-is. Then override `bg-*` and `text-*` with palette tokens only — e.g., `variant: "primary", className: "bg-light text-primary"` inverts colors for placement on a `bg-primary` section while inheriting the variant's shape. Never recolor a button to "add visual interest" or match an accent that isn't the brand's button color.

`variant: "link"` is bare text and takes freer styling — size, weight, underline, tracking can shift to fit the surrounding copy or editorial tone. Use it for inline navigation ("learn more", footer links) or when the brief calls for editorial / luxury restraint.

`variant: "custom"` is reserved for interactive-component triggers (tab buttons, disclosure triggers) — do NOT use it for standard CTAs or to fabricate a new button shape. Primary actions use `primary` or `secondary`.

### Fonts & Logos

**Fonts:** aeonik (Aeonik)

**Logos:**
- **light**: https://d2i6q9oka8sm2q.cloudfront.net/companies/a82a47e2-2a0d-42a0-a1a6-60ae2f707d1e/public_content/assets/logo.8aa1fef3fed0509448eeae2b088ab507.png
- **dark**: https://d2i6q9oka8sm2q.cloudfront.net/companies/a82a47e2-2a0d-42a0-a1a6-60ae2f707d1e/public_content/assets/logo.b26ea8c27e36258f3c6f5cd06ed1ddf5.png

Logo variant matches the section background — light-variant on dark sections, dark-variant on light. If the matching variant isn't available, move the section to a background where the available logo reads.

### Adherence priority
1. User's explicit request
2. Creative Brief (follow literally when not overridden by #1)
3. Theme tokens and variants above
4. Design Cognition instincts

When the user conflicts with #2–4, comply and briefly flag the deviation.

## Visual Composition — editor specifics

**Hierarchy per asset.** One dominant headline per section. Primary CTA: **pages** one per section (pricing tiers / feature comparisons have one per peer); **emails** one per email; **ads** one per asset; **slide decks** at most one closing-slide CTA, no inline CTAs in content slides.

**Text budget within symmetric grids.** Side-by-side headings max 1-line variance at `lg:`; 3-column heading variance ≤ 25%; body in < 300px cols is 2–3 sentences max. If a heading exceeds its column budget, rewrite before styling.

**Composition vocabulary by page type.** Pick one, apply consistently — don't force variety where content demands symmetry (pricing tiers, feature comparisons, case-study cards repeat by design). But when content is varied across sections — multiple distinct feature sections, multi-step narrative — vary the composition to match. Two adjacent identical grids reads as templated.
- **Landing:** centered statement, asymmetric split, editorial stack, proof strip, comparison block, full-bleed hero.
- **Long-form / editorial:** article body with pull quotes, full-bleed photo breaks, quote-forward.
- **Gallery / portfolio:** uniform grid, masonry, project-card stack.
- **Data-dense:** stat walls, tables, charts, timeline.

### Micro-composition relationships

The space BETWEEN elements carries design intent as much as the elements themselves. Decide the relationship before picking a gap value — the class follows the intent, not the reverse.

- **Caption-to-element.** A caption sits close enough to read as a pair, far enough that the dominant element breathes. Under a hero metric, oversized number, or iconography: use a reading gap (small but clearly intentional), never cramped. If the caption visually touches the element, the pair looks broken.

- **Horizontal budget in nav and CTA rows.** Navs hold logo + links + CTA pair within a fixed horizontal width. Before building, sum the parts — if four links + two CTAs press against the logo at typical desktop widths, the row will wrap. Fix at source: `shrink-0` on the logo, fewer middle links, or tighter CTAs. A nav that wraps to two lines reads as broken regardless of content.

- **Spotlight-box padding proportional to scale.** An accent or spotlight box (color band, callout, feature spotlight) needs internal padding that matches the scale of the text inside. Display-scale headlines in tight padding look cramped; body copy in dramatic padding looks lost. Match density to the longest line.

- **Editorial placement breathes.** Pull quotes, taglines, and brand-moment headlines need space on at least one side to punctuate. Flush against dense copy, they read as body text pretending to be oversized.

### Image Rendering

**Flex container safety.** Never place an image directly as a flex child without a sized wrapper.
- **`flex-col`**: wrap in a container with height or aspect ratio (`aspect-video`, `h-64`, `max-w-sm`). Image fills the wrapper. For unwrapped images in flex-col (logos, icons), see the image row of `node-architecture` — the flex-col stretch rule is the canonical source.
- **`flex-row`**: wrapper gets `flex-1` or fixed width; add `shrink-0` if it should hold its size.

**Split layouts require peer column containers.** A split is `flex-col lg:flex-row` with exactly **two peer columns** — text in one, media in the other. Flipping `lg:flex-row` on a parent whose children are heading + body + image as flat siblings produces an N-way row. When editing an existing section, identify the family first — "add an image to a stacked hero" usually means "insert within the stack," not "convert to split."

**Sibling consistency.** In a row of cards, `object-fit` is a row-level decision — one treatment per sibling, even when image content differs. If one card's heading wraps, rewrite to match siblings — don't `min-h-` the short ones.

Common patterns (adapt corner-radius and shadow to the brand):
- **Card image**: `aspect-video overflow-hidden` + `w-full h-full object-cover`.
- **Split column**: `flex-1 overflow-hidden` + `w-full h-full object-cover`.
- **Product screenshot**: `max-w-lg mx-auto` + `w-full h-auto`.
- **Avatar**: `w-12 h-12 rounded-full overflow-hidden shrink-0` + `w-full h-full object-cover`.
- **Full-width banner**: `relative w-full aspect-[21/9] overflow-hidden` + `w-full h-full object-cover`.
- **Editorial portrait**: `max-w-md`, no radius/shadow + `w-full h-auto`.
- **Gallery tile**: `aspect-square overflow-hidden` + `w-full h-full object-cover`.
- **Full-bleed ground**: outer `relative overflow-hidden`; image `absolute inset-0 w-full h-full object-cover`; content sibling `relative z-10`; scrim overlay if light text over mixed-value imagery.

### Composable Primitives

When a section's content calls for a concrete thing the library can't supply — a product UI, a flow diagram, a stat wall, a terminal block, a timeline — compose it from Tailwind primitives. The primitive represents the *content*, not decoration around it.

- **Product-UI-led** → compose the UI (chat cards, dashboard scaffolds, terminal blocks, input surfaces with chips).
- **Diagram-led** → for a simple 2–3 node box-and-arrow, compose it from Tailwind (pill-chips + connector lines + state indicators). For anything richer — smooth connectors, charts, flows, org/tree diagrams, or animation — build an SVG custom component instead; load the `svg-and-motion` skill (it owns the @visx/motion/gsap toolkit and the transform/SSR rules; not defined here).
- **Data-dense** → compose stat walls, tables, charts, timelines from layout primitives.
- **Photography-led** → either (a) designate a bordered placeholder frame with aspect ratio and a single image-intent affordance, or (b) lead with type and omit the slot.

**Decorative geometry belongs to the brand, not to every section.** Floating blobs, scattered circles or orbs, gradient meshes, abstract shape motifs, ray-bursts, spectral arcs — only compose these when the brand's characterization explicitly does them (you'd see the same treatment on the brand's real site). Absence of imagery is not a cue to reach for shapes; restraint — more negative space, bigger type, a single typographic anchor — is the better fallback. Scattered decorative shapes across a page are the clearest AI-slop tell.

Apply primitives as a **system** across the asset — all chat cards in the hero, all stat cards in the "by the numbers" section. Don't scatter one of each across the page. Adapt classNames to the brand's palette and corner-radius language.

Anchors for the non-obvious cases:
- **Stat card**: dominant number + quiet caption, caption spaced with a reading gap (tight gaps cramp the pair), optional single-axis accent rule. Example: `flex flex-col gap-3 p-6 border-l-2 border-primary` — adapt rule treatment to the brand. For a stat WALL, grid these.
- **Stat-numeric accent color.** When the brief names an accent-color treatment for stat numerics as a signature — e.g., "cyan stat numerics on dark navy," "teal numerics on black," "orange numerics against cream" — the numeric element MUST carry that color inline as its `text-*` class. The numeric IS the signature on these brands; a white/dark stat number weakens the brand to generic SaaS even when the surrounding composition is correct.

For standard primitives (chat cards, dashboards, terminals, code blocks, quote blocks, timelines, callouts, keyboard shortcuts, bar charts), compose from Tailwind directly — stay within the brand's palette tokens, apply consistently within a section.

A composed primitive carries brand signal; a labeled placeholder rectangle does not. Reach for `PLACEHOLDER:{...}` tokens only when the slot specifically demands a photographic substrate that primitives can't approximate, and never use external placeholder services (`placehold.co` etc.) that render text labels inside the tile.

### Logo Discipline

Every logo image requires an explicit `h-X` class — without one, logos render at source pixel size and look broken. Logos are pixel images with inherent colors — a dark logo on a dark background is invisible and no CSS class will fix it. Uniform height within a set (nav `h-7`–`h-8` with `shrink-0`, trust strips `h-8`–`h-10`, footer/inline `h-6`, hero larger). Trust strips are a B2B/SaaS convention — luxury, editorial, consumer, and nonprofit brands typically skip them.

**Logo alignment in columns.** A logo in a footer left-column usually wants to hug the left edge. Two things can accidentally center it:
- A plain parent with `text-center` (inline images respect text-align) — use a flex parent or add `block` to the logo.
- A flex parent with `items-center` (all children center cross-axis) — add `self-start` to the logo, or switch the parent to `items-start` if all children should left-align.

## Slide Decks

For slide decks (presentations, pitch decks, board decks, sales decks): load the `slide-decks` skill. It owns the slide-deck render mode activation, fixed 16:9 canvas, slide-type repertoire, projection-appropriate type/spacing scale, title grammar parallelism, AI-isms to avoid, and viewer keyboard shortcuts. Composition rules for slide decks are NOT defined here.

## Email & Ad Composition

**Emails:** single-column, ~600px width, mostly mobile. One primary CTA per email. Scannable — short paragraphs (≤ 3 lines), visual breaks between sections.

**Ads:** one composition, fixed aspect. One action per asset. Bold, oversized typography for thumb-scroll. 3–8 words on the visual, up to 20 in the copy slot. Brand mark present, not dominant.

## Responsive (pages)

Two breakpoints only. Slides are fixed-aspect, emails have their own model, ads are single-composition.

- **Base** (no prefix): mobile (<1024px)
- **lg:** desktop (≥1024px)

**Only `lg:` is supported** — never `sm:`, `md:`, `xl:`, `2xl:`.

Common patterns: `gap-4 lg:gap-8`, `grid-cols-1 lg:grid-cols-3`, `flex-col lg:flex-row`, `px-4 lg:px-8 py-6 lg:py-12`, `hidden lg:block`/`lg:hidden`. Source order IS mobile stacking order — after stacking, re-read top-to-bottom: most important content first? Does the primary CTA land before scrolling past feature cards? Fix at source order, not by hiding content.

## Tailwind class names

We're on Tailwind v4. A handful of legacy v3 names no longer exist as utilities; the wrong name produces no CSS rule and silently does nothing — often making content invisible (e.g. a missing `blur` reset leaves a parent's blur applied to your text). Don't reach for these from muscle memory:

- ❌ `blur-0` → ✅ `blur-none`
- ❌ `flex-shrink-0` / `flex-shrink` → ✅ `shrink-0` / `shrink`
- ❌ `flex-grow-0` / `flex-grow` → ✅ `grow-0` / `grow`
- ❌ `decoration-slice` / `decoration-clone` → ✅ `box-decoration-slice` / `box-decoration-clone`
- ❌ `overflow-ellipsis` → ✅ `text-ellipsis`

More broadly: if a utility doesn't seem to be doing anything visually, suspect a renamed or non-existent class before adding more CSS on top.

## Image Selection

Defer to the brief's Imagery Posture. Text-forward brands get fewer images; imagery-heavy brands need them on most sections. If the posture says "text-only" for a section type, omit the section entirely rather than render a decorative placeholder. When a library search returns no suitable asset and the brief supports typographic / UI-compose aesthetics, fall back to Composable Primitives — not before you've actually searched.

When you need imagery: use real library images first. If none match, **prefer a composed primitive that carries the intended imagery category** (see Composable Primitives). Only use `PLACEHOLDER:{width}x{height}:{description}:{background}` tokens when the slot specifically requires a photographic substrate and a primitive won't approximate it. Never use external placeholder services that render text labels in-tile. Never render a grid of placeholder logos.

**Fake data:** when generating illustrative data (pricing, comparisons), flag in chat that it must be verified.

## Final QA

Render the asset mentally. Pass the squint test. Then:

- **Characterization recheck.** Re-read your 2–3 word anchor. Point at one concrete element that would ONLY make sense for THIS characterization. If you can't, brand expression is too generic — revise before shipping.
- **Contrast.** Trace every bg → text chain. Sections with `backgroundSrc`: confirm scrim child exists. Check logos — dark logo on dark section is invisible.
- **Fit.** Text lengths fit. Images fill containers. Grids complete without orphans. Mobile stacking puts most important first.