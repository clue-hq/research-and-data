---
name: create-website
description: Author a complete branded website page in the constrained-HTML wire format — vocabulary, theme-token class grammar, responsive rules, and how to repair from ingestion diagnostics.
---

# Create a Website Page

You author **one complete page per call** to `author_web_page(html, custom_css?)`.
The markup is parsed into a typed tree; **any error rejects the whole batch and
nothing is stored** — you then repair with `patch_web_page` (see Repairing
below), not by re-drafting. Warnings do not block, but they are work: resolve
each one or explicitly justify it in your report — never carry one silently.

## Author once, at structural altitude

The tool call IS the artifact. Plan the page as structure — "hero, proof
strip, three feature panels, how-it-works, FAQ, CTA band" — and produce the
build call as soon as the structure is decided. Never draft the page's prose
or markup in your reasoning and then transcribe it into the call: that doubles
the cost and the two copies drift. Copy is written once, inside the markup.

## The vocabulary (everything else is rejected)

| You write | It becomes | Notes |
|---|---|---|
| `<header id="…">` `<section id="…">` `<footer id="…">` | page band | **Top level only.** Always give sections ids (`hero`, `features`) — they are anchors and edit targets. |
| `<div class="…">` | container | All layout: flex/grid utilities live here. |
| `<h1>`…`<h4>`, `<p>` | text | Variant from the tag. Override with `data-variant="display\|small\|overline"`. |
| `<a data-button="primary\|secondary\|outline\|ghost\|link" href="…">Label</a>` | button | Button styling comes from the theme — do not restyle with classes. |
| `<img data-asset="ASSET_ID" alt="…">` | image | `ASSET_ID` must already exist (generate/import first). External `src` is rejected. Optional `data-href`, `data-new-tab="true"`. |
| `<i data-icon="NAME"></i>` | icon | Must be empty. Size/color via classes (`size-6 text-primary`). |

Inline, inside text and button labels only: `strong em u s br a[href]
span[class]` — e.g. accent a phrase with `<span class="text-primary">…</span>`.

Icon names: `circle dot square diamond triangle-up play star heart bolt check x
plus minus arrow-right arrow-left arrow-up arrow-down shield lock key user
layers pencil sparkles download chart-bar lightbulb`.

Not in the vocabulary (rejected with hints): `nav ul li button main script
style iframe table`, inline `style=` attributes, event handlers, `aria-*`
(the renderer owns accessibility attributes). Lists are stacked `<div>`s;
a nav is a `<header>` band with text + buttons.

## Class grammar — the brand constraint

**Every color must be a theme token.** Raw values (`bg-[#231d40]`) and stock
Tailwind palettes (`text-slate-900`, `bg-red-500`) are hard errors.

- Semantic tokens, always present: `primary accent dark light card muted
  border inverse` — plus the kit's own names (listed in your brand card) and
  `white black transparent current`.
- Use them anywhere a color goes: `bg-light text-dark border-border
  bg-primary/10 from-primary to-dark text-inverse`.
- Opacity via slash: `bg-primary/15` (integer 0–100).
- Gradients: `bg-linear-to-br from-primary to-dark`, stops like `from-10%` ok.
- Allowed prefixes: `md: lg: hover: focus:` — no `dark:`, and no `sm:`/`xl:`:
  never author a breakpoint the review loop does not look at (375 is the
  base layer, 768 is `md:`, 1440 is covered by `lg:`).
- Non-color arbitrary values are fine: `max-w-[1180px] leading-[1.06]`.

**The theme already styles the type ramp and buttons.** An `<h1>` lands with
the brand's display face, size, and weight with **zero classes**; a
`data-button="primary"` is already the brand CTA. Add classes only for
*deviations*: color accents, spacing, width caps, alignment.

## Design guidance

Your design training carries most of this; these blocks fill in what is
specific to our editor, brands, and formats.

1. **Build against the brand anchor.** The director names the brand in 2–3
   creative-director words (from the brand card) — build every section
   against it. Kill test: if swapping the logo would let a section fit any
   company's site, the anchor isn't showing. The reviewer will be asked to
   point at one element that could ONLY belong to this characterization.
