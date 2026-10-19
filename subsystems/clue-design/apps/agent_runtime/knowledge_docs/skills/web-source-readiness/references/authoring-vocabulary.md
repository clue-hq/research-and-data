# Typed website authoring reference

Read before using `author_web_page`, `author_web_subtree`, or the vocabulary
lane of a repair. This grammar applies to newly authored typed content; do
not use its layout defaults to restyle healthy captured sections. A typed
WebDoc rendered by React is platform output, not recovered original React.

You author **one complete page per call** to `author_web_page(html, custom_css?)`.
The markup is parsed into a typed tree; **any error rejects the whole batch and
nothing is stored** — you then repair with `patch_web_page` (see Repairing
below), not by re-drafting. Warnings do not block, but they are work: resolve
each one or explicitly justify it in your report — never carry one silently.
A result's separate `advice` entries are informational: judge them, act only
where they are right for this page — they are never an obligation, never block,
and never repair work. Advice rides its own key on accepted results AND on
rejections; the `diagnostics` list you repair from never contains it.

## Author once, at structural altitude

The tool call IS the artifact. Build markup once from the active section
records: **Words** supplies the finished copy, **Evidence** its supported
meaning, and **Actions** each label, destination and expected receipt. Carry
resolved wording and actions into the markup instead of inventing a second
story during assembly. If these records are missing, resolve them with
`plan-design` and `conversion-copywriting` before building. Amend the active
record when a fit or evidence problem requires a change. Select only sections
that advance the reader's decision; there is no mandatory homepage section list.

## The vocabulary (everything else is rejected)

| You write | It becomes | Notes |
|---|---|---|
| `<header id="…">` `<section id="…">` `<footer id="…">` | page band | **Top level only.** Always give sections ids (`hero`, `features`) — they are anchors and edit targets. Optional registered-asset background fields are listed below. |
| `<div class="…">` | container | All layout: flex/grid utilities live here. Optional `data-href`, `data-new-tab="true"` makes the whole container clickable. |
| `<h1>`…`<h4>`, `<p>` | text | Variant from the tag. Override with `data-variant="display\|small\|overline"`. |
| `<div data-text="rich" data-variant="body\|small">…</div>` | structured text | One editable text node whose children may be semantic `<p>`, `<ul>`, `<ol>`, and `<li>` blocks. Use it when paragraphs/lists must remain one rich-text field. |
| `<a data-button="primary\|secondary\|outline\|ghost\|link" href="…">Label</a>` | button | Uses resolved theme styling. Preserve source buttons through the repair route when the theme mismatches; avoid arbitrary redesign. |
| `<img data-asset="ASSET_ID" alt="…">` | image | `ASSET_ID` must already exist (generate/import first). External `src` is rejected. Optional `data-href`, `data-new-tab="true"`. |
| `<i data-icon="NAME"></i>` | icon | Must be empty. Size/color via classes (`size-6 text-primary`). |

Sections and containers accept a typed image background:
`data-background-asset="ASSET_ID"` plus optional
`data-background-fit="cover|contain"` and
`data-background-position="center|top|right|bottom|left"`. When text needs
contrast over that image, add
`data-scrim-color="dark|light|primary|accent|black|white"` and
`data-scrim-opacity="0..100"` (default color/opacity: dark/50). The asset must
already be registered. These fields become one renderer-owned layered
background, so the scrim stays behind all child content in editor and export.

A clickable container becomes one semantic link. It may contain ordinary
layout, text, and unlinked images, but **must not** contain another clickable
container, a button/link, a component/embed, a linked image, or inline
`<a href>` text. Move the interactive child outside or keep the container
non-clickable; nested interactive HTML is rejected.

Inline, inside text and button labels only: `strong em u s br a[href]
span[class]` — e.g. accent a phrase with `<span class="text-primary">…</span>`.

Inside a `data-text="rich"` wrapper only, use semantic `p`, `ul`, `ol`, and
`li`. Lists may nest to six levels. The wrapper must use `body` or `small`;
Display/H1–H4/Overline remain a single paragraph. The wrapper becomes the text
node itself, so give it an `id` when later scoped edits need stable identity.
The delivered website preserves only semantic rich-text markup — no editor
attributes.

