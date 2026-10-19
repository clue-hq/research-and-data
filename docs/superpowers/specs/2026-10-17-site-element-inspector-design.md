# Site editor: an element inspector like the scene ad editor's — design

Date 2026-10-17. Founder conversation in the trenton session (brainstorming, mockups in
`.superpowers/brainstorm/95737-1792238115/content/`, git-ignored: `site-inspector-panels.html`,
`site-inspector-button.html`). Status: APPROVED by the founder 2026-10-17. Plan status and scope: §7.

## 1. Intent

A marketer editing a microsite in the Puck site editor clicks any element on the canvas — a piece of
text, a button, an image, or a box (a section, a card, a row, a div) — and a panel on the right lets them
style that element directly, the way the scene ad editor's panel does for ad elements. Today they can
only select a whole section and edit its content fields; anything visual means asking the agent, which
costs minutes and money per change.

The founder's words: copy the scene ad editor's inspector "for their counterpart element types in the
site doc … site would have more of a web (html/specific formatting)". Same look, same sections, same
controls, each doing the web version of its ad counterpart.

## 2. What the founder decided

- **Look and structure:** the scene ad editor's inspector (`apps/frontend/src/features/chat-shell/components/image-inspector.tsx`,
  `AdTextInspector`), reused, not redrawn. The mockups were approved ("looks perfect").
- **Element types and their panels** (mockups 1–4):
  - **Text** (heading, paragraph, link text): Typography — Color, Font, Size, Weight, **Bold / Italic /
    Underline**, Alignment (left, centre, right, justify); a Link row; Layers.
  - **Button:** Typography for its label (a Text box plus the same typography rows); Fill; Stroke (colour,
    width, **corner radius**: pill, a number, custom); Layout (padding, width); **Link** (a web address or
    a page on this site; same tab or new tab); Layers.
  - **Container** — any box element, not only cards ("any type of element"): Fill; Stroke (colour, width,
    corner radius); Layout (padding, gap between children, width: fill / fit / fixed); Arrange (move up or
    down among its neighbours; content alignment); Layers. The panel's title names what was clicked
    ("Section", "Card", "Row").
  - **Image:** Replace (the existing asset picker), Fit (fill / fit), Alt text, Stroke with corner radius,
    Layers.
  - **Layers:** a tree of everything inside the section, like the ad's, instead of today's list of sections.
- **Whole box or highlighted words:** if the whole text box is selected, a change applies to the whole box;
  if some words are highlighted, only to those words.
- **Colours:** the brand's colours first (the Theme tab), and the person can pick a custom colour (the
  Custom tab: picker, hex, recent swatches) — exactly the scene ad editor's colour control.
- **Fonts:** the brand's fonts and other fonts.
- **Scope:** sections we draw (brand sections), copied seller sections (clones), the agent's own
  sections, **and the shared header and footer** (founder: "it should work in the header as well").
- **The agent works on the header and footer too.** The founder asked the agent for a header layout change
  and it refused: the shell's layout is fixed in code (`site-kit/src/shell.tsx`; `ShellSchema`,
  `schemas.ts:182`, allows only the words, logo, nav links and one button). "Ideally that should not be
  the case."