2. **Anti-slop.** Decorative geometry — blobs, orbs, gradient meshes,
   scattered shapes — ONLY when the brand's real presence uses it.
   Scattered decorative shapes are the clearest AI-slop tell. The default
   fallback is restraint: negative space, bigger type, one typographic
   anchor per band.
3. **Composable primitives.** When no imagery fits, compose the CONTENT from
   the vocabulary: a dashboard scaffold, a stat wall, a terminal card, a
   chat exchange — built from containers, text, and utilities. Apply one
   primitive as a system across the page, never one-of-each. Placeholder
   tokens are for photographic substrates only; never a placeholder logo
   grid.
4. **Imagery posture.** Read it from the brief and brand card: text-forward
   brands get fewer, quieter images. When the posture says text-only, OMIT
   the imagery section rather than decorate it.
5. **Copy-fit budgets.** Sibling headings within one line of each other at
   desktop; card copy in a 3-column grid within ~25% length variance; 2–3
   sentences max in a narrow column. **Rewrite the copy before styling
   around it** — long copy is a copy problem, not a layout problem.
6. **Composition menu.** Name the layout of each band before building:
   centered statement, asymmetric split, editorial stack, proof strip,
   comparison block, full-bleed hero. Repeat a composition by design where
   the content is symmetric; vary it where the content varies. Two adjacent
   identical grids read as templated.
7. **Micro-spacing is intent.** Captions sit a reading-gap from their
   subject; sum the header's logo + links + CTA widths BEFORE building (a
   wrapping nav reads broken); spotlight padding scales with its type size;
   editorial elements breathe.
8. **Logo discipline.** Always an explicit height class, uniform per context
   (nav, trust strip, footer). A dark logo on a dark band is invisible — no
   class fixes it; pick the right asset variant. Two accidental-centering
   footguns: `text-center` on a plain parent centers nothing structural;
   `items-center` on a flex parent needs `self-start` on children that must
   not stretch or center.
9. **Fake data is flagged data.** Illustrative pricing, stats, or comparison
   rows must be named for verification in the finalize summary — same
   honesty rule as real links and real endpoints.

## Page structure and rhythm

- Wrap each section's content: `<div class="mx-auto max-w-[1180px] px-6 py-20
  …">` (hero py-24+, header py-4). Keep ONE max-width across the page.
- Band backgrounds alternate between `bg-light` and `bg-card` (or a
  `bg-dark`/`text-inverse` statement band). Footer usually `bg-dark`.
- Card grids: `grid gap-6 md:grid-cols-3`, cards `p-6 rounded-2xl bg-…`.
- Exactly ONE `h1` (the hero). Heading levels never skip.

## Responsive (mobile-first, no scripts)

Base classes are the phone layout; add `md:`/`lg:` for wider. The header
pattern without JS: logo + primary CTA always visible, the nav-link row
`hidden md:flex`. Stack hero content by default, `md:flex-row` when paired
with imagery. Verify nothing depends on hover to be reachable.

## Interactive components (Tier 2)

Interactivity is **typed vocabulary, never authored scripts**. Three platform
components plus command-wired buttons; behavior comes from the platform (native
`<dialog>`/`<details>` + one vetted runtime), so what you author stays a tree.

| You write | It becomes |
|---|---|
| `<div data-component="dialog" id="dlg_book" data-aria-label="Book a call">…</div>` | modal dialog — focus trap, Esc, backdrop close are platform-owned |
| `<div data-component="accordion" data-single-open="true" data-default-open="0">…</div>` | FAQ / drawer accordion (native, zero-JS) |
| `<div data-component="marquee" data-speed="30" data-direction="left">…</div>` | logo-strip marquee (CSS animation; reduced-motion honored) |
| `<a data-button="primary" data-command="show-modal" data-target="dlg_book">Book a call</a>` | trigger button — a command, not a link (**no href**) |
| `<div data-component="nav_menu">…buttons…</div>` | header nav: inline row at `md:`+, hamburger dropdown below (zero-JS) |
| `<div data-component="carousel" data-show-arrows="true" data-autoplay="6">…</div>` | scroll-snap carousel; arrows/autoplay are platform-owned |
| `<div data-component="tabs" data-default-tab="0">…</div>` | accessible tabs — items like accordion items (first child = the tab label) |
| `<div data-embed="calendly" data-url="https://calendly.com/…"></div>` | Calendly scheduling embed (empty element; give it a height class, e.g. `h-[700px]`) |