**Icon names — the COMPLETE set.** `circle dot square diamond triangle-up play
star heart bolt check x plus minus arrow-right arrow-left arrow-up arrow-down
shield lock key user layers pencil sparkles download chart-bar lightbulb`.
There is no globe, envelope, phone, or chevron. An unknown name is a hard
error (LUMW0114) that rejects the WHOLE page — a single guessed icon in a
footer discards every other section you wrote in that call. Use the nearest
name that IS in the set, or drop the icon; never guess one to see if it
exists.

Not in the vocabulary (rejected with hints): `nav button main script
style iframe table`, inline `style=` attributes, event handlers, `aria-*`
(the renderer owns accessibility attributes). `ul`, `ol`, and `li` are valid
only inside a structured-text wrapper; layout lists remain stacked `<div>`s. A
nav is a `<header>` band with text + buttons.

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

**The theme supplies the type ramp and buttons.** An `<h1>` uses the resolved
theme face, size and weight; `data-button="primary"` uses its button treatment.
These may be measured kit values or fallback defaults. Compare resolved values
and loaded font faces with the inspected source before relying on them. A valid
theme default is not proof of brand fidelity. Correct a measured mismatch;
preserve source weights and geometry rather than silently substituting defaults.

**Brand geometry — ten utilities that resolve the kit's shape or fallback.**
Radii, elevations, hairlines and rhythm matter as much as colors. Use the
resolved token when it agrees with the source measurement:

| Class | Resolves | Write it on |
|---|---|---|
| `rounded-button` | `radius.button` | buttons, inputs, chips, small controls |
| `rounded-card` | `radius.card` | cards, panels, media frames, wells |
| `rounded-badge` | `radius.badge` | badges, pills, eyebrow chips |
| `shadow-brand` | `shadow.brand` | the brand's signature elevation (hero card, floating CTA) |
| `shadow-card` | `shadow.card` | a card's resting elevation |
| `border-w-card` | `stroke.width.card` | a card/panel border's WIDTH (pair with a color: `border border-w-card border-border`) |
| `border-w-divider` | `stroke.width.divider` | hairlines and rules between rows |
| `py-section` | `space.section` | a band's vertical padding |
| `gap-stack` | `space.stack.default` | gaps between stacked items and grid cells |
| `p-card` | `space.card.padding` | a card's inner padding |

- **They resolve on every kit.** Missing measurements fall back to platform
  defaults. Check that origin and the rendered result; a flat source does not
  need a default shadow, and fallback spacing must not replace measured spacing.
  Prefer an accurate kit token over an invented number. For a measured mismatch,
  preserve the source treatment through the supported authoring/repair route.
- **`border-w-card`, NOT `border-card`.** `card` is a color token, so
  `border-card` is a border COLOR and will not change any width.
- **`shadow-brand` / `shadow-card` are elevations, not shadow colors.** They set
  the resolved box-shadow, which still needs comparison with the source.
- Everything geometry-shaped with no utility above — horizontal padding
  (`px-6`), max-widths, leading, one-off spacing — stays a raw class. That is
  correct, not a gap.

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
5. **Copy fit.** Review sibling wrapping and narrow-column density in the
   rendered page. Remove repetition through an explicit Words amendment,
   preserving requested wording, supported meaning and proof conditions. If
   necessary explanation cannot fit the source card, derive a source-based
   layout variant; do not delete a capability limit or shrink brand typography
   merely to satisfy a length target.
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
9. **Copy remains grounded.** Do not invent prices, metrics, customer proof
   or comparison claims to fill a layout. A requested illustrative example
   must be clearly identified as illustrative in its context; a caveat only
   in the final report does not make a factual-looking page claim true.

## Page structure and rhythm

For a new typed band, start with the inspected seller grammar. The examples
below are fallbacks when that evidence is absent, not rules for overriding
source container widths, image ratios, surfaces, or responsive composition.

- Example content wrapper: `<div class="mx-auto max-w-[1180px] px-6
  py-section …">` — use `py-section` when its resolved rhythm matches the
  source. A hero may go larger (`py-section md:py-32`) and a
  header stays tight (`py-4`); the horizontal `px-6` and the max-width are raw
  by design. Keep the source's deliberate container relationships; do not impose one width
  when its text, full-bleed media and chrome use different widths.