- **No hard-coded header or footer** (founder, plan 1 live check, 2026-10-17): "i should be able
  change Prepared for text as well... change the wordings or anything there actually", then "i dont
  want a hardcoded header version… standardised headers could be made and kept but should also be
  acceptable of change from human and agent both here, just like the rest of the site". Standard
  headers and footers exist as templates; the agent picks one and changes or rewrites it; the
  marketer edits words and styling in place like any section. Agent-written header code can still
  use placeholders for the seller's logo, the account's logo and name ("and that header code, should
  allow template placeholders for logo and account name and all even still okay"). This is **plan 6**.
- **Adding a link to plain text is in** (founder: "yes this should also be allowed"): highlighted words,
  or a whole text box, can become a link.
- **Reordering inside copied seller sections is in** (founder: "yes it should be there"), as well as in
  the sections we draw.
- **Quality bar (founder):** every step finished and correct, nothing left half-built, no silent errors;
  small steps are fine.
- **The agent is free to redo it:** if the agent later rewrites a section, it may replace or drop the
  person's manual styling. Manual styling is not protected from the agent.
- **Order of work:** text first, then buttons, then containers (images last — see §7).
- Out of scope for now: the ad panel's Stroke on text, Layout X / Y and Rotation, Arrange front / back
  (they have no web meaning in a flowing page), and vertical alignment (a web text box hugs its text).

## 3. Goals, non-goals, anti-goals

**Goals.** Every change a marketer makes in the panel shows instantly on the canvas, survives a reload,
is one undo step, and looks identical on the published page. The panel works on all three kinds of
section. The agent sees the page as it is, styling included.

**Non-goals.** Reordering, inserting, deleting or duplicating whole sections (item E8, waiting on the
founder's designs, C13). Free CSS editing. Animations. Responsive (per-breakpoint) styling — one value
applies at every width in this version, except font size: since 2026-10-18 a hand-set font size
follows the brand's measured type steps (founder; `2026-10-18-responsive-brand-type-design.md` §3.4).

**Anti-goals (what would make it a failure even if it works).** A style that shows in the editor but not
on the published page, or the reverse. A style change that silently breaks the section (a crash, a lost
inline edit, a clone's DOM rebuilt and its images reloaded). A panel control that looks live but does
nothing. Arbitrary CSS reaching the published page (the sanitizer is not an allow-list; values must be
validated where they are written).

## 4. How it works (the parts decided; my calls are marked)

### 4.1 Element addresses

Today a click resolves only to a section (`site-editor/src/client/dom.ts:38`) and the frame↔app protocol
carries only `componentId` (`site-kit/src/editor-protocol.ts:120-151`). An element needs an address
inside its section that is stable across reloads and is the same in the editor and in the published HTML.

*My call:* every styleable element carries `data-clue-el="<key>"`, with the key unique inside its section:

- **Brand sections** (`site-kit/src/sections.tsx`): our code stamps the key on each heading, body,
  button, card, row, image and the section box, derived from the prop path it draws (`headline`,
  `cards.2`, `cards.2.title`, `button`, `root`).
- **Agent sections:** the agent names what it wants editable. The kit pieces (`kit.Button`, `kit.Card`,
  `kit.Image`, `kit.Link`) take an optional `el` prop that becomes `data-clue-el`, and a plain element the
  agent writes itself carries `data-clue-el="name"`. A kit piece receives values, not prop paths, and an
  inline-edit prop is a plain string on the published page, so keys cannot be derived automatically
  (builder check, 2026-10-17). Elements the agent did not name are not selectable (clicking selects the
  nearest named ancestor, finally the section). The `writing-a-section` skill says how; that skill text is
  shown to the founder before it is written, and it is on the critical path for agent sections only.
- **Clones:** the key is the element's structural path inside the captured fragment (child indices from
  the fragment root, e.g. `0.2.1`), computed from the captured fragment markup (not the filled DOM, so a hidden slot never shifts its
  siblings' keys). Fragment ids are content-addressed, so the markup behind an id cannot change and the
  path is stable.

- **Header and footer:** `kit/shell.tsx` stamps keys on the header box, the "Prepared for" line, the
  logo, each nav link (`nav.0` …), the button, the footer box, the legal line and each footer link.

An element with no key cannot be selected; clicking it selects its nearest keyed ancestor, finally the
section (today's behaviour).

### 4.2 Selection

Selection becomes `(componentId, elementKey | null)`. The frame resolves a click to the nearest
`[data-clue-el]` inside the section (`dom.ts clickIntent`), keeps Puck's own section selection as it is,
and posts an extended `selected` message carrying `elementKey`, the element's kind (text, button,
container, image) and its current computed and stored styles. The app's `select` message gains an
optional `elementKey` so the Layers tree can select an element. The selected element is outlined by hand,
as the shell already is (`data-site-shell-selected`, `editor-app.tsx:104-111`). The `<Puck>` tree must not
re-render on selection (`editor-app.tsx:123-126`), so the outline is a DOM attribute, not React state.

Text highlighting inside an inline-edit or rich-text field reports "N words selected" and switches the
panel's typography rows to act on the highlighted range (§4.4).

### 4.3 Where styles are stored: one validated "edits" layer per section

Today no section has a style prop, by design: every schema is strict and `className` / `style` props are
refused (`site-kit/src/schemas.ts:4-6`, `render-core.tsx:130`), so the agent cannot drift off-brand
through raw CSS.

*My call:* each section in the site document — and the shell's `header` and `footer` — gains one
reserved, optional field, `edits`, a map from
element key to a **style override** with a strict, closed schema in site-kit (no free CSS):

| Property | Values |
|---|---|
| `color`, `fill`, `borderColor` | a brand token name, or a hex colour with an opacity 0–100 |
| `fontFamily` | a brand font family, or a family from the font library (§4.6) |
| `fontSize` | px, 8–200 |
| `fontWeight` | 100–900 in steps of 100 (only weights the family has) |
| `italic`, `underline` | true / false (bold is `fontWeight` 700) |
| `textAlign` | left, center, right, justify |
| `borderWidth`, `radius`, `gap` | px, 0–200; `radius` also `pill` |
| `padding` | px, one value or vertical + horizontal |
| `width` | fill, fit, or a px value |
| `imageFit` | fill, fit |
| `order` | on a container: the order of its children, as a list of their keys (§4.8) |
| `hidden` | on a header or footer element: true hides it (so the agent can drop the logo or a link) |

Text content and links are **not** in `edits`: a button's label and a heading's words stay in the
section's prop or the clone's slot, and a Link edit writes the link that already exists — `buttonHref` /
`linkHref` on brand sections, the link prop on agent sections, the `href` slot or `links` replacement on
clones. One source of truth each, and no attribute is changed after React renders (live pages hydrate, so
a post-render attribute change would break hydration). The Link section's "Open in a new tab" is a new
boolean beside each existing link prop (brand sections) or slot (clones); an agent section offers it only
if it declares one.

The structural brand rule stays for props (still no `className` / `style` props); `edits` is the one
sanctioned place for manual styling, and it is validated where it is written (`site_doc_validate.py` runs
the site-kit validator, which runs the schema). The agent may also write `edits` — the founder ruled it free to redo the person's styling — so `edits`
joins the agent's page-writing contract and its catalog; the agent's skills steer it to brand tokens, and
the validator checks shape, not taste (founder ruling 2026-10-08: judgement belongs to the agent).

### 4.4 Words: rich text

Styling highlighted words needs rich text, which the site layer does not have (item E7). The trial's spike
(`trials/puck-spike/RICHTEXT-R5.md`) proved Puck 0.23's `richtext` field works on our canvas with five
changes on our side, and lists the eight places adoption touches (its "Details 5"). Adopt it as R5
recommends, with one addition: the stored HTML allow-list is `p strong em u s ul ol li br`, **plus `a`** with an `href` in the existing
`link` grammar (`schemas.ts:33-37`; an internal `/route` must be a real page, as `validate.ts:126-131`
already checks) and an optional `data-new-tab` that the render turns into `target="_blank" rel="noopener"`,
**plus `span`
carrying a `data-s` attribute** whose value is a key into the section's `edits` (e.g. `headline~1`), so
highlighted-word colour, font and size go through the same validated override schema and never as inline
`style`. The R5 notes on the menu apply, except that our controls live in the right-hand panel, not in
Puck's inline menu (we still need `renderInlineMenu`'s `editor` handle to apply marks to the range, and
the `data-puck-rte-menu` marker on our panel so a click does not blur the editor — *builder: the panel
lives in the app, outside the frame; prove the range survives a click across the frame boundary, or keep a
minimal in-frame bar for B / I / U and colour*).

**Changed by plan 2 (2026-10-17, ruling R1):** the stored grammar is inline only — `strong em u s br`,
`a` and `span[data-s]`, optionally inside the one outer `<p>` the editor writes (the render drops it).
No `ul ol li` and no second `<p>`: Enter makes a line break. The panel's controls act on the range by
writing the `data-s` span and its `_edits` entry, through the stored text, not through Puck's inline
menu, so no in-frame bar is needed.

Which text is rich: every brand-section text field that is edited in place today, and every agent prop
marked for inline editing. Clone text slots of kind `text` accept the same allow-listed HTML (the clone
filler sets it as sanitized HTML instead of text). Clone text that is not a slot can be styled as a whole
box but not word by word, and cannot become a new link (its Link row shows disabled with a note); an
existing clone link is edited through its `href` slot or `links` replacement.

**Adding a link to text** wraps the highlighted words (or, with the whole box selected, all its words) in
an allow-listed `<a>`. Puck's richtext turns its own link extension off in R5; enabling it, restricted to
the grammar above, is part of this step. Pasted links are filtered to the same grammar.

### 4.5 Applying the styles (editor and published page alike)

One site-kit function turns a section's `edits` into a scoped stylesheet —
`[data-component-id="<id>"] [data-clue-el="<key>"] { … }` and `[data-s="<key>"] { … }` — emitted next to
the section in both the editor frame and the published render (`render-core.tsx`). The rules must win over
the theme, Tailwind utilities and the clones' own CSS; the clones' CSS is unlayered, so a CSS layer would
lose to it. *Builder's choice* of mechanism (for example unlayered rules with higher specificity), proven
on a Tailwind-built clone (Conduit). Applying by stylesheet (not by React props) works the same for brand, agent and clone
sections, never rebuilds a clone's DOM, and needs no change inside agent-written code.

### 4.6 Fonts

The Font list shows the brand's families first, then the font library the ad editor uses (the API's
`/font-library` manifest, ~27 families; `design-editor/engine/scene/libraryFonts.ts`). Today none of the
library reaches the site frame. *My call:* the site theme emits `@font-face` rules for every library family
an `edits` entry uses (WOFF2, from the manifest), in the editor and on the published page; publishing keeps
only faces the page uses (the existing page-weight item P2 covers trimming).

### 4.7 The panel

`site-inspector.tsx` grows one panel per element kind, built from the ad editor's exported primitives
(`ColorControl`, `InspectorSelect`, `RadiusControls`, `BackgroundFillControl` in
`inspector-primitives.tsx`). `TextAlignment` is private today (copies in `image-inspector.tsx:177` and
`web-inspector.tsx:182`); extract it once and use it in all three. The colour Theme tab needs a site
palette built from the brand's tokens (the ad's comes from `ScenePaletteContext`, scene-only). A control the
selected element cannot take (an agent section's element that is not keyed, a clone element that has no
text slot for its words) shows disabled with a one-line note — never a live control that does nothing.

