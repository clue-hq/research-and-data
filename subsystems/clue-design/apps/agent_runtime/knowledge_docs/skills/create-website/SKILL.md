---
name: create-website
description: Author a complete branded website page in the constrained-HTML wire format — vocabulary, theme-token class grammar, responsive rules, and how to repair from ingestion diagnostics.
---

# Create a Website Page

You author **one complete page per call** to `author_web_page(html, custom_css?)`.
The markup is parsed into a typed tree; **any error rejects the whole batch and
nothing is stored** — you then fix the markup and resend the FULL page, not a
fragment. Warnings do not block, but read them: they name real losses.

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
- Allowed prefixes: `sm: md: lg: xl: hover: focus:` — no `dark:`.
- Non-color arbitrary values are fine: `max-w-[1180px] leading-[1.06]`.

**The theme already styles the type ramp and buttons.** An `<h1>` lands with
the brand's display face, size, and weight with **zero classes**; a
`data-button="primary"` is already the brand CTA. Add classes only for
*deviations*: color accents, spacing, width caps, alignment.

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

## Repairing from diagnostics

Errors void the batch — the stored page is unchanged until your markup is
clean. Each diagnostic carries a code, the offending node id, and a hint;
fix ALL of them, then resend the complete page. Common ones:

| Code | Meaning | Fix |
|---|---|---|
| LUMW0100 | markup does not parse | close every tag, quote every attribute |
| LUMW0102 | non-section at top level | wrap in `<section>` / move inside one |
| LUMW0105 | element outside vocabulary | use the table above |
| LUMW0107/0108 | button href missing/bad scheme | real https/mailto/#anchor/relative |
| LUMW0110/0111 | external or missing image ref | generate/import → `data-asset` |
| LUMW0117 | loose text between elements | wrap copy in `<p>`/headings |
| LUMW0210/0211/0212 | raw hex / stock palette / unknown color | use a theme token (hint names the nearest) |
| LUMW0123 | unknown component name | valid: `dialog accordion marquee` |
| LUMW0125/0126 | unknown command / trigger without target | `data-command="show-modal\|close"` + `data-target="<dialog id>"` |
| LUMW0127 | button has both href and data-command | pick one: link or trigger |
| LUMW0018 | command targets a missing/non-dialog node | point `data-target` at a real dialog's id |
| LUMW0132 (warning) | attribute ignored (e.g. `style=`) | express it as utility classes |
| LUMW0124 (warning) | bad component prop value | defaults applied; fix the `data-*` value |