- When supported by the source, band backgrounds can alternate between `bg-light` and `bg-card` (or a
  `bg-dark`/`text-inverse` statement band). Choose the footer surface from the source, not this example.
- Card grids: `grid gap-stack md:grid-cols-3`, cards `p-card rounded-card
  bg-…`. Add `shadow-card` or `border border-w-card border-border` only when
  supported by the source; a flat card may need neither.
- Badges/pills may use `rounded-badge`; controls may use `rounded-button`.
  Both resolve kit values or defaults, so compare the actual radius with the
  source. A `data-button` already receives the resolved button radius.
- Exactly ONE `h1` (the hero). Heading levels never skip.

## Multi-page sites

A site is one document with many pages. Each page has an id, a name and a route.
The home page's route is `/`. Other routes look like `/pricing` or `/security/soc-2`:
lowercase words joined by dashes, no trailing slash.

- The director creates pages and switches the active page before briefing you.
  You author the active page. Every op you write names its `page_id`.
- `list_pages` tells you which page is active and what routes the others answer
  on. It only reads; the director is who adds, removes and switches pages.
- Link between pages by route: `<a href="/pricing">`. Publishing turns the route
  into the live address.
- Follow the Actions record for destinations, including useful product,
  evidence or informational links off the page. Retention, replacement or
  removal applies to every inherited button, including unslotted ones. A source
  booking CTA does not establish this page's goal. A page may have no primary action.

## Responsive (mobile-first, no scripts)

Base classes are the phone layout; add `md:`/`lg:` for wider. When the selected
shell includes navigation and an action, keep the seller identity and chosen
action usable while the nav-link row collapses. A page without navigation or a
primary action needs neither added. Place target-account identity according to
the section plan, not automatically in the navigation. Stack hero content by
default and verify nothing depends on hover to be reachable.

## Interactive components (Tier 2)

Interactivity is **typed vocabulary, never authored scripts**. Six platform
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
- **calendly embed** — the ONLY embed you may author, and only when the chosen
  action requires scheduling and a real `https://calendly.com/…` destination
  is supplied. A missing destination stays an unresolved dependency; do not
  insert a booking placeholder. The element is empty and needs an
  explicit height class. **A calendly embed inside a dialog is the
  scheduling structure** — dialog owns open/close, the embed owns
  scheduling. Verify the supplied destination and embed before calling the flow
  working. Custom URL/snippet embeds are human-editor territory, never
  authored.

**The escalation ladder — climb reluctantly.** Palette (sections, text,
buttons, images) → platform component → embed → custom component. Take the
FIRST rung that expresses the need; most "interactive" asks are a dialog or an
accordion. When the first three rungs provably cannot express the requirement,
load the `custom-components` skill, record the concrete `ladder_gap`, and use
its durable source → compile → explicit placement workflow. Never fake
interactivity with static markup that pretends to work, and never reach for
custom source merely to avoid composing ordinary typed nodes.

**Separation of concerns (binding).** A platform node owns everything it can:
the dialog owns visibility, backdrop, and close; buttons own triggering. Wire
every CTA that should open the same dialog to the SAME dialog id — never
duplicate a dialog per trigger, never nest a trigger's logic into the
component.

**Real endpoints only.** The recipe's "real links only" extends to endpoints:
never invent a booking URL, form endpoint, or integration. When the selected
action needs one and none was given, record the missing destination and ask for
it. Keep that conversion path incomplete instead of emitting a clickable fake.
An informational page with no booking action needs no scheduling flow.

## Personalization markers (templates & account pages)

A page meant to serve MANY accounts (or authored for one account but derived
for others later) carries markers where content varies per account. Derivation
is deterministic: markers look up the account's value map; an unbound marker
keeps the template content as its fallback. **Markers are load-bearing and
survive derivation — never strip one while editing.**