Each committed change is one site write (`PUT /documents/{id}/site`) and therefore one server undo step,
like inspector edits today. Number boxes commit on blur / Enter, never per keystroke.

### 4.8 Arrange

"Move up / down among neighbours" reorders an element among its siblings:

- **Brand and agent sections:** where the siblings come from a prop array (a row of cards), the move
  reorders the array; the stamped keys follow the items.
- **Clones and the header / footer:** the move writes `order` on the parent's `edits` entry. The clone
  filler (and `kit/shell.tsx`) rearranges the children in that order before the markup is produced, in
  the editor and on the published page alike. Because clone keys are computed from the captured markup,
  not from the rearranged DOM, a moved element keeps its key, so its styles move with it and no remapping
  is needed.
- A container whose children are neither a prop array nor clone / shell markup (an agent section's plain
  layout) offers move only if the agent made the children a prop array.

*My call:* moving whole sections stays with item E8 and its designs.

### 4.9 The agent

**Header and footer.** The agent writes the shell's `edits` as it does a section's, so it can restyle and
rearrange the header and footer: spacing, alignment, colours and fonts, the order of its parts, hiding the
logo or a link. The prompt and `building-with-puck` stop implying the header is off-limits (skill text,
founder review first). A header with a structurally different composition (new elements, a two-row header, an
agent-written header) — and no hard-coded header at all — is **plan 6** (founder, 2026-10-17).

The agent's view of the page (`site.md`, the section cards) shows each section's `edits` in plain words
("headline: colour #0F59B0, Semi Bold"). When it rewrites a section it may keep, change or drop them.
An `edits` entry whose key no longer exists after a rewrite simply matches nothing; it is kept, never
an error (the save check does not run agent-section code, so it cannot know the keys). The agent may clear
such entries.

## 5. Prerequisite