Contracts:
- **Children are ordinary nodes** — everything inside a component is normal
  vocabulary (divs, text, buttons, images) and stays individually editable.
- **dialog** — hidden until triggered. The close control is platform-supplied;
  do not author one. Put the dialog inside the section that owns its primary
  trigger; `data-target` on every trigger is the dialog's `id`. A dialog's
  content follows the same class grammar as any card.
- **accordion** — each item is a `<div>` whose FIRST child is the summary row
  (typically an `<h3>` or `<p>`) and whose remaining children are the content.
  `data-single-open="true"` makes items exclusive; `data-default-open="0"`
  opens the first item initially.
- **marquee** — author each logo/child ONCE; the seamless-loop duplication is
  automatic. `data-speed` is seconds per loop (5–120).
- A button is a link (`href`) **or** a trigger (`data-command` +
  `data-target`), never both — the parser rejects the combination. Valid
  commands: `show-modal` (open a dialog), `close` (close the one it is in).
- **nav_menu** — children are the nav links (buttons, `ghost`/`link`
  variants) and optional label text. The desktop row and the mobile
  hamburger panel are both platform-rendered from the same children —
  author them ONCE. Put the nav_menu inside the header band next to the
  logo and CTA.
- **carousel** — children are the slides (cards, images); each slide sizes
  itself (`w-72`, `md:w-96`). `data-autoplay` is seconds per step (2–60);
  omit it for a manual carousel. Needs ≥2 slides to be a carousel.
- **tabs** — items exactly like accordion items: each child is a `<div>`
  whose FIRST child is a short Text label (it becomes the tab button) and
  whose remaining children are the panel. `data-default-tab` is the
  0-based initially-open item.
- **calendly embed** — the ONLY embed you may author, and only with a real
  `https://calendly.com/…` link from the brief; none given → the obvious
  placeholder + flag at finalize. The element is empty and needs an
  explicit height class. **A calendly embed inside a dialog is the
  complete book-a-call flow** — dialog owns open/close, the embed owns
  scheduling. Custom URL/snippet embeds are human-editor territory, never
  authored.

**The escalation ladder — climb reluctantly.** Palette (sections, text,
buttons, images) → platform component → embed → custom component. Take the
FIRST rung that expresses the need; most "interactive" asks are a dialog or an
accordion. If no rung can express what the brief truly needs, build the
closest palette approximation and report the gap through the `ladder_gap`
field at finalize — never fake interactivity with static markup that pretends
to work.

**Separation of concerns (binding).** A platform node owns everything it can:
the dialog owns visibility, backdrop, and close; buttons own triggering. Wire
every CTA that should open the same dialog to the SAME dialog id — never
duplicate a dialog per trigger, never nest a trigger's logic into the
component.

**Real endpoints only.** The recipe's "real links only" extends to endpoints:
never invent a booking URL, form endpoint, or integration. When a dialog needs
one and none was given, use an obvious placeholder
(`https://example.com/PLACEHOLDER-booking`), flag it in the finalize summary,
and ask for the real one.

## Imagery

Generate before you reference: use the `asset` tool, then
`<img data-asset="…">`. One hero image at most; never reuse an image twice;
sibling cards use icons OR images uniformly, never a mix. Every image gets
concrete `alt` text. Brand logos come from `use_brand_asset`, never redrawn.

## custom_css (escape hatch, rarely)

Page-level `@keyframes`, mesh-gradient backgrounds, `prefers-reduced-motion`
guards. Plain CSS only — no `@import`, no `</style`, no external URLs.

## Copy