| You write | Meaning |
|---|---|
| `<span data-var="account.name">Acme Health</span>` | inline variable — inner text is the fallback; derivation swaps the text, keeps the span |
| `<img data-slot="account.logo" data-asset="…" alt="…">` | node slot — derivation swaps the asset; the template's asset is the fallback |
| `<h2 data-slot="account.headline">…</h2>` | text slot — bound text replaces this node's content |
| `<section data-slot-when="account.proof" …>` | presence gate — the whole band is REMOVED when the key is unbound (Section/Container only) |
| `<div data-slot="account.peer_logos"><img …>…</div>` | repeater — a bound List replaces the children with one clone of the FIRST child per item (≤12) |

Rules:
- Keys are `[a-z0-9_.-]`, ≤64 chars. The account namespace: `account.name`,
  `account.domain`, `account.logo`, plus `account.<key>` for the account's
  custom data fields.
- The same slot key on multiple nodes is deliberate multi-placement (the
  logo in header AND footer) — every carrier updates together.
- Fallback content must read as a real, shippable page — a template renders
  as-is when no account is bound; never leave lorem or empty markers.
- The account's own logo is registered with
  `asset(action="use_account_asset")`, then referenced by the returned id.
- On a 1:1 account page (account card in your brief): the account's name
  hardcoded OUTSIDE a marker is a defect — route it through `data-var`.

**Recipe selection:** use the current `campaign-landing-page` skill for
campaign structure and chrome policy; consult the landing-page and ABM recipe
references for the relevant content pattern. The seller owns the visual system;
the target is quoted. Personalization is factual, never inferred. Account
markers alone do not require typed authoring: raw fragment slot values can
carry `{{account.*}}` markers. Attribute-level `data-var` and `data-slot-when`
are the typed lane's distinct capability.

## Imagery

Register before referencing: search and inspect real brand/library assets,
use the appropriate `asset` action, then `<img data-asset="…">`. Generate only
when the brief calls for newly created imagery; never generate replacement
"original" product or customer evidence. Follow the inspected source's image
anatomy, including intentional repeated marks or compound hero imagery; do not
force a single-image rule onto a captured design. Every image gets meaningful
`alt` text. Brand logos use `asset(action="use_brand_asset", asset_id=…)`.

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

**The default repair is `patch_web_page(patches_json)`**, not a resend: submit
a JSON array string of `{old_string, new_string, replace_all?}` patches against your
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
| `web_ops` against a guessed id (`n1`, `hero-2`) | `view("doc")` for top-level section ids; `view("node:<id>")` for complete current-turn fields and child ids; follow exact ids and name a refused read | 50 live rejections were ops on ids that don't exist |
| `<a href="…">See more</a>` at block level | `<a data-button="link" href="…">See more</a>`, or the link inside a `<p>` | bare block-level `<a>` is outside the vocabulary (20 rejections) |
| copy dropped between tags | every word inside `<p>`/`<h1>`–`<h4>`/`<span>` | loose text is an error, not autowrapped (20 rejections) |
| `set_text` on a section/button/component | `view("node:<id>")` to confirm an actual Text node, then the appropriate text operation; preserve rich-text structure using its complete content; the doc summary alone does not expose interior ids | 15 rejections targeted non-text nodes |
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
| LUMW0123 | unknown component name | valid: `dialog accordion marquee nav_menu carousel tabs` |
| LUMW0125/0126 | unknown command / trigger without target | `data-command="show-modal\|close"` + `data-target="<dialog id>"` |
| LUMW0127 | button has both href and data-command | pick one: link or trigger |
| LUMW0018 | command targets a missing/non-dialog node | point `data-target` at a real dialog's id |
| LUMW0132 (warning) | attribute ignored (e.g. `style=`) | express it as utility classes |
| LUMW0124 (warning) | bad component prop value | defaults applied; fix the `data-*` value |
| LUMW0133 | invalid slot/variable key | keys are `[a-z0-9_.-]`, ≤64 chars |
| LUMW0134 | `data-slot-when` on a non-band element | presence gates go on `<section>`/`<div>` only |
| LUMW0306 (advice) | raw radius/shadow step on a kit whose Creative Brief measured its shape | prefer `rounded-button\|card\|badge` / `shadow-brand\|card` where the shape is a brand decision — informational, never blocking |