**S1-3** (open review finding, `docs/superpowers/verification/2026-10-14-wave2-area-review-findings.md:172-187`):
clone text replacements the check accepts are never applied, because three places read clone text three
ways. Fix it before clone text editing grows (one shared "visible text" function; accept only what the
renderer can replace).

## 6. Constraints

- Puck stays pinned at `@puckeditor/core` 0.23.0.
- Every new runtime flag goes in `.env.example` with its default (repo parity rule). *My call:* no flag; the
  panel ships on.
- Published sites ship JavaScript (founder 2026-10-15), so a live page may use the same render path.
- Nothing outside `subsystems/clue-design/` imports design internals (seam rule).
- Verification is business-logic scenarios through the real routes, DB and published render, plus a live
  check on Garner, Conduit and Clue in the in-app browser (founder rulings 2026-10-04 and 2026-10-13).
- Skill or prompt text changes (the agent's `writing-a-section`, `building-with-puck`) are shown to the
  founder before they are written.

## 7. The plans

The work ships as **six plans, built one at a time in this order** (plan 6 added 2026-10-17). A plan starts only when the one before
it is finished: built, reviewed, proven by its scenario tests, and checked live in the in-app browser on
Garner, Conduit and Clue. Each plan delivers one kind of element **everywhere it appears**: in our brand
sections, in copied seller sections (clones), in the agent's own sections, and in the shared header and
footer.

### 7.1 Status (keep this table current)

| Plan | What the marketer gets | Status | Plan file |
|---|---|---|---|
| 1 | Click any text and style the whole text box | Finished 2026-10-17; live-checked on Garner (Carmel Clay) and Conduit (Oliver Hotels) 2026-10-17; Clue has no microsite in the lane yet | `docs/superpowers/plans/2026-10-17-site-element-inspector-plan-1-foundations-and-text.md` |
| 2 | Style and link highlighted words; more fonts | Finished 2026-10-17: built, reviewed, live-checked on Conduit (Oliver Hotels) and Garner (Carmel Clay); skill text approved and written; Clue has no microsite in the lane yet | `docs/superpowers/plans/2026-10-17-site-element-inspector-plan-2-words-links-fonts.md` |
| 3 | Click a button and edit everything about it | Built 2026-10-18 (Tasks 1–7, 9 and the site.md part of 8); live-checked on Garner (Carmel Clay: header and CTA band buttons) and Conduit (Oliver Hotels: a copied hero button), both restored to their starting content; end-of-plan review done 2026-10-18 and all 11 findings fixed; skill text approved and written 2026-10-18; frontend `build` owed with the lane stack down |  `docs/superpowers/plans/2026-10-17-site-element-inspector-plan-3-buttons.md` |
| 4 | Click any box (section, card, row, div) and style or move it | Finished 2026-10-18: built, reviewed (1 Critical, 6 Important fixed; 8 Minor deferred), skill text approved and written; live-checked on Conduit (Oliver Hotels: a copied card restyled, centred and moved, header logo hidden and shown) and Garner (Carmel Clay on kit v7: Feature split's own box padding, a heading's fixed-place note, the footer's link group alignment note and move), both undone back to their starting versions (stored sites equal); Clue has no microsite in the lane. Rulings R1/R2 changed by the founder 2026-10-19 (see §7.7): a whole section shows only Layers, and its own box is selected as its Background | `docs/superpowers/plans/2026-10-18-site-element-inspector-plan-4-containers.md` |
| 5 | Click an image and set its fit, alt text and corners | Finished 2026-10-18: built, reviewed (3 Important and 1 Minor fixed; 8 Minor deferred), skill text approved and written; live-checked on Conduit (Oliver Hotels: a copied image's alt text with quotes, & and <>, 24 px corners, replaced from the library through its slot) and Garner (Carmel Clay: the Feature split photo's alt text and a library replacement), both undone back to their starting versions (stored sites equal); Clue has no microsite in the lane | `docs/superpowers/plans/2026-10-18-site-element-inspector-plan-5-images.md` |
| 6 | Headers and footers as editable templates, changed by the marketer and the agent like any section | Finished 2026-10-18: built, reviewed (I1–I7 fixed, I3 by founder option a: an inline-SVG seller logo becomes the kit's logo file), site agent `fetch_logo` added (founder yes); live-checked on Conduit (Oliver Hotels) and Garner (Carmel Clay): agent turns built both headers and footers from the templates, the editor walk (account line, sticky, overlay, fill, logos) was undone back to the agents' versions; six live-check defects fixed with tests (template lineage, re-minting, the account parts' phone and desktop layout). Prompt and skill lines written, uncommitted until the founder's trial review | `docs/superpowers/specs/2026-10-18-site-header-footer-templates-design.md`, `docs/superpowers/plans/2026-10-18-site-element-inspector-plan-6-header-footer.md` |

### 7.2 What each plan covers

**Plan 1: foundations and whole-box text styling.**
- Foundations every later plan builds on:
  - element names (`data-clue-el`) on text elements: brand sections, clones, the header and footer, and
    the agent's own sections where the agent names them (§4.1);
  - clicking selects the text under the pointer (§4.2);
  - the `edits` storage layer with its validation and the stylesheet that draws it, in the editor and on
    the published page (§4.3, §4.5);
  - the site colour palette; the shared alignment control and the B / I / U toggles (§4.7).
- The text panel: colour (brand or custom), font (the brand's fonts only), size, weight, bold, italic,
  underline, alignment, applied to the **whole** text box.
- Layers: the selected section's text elements, listed under it.
- `edits` properties added: `color`, `fontFamily`, `fontSize`, `fontWeight`, `italic`, `underline`,
  `textAlign`.
- The agent: may write `edits` (including the header's and footer's); sees manual styling in `site.md`;
  skill text on naming text elements and on `edits` (founder review first). The prompt stops implying the
  header is off-limits.

**Plan 2: highlighted words, links on text, more fonts.**
- Fix S1-3 first (§5).
- Rich text (§4.4): highlight words and style just those words (colour, font, size, weight, bold, italic,
  underline); the panel says "N words selected".
- Links on text: edit an existing text link (ProofCard's link, nav links, footer links, a clone's text
  link through its `href` slot or `links` replacement), and turn highlighted words or a whole text box into
  a new link; web address or page on this site; same tab or new tab (the "new tab" boolean for text links).
- Clone text slots accept rich text; clone text that is not a slot shows its word-level and new-link
  controls disabled with a note.
- Fonts: the ad editor's library fonts after the brand's, loaded in the editor and on the published page
  (§4.6), with their own weights.
- The agent: `site.md` shows rich text and links in plain words; skill text on rich text and links
  (founder review first).

**Plan 3: buttons.**
- Clicking a button selects the button (keys on buttons; `kit.Button` takes `el`).
- The button panel: label text; label typography; fill; stroke (colour, width, corner radius: pill, a
  number, custom); padding and width; Link (web address or page on this site; same tab or new tab).
- Everywhere: brand-section buttons, clone buttons, the header's call-to-action button, agent buttons.
- `edits` properties added: `fill`, `borderColor`, `borderWidth`, `radius`, `padding`, `width` (as they
  apply to buttons). The "new tab" boolean for button links.
- Layers gains buttons. The agent: `site.md` and skill text for buttons (founder review first).
- Added when plan 3 was written (2026-10-17): button labels are rich text without links (the approved
  mockup styles highlighted words in a label); the Link section takes the mockup's
  layout (Goes to · Open in) for every link, text links included.

**Plan 4: containers and Arrange.**
- Clicking any box selects it: a section, a card, a row, a column, a list item, a div, the header or footer
  box (keys on containers; `kit.Card` takes `el`). The panel's title names what was clicked.
- The container panel: fill; stroke (colour, width, corner radius); padding; gap between children; width
  (fill, fit, fixed); content alignment.
- Arrange (§4.8): move an element up or down among its siblings — in prop arrays (brand and agent
  sections), in clones and in the header and footer (`order`).
- Hiding a header or footer element (`hidden`), so the logo or a link can be dropped.
- `edits` properties added: `gap`, `order`, `hidden`; the plan-3 box properties extended to containers.
- Layers becomes the full nested tree of the section. The agent: `site.md` and skill text for containers,
  ordering and hiding (founder review first).
- Added when plan 4 was written (2026-10-18, approved by the founder): `edits` also gains `contentAlign`
  (`{along, to}`, the CSS it set kept with it); Arrange is offered for text, buttons and images too; images
  become selectable here (keys on images, `kit.Image` takes `el`) with Arrange, Hide and a Layers row only
  (R8); a click on blank section space still selects the section, whose panel adds its box's Fill, Stroke
  and Layout (R1, R2).

**Plan 5: images.**
- (Selecting images, their keys and `kit.Image`'s `el` moved to plan 4: plan 4's R8, approved 2026-10-18.)
- The image panel: Replace (the existing asset picker), fit (fill or fit), alt text, stroke with corner
  radius.
- `edits` property added: `imageFit`; stroke and radius extended to images.
- Layers gains images. The agent: `site.md` and skill text for images (founder review first).

**Plan 6: headers and footers as editable templates.** (Its own design first: it changes how the
site document, the editor and publishing treat the header and footer.)
- No hard-coded header or footer. Standard headers and footers exist as templates (today's header is
  the first; the seller's own captured header can be another); the agent picks one and changes or
  rewrites it, including writing its own header code; the marketer changes any word and any styling
  in place, like any section; saved, undoable and published the same way.
- Agent-written header code can use placeholders for the seller's logo, the account's logo and the
  account's name, filled the same way templates fill them.
- Its design (2026-10-18) is the authority for its scope:
  `docs/superpowers/specs/2026-10-18-site-header-footer-templates-design.md`. In short: one shared
  header and footer per site, stored as section entries; one header and one footer template per brand
  kit derived at extraction from the seller's own top bar and footer, made ABM-focused, no approval gate;
  the agent may change them or write its own on-brand header; account name and logo are filled in once
  at site start (live markers and per-account copies come later with site templating); a compact header
  on phones; see-through over the hero and sticky as header properties; the older ABM pair stays offered
  until the founder retires it.
- Everything plans 1–5 built (selecting, styling, typing in place, links, buttons, boxes, images)
  works in the header and footer because they are sections.

### 7.3 Where every requirement lives (nothing in two plans, nothing in none)

| Requirement (section of this doc) | Plan |
|---|---|
| Element names and selection, for text (§4.1, §4.2) | 1 |
| ... for buttons / containers / images | 3 / 4 / 4 (plan 4's R8, approved 2026-10-18; the image panel stays 5) |
| `edits` storage, validation and stylesheet (§4.3, §4.5) | 1 (later plans add properties) |
| Whole-box text typography, brand fonts | 1 |
| Header and footer as editable templates (any words, any styling, agent-rewritable, placeholders for logo and account name) | 6 |
| Site colour palette, shared alignment control, B / I / U toggles (§4.7) | 1 |
| Agent may write `edits`; `site.md` shows manual styling; header not off-limits (§4.3, §4.9) | 1 (later plans extend `site.md` and the skills for their element) |
| S1-3 clone text fix (§5) | 2 |
| Highlighted words, "N words selected", rich text in brand, agent and clone slots (§4.2, §4.4) | 2 |
| Links on text: editing existing text links, creating new ones, new tab (§2, §4.3, §4.4) | 2 |
| Library fonts and their loading (§4.6) | 2 |
| Button label, typography, fill, stroke, radius, padding, width, Link, new tab (§2) | 3 |
| Header call-to-action button | 3 |
| Container fill, stroke, radius, padding, gap, width, content alignment, panel title (§2) | 4 |
| Arrange in prop arrays, clones, header and footer; `order` (§4.8) | 4 |
| Hiding header and footer elements; `hidden` (§4.3, §4.9) | 4 |
| Layers as the full nested tree (§2) | 4 (plans 1, 3 and 5 add their element rows) |
| Image replace, fit, alt text, stroke and radius; logos (§2) | 5 |
| Disabled-with-a-note controls; number boxes commit on blur; one save per change (§4.7) | every plan, for its own controls |
| Scenario tests and the live check on Garner, Conduit and Clue (§6) | every plan |

### 7.4 Not in any of the five plans

- Moving, inserting, deleting or duplicating whole sections (item E8, waiting on the founder's designs, C13).
- Styling that differs by screen width; animations; free CSS (§3 non-goals).
- Trimming unused font files from published pages (the existing page-weight item P2).
- The ad panel's Stroke on text, Layout X / Y, Rotation, Arrange front / back, and vertical alignment (§2).

### 7.5 When a plan is done

A plan is done when: every control it adds works on every section kind it names (or is shown disabled with
a note where §4 says so); each change shows identically in the editor and on a published page; it survives
a reload and is one undo step; a business-logic scenario test proves it through the real write route, the
stored document and the published render; and it is checked live in the in-app browser on Garner, Conduit
and Clue. No plan leaves a control that looks live but does nothing.

### 7.6 Keeping this document current (every agent working on this)

This document is the source of truth for the five plans. Read §7 before writing or executing any of them,
and update it whenever any of these happens:

- a plan is written: fill in its plan file and set its status to "Plan written <date>; not started";
- a plan starts or finishes: update its status (finished means §7.5 is met, with the live-check date);
- the founder changes what a plan covers, or something moves between plans: update §7.2 and §7.3 in the
  same commit, so no requirement ends up in two plans or in none;
- a decision changes §2 or §4: edit that section and add a line to the change log below.

Never leave a plan's scope only in a plan file or a chat; it belongs here.

### 7.7 Change log
- 2026-10-19: founder, after plan 6 (scope change to plan 4's R1/R2 and plan 6's whole-section panel): selecting a whole section — ours, a copied one, the header or the footer — shows only Layers (the header keeps its two placement switches); "for now", so the Content fields panel stays built, switched off in `use-site-editing-session.ts`. A section's own outermost box (`root`, or a copied section's one top element) is its **Background**: listed first under the selected section in Layers, selected by a second click on blank space of the selected section (the first selects the section), and it opens the section-box panel (Fill and Stroke on the outer box, Layout and content alignment on the inner). The section and its background get the canvas outlines elements get (dashed under the pointer, previewing the next click; solid when selected), drawn by the section's wrapper above everything in it (a CSS outline was painted under a copied section's positioned layers — Oliver's hero), and Puck's own section outline and hover tint are off. The protocol's `selected` carries `backgroundKey` always and `sectionBox` only for the background. Arrange's Order row became the ad editor's icon tiles (founder, same day). Live-checked on Conduit (Oliver Hotels): the hero and the header, section then background, nothing saved.

- 2026-10-18: plan 6 finished. Final review fixed (I1–I7); founder rulings: I3 option a (the kit's logo file stands in for a seller's inline-SVG logo), the site agent gets `fetch_logo`, the agent prompt frames the header rules as ABM focus, not creative limits. Live check found and fixed: a template no longer supersedes its source band (the seller's nav and footer stay offered); a template made again replaces the one before; the account line keeps its width on desktop, drops a borrowed menu link's phone-drawer box, sits above the header's own background layer and shrinks only on phones; a very wide account logo is capped. Ruling: on phones the seller's own CSS may hide its header button, kept as the seller's phone behaviour.

- 2026-10-18: founder approved plan 6's design ("yes please proceed with writing a detailed plan 6"). Plan 6 written (`docs/superpowers/plans/2026-10-18-site-element-inspector-plan-6-header-footer.md`). Its rulings R1–R13 await the founder's check: the shell's two entries are sections (`{type, props}`, ids `header`/`footer`) drawn as the page's first and last sections everywhere; the editor keeps the `shell` address; templates are copied sections derived deterministically from the kit's `nav`/`footer` fragments and released at once; `SiteHeader`/`SiteFooter` rewritten so every word is editable; the menu follows the site's pages (keys `menu._home`/`menu.<name>`, `menuLabels`, `menuExtra`); `sticky`/`overlay` as header-root `_edits` facts; the panel's Header group; templates first in the catalog.
- 2026-10-18: plan 6's design written (`docs/superpowers/specs/2026-10-18-site-header-footer-templates-design.md`) from the founder conversation and builder-checked. Founder answers: header and footer templates derived per brand kit from the seller's own, no approval gate; account name and logo filled in once at site start (live markers and per-account copies wait for site templating); compact header on phones, no drawer; the older ABM pair stays offered until the founder retires it. Awaiting the founder's review of the design; plan 6 not written.
- 2026-10-18: plan 5 finished and live-checked. The image panel caught up by itself after each undo (the picture and alt text came back), and the Layers row and panel title took the new alt text.
- 2026-10-18: plan 5's end-of-plan review fixed: the image panel catches up after an undo and when a picture's file loads; a picture whose file has not loaded keeps Fit live; an agent image is replaceable only through the prop that holds its own file; a backslash in a copied image's alt text survives. Founder approved plan 5's skill text; written.
- 2026-10-18: plan 5 built. Found while building: the HTML parser escapes only quotes in an attribute, so the clone filler escapes `&`, `<` and `>` in alt text itself; an image slot filled on a `<picture>`'s `<img>` also removes the picture's `<source>` elements, which would otherwise be chosen over the new picture.
- 2026-10-18: founder approved plan 5's rulings R1–R8 ("rulings approved, go ahead with plan 5 implementation"); plan 5 started.
- 2026-10-18: plan 5 written (images). Its rulings R1–R8 await the founder's check: where an image's file is written (our image prop, the header's account logo, a copied image slot, an agent's image named after its prop; the seller's logo fixed); where alt text is written (`imageAlt`, `logoAlt`, `accountLogoAlt`, a copied section's `alts` by element key; the agent's own for agent images); `imageFit` fill = cover, fit = contain, disabled with a note where the box keeps the image's own shape; a `<picture>`'s `<img>` is the image; videos get Fit and Stroke, icons keep plan 4's panel; Replace is the dock's existing image field; Stroke reuses the box panel; the new shapes. Also 2026-10-18: after an undo the panel shows the drawn look again (frame re-posts when the look changed after a new copy of the site).
- 2026-10-18: founder asked to fix two live-check findings; fixed and re-checked live: padding saves only the side typed (`_edits` padding may be `{ "y": … }` or `{ "x": … }` alone; the other side keeps the element's own, so a section's responsive side margin stays); a box or image covering at least 95% of the section's width and 85% of its height (a copied hero's full-width padded column, its background photo) is no click target, so blank space selects the section; both stay in Layers. Also seen: after an undo the panel can show the old drawn value until the element is selected again (frame re-describes only when the element list changes).
- 2026-10-18: plan 4 live check. Found, not changed (for the founder): on a real copied hero a full-width column with its own padding covers the section, so a blank click selects that "Column" rather than the section (the Layers row still selects the section); unnamed header parts read "Box" in Layers; typing only Padding Y also pins Padding X at the drawn value (so a section's responsive side margin is fixed); two changes made within a second can go out as one save (the save queue, older than plan 4); a header or footer edit stamps `id` on the shell part (older than plan 4, harmless).
- 2026-10-18: plan 4's end-of-plan review, all Critical and Important fixed: a copied section's box is the first element under ingestion's display:contents wrappers (was the wrapper, so its controls did nothing); empty overlays and decorations are boxes only with a visible fill or stroke; a named element of unnamed blocks (an agent's kit.Card) is a box, while an element holding Puck's in-place editor stays text; a move keeps the selection on the selected element and a quick second press builds on the first; the header's two groups are drawn in their order; content alignment is greyed out with a note on a box only as wide as its contents. Founder approved plan 4's skill text; written.
- 2026-10-18: plan 4 built. Boxes are keyed everywhere (every copied element by its captured path; keys of text and buttons unchanged, proven against a snapshot); clicks select the innermost box, text, button or image, and blank section space still the section, whose panel adds its own box; Arrange writes prop arrays (keys, styled spans and their `_edits` move with the item) or `order`; the header and footer draw their parts in `order` and hide parts by `hidden`. Found while building: the header's and footer's own box needs a same-element selector (their scope attribute sits on the box), and a copied button's label must skip its keyed icon.
- 2026-10-18: founder approved plan 4's rulings R1–R11 ("rulings approved, go ahead with plan 4 implementation"); plan 4 started.
- 2026-10-18: plan 4 written (boxes and Arrange). Its rulings R1–R11 await the founder's check: blank section space still selects the section, whose panel adds its box's controls; a section's box is two keys (`root` outer, `root.inner` holding the brand's padding); content alignment stored with the CSS it set; gap live only for rows and grids; how a move is written (prop array with `_edits` keys remapped, else `order`, else fixed); Arrange on every element kind; panel names; images selectable in plan 4 (R8, moves a §7.3 row); hidden parts stay hidden in the editor; pass-through wrappers not listed; the new properties' shapes.
- 2026-10-17: design approved by the founder; split into five plans; plan 1 written.
- 2026-10-17: plan 6 (a structurally different, agent-written header) proposed; founder deferred it. Plan 1 started.
- 2026-10-17: plan 1 finished. Live checks found and fixed: re-picking the shown font made a no-op save; Bold on a font with no 700 weight never showed as pressed (Bold now follows the font's own boldest weight, and is disabled with a note when there is none); the Theme tab listed palette ramps (hidden, ruling F3).
- 2026-10-17: plan 2 written and started. Its rulings change §4.4: rich text is **inline only** (`strong em u s br`, `a`, `span[data-s]`; no lists or second paragraph inside one text box, Enter makes a line break), because block markup inside a heading or paragraph breaks the published HTML; the panel styles highlighted words through `span[data-s]` + `_edits` (⌘B/⌘I/⌘U in the text still make `<strong>`/`<em>`/`<u>`); alignment stays whole-box; an agent's text takes word-level edits when its `data-clue-el` is the prop's own name; header and footer words stay whole-box until plan 6; the dock shows rich fields read-only; a clone link's new tab is stored as element keys (`newTab`). Full list in the plan's Rulings.
- 2026-10-17: plan 2 built. Found and fixed while building: ProseMirror drops a second paragraph when the document allows one (so the editor keeps Puck's document and paragraphs become line breaks on save); Puck draws a rich text field as its own widget in preview too (agent sections and `_edits` are now read from stored props anywhere in the editor); publishing checked the site against the licence-gated fonts, so styling that named a held-back brand font or an unprovisioned library font refused the whole publish (now checked against the fonts as offered, drawn with what can ship). Live check found and fixed a stray save: the frame re-spelled an agent's plain `&` as `&amp;` when Puck reported the page back.
- 2026-10-17: plan 2's end-of-plan review: fixed — the Link row and the words' look now refuse highlighted words the stored text no longer holds; words highlighted in text that is already a link change that link instead of nesting another; a named HTML entity other than amp/lt/gt/quot/apos/nbsp is refused ("write the character itself"); clone slot names with dashes or a leading digit are valid prop paths; a clone slot set to its original words keeps its captured markup; the rich text reader runs in linear time; one link rule (no protocol-relative `//host`, no spaces) for the save check, the editor and the Link row; text replacements never reach into a text slot; library faces stored with their real font type and named in the publish manifest. Kept as a residual: styling words in a never-edited clone slot stores its words in the grammar, so the seller's own inline styling there (a coloured span) is dropped.
- 2026-10-18: founder: a font size set in the inspector follows the brand's measured type steps (the nearest kind of text's, headline or body), on our sections and copied ones, so a marketer who never checks the phone view still gets a consistent site. Scope change to §3's non-goal for font size only; built as part of the responsive brand type work (`docs/superpowers/specs/2026-10-18-responsive-brand-type-design.md`), not as one of plans 4–6.
- 2026-10-18: founder: a button with no words is not drawn in the editor, as on the published page (option A), with no "add a button" control — the marketer asks the agent; no alignment change for our sections (the misplaced paragraph was a one-off, probably the agent's); text that changes size with the window is a separate design (measure the seller's type at several widths at extraction), to be done in its own workspace. Plan 3's skill text approved and written.
- 2026-10-18: plan 3's end-of-plan review (5 Important, 6 Minor), all fixed: a button is now only our own `brand-btn`, or, inside a copied section, an inline-only link or `<button>` with no image and at most one text (and, for a link, a visible box) — so menu, footer, ProofCard and agent links keep their Link and Text rows, and a card's texts stay selectable; every button's words are drawn without links on the page (an agent's rich prop could nest a link inside the button); a copied button's Open in reads and clears a new-tab key on its words too; the header's button words are a rich-text field in the dock; drawn values are held within the message's limits (percentage corners read from the box), a drawn pill reads as Pill, a clear fill as 0%; copied button words that repeat in the section say so; line breaks show as spaces; refusal notes sit under their own section. R6 amended: an agent button's words are editable when the agent names the button after the marked prop holding them (`el="cta"`, `label={props.cta}`); otherwise they stay "ask the agent".
- 2026-10-18: plan 3 built. Found and fixed by the browser proof and live checks: in edit mode Puck mounts its in-place editor (block divs) inside a button's words, so every brand button read as plain text when its words were clicked (the block check now ignores Puck's overlay portal); a menu link laid out as a block was classified as a button (a link now needs a visible fill or stroke); copied Webflow buttons' empty overlay links showed in Layers as rows named by their key (empty elements are no longer listed); switching corner radius or width mode started from drawn values the schema refuses (a pill draws 9999px; mode switches now start within range). Recorded, not changed: copied buttons whose content holds block elements (Garner's Webflow `<button><div>…`) stay text, as §7.2's inline-only rule says — the marketer can style their words but not their box.
- 2026-10-18: founder: drop the one-primary-destination save check now ("yes drop it, then go ahead with plan 3"); buttons may go to different places; one destination for the offer stays the agent's skill. Removed from `validate.ts` before plan 3's Task 1. Plan 3's rulings approved; plan 3 started.
- 2026-10-18: founder, on plan 3's ruling R5: keep the one-primary-destination save check for now, but it was meant as a directive the agent follows, not a code gate ("i thought it was being said as a directive that agent would follow, not something that would be enforced by code gates"). It is judgement enforced as code, against the 2026-10-08 ruling (judgement belongs to the agent). Open follow-up, owner: founder decision on when — move the rule into the agent's skill text and drop it from `validate.ts` (plan 3's shared `primaryDestinations` function makes that a small change). Until then plan 3 handles it with a clear refusal and "Use for every button".
- 2026-10-17: plan 3 written (buttons). Its rulings R1–R9 await the founder's check: a button is a box key and a label key; which clone links count as buttons; labels are rich text without links; hand-set fill holds on hover; the one-destination rule stays, with "Use for every button"; agent buttons' words and links stay the agent's; clone button words via slot, replacement or a note; the Link section's mockup layout for every link; the shapes of the new `_edits` properties.
- 2026-10-17: plan 2 finished: the founder approved its skill text, written into writing-a-section and building-with-puck.
- 2026-10-17: founder, during plan 1's live check: every word in the header and footer must be changeable, and the header must not be hard-coded — standard headers become templates the agent and the marketer change like any section. Briefly added to plan 1, then moved to **plan 6** (founder: "we do it as a part of plan 6"). Plan 1 keeps what it built: the header's account name and nav links, and the footer's text, are selectable and styleable.

## 8. Left to the builder

Exact key derivation per section, the message field names, the CSS layer name, the panel's internal
structure, how the Layers tree is built from the frame's DOM, test layout, and the font-face loading
mechanics — within the rules above.