Concrete and scannable; sentence case; no emojis; no em-dashes; never invent
facts, statistics, customers, or testimonials (see the landing-page recipe in
`knowledge_docs/knowledge/web/landing-page.md` — read it before authoring a
landing page).

## Repairing from diagnostics — patch first

Errors void the batch — the stored page is unchanged until your markup is
clean. Each diagnostic carries a code, the offending node id, and a hint.

**The default repair is `patch_web_page(patches)`**, not a resend: submit
targeted `{old_string, new_string, replace_all?}` patches against your
rejected markup and it re-ingests as the same atomic batch. Fix ALL the
diagnostics in ONE patch call (a rejection lists every error — patching one
at a time wastes rounds). `old_string` must match exactly and be unique
(or set `replace_all`). Re-send the complete page via `author_web_page`
only when the fix is structural — reordering sections, rewriting a band —
not for classes, copy, attributes, or ids.

## Patterns that will fail (measured from live runs)

| WRONG | CORRECT | Why |
|---|---|---|
| `text-secondary`, `bg-brand` assumed | only the tokens in THEME TOKENS / your brand card | 153 live rejections came from two invented names (`secondary`, `brand`) — the token set is per-kit; when the lint's hint lists the real tokens, use one, don't retry the invented name |
| `web_ops` against a guessed id (`n1`, `hero-2`) | `view("doc")` first; use ids from it | 50 live rejections were ops on ids that don't exist |
| `<a href="…">See more</a>` at block level | `<a data-button="link" href="…">See more</a>`, or the link inside a `<p>` | bare block-level `<a>` is outside the vocabulary (20 rejections) |
| copy dropped between tags | every word inside `<p>`/`<h1>`–`<h4>`/`<span>` | loose text is an error, not autowrapped (20 rejections) |
| `set_text` on a section/button/component | `set_text` on the Text NODE inside it (view the doc for its id) | 15 rejections targeted non-text nodes |
| `<img data-asset="hero">` before generating | `asset` tool first → use the RETURNED id | referencing unknown assets voids the batch (10 rejections) |
| image inside `flex flex-col` stretching full-width | `self-start` (or an explicit `w-…`) on the image | flex stretch distorts imagery on mobile |
| icon with no size class | explicit `size-5`/`size-6` + a color token | unsized icons render at unpredictable glyph sizes |
| centering an inline image with `text-center` on a `div` | make the parent `flex justify-center`, or `mx-auto` on the image | block images ignore text alignment |

Common diagnostic codes:

| Code | Meaning | Fix |
|---|---|---|
| LUMW0100 | markup does not parse | close every tag, quote every attribute |
| LUMW0102 | non-section at top level | wrap in `<section>` / move inside one |
| LUMW0105 | element outside vocabulary | use the table above |
| LUMW0107/0108 | button href missing/bad scheme | real https/mailto/#anchor/relative |
| LUMW0110/0111 | external or missing image ref | generate/import → `data-asset` |
| LUMW0117 | loose text between elements | wrap copy in `<p>`/headings |
| LUMW0210/0211/0212 | raw hex / stock palette / unknown color | use a theme token (hint names the nearest) |
| LUMW0203 | `sm:`/`xl:` breakpoint | base layer covers 375, `md:` covers 768, `lg:` covers 1440 |
| LUMW0221 | dead Tailwind v3 name (`flex-shrink-*`, `overflow-ellipsis`, …) | the hint names the v4 rename (`shrink-*`, `text-ellipsis`) |
| LUMW0123 | unknown component name | valid: `dialog accordion marquee` |
| LUMW0125/0126 | unknown command / trigger without target | `data-command="show-modal\|close"` + `data-target="<dialog id>"` |
| LUMW0127 | button has both href and data-command | pick one: link or trigger |
| LUMW0018 | command targets a missing/non-dialog node | point `data-target` at a real dialog's id |
| LUMW0132 (warning) | attribute ignored (e.g. `style=`) | express it as utility classes |
| LUMW0124 (warning) | bad component prop value | defaults applied; fix the `data-*` value |
