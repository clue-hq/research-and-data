# Lane A — A9 rewritten: brand fidelity from what the extraction measured — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Replaces:** the block "A9 — brand fidelity in site-kit" (Tasks 4, 5, 6, 7) of
`docs/superpowers/plans/2026-10-11-lane-a-site-backend-and-publishing.md`. Task 6 of that plan is
kept as written (it is unaffected) and runs where it stands; everything else in Tasks 4, 5 and 7
is replaced by the tasks below. The Lane A plan's Global Constraints, test command forms
(`DESIGN_PYTEST <file>`, `PLATFORM_PYTEST <file>`, `SITE-KIT`) and Review Focus apply unchanged.

**Goal:** Every button, link, card, surface, type colour, spacing step and motion a site draws comes
from what the brand-kit extraction measured on the seller's own site — kept in the kit as
brand-scoped tokens minted by code — then from the kit's other tokens, and from a named fallback
only where the kit has neither. No component in site-kit carries a style value of its own.

**Architecture:** The capture measures each element style in rest, hover, pressed, focus-visible
and disabled, with its transition, icon and the page's CSS animations, reveals and scripted motion
(`capture/states.py`, after the screenshot). The normalizer mints every measured value as a token of
this kit (exact-match reuse, no tolerance; stable names made from where it was measured), including
each section background as a `surface.band.<hex>` token. A code-owned kit section
`measured_components` names those tokens per style (the measured recipe), beside the model-written
brief's recipe for the same `(component, variant)`. The engine carries the values its typed groups
cannot hold (keywords, durations, easings, transforms, keyframes, icons) in one new token group,
`styles`. site-kit resolves all of it through `brand-values.ts` / `surfaces.ts` / `looks.ts` and
generates its CSS from it (`theme.ts`); `brand.md` shows each style's values with their token names.

**Tech Stack:** Python 3.12, Playwright 1.61 (async) and patchright 1.61.2 (the stealth backend's
Chromium), tinycss2, selectolax, pydantic 2; Rust (lumen-core, serde); TypeScript, React 19.2,
`@puckeditor/core` 0.23, Zod 4.4, Tailwind 4.3.

**Spec:** the founder rulings of 2026-10-12 (recorded in
`docs/superpowers/plans/2026-10-11-wave2-founder-review.md`, "Founder answers"), the four coordinator
messages of 2026-10-12 that carried them (measured states; motion and behaviour; minted tokens;
section backgrounds; Q4 = (b)), and the master plan's Wave 2 contracts.

---

## Controller review (2026-10-12) — read first

Verified first-hand against the code before the founder saw this draft:
- **The engine drops what it does not know.** `BrandKit` (`crates/lumen-core/src/brand.rs:193-213`)
  has no catch-all field, and the pipeline itself attaches `brief` and `grammar_audit` only after
  validation for that reason (`lumen_ingestion/pipeline.py:1076-1095`). So Task X1's `styles` group
  is required, not optional.
- **The curation routes lose kit sections (a live defect).** `POST /brand-kits/{id}/logo` and
  `/describe-assets` re-validate and publish `validation["brand_kit"]`
  (`lumen_api/main.py:2349-2370`, `:2446-2462`) without re-attaching them, so a kit edited there is
  republished without its brief and grammar audit. Task X5 fixes it.
- **Band renaming is low-risk.** No code reads a particular band name (agents see them through
  generic token lists); in the lane DB one kit version carries a `surface.band.*` token and no web or
  scene document names one. Residual, recorded here: before moving (re-pinning) any document to a
  re-extracted kit version, check its scene for an old `surface.band.<rank>` name; a pinned document
  is never affected on its own.
- **The scroll reveal cannot hide content:** its CSS sits under `@supports (animation-timeline:view())`
  and `prefers-reduced-motion: no-preference` (Task 4).

Open from the review (founder question Q-A9-6, added to the list below): **style names are not
stable across re-extractions.** Variants are numbered by how often the site uses each look
(`solid.1` is the most common), so a re-extracted site whose counts shift renumbers them, and a
saved `buttonLook: "solid.2"` would silently point at a different style once the document moves to
the new kit version. Recommended fix: name each style by its measured look (for example by its fill,
border or text colour, with a short suffix only when two looks share it), the way section
backgrounds are already keyed by colour. This changes `_cluster_shapes` naming and every task that
builds a token name from a variant; old kits keep their names.

## What changed and why

- **Buttons are drawn from measurement, not invented.** Lane A's `secondaryButton()` (first
  `outline*` recipe, else a made-up outline) and `brand.measured.primary_button` (a spike-only hero
  measurement) are removed. A button is the kit's standard button (its tokens) or a recipe the agent
  names with `look`; FeatureSplit and CtaBand get `buttonLook`.
- **The extraction now measures states and motion** (founder: "rest, hover, pressed, focus, disabled …
  well captured and actively used"; "every behaviour and animation"). Today it reads rest only
  (`capture/geometry.py:93-121`), plus one generic focus pass (`:262-287`).
- **Measured values become tokens of the kit** (founder design change), so a recipe is complete and
  passes the token law (`brief.py` `validate_brief`) because every name is in the kit's own set.
- **Section backgrounds are minted as surfaces** (`surface.band.<hex>`), keyed by colour so a shifted
  band order never renames one, and **our four sections' Surface field offers them** (founder Q4 =
  (b)), validated like `buttonLook`.
- **No hard-coded style values in site-kit components** (founder): colours, opacity de-emphasis,
  forced uppercase, always-appended arrows, Tailwind spacing steps, weights and underlines in
  `sections.tsx`/`shell.tsx`/`config.tsx`/`agent-kit.tsx` go; a guard test refuses new ones.
- **One engine change is needed** (Task X1): `validate_brand_kit` re-serializes the kit through the
  typed Rust `TokenCatalog` and silently drops anything it does not know — verified 2026-10-12 by
  running the helper over Garner's kit: `brief` and `grammar_audit` came back absent. A `styles`
  group is the only way keywords, durations, easings, transforms, keyframes and icons can be kit
  tokens. It is additive and omitted when empty, so every existing kit and golden is byte-identical.
- **A pre-existing defect is fixed on the way** (Task X5): `POST /brand-kits/{id}/logo` and
  `POST /brand-kits/{id}/describe-assets` publish `validation["brand_kit"]`
  (`lumen_api/main.py:2349-2370`, `:2446-2462`), and the helper returns no `brief` or
  `grammar_audit` (verified on Garner's kit), so a kit curated through either route is republished
  without them — and would be without `measured_components`. (Inferred from the code and the helper's
  behaviour; no stored kit version was inspected for it.)

### Facts in the brief that the code does not bear out

- "No hover/active capture anywhere in lumen_ingestion/capture": the capture probe reads none, but
  `capture/parse.py:568-616` (`_collect_state_styles`, clone-fidelity F0.3) records DECLARED
  `:hover/:focus/:active/:disabled` rules from stylesheets into `BrandEvidence.state_styles`. They
  are keyed by selector, never joined to a measured style, carry declared (not computed) values, miss
  script-driven hovers, and have no consumer (`grep state_styles` finds only the producer). This
  plan leaves them as they are and measures computed states instead.
- The existing band-surface mint (`normalizer/bands.py`) is not exact-match: it skips a band within
  OKLab merge distance 0.03 of any kit colour and mints only recurring or ≥20%-height bands, named by
  rank (`surface.band.statement-2`). That is why Garner's `#FFFFFF` shells (vs `surface.page`
  `#F9FAF8`) and its single `#014036` forest band reached no token. Task X4 rewrites it.
- "Raw measured values are discarded": they are not in the kit, but each website ingestion keeps its
  whole evidence, shape records included, on its job row (`design_ingestion_job.evidence_json`) —
  which is what makes the rest-only backfill of Q-A9-4 possible.
- "The lane DB has 3 kits with briefs": a read-only query on 2026-10-12 found four kit lineages with a
  brief — Alt Carbon, Conduit (versions 1–3), Doctor Quality Analytics and Stripe.

## Open questions for the founder

The plan is written to each recommendation; an answer changes only the place named.

- **Q-A9-1. The header's call-to-action button.** `shell.json`'s header button has no look today, so
  it is always the standard button — which for Conduit is a `surface.brand` cyan fill its own brief
  forbids ("Do not paint … primary demo button … with surface.brand"). (a) Give the shell header a
  `ctaLook` field like `buttonLook` (same select control in the dock, same validator rule).
  (b) Leave the header on the standard button. **Recommended: (a).** It touches Task 5 (schema,
  `SiteHeader`, header fields) and Task 6b (validator) only.
- **Q-A9-2. Kits whose brief stage did not run.** Looks are the brief's recipes (ruling), so a kit
  published briefless (refusal, gateway failure, stage off) offers only the standard button even
  though its styles were measured and minted. (a) As written. (b) Offer each measured button style as
  a look named by its variant when the kit has no brief. **Recommended: (a)**; a briefless kit is
  itself flagged on the kit.
- **Q-A9-3. Minted tokens in the brand-context review panel.** The panel lists every colour token
  (`brand-context-mapping.ts:178-209`) and every typography token (`:297-320`); minted component
  tokens would land in the "Semantic roles" group and the text-style table under names like
  `button.solid-2.fill`. (a) Hide component tokens there until a design for them exists (band
  surfaces stay, as `surface.band.*` already do). (b) Show them in the existing lists. **Recommended:
  (a)**; it is Task X6, a filter, no new UI.
- **Q-A9-4. Existing kits.** They gain measured tokens only through a new extraction (your go per
  kit). A rest-only backfill exists as an alternative: each kit's ingestion job row keeps its evidence
  (`design_ingestion_job.evidence_json`, e.g. Conduit's `ingest_3e85c884…` carries 18 shape records
  and 9 band backgrounds), so rest colours, borders, corners, padding and band surfaces could be
  minted into a new kit version without a crawl — but no states, motion, letter-spacing, case or
  icons (never captured). (a) Re-extract per kit when you say. (b) Add a dry-run-by-default backfill
  script for the rest values first. **Recommended: (a)**; (b) would publish a second, half-measured
  version of each kit. Nothing in this plan runs either.
- **Q-A9-6 (controller review). Stable style names.** See "Controller review" above. (a) Name each
  measured style by its look (value-keyed, like `surface.band.<hex>`), so re-extraction keeps names.
  (b) Keep frequency numbering (`solid.1` = most common) and accept renumbering. **Recommended:
  (a).** It touches Task X2 (`shape_groups` naming) and every place a token name is built from a
  variant (X4, X5, Task 4); the brief agent copies variant names as given, so its prompt does not
  change.
- **Q-A9-5. The web and ad lanes.** Minted colour tokens become usable web theme classes and scene
  tokens automatically (the web author's THEME TOKENS list is every kit colour,
  `tools/web_substrate.py:652-682`). (a) Let them appear now. (b) Hide component tokens from those two
  lists until the follow-up below lands. **Recommended: (a)**: the names are the brand's exact
  colours and the engine resolves them; the list is code-generated vocabulary, not prose.

## Agent-facing and marketer-facing text to approve (verbatim)

Every step that writes one of these starts with "confirm approved". Angle brackets are filled from
the kit; `[...]` appears only when the kit has it.

### T-A9-1 — `brand/brand.md` (site agent; Task 7)

```markdown
# Brand: <seller>

Every brand section takes its colours, type, spacing, buttons and motion from these values. You
choose by name (for example `surface: "brand"`); you never write a colour or a size.

## Surfaces
Every section stands on one of these surfaces. Choose one by its name: `"surface": "brand"` on one
of our sections, or `kit.Shell surface="<choice>"` (or the classes
`bg-surface-<choice> text-on-surface-<choice>`) in a section you write. Text on a surface takes the
colour under "text on it".
| choice | name | kit name | colour | text on it | from |
|---|---|---|---|---|---|
| page | Page | surface.page | #F9FAF8 | #0E1110 (text.primary) | measured |
| … one row for each of card, muted, brandSubtle, brand, inverse, then every other surface the kit has … |
| band-014036 | Dark band | surface.band.014036 | #014036 | #FFFFFF (text.inverse), measured on the band | measured: a section background on the seller's site (1 band, 733px tall) |

## Type roles
Each role is a pair of classes, `font-<role> text-<role>` (for example `font-title text-title`).
"measured" means the seller's own site showed it, for the fields listed; "derived" means the kit
worked it out from the measured roles. On a light surface a role takes the colour shown when the kit
measured that colour; otherwise, and on every dark surface, it takes the surface's text colour.
| role | classes | font | size at 1440 | weight | line height | colour | from |
|---|---|---|---|---|---|---|---|
| headline | `font-headline text-headline` | Stix Two Text | 87px | 500 | 1 | #0E1110 (text.primary) | measured: family, size, weight, line height |
| … one row for each of the twelve roles … |

Our sections' headings choose from display, headline and title (`headingRole`).

## Spacing
The seller's spacing, as classes you can use: `py-section` (space.section, <96px> at 1440),
`px-page-margin` (space.page.margin, <30px>), `mt-stack-tight` or `gap-stack-tight`
(space.stack.tight, <8px>), `mt-stack-default` (<16px>), `mt-stack-loose` (<32px>) and
`p-card-padding` (space.card.padding, <32px>). Values above 24px shrink on smaller screens.

## Buttons
`kit.Button` draws a button. Below are the button styles the seller's own site uses, as its brand kit
recorded them, and the kit's standard button. You choose the style of each button by its name, with
`look`: `kit.Button look="<first look>"` in a section you write, or `"buttonLook": "<first look>"` on
a FeatureSplit or a CtaBand. A button with no look is the standard button.
| look | kind | fill | label | border | corners | confidence | notes from the brand kit |
|---|---|---|---|---|---|---|---|
| (none) | the kit's standard button | #047464 (surface.brand) | #FFFFFF (text.inverse) | none | 16px (radius.button) | — | Used when you name no look. |
| outline.1 | outline | none | #0D2B25 (button.outline-1.label) | 1px (stroke.width.thin) #0D2B25 (button.outline-1.border) | 9999px (radius.full) | high | Stroke color is text.primary, … |
| … one row per button style … |
[Each style's hover, pressed and focus looks, and the motion between them, come from the seller's
site; `kit.Button` draws them.]
[This kit was made before button styles were measured: their values come from the kit's tokens, and
a part the kit has no value for is drawn as the standard button's part.]

How to choose:
- For the page's main ask, use the style the seller's site uses for its own main call to action (the
  notes and the brand's rules below say which); if none is clear, use the standard button.
- For quieter actions, use an outline or text-only style the site uses.
- Leave out styles the notes say are not page buttons (for example "inside product screenshots"), and
  be careful with low-confidence styles.
- Where the kit has no value for a part, the table says what is drawn instead.
- Add `disabled` for a button that cannot be used yet; it takes the style's disabled look.

On a dark surface, a button whose text or fill would not stand out from the surface changes: outline
and text-only styles take the surface's text colour, and filled styles and the standard button take
their light version (the kit's page colour, with its text colour). Every other button is drawn as the
seller's site draws it.
(or, when the kit has no button recipes: This brand's kit records no button styles, so every button
is the kit's standard button: <fill>, <label>, <corners>.)

## Cards
`kit.Card` draws a card on a section's surface. Below are the card styles the seller's site uses, as
its brand kit recorded them, and the kit's standard card. Choose one with `look`
(`kit.Card look="<first card look>"`), or leave it out for the standard card. Give it `href` to make
the whole card a link; it then takes the style's hover and focus looks from the seller's site.
| look | kind | fill | border | corners | padding | confidence | notes from the brand kit |
|---|---|---|---|---|---|---|---|
| (none) | the kit's standard card | #F9FAF8 (surface.card) | none | 8px (radius.card) | 32px (space.card.padding) | — | Used when you name no look. |
| … one row per card style … |
(or: This brand's kit records no card styles; `kit.Card` draws the kit's standard card: <fill>,
<corners>, <padding>.)

## Links
Write every link with `kit.Link` (a text link) or `kit.Button`, never a bare `<a>`. A link to another
page of this site is written `/` or `/<page>`; the kit points it at the right address wherever the
site is published.
Text links look like the seller's own: <#0D2B25 (link.ghost-1.label)>, <underlined on hover>.
(or: The kit recorded no text-link style, so text links are underlined in the surrounding text's
colour.)

## Motion
`kit.Button`, `kit.Link` and `kit.Card` already move the way the seller's site does on hover and
press. Nothing else moves unless you add one of these classes to an element; write no transition or
animation of your own.
| class | what it does | timing | where the seller's site uses it |
|---|---|---|---|
| `brand-motion-reveal-3f2a91c0` | fades in from opacity 0 and moves into place from 24px below as it scrolls into view | ease-out | 6 elements: section.reveal |
| `brand-motion-pulse` | opacity 1 → .4, transform scale(1) → scale(1.2); repeats forever, alternating | 1.6s ease-in-out | 1 element: div#pulse.pulse |
Visitors who ask their device for less motion see every element still, in its final place.
[The seller's site also moves in ways a published page cannot, because they need a script: <a canvas
animation (canvas.hero); a scripted animation (div#spin); a video (video.bg)>. Do not imitate them.]
(or: The seller's site shows no motion a page can reuse; nothing moves except the kit's buttons,
links and cards.)

[## The brand's own rules (from its brand kit)
Where a rule names a kit colour such as `surface.brand`, the matching choice is in the surfaces table.
- <rule> (<scope>)]

## Logos (always shown whole)
`kit.Image` shows a logo whole: never cropped, never rounded.
- `/asset-store/<sha256>`: <logo title>, <variant name>; on <allowed backgrounds>
(or: This kit has no logo files.)

## Assets (the only images and logos a page may use)
- `/asset-store/<sha256>` (<kind>, <asset id>): <description>
```

Changes from the Buttons draft you saw: the example look is this brand's first look (a brand
without `outline.1` would otherwise be shown a name it does not have); each cell shows its token
name; the two bracketed lines and the `disabled` bullet are new; the dark-surface sentence is
rewritten for measured styles (the old one forced every button to a light version). The Surfaces
section drops "Our sections take only the six choices above" (Q4 = (b)) and merges the two tables.

### T-A9-2 — `catalog/sections.md` rows (site agent; Task 7)

- the `surface` row of each of our sections:
  `| \`surface\` | text | yes | one of this brand's surfaces (brand/brand.md, Surfaces): page (Page), card (Card), muted (Muted), brandSubtle (Brand, subtle), brand (Brand), inverse (Inverse), canvas (Canvas), band-014036 (Dark band) |`
- the new `buttonLook` row (FeatureSplit, CtaBand):
  `| \`buttonLook\` | text | no | default ""; empty is the standard button, or a button style from brand/brand.md (Buttons): outline.1, ghost.1, solid.1 |`
  (or, with no button recipes: `default ""; this brand's kit records no button styles, so leave it empty`)
- the intro sentence "Style options are fixed choices; there are no colour, size, class or style
  fields." becomes "Style options are names from brand/brand.md; there are no colour, size, class or
  style fields."

### T-A9-3 — validator refusals (site agent; Task 6b)

- `<where>: "<value>" is not one of this brand's surfaces; its surfaces are <list> (brand/brand.md, Surfaces)`
- `<where>: "<value>" is not one of this brand's button styles; its styles are <list>, or leave it empty for the standard button (brand/brand.md, Buttons)`
- `<where>: this brand's kit records no button styles; leave it empty for the standard button (brand/brand.md, Buttons)`
- `<where>: "<value>" is not one of this brand's card styles; its styles are <list>, or leave it out for the standard card (brand/brand.md, Cards)`

### T-A9-4 — section-check refusals (site agent, `write_section`; Task 6b)

- `look "<value>" on kit.Button is not one of this brand's button styles; the styles are <list> (brand/brand.md, Buttons)`
- `look "<value>" on kit.Card is not one of this brand's card styles; the styles are <list> (brand/brand.md, Cards)`
- `class "<class>" is motion of your own; motion comes from the brand: kit.Button, kit.Link and kit.Card carry it, and a class from brand/brand.md (Motion) adds it to an element`
- `class "<class>" is not one of this brand's motion classes; its motion classes are <list> (brand/brand.md, Motion)`

### T-A9-5 — `writing-a-section` skill (site agent; carried by Lane B Task 4, reviewed in Lane B Task 0)

In `skills-e5/writing-a-section/SKILL.md`: the example's
`surface: z.enum(["page", "card", "muted", "brandSubtle", "brand", "inverse"]),` becomes
`surface: z.string(),`, and the kit list becomes:

```markdown
The kit gives you these pieces, with exactly these props:
- `<kit.Shell surface={...}>…</kit.Shell>`: the section and its surface (it sets the right text
  colour). `surface` is any surface in brand/brand.md.
- `<kit.Button label="…" href="…" surface={...} look="…" />`: a button. `look` is a button style
  from brand/brand.md (Buttons); leave it out for the kit's standard button. Its words go in `label`.
- `<kit.Link href="…">…</kit.Link>`: a text link, drawn like the seller's own links.
- `<kit.Card look="…" href="…">…</kit.Card>`: a card, drawn like the seller's own cards
  (brand/brand.md, Cards). With `href` the whole card is a link.
- `<kit.Eyebrow>…</kit.Eyebrow>`: the small label above a heading.
- `<kit.Image src="…" alt="…" />`: an image from brand/brand.md, by its file path. Add
  `fit="fill"` to make it cover a box you position, for a background photo, or `fit="contain"` to
  show the whole image. A logo is always shown whole.
- Motion: add a class from brand/brand.md (Motion) to an element, for example
  `className="brand-motion-pulse"`. Write no transition or animation of your own.
```

and the Rules bullet's "spacing through Tailwind's scale (`mt-6`, `gap-8`)" becomes "spacing
through the brand's spacing classes (`py-section`, `mt-stack-tight`, brand/brand.md) or Tailwind's
scale (`mt-6`, `gap-8`)".

### T-A9-6 — the brief agent's prompt (ingestion; Task X4)

`lumen_ingestion/brief_agent_prompt.md:72-75` today: "A background color the page recurs on is
minted as a `surface.band.*` token (`surface.band.statement` for a dark band, `surface.band.tint`
for a light one) — when the kit carries those, name the bands by them rather than by the nearest
approximation." Required replacement (the naming it describes changes):

> Every flat section background the page shows is a surface token: an existing `surface.*` token
> when one holds exactly that colour, otherwise a `surface.band.<hex>` token minted from it (for
> example `surface.band.014036`) — name the bands by them rather than by the nearest approximation.

Optional addition, after the `component_recipes[]` bullet (the plan works without it; it lets the
model's own recipe slots and notes use the exact tokens):

> The kit also carries tokens minted from those shape records, named for where they were measured
> (`button.solid-2.fill`, `card.solid-1.radius`); when a slot's measured value has one, name it.

### T-A9-7 — the marketer's dock (Lane C draws them with the existing select control)

- Field "Button style" on FeatureSplit and CtaBand, options: "Standard", then one per button style
  named by its kind — "Outline", "Text only", "Filled" — with a number only when a kind repeats
  ("Filled 1", "Filled 2"); a style whose variant is not `outline.N`/`ghost.N`/`solid.N` reads as its
  variant in words. The field is left out for a brand with no button styles.
- Field "Surface" on our four sections, options: the six as today ("Page", "Card", "Muted", "Brand,
  subtle", "Brand", "Inverse"), then this brand's other surfaces. **Label rule:** a kit surface's name
  reads as words (`surface.canvas` → "Canvas", `surface.elevated` → "Elevated", `surface.accent` →
  "Accent"); a minted section background `surface.band.<hex>` reads by what it measured — "Dark band"
  when its text is lighter than it, "Tinted band" when it is light and coloured (OKLCH chroma ≥ 0.04),
  "Light band" otherwise — numbered only when a kind repeats; an older kit's `surface.band.statement`
  / `surface.band.tint-2` reads "Statement band" / "Tint band 2". Labels come from the band data, not
  from the brief's prose notes (reading meaning out of model prose in code would be judgement in
  code). **Examples from the three real kits** (bands from their stored evidence; minted only after
  a re-extraction): Garner — Canvas, Elevated, Accent, "Dark band" (`#014036`, the forest statement
  band), "Light band" (`#FFFFFF`, the white shells; `surface.page` is `#F9FAF8`); Conduit — Canvas,
  Elevated, Accent, "Dark band" (`#28241E`, the procedures band; its white bands are `surface.page`
  exactly, so they mint nothing); Alt Carbon — Canvas, Elevated, Accent (both bands are `#F1F0DE`,
  `surface.page` exactly).

## Cross-lane changes

- **Lane B Task 8** (`lumen_api/site_brand.py`): BrandData drops `measured` (site-kit's type no
  longer has it — Task 5 here); `site_brand_data` stops emitting `"measured": None` and its two test
  assertions (`brand["measured"] is None`) go. The `kit` it passes must be the stored
  `brand_kit_json` whole — `brief`, `grammar_audit`, `measured_components` and `tokens.styles`
  included; Lane B adds one assertion that a kit carrying all four comes back in `brand["kit"]`
  unchanged. No other interface changes: every new value reaches site-kit inside `brand.kit`.
- **Lane B Task 15** (`bin/compile-section.ts`): `lint(source, { extraSurfaces: extraSurfaceRoles(brand) })`
  becomes `lint(source, lintOptionsFor(brand))` (exported by site-kit, Task 6b), so `write_section`
  checks looks and motion classes against the brand.
- **Lane B Task 4 / Task 0**: carry T-A9-5 into the ported `writing-a-section` skill after the
  founder's yes.
- **Lane C Task 9** (dock): no code change — `describeField` already turns a Puck `select`'s options
  into `FieldDescription.options` (`lane-c` plan `src/client/fields.ts`); add two assertions to its
  fields test: FeatureSplit's `buttonLook` is a select whose options come from the brand ("Standard"
  first), and `surface` lists the brand's extra surfaces after the six.
- **Lane A Tasks 17, 18, 22** (this lane): every screenshot and PDF context is created with
  `reduced_motion="reduce"` (Task 16b gives the one-line edits). Verified 2026-10-12: a scroll-driven
  reveal left an element at opacity 0 in a full-page screenshot without it.
- **Master plan, Wave 2 rulings** (`2026-10-09-website-agent-on-puck-integration.md:216-219`): the
  sentence "There is no production 'measured' button: button styles come from the kit's tokens,
  `brief.constraints` and `brief.component_recipes`" is superseded by the 2026-10-12 rulings; record
  "button and other component styles come from measured, kit-minted tokens named by
  `measured_components`, then the kit's tokens and recipes" there.
- **Frontend brand-context** (Task X6, owned here): a filter in `brand-context-mapping.ts`; Lane C
  does not touch that file.

## The state mechanism, and the offline probe that chose it

**Chosen:** real pointer hover (`locator.hover()`) for hover, falling back to CDP
`CSS.forcePseudoState(['hover'])` when the element cannot take the pointer; CDP forced
`['hover','active']` for pressed (no click is ever sent) and `['focus','focus-visible']` for focus,
with the pointer moved away first; `disabled`/`aria-disabled` set and restored for disabled; every
transition on the element and its descendants switched off inline through the CSSOM first (a page CSP
cannot block CSSOM writes), and script-driven hovers read every 50 ms until two reads agree. Why: CDP
forcing alone never runs `mouseenter` handlers; pointer input alone cannot press without clicking (a
click follows links) and does not give `:focus-visible` deterministically after mouse input.

**Offline probe, 2026-10-12** (a local fixture page in the session scratchpad; no network; Playwright
1.61.0 and patchright 1.61.2, both headless Chromium):

| case | result (identical on both engines) |
|---|---|
| CSS `:hover` (background, shadow) | read: `rgb(3, 90, 78)`, `rgba(0, 0, 0, 0.2) 0px 4px 12px 0px` |
| CSS `:active` | read: `rgb(2, 63, 55)`, `matrix(0.98, 0, 0, 0.98, 0, 0)`; no click fired (`__clicked` 0) |
| `:focus-visible` | read: `3px solid rgb(245, 166, 35)`, offset 2; a site with none reads the browser's `1px auto rgb(0, 95, 204)` (recorded as "browser ring", never a value) |
| JS `mouseenter` hover | read: class toggled, background `rgb(90, 47, 214)` |
| transform on hover with a 250 ms transition | read the end value at once: `matrix(1, 0, 0, 1, 0, -2)` |
| icon moving on hover | read: svg `matrix(1, 0, 0, 1, 4, 0)` |
| disabled (forced) | read: opacity 0.45, cursor not-allowed |
| element covered by an overlay | pointer timed out at 1.2 s; forced `:hover` read the CSS look |
| restoration | every look identical to rest afterwards; full-page screenshot byte-identical before/after |
| `@keyframes` in use | `pulse 1.6s ease-in-out infinite alternate`, definition read |
| CSS reveal (IntersectionObserver adds a class) | before scroll opacity 0 + `matrix(1,0,0,1,0,24)`; after, opacity 1, class `is-in` added, transition `opacity, transform 0.6s ease-out` |
| `requestAnimationFrame` inline transform | detected as scripted motion |
| cost | 99–136 ms per element with a pointer hover |

Tailwind 4.3.3 was also checked offline: `@theme inline { --spacing-section: var(--brand-space-section) }`
makes `py-section`, `mt-stack-tight`, `gap-stack-tight` and `p-card-padding` real utilities.

## Order and ownership

| block | tasks | lane | before / after |
|---|---|---|---|
| Extraction | X1 engine `styles` group → X2 probe → X3 evidence → X4 mint (+ bands) → X5 kit section, pipeline, republish fix, site-kit fixtures → X6 panel filter | A (design subsystem; X6 frontend) | independent of A0; X5 before Task 4 (its fixtures) |
| site-kit | Task 4 values, surfaces, looks, theme → Task 5 components and schema → Task 6 (as written in the Lane A plan) → Task 6b validator and lint → Task 7 brand.md | A | after Lane A Tasks 1–3; all before Task 15 |
| Renderer check | Task 16b | A | after Lane A Tasks 16 and 17 |
| Carried elsewhere | Lane B Tasks 8, 15, 4/0; Lane C Task 9 assertions | B, C | B Task 15 needs Task 6b |

## Constraints specific to this block

- Never run a brand-kit extraction against a real site, never call a paid model, never write to the
  lane database. Every capture test drives the local fixture page through `file://`.
- Design DB suites (`test_api.py`) only on `clue_trenton_wave1`, design stack down.
- Engine change gate (`subsystems/clue-design/AGENTS.md` §3): `cargo test --workspace` (after the
  untracked raster goldens and visual baselines are generated from the base commit in a temp
  worktree — never from HEAD), `cargo build -p lumen-api-helper --release`, the wasm rebuild, then
  the focused Python files below; the full design suite at most once, in the background. Never
  `cargo fmt --all`: `rustfmt --edition 2021 --check <file>` on touched files only; stage by explicit
  path. Commit the rebuilt tracked wasm deliberately.
- New code constants that bound work (caps, deadlines) are constants with a stated reason, not env
  flags; this block adds no runtime flag, so `.env.example` is untouched.
- `CAPTURE_PYTEST <file>` below stands for `DESIGN_PYTEST <file>` without the database: from
  `subsystems/clue-design`,
  `LUMEN_INGESTION_DESCRIBE=0 LUMEN_INGESTION_VISION=0 PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest apps/api/tests/<file> -q -o addopts="" --ignore-glob='*_live.py'`.

## File structure

```
subsystems/clue-design/crates/lumen-core/src/brand.rs           MODIFY  TokenCatalog.styles, StyleToken, validation
subsystems/clue-design/crates/lumen-core/src/lib.rs             MODIFY  exports
subsystems/clue-design/crates/lumen-core/tests/brand_style_tokens.rs   CREATE
subsystems/clue-design/crates/lumen-core/tests/brand_tokens.rs  MODIFY  struct literal gains styles
subsystems/clue-design/apps/editor/public/wasm/lumen_wasm{.js,_bg.wasm}  REBUILD (tracked)
subsystems/clue-design/apps/api/lumen_ingestion/
  capture/geometry.py        MODIFY  link/nav_link classes, probe marks, section ink, animations, shape_groups, styles
  capture/states.py          CREATE  per-style states, motion, reveals, scripted motion
  capture/motion.py          CREATE  keyframe definitions from stylesheets, icon svg cleaning
  capture/rendered.py        MODIFY  reveal snapshot before scroll, state pass after geometry
  capture/__init__.py        MODIFY  states measured on the entry page only
  capture/evidence_builder.py MODIFY keyframes attached to motion evidence
  evidence.py                MODIFY  StyleLook, MeasuredStyle, MotionEvidence…, SectionBackground.ink
  normalizer/component_tokens.py CREATE minting (exact reuse, names, caps)
  normalizer/bands.py        REWRITE value-keyed exact band surfaces + inks
  normalizer/__init__.py     MODIFY  band inks and pairs, minting, NormalizeResult.measured_components
  measured_components.py     CREATE  MeasuredComponents@1 model and token-law check
  brief.py                   MODIFY  "styles" in the token groups
  brief_agent.py             MODIFY  brief input unchanged by ink and minted spacing
  brief_agent_prompt.md      MODIFY  band paragraph (T-A9-6, after approval)
  pipeline.py                MODIFY  attach measured_components
subsystems/clue-design/apps/api/lumen_api/brand_kit_sections.py  CREATE  carry kit sections across re-validation
subsystems/clue-design/apps/api/lumen_api/main.py                MODIFY  logo + describe-assets routes
subsystems/clue-design/scripts/build_site_kit_brand_fixtures.py  CREATE  site-kit fixture kits from real values
subsystems/clue-design/apps/api/tests/  fixtures/capture/style_states.html, test_capture_style_states.py,
  test_ingestion_measured_styles.py, test_ingestion_component_tokens.py, test_measured_components.py,
  test_kit_style_tokens_engine.py, test_brand_kit_sections_carry.py, test_site_state_css.py (16b);
  MODIFY test_ingestion_geometry.py, test_ingestion_brief.py, test_ingestion_grammar_audit.py, test_api.py
apps/frontend/src/features/brand-context/model/brand-context-mapping{.ts,.test.ts}  MODIFY (X6)
apps/frontend/packages/site-kit/
  src/brand-values.ts  CREATE  token resolution, colour maths, FALLBACKS
  src/surfaces.ts      CREATE  surfaces, inks, choices, labels
  src/looks.ts         CREATE  recipes + measured recipes → looks, drawn parts, motion
  src/theme.ts         REWRITE themeCss, tailwindThemeCss from the above
  src/brand.ts         MODIFY  BrandData without `measured`
  src/sections.tsx, src/shell.tsx, src/agent-kit.tsx  REWRITE
  src/config.tsx, src/schemas.ts, src/validate.ts, src/check-section.ts, src/catalog.ts, src/index.ts  MODIFY
  test/fixtures/kits/{garner,conduit,altcarbon,garner.minted,conduit.minted,probe.minted}.json  CREATE (by Task X5's script)
  test/fixtures/{kits.ts,write-probe-page.tsx}  CREATE
  test/{looks,theme,style-literals,brand-md}.test.ts, test/{agent-kit,sections,probe-page}.test.tsx  CREATE
  test/fixtures/garner.ts, test/{check-section,catalog,contracts,multipage}.test.ts  MODIFY; test/fixtures/measured.json  DELETE
```

---
## A9-X — the extraction measures states and motion, and mints them as kit tokens

### Task X1: The kit's `styles` token group in the engine (lumen-core)

`TokenCatalog` (`crates/lumen-core/src/brand.rs:1189-1212`) has typed groups only, and
`validate_brand_kit` re-serializes through it, so a group or field it does not know never comes back
(the pipeline persists what comes back, `lumen_ingestion/pipeline.py:1075`). Keywords (case, cursor,
decoration, border style), durations, easings, transforms, keyframes, animation and reveal entries
and button icons have no typed home; this task gives them one.

**Files:**
- Modify: `subsystems/clue-design/crates/lumen-core/src/brand.rs` (`TokenCatalog`, new types,
  `validate_token_keys`, `validate_brand_kit`, new `validate_style_tokens`)
- Modify: `subsystems/clue-design/crates/lumen-core/src/lib.rs` (exports)
- Modify: `subsystems/clue-design/crates/lumen-core/tests/brand_tokens.rs:2166` (the one
  `TokenCatalog { … }` literal in the workspace)
- Create: `subsystems/clue-design/crates/lumen-core/tests/brand_style_tokens.rs`
- Create: `subsystems/clue-design/apps/api/tests/test_kit_style_tokens_engine.py`
- Rebuild (tracked): `subsystems/clue-design/apps/editor/public/wasm/lumen_wasm.js`,
  `lumen_wasm_bg.wasm`

**Interfaces:**
- Produces: `TokenCatalog.styles: BTreeMap<String, StyleToken>` (serde default, omitted when empty);
  `StyleToken { value: ModeValue<StyleTokenValue>, description, provenance }`;
  `StyleTokenValue::{Keyword{property, value}, Duration{ms}, Easing{function}, Transform{value},
  Keyframes{frames}, Animation{keyframes, duration, easing, delay, iterations, direction, fill_mode},
  Reveal{from_opacity, from_transform, duration, easing}, Glyph{text}, Svg{markup, width, height},
  Alias{token}}` (JSON `"kind"` snake_case); `KeyframeStep { offset, declarations }`; diagnostics
  `LUMB0260`–`LUMB0266` (errors). The rules are mirrored in Python (`component_tokens.py`, Task X4),
  which never mints a value the engine would refuse.

- [ ] **Step 1: Write the failing Rust test** `crates/lumen-core/tests/brand_style_tokens.rs`:

```rust
//! The kit's `styles` token group (Wave 2 A9): measured values the typed groups cannot hold.
use lumen_core::{validate_brand_kit, BrandKit, DiagnosticSeverity, StyleTokenValue};
use serde_json::{json, Value};

const ACME_BRAND_KIT: &str = include_str!("../fixtures/brand_kits/acme_full.json");

fn token(value: Value) -> Value {
    json!({
        "value": {"default": value, "modes": {}},
        "description": null,
        "provenance": {"source": "website:https://example.test/ :: button solid.1 rest", "confidence": 0.8}
    })
}

fn kit_with(styles: Value) -> BrandKit {
    let mut kit: Value = serde_json::from_str(ACME_BRAND_KIT).unwrap();
    kit["tokens"]["styles"] = styles;
    serde_json::from_value(kit).unwrap()
}

fn errors(kit: &BrandKit) -> Vec<String> {
    validate_brand_kit(kit)
        .into_iter()
        .filter(|diagnostic| diagnostic.severity == DiagnosticSeverity::Error)
        .map(|diagnostic| diagnostic.code)
        .collect()
}

const ICON: &str = "<svg viewBox=\"0 0 12 12\" fill=\"none\"><path d=\"M1 6h9M7 2l4 4-4 4\" stroke=\"currentColor\" stroke-width=\"1.5\"></path></svg>";

fn valid_styles() -> Value {
    json!({
        "button.solid-1.case": token(json!({"kind": "keyword", "property": "text-transform", "value": "uppercase"})),
        "button.solid-1.hover.shadow": token(json!({"kind": "keyword", "property": "box-shadow", "value": "none"})),
        "motion.button.solid-1.duration-1": token(json!({"kind": "duration", "ms": 200.0})),
        "motion.button.solid-1.easing-1": token(json!({"kind": "easing", "function": "cubic-bezier(0.2, 0.8, 0.2, 1)"})),
        "button.solid-1.hover.transform": token(json!({"kind": "transform", "value": "matrix(1, 0, 0, 1, 0, -2)"})),
        "button.solid-1.icon": token(json!({"kind": "glyph", "text": "→"})),
        "button.outline-1.icon": token(json!({"kind": "svg", "markup": ICON, "width": 12.0, "height": 12.0})),
        "motion.keyframes.pulse": token(json!({"kind": "keyframes", "frames": [
            {"offset": 0.0, "declarations": {"opacity": "1", "transform": "scale(1)"}},
            {"offset": 100.0, "declarations": {"opacity": "0.4", "transform": "scale(1.2)"}}
        ]})),
        "motion.animation.pulse.duration": token(json!({"kind": "duration", "ms": 1600.0})),
        "motion.animation.pulse.easing": token(json!({"kind": "easing", "function": "ease-in-out"})),
        "motion.animation.pulse": token(json!({"kind": "animation", "keyframes": "motion.keyframes.pulse",
            "duration": "motion.animation.pulse.duration", "easing": "motion.animation.pulse.easing",
            "delay": null, "iterations": "infinite", "direction": "alternate", "fill_mode": "none"})),
        "motion.reveal.3f2a91c0.from-transform": token(json!({"kind": "transform", "value": "matrix(1, 0, 0, 1, 0, 24)"})),
        "motion.reveal.3f2a91c0": token(json!({"kind": "reveal", "from_opacity": null,
            "from_transform": "motion.reveal.3f2a91c0.from-transform",
            "duration": "motion.animation.pulse.duration", "easing": "motion.animation.pulse.easing"})),
    })
}

#[test]
fn a_kit_with_measured_style_tokens_validates_and_round_trips() {
    let kit = kit_with(valid_styles());
    assert_eq!(errors(&kit), Vec::<String>::new());
    assert!(matches!(
        kit.tokens.styles["button.solid-1.case"].value.default,
        StyleTokenValue::Keyword { .. }
    ));
    let json = serde_json::to_value(&kit).unwrap();
    assert_eq!(
        json["tokens"]["styles"]["motion.animation.pulse"]["value"]["default"]["iterations"],
        "infinite"
    );
    let back: BrandKit = serde_json::from_value(json).unwrap();
    assert_eq!(back, kit);
}

#[test]
fn a_kit_without_style_tokens_serializes_exactly_as_before() {
    let original: Value = serde_json::from_str(ACME_BRAND_KIT).unwrap();
    let kit: BrandKit = serde_json::from_value(original).unwrap();
    let json = serde_json::to_value(&kit).unwrap();
    assert!(json["tokens"].get("styles").is_none(), "an empty styles group is omitted");
}

#[test]
fn each_unsafe_or_dangling_style_token_is_refused_by_its_code() {
    let cases = [
        ("LUMB0260", json!({"kind": "keyword", "property": "background-image", "value": "none"})),
        ("LUMB0260", json!({"kind": "keyword", "property": "cursor", "value": "url(x.cur), auto"})),
        ("LUMB0260", json!({"kind": "keyword", "property": "box-shadow", "value": "0 0 2px red"})),
        ("LUMB0261", json!({"kind": "duration", "ms": -1.0})),
        ("LUMB0262", json!({"kind": "easing", "function": "bounce"})),
        ("LUMB0263", json!({"kind": "transform", "value": "translateX(4px)"})),
        ("LUMB0264", json!({"kind": "keyframes", "frames": [
            {"offset": 0.0, "declarations": {"background-image": "url(x)"}},
            {"offset": 100.0, "declarations": {"opacity": "1"}}
        ]})),
        ("LUMB0265", json!({"kind": "glyph", "text": "<b>"})),
        ("LUMB0265", json!({"kind": "svg", "markup": "<svg onload=\"x()\"></svg>", "width": 12.0, "height": 12.0})),
        ("LUMB0265", json!({"kind": "svg", "markup": "<svg><use href=\"#a\"></use></svg>", "width": 12.0, "height": 12.0})),
        ("LUMB0266", json!({"kind": "animation", "keyframes": "motion.keyframes.missing", "duration": "x",
            "easing": "y", "delay": null, "iterations": "1", "direction": "normal", "fill_mode": "none"})),
    ];
    for (code, value) in cases {
        let kit = kit_with(json!({"button.solid-1.case": token(value.clone())}));
        assert!(errors(&kit).contains(&code.to_owned()), "{code} for {value}");
    }
    let bad_key = kit_with(json!({"button solid": token(json!({"kind": "duration", "ms": 1.0}))}));
    assert!(errors(&bad_key).contains(&"LUMB0120".to_owned()));
}
```

- [ ] **Step 2: Run it to see it fail.**

Run: `cd subsystems/clue-design && cargo test -p lumen-core --test brand_style_tokens`
Expected: FAIL to compile — no `StyleTokenValue` in `lumen_core`, no field `styles` on `TokenCatalog`.

- [ ] **Step 3: Add the group to `brand.rs`.**
  1. In `pub struct TokenCatalog` after `pub aliases: BTreeMap<String, TokenAlias>,` add:

```rust
    /// Measured style values the typed groups cannot hold (Wave 2 A9): keywords (case, cursor,
    /// decoration, border style…), durations, easings, transforms, keyframes, animation and reveal
    /// entries, and button icons. Minted by ingestion only; omitted when empty, so every kit without
    /// them serializes exactly as before.
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub styles: BTreeMap<String, StyleToken>,
```
  2. After `pub struct TokenProvenance { … }` add:

```rust
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct StyleToken {
    pub value: ModeValue<StyleTokenValue>,
    pub description: Option<String>,
    pub provenance: Option<TokenProvenance>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct KeyframeStep {
    pub offset: f64,
    #[serde(default)]
    pub declarations: BTreeMap<String, String>,
}

/// One measured style value. Entries that combine others (`Animation`, `Reveal`) name them, the
/// way an effect names its shadow token.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum StyleTokenValue {
    Keyword { property: String, value: String },
    Duration { ms: f64 },
    Easing { function: String },
    Transform { value: String },
    Keyframes { frames: Vec<KeyframeStep> },
    Animation {
        keyframes: String,
        duration: String,
        easing: String,
        #[serde(default)]
        delay: Option<String>,
        iterations: String,
        direction: String,
        fill_mode: String,
    },
    Reveal {
        #[serde(default)]
        from_opacity: Option<String>,
        #[serde(default)]
        from_transform: Option<String>,
        duration: String,
        easing: String,
    },
    Glyph { text: String },
    Svg { markup: String, width: f64, height: f64 },
    Alias { token: String },
}

/// The CSS properties a keyword token may carry. Each value is a plain keyword list
/// (`uppercase`, `pointer`, `underline`), never free CSS; `box-shadow` only ever as `none`
/// (a state that removes the rest shadow).
const STYLE_KEYWORD_PROPERTIES: &[&str] = &[
    "text-transform",
    "text-decoration-line",
    "text-decoration-thickness",
    "text-underline-offset",
    "cursor",
    "border-style",
    "outline-style",
    "transition-property",
    "filter",
    "box-shadow",
];
/// What a measured keyframe may animate: compositing and paint properties only.
const KEYFRAME_PROPERTIES: &[&str] = &[
    "opacity",
    "transform",
    "translate",
    "scale",
    "rotate",
    "filter",
    "color",
    "background-color",
    "border-color",
    "box-shadow",
    "background-position",
];
const ANIMATION_DIRECTIONS: &[&str] = &["normal", "reverse", "alternate", "alternate-reverse"];
const ANIMATION_FILL_MODES: &[&str] = &["none", "forwards", "backwards", "both"];
const MAX_STYLE_TEXT: usize = 400;
const MAX_KEYFRAME_STEPS: usize = 32;
const MAX_KEYFRAME_DECLARATIONS: usize = 12;
const MAX_ICON_SVG_BYTES: usize = 4096;

fn style_text_ok(value: &str, max: usize) -> bool {
    let lower = value.to_ascii_lowercase();
    !value.trim().is_empty()
        && value.len() <= max
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b" ,.()%#+-/".contains(&byte))
        && !lower.contains("url(")
        && !lower.contains("var(")
        && !lower.contains("expression")
}

fn style_keyword_ok(property: &str, value: &str) -> bool {
    STYLE_KEYWORD_PROPERTIES.contains(&property)
        && style_text_ok(value, 200)
        && (property != "box-shadow" || value == "none")
}

fn easing_ok(function: &str) -> bool {
    matches!(
        function,
        "linear" | "ease" | "ease-in" | "ease-out" | "ease-in-out" | "step-start" | "step-end"
    ) || ((function.starts_with("cubic-bezier(")
        || function.starts_with("steps(")
        || function.starts_with("linear("))
        && function.ends_with(')')
        && style_text_ok(function, MAX_STYLE_TEXT))
}

fn transform_ok(value: &str) -> bool {
    if value == "none" {
        return true;
    }
    let inner = value
        .strip_prefix("matrix(")
        .or_else(|| value.strip_prefix("matrix3d("))
        .and_then(|rest| rest.strip_suffix(')'));
    match inner {
        Some(args) => {
            !args.is_empty()
                && args.len() <= MAX_STYLE_TEXT
                && args.bytes().all(|byte| byte.is_ascii_digit() || b" ,.-e".contains(&byte))
        }
        None => false,
    }
}

fn keyframes_ok(frames: &[KeyframeStep]) -> bool {
    (2..=MAX_KEYFRAME_STEPS).contains(&frames.len())
        && frames.iter().all(|frame| {
            finite_in_range(frame.offset, 0.0, 100.0)
                && !frame.declarations.is_empty()
                && frame.declarations.len() <= MAX_KEYFRAME_DECLARATIONS
                && frame.declarations.iter().all(|(property, value)| {
                    KEYFRAME_PROPERTIES.contains(&property.as_str()) && style_text_ok(value, 200)
                })
        })
}

fn glyph_ok(text: &str) -> bool {
    let count = text.chars().count();
    (1..=4).contains(&count) && !text.chars().any(|c| c.is_control() || "<>&\"'".contains(c))
}

fn has_event_attribute(lower: &str) -> bool {
    lower.match_indices(" on").any(|(index, _)| {
        let rest = &lower[index + 3..];
        let name = rest.bytes().take_while(|byte| byte.is_ascii_alphabetic()).count();
        name > 0 && rest[name..].trim_start().starts_with('=')
    })
}

fn icon_svg_ok(markup: &str) -> bool {
    let lower = markup.to_ascii_lowercase();
    let trimmed = lower.trim();
    markup.len() <= MAX_ICON_SVG_BYTES
        && trimmed.starts_with("<svg")
        && trimmed.ends_with("</svg>")
        && ![
            "<script", "javascript:", "url(", "href", "<foreignobject", "<!", "<?", "<style", "<use",
            "<image", "<a ", "<a>",
        ]
        .iter()
        .any(|bad| lower.contains(bad))
        && !has_event_attribute(&lower)
}

fn iterations_ok(value: &str) -> bool {
    value == "infinite"
        || value
            .parse::<f64>()
            .map(|count| count.is_finite() && count > 0.0 && count <= 1000.0)
            .unwrap_or(false)
}

fn validate_style_tokens(brand_kit: &BrandKit, diagnostics: &mut Vec<Diagnostic>) {
    let styles = &brand_kit.tokens.styles;
    let is_kind = |name: &str, want: fn(&StyleTokenValue) -> bool| {
        styles.get(name).map(|token| want(&token.value.default)).unwrap_or(false)
    };
    let is_duration = |value: &StyleTokenValue| matches!(value, StyleTokenValue::Duration { .. });
    let is_easing = |value: &StyleTokenValue| matches!(value, StyleTokenValue::Easing { .. });
    for (path, token) in styles {
        validate_mode_keys(path, &token.value.modes, &brand_kit.modes, diagnostics);
        for value in std::iter::once(&token.value.default).chain(token.value.modes.values()) {
            let problem: Option<(&str, &str)> = match value {
                StyleTokenValue::Keyword { property, value } if !style_keyword_ok(property, value) => {
                    Some(("LUMB0260", "an invalid keyword"))
                }
                StyleTokenValue::Duration { ms } if !finite_in_range(*ms, 0.0, 60_000.0) => {
                    Some(("LUMB0261", "an invalid duration"))
                }
                StyleTokenValue::Easing { function } if !easing_ok(function) => {
                    Some(("LUMB0262", "an invalid easing"))
                }
                StyleTokenValue::Transform { value } if !transform_ok(value) => {
                    Some(("LUMB0263", "an invalid transform"))
                }
                StyleTokenValue::Keyframes { frames } if !keyframes_ok(frames) => {
                    Some(("LUMB0264", "invalid keyframes"))
                }
                StyleTokenValue::Glyph { text } if !glyph_ok(text) => {
                    Some(("LUMB0265", "an invalid icon glyph"))
                }
                StyleTokenValue::Svg { markup, width, height }
                    if !icon_svg_ok(markup)
                        || !finite_in_range(*width, 1.0, 256.0)
                        || !finite_in_range(*height, 1.0, 256.0) =>
                {
                    Some(("LUMB0265", "an invalid icon svg"))
                }
                StyleTokenValue::Animation {
                    keyframes,
                    duration,
                    easing,
                    delay,
                    iterations,
                    direction,
                    fill_mode,
                } => {
                    let refs = is_kind(keyframes, |v| matches!(v, StyleTokenValue::Keyframes { .. }))
                        && is_kind(duration, is_duration)
                        && is_kind(easing, is_easing)
                        && delay.as_deref().map_or(true, |name| is_kind(name, is_duration));
                    if !refs {
                        Some(("LUMB0266", "a reference to a missing or wrong-kind token"))
                    } else if !iterations_ok(iterations)
                        || !ANIMATION_DIRECTIONS.contains(&direction.as_str())
                        || !ANIMATION_FILL_MODES.contains(&fill_mode.as_str())
                    {
                        Some(("LUMB0264", "an invalid animation"))
                    } else {
                        None
                    }
                }
                StyleTokenValue::Reveal { from_opacity, from_transform, duration, easing } => {
                    let refs = from_opacity
                        .as_deref()
                        .map_or(true, |name| brand_kit.tokens.opacity.contains_key(name))
                        && from_transform.as_deref().map_or(true, |name| {
                            is_kind(name, |v| matches!(v, StyleTokenValue::Transform { .. }))
                        })
                        && is_kind(duration, is_duration)
                        && is_kind(easing, is_easing);
                    (!refs).then_some(("LUMB0266", "a reference to a missing or wrong-kind token"))
                }
                StyleTokenValue::Alias { token } if !styles.contains_key(token) => {
                    Some(("LUMB0266", "a reference to a missing or wrong-kind token"))
                }
                _ => None,
            };
            if let Some((code, what)) = problem {
                diagnostics.push(brand_error(code, format!("style token {} has {}", path, what)));
            }
        }
    }
}
```
  3. In `validate_token_keys` add, after the alias line:
     `validate_map_keys("style", tokens.styles.keys(), diagnostics);`
  4. In `pub fn validate_brand_kit`, after `validate_token_values(brand_kit, &mut diagnostics);` add
     `validate_style_tokens(brand_kit, &mut diagnostics);`
  5. In `lib.rs`'s `pub use brand::{ … }` list add `KeyframeStep, StyleToken, StyleTokenValue,`
     (alphabetical places: after `FontStyle,` and after `ShadowValue,`).
  6. In `tests/brand_tokens.rs`, in the `tokens: TokenCatalog { … }` literal, after the `aliases`
     entry add `styles: BTreeMap::new(),`.

- [ ] **Step 4: Run the engine tests.**

Run: `cd subsystems/clue-design && cargo test -p lumen-core --test brand_style_tokens --test brand_tokens`
Expected: PASS (3 new tests; `brand_tokens` unchanged).
Run: `rustfmt --edition 2021 --check crates/lumen-core/src/brand.rs crates/lumen-core/tests/brand_style_tokens.rs crates/lumen-core/tests/brand_tokens.rs`
Expected: no output for your hunks (fix only your own hunks if it reports any).

- [ ] **Step 5: Rebuild the helper and write the Python round-trip test**
  `apps/api/tests/test_kit_style_tokens_engine.py`:

```python
"""The kit's `styles` token group survives the real engine round trip (Wave 2 A9, Task X1).

`validate_brand_kit` re-serializes a kit through the typed Rust `TokenCatalog`, and the pipeline
persists what comes back — a group the engine did not know used to vanish here.
"""

from __future__ import annotations

import json
from pathlib import Path

from lumen_api.core import CoreClient

GARNER = (
    Path(__file__).resolve().parents[5] / "trials" / "puck-spike" / "data" / "brands" / "garner" / "kit.json"
)


def _token(value: dict) -> dict:
    return {
        "value": {"default": value, "modes": {}},
        "description": None,
        "provenance": {"source": "website:https://example.test/ :: button solid.1 rest case", "confidence": 0.8},
    }


def _kit() -> dict:
    kit = json.loads(GARNER.read_text())
    kit["tokens"]["styles"] = {
        "button.solid-1.case": _token({"kind": "keyword", "property": "text-transform", "value": "uppercase"}),
        "motion.button.solid-1.duration-1": _token({"kind": "duration", "ms": 200.0}),
    }
    return kit


def test_style_tokens_come_back_from_the_engine_unchanged() -> None:
    kit = _kit()
    validation = CoreClient().validate_brand_kit(kit, product_ready=False, raise_on_error=False)
    assert validation["ok"] is True
    assert validation["brand_kit"]["tokens"]["styles"] == kit["tokens"]["styles"]


def test_a_kit_without_style_tokens_comes_back_without_the_group() -> None:
    kit = _kit()
    del kit["tokens"]["styles"]
    validation = CoreClient().validate_brand_kit(kit, product_ready=False, raise_on_error=False)
    assert "styles" not in validation["brand_kit"]["tokens"]


def test_the_engine_refuses_a_style_token_ingestion_would_never_mint() -> None:
    kit = _kit()
    kit["tokens"]["styles"]["button.solid-1.case"]["value"]["default"] = {
        "kind": "keyword",
        "property": "background-image",
        "value": "url(x)",
    }
    validation = CoreClient().validate_brand_kit(kit, product_ready=False, raise_on_error=False)
    errors = {d["code"] for d in validation["diagnostics"] if d["severity"] == "error"}
    assert "LUMB0260" in errors
```

Run: `cd subsystems/clue-design && cargo build -p lumen-api-helper --release && cd - && CAPTURE_PYTEST test_kit_style_tokens_engine.py`
Expected: `3 passed`.

- [ ] **Step 6: The engine gate.**
  1. Untracked goldens from the base commit (never from HEAD):
     `git worktree add /tmp/a9-base $(git merge-base HEAD puck/integration-wave1)` then, inside
     `/tmp/a9-base/subsystems/clue-design`, with
     `CARGO_TARGET_DIR=<this worktree>/subsystems/clue-design/target`:
     `UPDATE_SKIA_GOLDENS=1 cargo test -p lumen-skia --test raster_golden` and
     `UPDATE_LUMEN_VISUAL_BASELINES=1 cargo test -p lumen-skia --test visual_regression`; copy the
     written PNGs into the same paths here; `git worktree remove --force /tmp/a9-base`. Never stage
     them.
  2. `cd subsystems/clue-design && cargo test --workspace` — Expected: all pass (no golden drift:
     the change is additive and omitted when empty).
  3. `./scripts/build_wasm_core.sh` — Expected: `OK: wasm bundle within budget`.
  4. `CAPTURE_PYTEST test_ingestion_asset_slurp.py` and `CAPTURE_PYTEST test_kit_style_tokens_engine.py`
     — Expected: pass. Launch the full design suite once in the background and compare its reds
     with the documented pre-existing ones before the X-block's last commit.

- [ ] **Step 7: Commit.**

```bash
git add subsystems/clue-design/crates/lumen-core/src/brand.rs subsystems/clue-design/crates/lumen-core/src/lib.rs \
  subsystems/clue-design/crates/lumen-core/tests/brand_style_tokens.rs subsystems/clue-design/crates/lumen-core/tests/brand_tokens.rs \
  subsystems/clue-design/apps/api/tests/test_kit_style_tokens_engine.py \
  subsystems/clue-design/apps/editor/public/wasm/lumen_wasm.js subsystems/clue-design/apps/editor/public/wasm/lumen_wasm_bg.wasm
git commit -m "lumen-core: a styles token group for measured keywords, durations, easings, transforms, keyframes and icons, so they survive the kit round trip"
```

### Task X2: The capture measures every style in rest, hover, pressed, focus and disabled, with its motion

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/capture/geometry.py` (`GEOMETRY_JS`,
  `shape_key`, `shape_groups`, `state_targets`, `_read_surface`, `_cluster_shapes`)
- Create: `subsystems/clue-design/apps/api/lumen_ingestion/capture/states.py`
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/capture/rendered.py` (`_harvest_page`,
  `fetch_rendered`, both backends)
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/capture/__init__.py` (`_capture_page`,
  `capture_website`)
- Create: `subsystems/clue-design/apps/api/tests/fixtures/capture/style_states.html`
- Create: `subsystems/clue-design/apps/api/tests/fixtures/capture/make_style_states_harvest.py`
  and the JSON it writes, `style_states.harvest.json`
- Create: `subsystems/clue-design/apps/api/tests/test_capture_style_states.py`

**Interfaces:**
- Produces: `GEOMETRY_JS` records carry `idx` and `disabled`, mark each measured element
  `data-lumen-probe="<idx>"`, add classes `nav_link` and `link`, sections carry `ink`, and the harvest
  carries `animations`; `shape_key(entry)`, `shape_groups(surfaces, classes) -> [(variant, members)]`,
  `state_targets(surfaces) -> [((cls, variant), [idx…])]`, `STATE_TARGET_CAPS`,
  `STYLE_ONLY_SURFACES`; `states.probe_states(page, geometry, *, reveal_before, diagnostics) -> dict`
  (`{"styles": [...], "reveals": [...], "scripted": [...], "truncated": bool}`, stored as
  `harvest["geometry"]["states"]`), `REVEAL_BEFORE_JS`, `look_delta(rest, other)`; diagnostics
  `LUMI0543` (no CDP session, warning) and `LUMI0544` (deadline reached, info);
  `fetch_rendered(..., measure_states=False)`.

- [ ] **Step 1: Write the fixture page** `apps/api/tests/fixtures/capture/style_states.html`:

```html
<!doctype html>
<html><head><meta charset="utf-8"><title>Style states fixture</title>
<style>
  body { margin: 0; font-family: Arial, sans-serif; background: #fff; color: #111; }
  header { display: flex; gap: 24px; padding: 16px 40px; }
  header a { color: #0d2b25; text-decoration: none; transition: color 150ms ease; }
  header a:hover { color: #047464; }
  .wrap { padding: 40px; display: flex; gap: 24px; flex-wrap: wrap; align-items: center; }
  .btn { display: inline-flex; align-items: center; gap: 8px; padding: 12px 24px; border-radius: 999px;
         background: #047464; color: #fff; border: 1px solid #047464; font: 500 14px/1.4 Arial;
         letter-spacing: 0.02em; text-transform: uppercase; text-decoration: none; cursor: pointer;
         transition: background-color 200ms ease-out, transform 150ms ease, box-shadow 300ms ease 50ms; }
  .btn:hover { background: #035a4e; box-shadow: 0 4px 12px rgba(0,0,0,.2); }
  .btn:active { background: #023f37; transform: scale(0.98); }
  .btn:focus-visible { outline: 3px solid #f5a623; outline-offset: 2px; }
  .btn:disabled, .btn[aria-disabled="true"] { opacity: 0.45; cursor: not-allowed; }
  .btn svg { transition: transform 200ms ease; }
  .btn:hover svg { transform: translateX(4px); }
  .outline { background: transparent; color: #0d2b25; border: 1px solid #0d2b25; }
  .outline:hover { background: #0d2b25; color: #fff; }
  .outline .label { color: #0d2b25; }
  .outline:hover .label { color: #fff; }
  .lift { background: #28241e; color: #fff; border-radius: 8px; border: 0; transition: transform 250ms cubic-bezier(.2,.8,.2,1); }
  .lift:hover { transform: translateY(-2px); }
  .jsbtn { background: #7c4cff; color: #fff; border-radius: 6px; padding: 10px 18px; border: 0; }
  .jsbtn.is-hot { background: #5a2fd6; }
  .covered { position: relative; }
  .covered .shield { position: absolute; inset: -4px; background: rgba(255,255,255,0.01); }
  .covered .btn { background: #0a4a8a; border-color: #0a4a8a; }
  .covered .btn:hover { background: #083a6c; }
  a.text { color: #0d2b25; text-decoration: none; text-underline-offset: 4px; transition: color 120ms linear; }
  a.text:hover { text-decoration: underline; text-decoration-thickness: 2px; color: #047464; }
  article { width: 240px; padding: 24px; border-radius: 12px; background: #f1f0de; transition: box-shadow 200ms ease; }
  article:hover { box-shadow: 0 8px 24px rgba(0,0,0,.12); }
  .pulse { width: 40px; height: 40px; border-radius: 50%; background: #f5a623; animation: pulse 1.6s ease-in-out 0s infinite alternate; }
  @keyframes pulse { from { transform: scale(1); opacity: 1; } 50% { opacity: .7; } to { transform: scale(1.2); opacity: .4; } }
  .spacer { height: 2400px; }
  section.band { padding: 60px 40px; background: #014036; color: #fff; }
  .reveal { opacity: 0; transform: translateY(24px); transition: opacity 600ms ease-out, transform 600ms ease-out; padding: 40px; }
  .reveal.is-in { opacity: 1; transform: none; }
  .spin { width: 30px; height: 30px; background: #111; }
</style></head>
<body>
<header><nav><a id="n-home" href="#home">Home</a><a href="#pricing">Pricing</a></nav></header>
<main>
<div class="wrap">
  <a href="#go" class="btn" id="b-solid">Request the analysis <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M1 6h9M7 2l4 4-4 4" stroke="currentColor" stroke-width="1.5"/></svg></a>
  <button class="btn outline" id="b-outline"><span class="label">See how it works</span> →</button>
  <button class="btn lift" id="b-lift">Book a demo</button>
  <button class="jsbtn" id="b-js">JS hover</button>
  <span class="covered"><button class="btn" id="b-covered">Covered</button><span class="shield"></span></span>
  <p>Read <a class="text" id="l-text" href="#more">the full analysis</a> here.</p>
  <article id="c-card"><h3>Card</h3><p>Body</p></article>
  <div class="pulse" id="pulse"></div>
  <div class="spin" id="spin"></div>
</div>
<div class="spacer"></div>
<section class="band" id="band"><h2>The statement band</h2><p>Light text on a dark band.</p></section>
<section class="reveal" id="reveal"><h2>Revealed on scroll</h2><p>Content.</p></section>
</main>
<script>
  const js = document.getElementById('b-js');
  js.addEventListener('mouseenter', () => js.classList.add('is-hot'));
  js.addEventListener('mouseleave', () => js.classList.remove('is-hot'));
  const io = new IntersectionObserver((entries) => entries.forEach((e) => { if (e.isIntersecting) e.target.classList.add('is-in'); }));
  document.querySelectorAll('.reveal').forEach((el) => io.observe(el));
  const spin = document.getElementById('spin'); let angle = 0; let frame = 0;
  (function tick() { angle = (angle + 6) % 360; spin.style.transform = `rotate(${angle}deg)`; frame = requestAnimationFrame(tick); })();
  document.querySelectorAll('a[href^="#"]').forEach((a) => a.addEventListener('click', (e) => { e.preventDefault(); window.__clicked = (window.__clicked || 0) + 1; }));
  window.__stopMotion = () => { cancelAnimationFrame(frame); document.getAnimations().forEach((a) => a.pause()); };
</script>
</body></html>
```

- [ ] **Step 2: Write the failing tests** `apps/api/tests/test_capture_style_states.py`:

```python
"""The per-style state pass on a live page (Wave 2 A9, Task X2).

The real probe in headless Chromium — Playwright's and patchright's (the stealth backend's) — over a
local fixture page: CSS hover, press and focus-visible, a script-driven hover, a transform under a
transition, a moving icon, a disabled control, a covered button, a text link, a nav item, a card, a
CSS reveal, a keyframe animation and a scripted animation. No network.
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import pytest

from lumen_ingestion.capture import states as states_module
from lumen_ingestion.capture.geometry import GEOMETRY_JS
from lumen_ingestion.capture.states import LOOK_JS, REVEAL_BEFORE_JS, probe_states

FIXTURE = (Path(__file__).resolve().parent / "fixtures" / "capture" / "style_states.html").as_uri()


async def _capture(engine: str, *, before_probe=None) -> dict:
    if engine == "patchright":
        from patchright.async_api import async_playwright
    else:
        from playwright.async_api import async_playwright
    diagnostics: list[dict] = []
    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.launch(headless=True)
        except Exception as error:  # noqa: BLE001
            pytest.skip(f"{engine} chromium unavailable: {error}")
        try:
            page = await browser.new_page(viewport={"width": 1440, "height": 900})
            await page.goto(FIXTURE)
            reveal_before = await page.evaluate(REVEAL_BEFORE_JS)
            for y in range(0, 4200, 600):
                await page.evaluate(f"window.scrollTo(0, {y})")
                await page.wait_for_timeout(120)
            await page.wait_for_timeout(700)
            await page.evaluate("window.scrollTo(0, 0)")
            geometry = await page.evaluate(GEOMETRY_JS)
            ids = await page.evaluate(
                "() => Object.fromEntries([...document.querySelectorAll('[data-lumen-probe]')]"
                ".map((el) => [el.dataset.lumenProbe, el.id]))"
            )
            if before_probe is not None:
                await before_probe(page)
            looks_before = {
                idx: await page.locator(f'[data-lumen-probe="{idx}"]').evaluate(LOOK_JS) for idx in ids
            }
            shot_before = hashlib.sha256(await page.screenshot(full_page=True)).hexdigest()
            result = await probe_states(page, geometry, reveal_before=reveal_before, diagnostics=diagnostics)
            await page.evaluate("window.scrollTo(0, 0)")
            looks_after = {
                idx: await page.locator(f'[data-lumen-probe="{idx}"]').evaluate(LOOK_JS) for idx in ids
            }
            shot_after = hashlib.sha256(await page.screenshot(full_page=True)).hexdigest()
            clicked = await page.evaluate("window.__clicked || 0")
        finally:
            await browser.close()
    by_id = {ids.get(str(record["idx"])): record for record in result["styles"]}
    return {
        "geometry": geometry, "result": result, "by_id": by_id, "diagnostics": diagnostics,
        "same_looks": looks_before == looks_after, "same_shot": shot_before == shot_after, "clicked": clicked,
    }


async def _stop_motion(page) -> None:
    await page.evaluate("window.__stopMotion()")


@pytest.mark.parametrize("engine", ["playwright", "patchright"])
def test_each_style_is_measured_in_every_state(engine: str) -> None:
    run = asyncio.run(_capture(engine))
    solid = run["by_id"]["b-solid"]
    assert solid["how"] == "pointer"
    assert solid["hover"]["background"] == "rgb(3, 90, 78)"
    assert "0px 4px 12px" in solid["hover"]["box_shadow"]
    assert solid["hover"]["icon_transform"] == "matrix(1, 0, 0, 1, 4, 0)"
    assert solid["pressed"]["background"] == "rgb(2, 63, 55)"
    assert solid["pressed"]["transform"] == "matrix(0.98, 0, 0, 0.98, 0, 0)"
    assert solid["focus"]["outline_style"] == "solid"
    assert solid["focus"]["outline_color"] == "rgb(245, 166, 35)"
    assert solid["focus"]["outline_width"] == 3 and solid["focus"]["outline_offset"] == 2
    assert solid["disabled"] == {"opacity": 0.45, "cursor": "not-allowed"}
    assert [(t["property"], t["duration_ms"], t["easing"], t["delay_ms"]) for t in solid["motion"]["transitions"]] == [
        ("background-color", 200, "ease-out", 0), ("transform", 150, "ease", 0), ("box-shadow", 300, "ease", 50),
    ]
    assert solid["motion"]["icon"]["kind"] == "svg" and solid["motion"]["icon"]["position"] == "end"
    assert solid["rest"]["text_transform"] == "uppercase" and solid["rest"]["letter_spacing"] == 0.28

    outline = run["by_id"]["b-outline"]
    assert outline["motion"]["icon"] == {"kind": "glyph", "position": "end", "glyph": "→"}
    assert outline["hover"]["label_color"] == "rgb(255, 255, 255)"

    assert run["by_id"]["b-js"]["hover"]["background"] == "rgb(90, 47, 214)", "the mouseenter hover"
    assert run["by_id"]["b-js"]["focus"] == {"browser_focus_ring": True}, "the browser's ring is not a brand value"
    assert run["by_id"]["b-lift"]["hover"]["transform"] == "matrix(1, 0, 0, 1, 0, -2)"
    covered = run["by_id"]["b-covered"]
    assert covered["how"] == "forced" and covered["hover"]["background"] == "rgb(8, 58, 108)"

    link = run["by_id"]["l-text"]
    assert link["hover"]["decoration_line"] == "underline"
    assert link["hover"]["decoration_thickness"] == "2px"
    assert link["hover"]["color"] == "rgb(4, 116, 100)"
    assert run["by_id"]["n-home"]["hover"]["color"] == "rgb(4, 116, 100)"
    assert "0px 8px 24px" in run["by_id"]["c-card"]["hover"]["box_shadow"]

    assert run["clicked"] == 0, "pressing never clicks"
    assert run["same_looks"], "every element is left as the pass found it"


@pytest.mark.parametrize("engine", ["playwright", "patchright"])
def test_animations_reveals_and_scripted_motion_are_found(engine: str) -> None:
    run = asyncio.run(_capture(engine))
    pulse = next(a for a in run["geometry"]["animations"] if a["name"] == "pulse")
    assert (pulse["duration"], pulse["iterations"], pulse["direction"]) == ("1.6s", "infinite", "alternate")
    reveal = next(r for r in run["result"]["reveals"] if r["where"] == "section#reveal.reveal")
    assert reveal["kind"] == "css" and reveal["from_opacity"] == 0
    assert reveal["from_transform"] == "matrix(1, 0, 0, 1, 0, 24)" and reveal["trigger"] == ["is-in"]
    assert {"kind": "scripted", "where": "div#spin.spin"} in run["result"]["scripted"]
    band = next(s for s in run["geometry"]["sections"] if s.get("id") == "band")
    assert band["ink"] == "rgb(255, 255, 255)"


def test_the_pass_leaves_the_pixels_as_it_found_them() -> None:
    run = asyncio.run(_capture("playwright", before_probe=_stop_motion))
    assert run["same_shot"]


def test_without_a_cdp_session_pointer_hovers_are_still_measured(monkeypatch) -> None:
    async def no_cdp(page) -> None:
        async def refuse(_page):
            raise RuntimeError("no cdp here")
        monkeypatch.setattr(page.context, "new_cdp_session", refuse)

    run = asyncio.run(_capture("playwright", before_probe=no_cdp))
    solid = run["by_id"]["b-solid"]
    assert solid["hover"]["background"] == "rgb(3, 90, 78)"
    assert "pressed" not in solid and "focus" not in solid
    assert any(d["code"] == "LUMI0543" for d in run["diagnostics"])


def test_the_pass_stops_at_its_deadline(monkeypatch) -> None:
    monkeypatch.setattr(states_module, "STATE_PASS_DEADLINE_S", 0.0)
    run = asyncio.run(_capture("playwright"))
    assert run["result"]["styles"] == [] and run["result"]["truncated"] is True
    assert any(d["code"] == "LUMI0544" for d in run["diagnostics"])
```

- [ ] **Step 3: Run them to see them fail.**

Run: `CAPTURE_PYTEST test_capture_style_states.py`
Expected: FAIL at import — `ModuleNotFoundError: No module named 'lumen_ingestion.capture.states'`.

- [ ] **Step 4: Extend `GEOMETRY_JS`** in `capture/geometry.py`.
  1. In `record()`'s returned object, after `font: …,` add
     `disabled: el.matches(':disabled, [aria-disabled="true"]'),`.
  2. Add two entries at the END of `CLASSES` (so a styled `<a class="btn">` stays a button):
     `['nav_link', 'nav a[href], header a[href]'],` and `['link', 'a[href]'],`, and right after the
     `CLASSES` array:

```js
  // Text links and navigation items (Wave 2 A9): a link is an anchor with words outside the page
  // chrome; a nav item is one inside it. Both are measured for their states and motion only.
  const FILTERS = {
    nav_link: (el) => !!(el.textContent || '').trim(),
    link: (el) => !!(el.textContent || '').trim() && !el.closest('nav, header, footer'),
  };
```
  3. In the measuring loop, after `if (seen.has(el)) continue;` add
     `if (FILTERS[cls] && !FILTERS[cls](el)) continue;`, and replace `surfaces.push(entry);` with:

```js
      entry.idx = surfaces.length;
      surfaces.push(entry);
      // Marked for the state pass (capture/states.py). This probe runs after the screenshot and the
      // captured HTML, so the mark is never part of what was captured.
      try { el.setAttribute('data-lumen-probe', String(entry.idx)); } catch (e) { /* an element that refuses attributes */ }
```
  4. Before `const sections = [];` add:

```js
  // The text colour a band carries (Wave 2 A9): its first visible heading or paragraph, so a minted
  // band surface can say what text the seller put on it.
  const inkOf = (el) => {
    const nodes = Array.from(el.querySelectorAll('h1, h2, h3, h4, h5, h6, p, li, blockquote')).slice(0, 40);
    for (const node of nodes) {
      const r = node.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0 || !(node.textContent || '').trim()) continue;
      return opaque(getComputedStyle(node).color);
    }
    return null;
  };
```
     and in `sections.push({ … })` add `ink: inkOf(el),` after `bgImage: bgImage,`.
  5. Before the `return {` of the probe add:

```js
  // CSS animations running on the page (Wave 2 A9): one entry per distinct animation, bounded. The
  // @keyframes bodies are read from the captured stylesheets in Python (capture/motion.py), which
  // also holds the cross-origin sheets the CSSOM will not show.
  const MAX_ANIMATIONS = 12;
  const animations = new Map();
  for (const el of Array.from(document.querySelectorAll('body *')).slice(0, 6000)) {
    if (animations.size >= MAX_ANIMATIONS) break;
    const cs = getComputedStyle(el);
    if (!cs.animationName || cs.animationName === 'none') continue;
    const key = [cs.animationName, cs.animationDuration, cs.animationTimingFunction,
      cs.animationIterationCount, cs.animationDirection].join('|');
    const found = animations.get(key);
    if (found) { found.count += 1; continue; }
    const cls = el.getAttribute('class');
    animations.set(key, {
      name: cs.animationName.slice(0, 120), duration: cs.animationDuration,
      easing: cs.animationTimingFunction.slice(0, 120), delay: cs.animationDelay,
      iterations: cs.animationIterationCount, direction: cs.animationDirection, fill: cs.animationFillMode,
      where: (el.tagName.toLowerCase() + (el.id ? '#' + el.id : '')
        + (cls ? '.' + String(cls).trim().split(/\s+/)[0] : '')).slice(0, 120),
      count: 1,
    });
  }
```
     and add `animations: Array.from(animations.values()),` to the returned object after
     `focus: focus,`.

- [ ] **Step 5: Share the grouping key, and keep links out of the scales and the brief's shapes.**
  In `capture/geometry.py`:
  1. After `_MAX_SPACING_PX = 320.0` add:

```python
#: Text links and navigation items (Wave 2 A9). Measured for their states and motion only: they add
#: no number samples (the kit's scales stay what they were) and no shape records (the brief agent's
#: evidence stays what it was).
STYLE_ONLY_SURFACES = ("link", "nav_link")
#: The classes whose styles the state pass measures, and how many styles of each it tries. Buttons
#: carry the looks the agent chooses from, so they get the most; the rest are drawn by the kit.
STATE_TARGET_CAPS = {"button": 10, "link": 2, "nav_link": 2, "card": 4, "chip": 2, "input": 2, "image": 2}
#: Elements of one style tried before its states are given up (the first may be covered).
_CANDIDATES_PER_STYLE = 3
```
  2. At the top of `_read_surface`, after `cls = …`, add
     `if cls in STYLE_ONLY_SURFACES:\n        return`.
  3. Replace `_cluster_shapes` (whole function) with:

```python
def shape_key(entry: dict) -> tuple:
    """The one structural grouping key: fill kind, corners, border weight, shadow, background."""
    radius = _numbers(entry.get("radius"))
    border = _numbers(entry.get("border"))
    bg = _hex(entry.get("bg"))
    style = str(entry.get("borderStyle") or "none").lower()
    has_border = style not in ("none", "hidden") and any(v > 0 for v in border)
    fill = "solid" if bg else ("outline" if has_border else "ghost")
    return (
        str(entry.get("cls") or ""), fill, tuple(radius), bool(entry.get("pill")), tuple(border),
        _text(entry.get("shadow")), bg,
    )


def shape_groups(surfaces: list[dict], classes: tuple[str, ...]) -> list[tuple[str, list[dict]]]:
    """`(variant, members)` per visual variant of `classes`, most frequent first.

    The variant is `<fill>.<seat>` within its class — the name the brief's recipes and the minted
    tokens use — and `members[0]` is the first element measured with that shape.
    """
    groups: dict[tuple, list[dict]] = {}
    for entry in surfaces:
        if str(entry.get("cls") or "") in classes:
            groups.setdefault(shape_key(entry), []).append(entry)
    ordered = sorted(groups.items(), key=lambda item: (-len(item[1]), _order_key(item[0])))
    seats: dict[tuple[str, str], int] = {}
    out: list[tuple[str, list[dict]]] = []
    for key, members in ordered:
        seat = seats.get((key[0], key[1]), 0) + 1
        seats[(key[0], key[1])] = seat
        out.append((f"{key[1]}.{seat}", members))
    return out


def state_targets(surfaces: list[dict]) -> list[tuple[tuple[str, str], list[int]]]:
    """The styles the state pass measures, buttons first, and the elements to try for each."""
    taken: dict[str, int] = {}
    targets: list[tuple[tuple[str, str], list[int]]] = []
    for variant, members in shape_groups(surfaces, tuple(STATE_TARGET_CAPS)):
        cls = str(members[0].get("cls") or "")
        if taken.get(cls, 0) >= STATE_TARGET_CAPS[cls]:
            continue
        usable = [m for m in members if isinstance(m.get("idx"), int)]
        usable.sort(key=lambda m: bool(m.get("disabled")))  # an enabled element first
        candidates = [int(m["idx"]) for m in usable][:_CANDIDATES_PER_STYLE]
        if candidates:
            taken[cls] = taken.get(cls, 0) + 1
            targets.append(((cls, variant), candidates))
    order = list(STATE_TARGET_CAPS)
    targets.sort(key=lambda item: order.index(item[0][0]))
    return targets


def _cluster_shapes(surfaces: list[dict], url: str) -> list[SurfaceShape]:
    """Group measured elements into visual variants.

    The grouping key is purely structural — fill kind, radius, border weight,
    shadow, background — so "primary / secondary / ghost" falls out of what the
    page actually draws rather than from a guess about intent.
    """
    shapes: list[SurfaceShape] = []
    for variant, members in shape_groups(surfaces, _SHAPE_SURFACES):
        entry = members[0]
        cls = str(entry.get("cls") or "")
        fill = variant.split(".", 1)[0]
        shapes.append(
            SurfaceShape(
                surface=cls,  # type: ignore[arg-type]
                variant=variant,
                count=len(members),
                fill=fill,  # type: ignore[arg-type]
                radius_px=_numbers(entry.get("radius")),
                pill=bool(entry.get("pill")),
                padding_px=_numbers(entry.get("padding")),
                border_width_px=_numbers(entry.get("border")),
                border_style=_text(entry.get("borderStyle")),
                border_color=_hex(entry.get("borderColor")),
                shadow=_text(entry.get("shadow")),
                background=_hex(entry.get("bg")),
                text_color=_hex(entry.get("color")),
                font=_text(entry.get("font")),
                pointer=_pointer(url, f"{cls} {fill} variant"),
            )
        )
    return shapes
```

- [ ] **Step 6: Write `capture/states.py`.**

```python
"""Per-style interaction states, motion and behaviour, measured on the live page (Wave 2 A9).

The geometry probe (`geometry.py`) reads each measured element at REST. A brand's buttons, links and
cards are also what they do: the colour a button takes under the pointer, the press, the keyboard
focus ring, the disabled look, the transition that carries them, an arrow that slides. This pass
measures those after the screenshot, the captured HTML and the rest harvest, so it can never change
a captured pixel.

How each state is reached (offline probe, 2026-10-12, Playwright 1.61 and patchright 1.61.2,
recorded in docs/superpowers/plans/2026-10-12-lane-a-a9-brand-fidelity-rewrite.md):

* hover — a real pointer move (`locator.hover`), so CSS `:hover` and script-driven hovers (a
  mouseenter handler toggling a class) both show; when the element is covered or cannot take the
  pointer, CDP `CSS.forcePseudoState(['hover'])` reads the CSS hover, and the record says "forced";
* pressed — `CSS.forcePseudoState(['hover', 'active'])`: the real `:active` cascade with no click,
  so no link is followed and no handler runs;
* focus — `CSS.forcePseudoState(['focus', 'focus-visible'])` with the pointer moved away; a browser
  default ring (`outline-style: auto`) is recorded as that, never as a brand value;
* disabled — the element's own `disabled` (form controls) or `aria-disabled="true"`, set and
  restored, so the site's `:disabled` / `[aria-disabled]` rules show.

Transitions on the element and its descendants are switched off inline through the CSSOM first (a
page CSP cannot block a CSSOM write), so each read is the state's end look; a script-driven hover is
read every 50 ms until two reads agree. Everything is restored afterwards.

Bounded like the geometry probe, for the same reason (an ingestion is one job among many): at most
`STATE_TARGET_CAPS` styles, an 8-second wall clock for the whole pass, a 1.2-second pointer attempt,
a 0.6-second settle, 240 characters per value, 8 transitions per element. Fail-soft: a target that
throws is skipped; without a CDP session the pointer hovers are still measured; nothing here can fail
a capture.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from .geometry import state_targets

#: The whole pass's wall clock. Ten buttons and a dozen other styles take about 2.5 s at the
#: measured 100-140 ms each; the rest is headroom for covered elements (1.2 s each).
STATE_PASS_DEADLINE_S = 8.0
HOVER_TIMEOUT_MS = 1200
SETTLE_LIMIT_S = 0.6
SETTLE_STEP_S = 0.05

_TRANSITIONS_FN = r"""
  const transitionsOf = (node) => {
    if (!node) return [];
    const cs = getComputedStyle(node);
    const split = (value) => {
      const out = []; let depth = 0; let current = '';
      for (const ch of String(value || '')) {
        if (ch === '(') depth += 1;
        if (ch === ')') depth -= 1;
        if (ch === ',' && depth === 0) { out.push(current.trim()); current = ''; } else current += ch;
      }
      if (current.trim()) out.push(current.trim());
      return out;
    };
    const ms = (v) => String(v).trim().endsWith('ms') ? parseFloat(v) : parseFloat(v) * 1000;
    const props = split(cs.transitionProperty), durs = split(cs.transitionDuration);
    const eases = split(cs.transitionTimingFunction), delays = split(cs.transitionDelay);
    const out = [];
    props.forEach((property, i) => {
      const duration = ms(durs[i % durs.length] || '0s');
      if (!(duration > 0)) return;
      out.push({ property: property.slice(0, 60), duration_ms: Math.round(duration),
        easing: (eases[i % eases.length] || 'ease').slice(0, 120), delay_ms: Math.round(ms(delays[i % delays.length] || '0s')) });
    });
    return out.slice(0, 8);
  };
"""

#: One element's look: its box, the element that paints its words, and its icon.
LOOK_JS = r"""
(el) => {
  const num = (v) => { const n = parseFloat(v); return Number.isFinite(n) ? Math.round(n * 100) / 100 : null; };
  const cut = (v) => (v === undefined || v === null || v === '') ? null : String(v).slice(0, 240);
  const host = (() => {
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) { if (node.textContent.trim()) return node.parentElement; }
    return el;
  })();
  const icon = el.querySelector('svg, img');
  const cs = getComputedStyle(el);
  const hs = getComputedStyle(host);
  const look = {
    background: cut(cs.backgroundColor),
    color: cut(cs.color),
    label_color: host === el ? null : cut(hs.color),
    border_color: cut(cs.borderTopColor),
    border_width: [cs.borderTopWidth, cs.borderRightWidth, cs.borderBottomWidth, cs.borderLeftWidth].map(num),
    border_style: cut(cs.borderTopStyle),
    radius: [cs.borderTopLeftRadius, cs.borderTopRightRadius, cs.borderBottomRightRadius, cs.borderBottomLeftRadius].map(num),
    padding: [cs.paddingTop, cs.paddingRight, cs.paddingBottom, cs.paddingLeft].map(num),
    height: num(el.getBoundingClientRect().height),
    gap: cs.columnGap === 'normal' ? null : num(cs.columnGap),
    font_family: cut(hs.fontFamily), font_size: num(hs.fontSize), font_weight: num(hs.fontWeight),
    line_height: hs.lineHeight === 'normal' ? null : num(hs.lineHeight),
    letter_spacing: hs.letterSpacing === 'normal' ? 0 : num(hs.letterSpacing),
    text_transform: cut(hs.textTransform),
    decoration_line: cut(hs.textDecorationLine),
    decoration_thickness: cut(hs.textDecorationThickness),
    underline_offset: cut(hs.textUnderlineOffset),
    box_shadow: cs.boxShadow === 'none' ? null : cut(cs.boxShadow),
    opacity: num(cs.opacity),
    transform: cs.transform === 'none' ? null : cut(cs.transform),
    filter: cs.filter === 'none' ? null : cut(cs.filter),
    cursor: cut(cs.cursor),
    outline_style: cut(cs.outlineStyle),
    outline_color: cut(cs.outlineColor),
    outline_width: num(cs.outlineWidth),
    outline_offset: num(cs.outlineOffset),
  };
  if (icon) {
    const is = getComputedStyle(icon);
    look.icon_transform = is.transform === 'none' ? null : cut(is.transform);
    look.icon_color = cut(is.color);
    look.icon_opacity = num(is.opacity);
  }
  return look;
}
"""

#: The element's transitions (its own, its words' and its icon's) and its icon.
MOTION_JS = r"""
(el) => {
""" + _TRANSITIONS_FN + r"""
  const host = (() => {
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) { if (node.textContent.trim()) return node.parentElement; }
    return el;
  })();
  const icon = el.querySelector('svg, img');
  const glyphs = /[→›»↗➔⟶←‹«↘]/;
  const text = (el.textContent || '').trim();
  let info = null;
  if (icon) {
    const r = icon.getBoundingClientRect(), b = el.getBoundingClientRect();
    const svg = icon.tagName.toLowerCase() === 'svg';
    info = { kind: svg ? 'svg' : 'img', position: (r.left - b.left) < (b.right - r.right) ? 'start' : 'end',
      width: Math.round(r.width * 100) / 100, height: Math.round(r.height * 100) / 100,
      svg: svg ? icon.outerHTML.slice(0, 8192) : null };
  } else if (text && glyphs.test(text.slice(-1))) {
    info = { kind: 'glyph', position: 'end', glyph: text.slice(-1) };
  } else if (text && glyphs.test(text.slice(0, 1))) {
    info = { kind: 'glyph', position: 'start', glyph: text.slice(0, 1) };
  }
  return { transitions: transitionsOf(el), label_transitions: host === el ? [] : transitionsOf(host),
    icon_transitions: transitionsOf(icon), icon: info };
}
"""

FREEZE_JS = r"""
(el) => [el, ...el.querySelectorAll('*')].slice(0, 16).map((node) => {
  const prior = [node.style.getPropertyValue('transition'), node.style.getPropertyPriority('transition')];
  node.style.setProperty('transition', 'none', 'important');
  return prior;
})
"""

THAW_JS = r"""
(el, priors) => [el, ...el.querySelectorAll('*')].slice(0, 16).forEach((node, i) => {
  const [value, priority] = priors[i] || ['', ''];
  if (value) node.style.setProperty('transition', value, priority); else node.style.removeProperty('transition');
})
"""

DISABLE_JS = r"""
(el) => {
  const formish = ['BUTTON', 'INPUT', 'SELECT', 'TEXTAREA', 'FIELDSET'].includes(el.tagName);
  if (formish) { const was = el.disabled; el.disabled = true; return { formish, was }; }
  const was = el.getAttribute('aria-disabled');
  el.setAttribute('aria-disabled', 'true');
  return { formish, was };
}
"""

ENABLE_JS = r"""
(el, prior) => {
  if (prior.formish) { el.disabled = prior.was; return; }
  if (prior.was === null) el.removeAttribute('aria-disabled'); else el.setAttribute('aria-disabled', prior.was);
}
"""

#: Read BEFORE the page is scrolled (rendered.py): elements that start hidden or shifted and carry
#: motion — the candidates for an entrance reveal. Read-only; elements are re-found by child path.
REVEAL_BEFORE_JS = r"""
() => {
  const out = [];
  const body = document.body;
  if (!body) return out;
  const els = Array.from(body.querySelectorAll('*')).slice(0, 6000);
  const pathOf = (el) => {
    const parts = []; let node = el;
    while (node && node !== body) { const p = node.parentElement; if (!p) return null; parts.unshift(Array.prototype.indexOf.call(p.children, node)); node = p; }
    return parts;
  };
  const ms = (v) => String(v).trim().endsWith('ms') ? parseFloat(v) : parseFloat(v) * 1000;
  for (const el of els) {
    if (out.length >= 24) break;
    const r = el.getBoundingClientRect();
    if (r.width * r.height < 1000) continue;
    if (!(el.textContent || '').trim() && !el.querySelector('img, svg, picture, video')) continue;
    const cs = getComputedStyle(el);
    const moving = String(cs.transitionDuration).split(',').some((d) => ms(d) > 0) || (cs.animationName && cs.animationName !== 'none');
    const hidden = parseFloat(cs.opacity) < 0.05;
    const shifted = cs.transform !== 'none' && moving;
    if (!hidden && !shifted) continue;
    if (out.some((o) => o.el.contains(el))) continue;
    const path = pathOf(el);
    if (!path) continue;
    out.push({ el, path, tag: el.tagName.toLowerCase(), opacity: parseFloat(cs.opacity), transform: cs.transform,
      classes: (el.getAttribute('class') || '').slice(0, 240) });
  }
  return out.map(({ el, ...rest }) => rest);
}
"""

REVEAL_AFTER_JS = r"""
(items) => {
""" + _TRANSITIONS_FN + r"""
  return items.map((item) => {
    let node = document.body;
    for (const i of item.path) { node = node && node.children[i]; }
    if (!node) return null;
    const cs = getComputedStyle(node);
    const cls = node.getAttribute('class');
    return { tag: node.tagName.toLowerCase(), opacity: parseFloat(cs.opacity), transform: cs.transform,
      classes: (cls || '').slice(0, 240), transitions: transitionsOf(node),
      where: (node.tagName.toLowerCase() + (node.id ? '#' + node.id : '') + (cls ? '.' + String(cls).trim().split(/\s+/)[0] : '')).slice(0, 120) };
  });
}
"""

#: Motion a published page cannot carry: canvases, playing videos, and inline styles a script keeps
#: rewriting. Recorded as notes (what and where), never reproduced.
SCRIPTED_JS = r"""
async () => {
  const describe = (el) => {
    const cls = el.getAttribute('class');
    return (el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (cls ? '.' + String(cls).trim().split(/\s+/)[0] : '')).slice(0, 120);
  };
  const notes = [];
  for (const el of Array.from(document.querySelectorAll('canvas'))) {
    const r = el.getBoundingClientRect();
    if (r.width * r.height >= 10000 && notes.length < 4) notes.push({ kind: 'canvas', where: describe(el) });
  }
  for (const el of Array.from(document.querySelectorAll('video'))) {
    if ((el.autoplay || !el.paused) && notes.length < 8) notes.push({ kind: 'video', where: describe(el) });
  }
  const els = Array.from(document.querySelectorAll('body *')).slice(0, 4000);
  const before = els.map((el) => el.getAttribute('style') || '');
  await new Promise((resolve) => setTimeout(resolve, 300));
  let moved = 0;
  els.forEach((el, i) => {
    if (moved >= 4) return;
    const now = el.getAttribute('style') || '';
    if (now !== before[i] && /transform|opacity|translate|scale|rotate/.test(now)) { notes.push({ kind: 'scripted', where: describe(el) }); moved += 1; }
  });
  return notes.slice(0, 12);
}
"""

_STRING_REMOVALS = ("box_shadow", "transform", "filter")
_OUTLINE = ("outline_style", "outline_color", "outline_width", "outline_offset")


def look_delta(rest: dict, other: dict) -> dict:
    """Only what changed from rest. Values that are not brand choices are dropped."""
    out = {key: value for key, value in other.items() if rest.get(key) != value}
    # A value the state removes is recorded as "none", so "no shadow on hover" survives storage.
    for key in _STRING_REMOVALS:
        if key in out and out[key] is None and rest.get(key) is not None:
            out[key] = "none"
    # A border colour with no drawn border is the text colour leaking through `currentColor`.
    if not any((width or 0) > 0 for width in (other.get("border_width") or [])):
        out.pop("border_color", None)
    style = other.get("outline_style")
    if style in (None, "none") or style == "auto":
        for key in _OUTLINE:
            out.pop(key, None)
        if style == "auto" and rest.get("outline_style") != "auto":
            out["browser_focus_ring"] = True
    out.pop("height", None)  # layout, not a state
    return out


async def _settled(locator: Any) -> dict:
    deadline = time.monotonic() + SETTLE_LIMIT_S
    previous = await locator.evaluate(LOOK_JS)
    while time.monotonic() < deadline:
        await asyncio.sleep(SETTLE_STEP_S)
        current = await locator.evaluate(LOOK_JS)
        if current == previous:
            return current
        previous = current
    return previous


async def _force(cdp: Any, root: int, idx: int, classes: list[str]) -> None:
    node = await cdp.send("DOM.querySelector", {"nodeId": root, "selector": f'[data-lumen-probe="{idx}"]'})
    await cdp.send("CSS.forcePseudoState", {"nodeId": node["nodeId"], "forcedPseudoClasses": classes})


async def _pointer_away(page: Any, locator: Any) -> None:
    box = await locator.bounding_box()
    viewport = page.viewport_size or {"width": 1440, "height": 900}
    point = (0, 0)
    if box and box["x"] <= 0 <= box["x"] + box["width"] and box["y"] <= 0 <= box["y"] + box["height"]:
        point = (viewport["width"] - 1, viewport["height"] - 1)
    await page.mouse.move(*point)


async def _probe_one(page: Any, cdp: Any, root: int | None, idx: int) -> dict:
    locator = page.locator(f'[data-lumen-probe="{idx}"]')
    motion = await locator.evaluate(MOTION_JS)
    rest = await locator.evaluate(LOOK_JS)
    priors = await locator.evaluate(FREEZE_JS)
    record: dict[str, Any] = {"idx": idx, "motion": motion, "rest": rest}
    try:
        try:
            await locator.hover(timeout=HOVER_TIMEOUT_MS)
            hover = await _settled(locator)
            record["how"] = "pointer"
        except Exception:  # noqa: BLE001 — covered or pointer-proof: read the CSS hover
            if cdp is None:
                raise
            await _force(cdp, root, idx, ["hover"])
            hover = await locator.evaluate(LOOK_JS)
            await _force(cdp, root, idx, [])
            record["how"] = "forced"
        record["hover"] = look_delta(rest, hover)
        if cdp is not None:
            await _force(cdp, root, idx, ["hover", "active"])
            record["pressed"] = look_delta(rest, await locator.evaluate(LOOK_JS))
            await _force(cdp, root, idx, [])
            await _pointer_away(page, locator)
            await _force(cdp, root, idx, ["focus", "focus-visible"])
            record["focus"] = look_delta(rest, await locator.evaluate(LOOK_JS))
            await _force(cdp, root, idx, [])
        await _pointer_away(page, locator)
        prior = await locator.evaluate(DISABLE_JS)
        try:
            record["disabled"] = look_delta(rest, await locator.evaluate(LOOK_JS))
        finally:
            await locator.evaluate(ENABLE_JS, prior)
    finally:
        await locator.evaluate(THAW_JS, priors)
    return record


def _reveals(before: list, after: list) -> list[dict]:
    out: list[dict] = []
    for prior, now in zip(before, after):
        if not isinstance(prior, dict) or not isinstance(now, dict) or now.get("tag") != prior.get("tag"):
            continue
        settled = (now.get("opacity") or 0) >= 0.95 and now.get("transform") in (None, "none", "matrix(1, 0, 0, 1, 0, 0)")
        if not settled:
            continue
        transitions = [
            t for t in now.get("transitions") or []
            if t.get("property") in ("all", "opacity", "transform", "translate")
        ]
        added = sorted(set(str(now.get("classes") or "").split()) - set(str(prior.get("classes") or "").split()))
        out.append({
            "kind": "css" if transitions else "scripted",
            "where": str(now.get("where") or "")[:120],
            "from_opacity": prior.get("opacity"),
            "from_transform": prior.get("transform") if prior.get("transform") not in (None, "none") else None,
            "transitions": transitions,
            "trigger": [name[:40] for name in added[:3]],
        })
    return out


def _diag(code: str, severity: str, message: str) -> dict:
    return {"code": code, "severity": severity, "message": message}


async def probe_states(page: Any, geometry: dict, *, reveal_before: list | None, diagnostics: list[dict]) -> dict:
    """Measure every targeted style's states, the page's reveals and its scripted motion. Never raises."""
    result: dict[str, Any] = {"styles": [], "reveals": [], "scripted": [], "truncated": False}
    surfaces = geometry.get("surfaces") if isinstance(geometry, dict) else None
    targets = state_targets(surfaces if isinstance(surfaces, list) else [])
    cdp = None
    root: int | None = None
    try:
        cdp = await page.context.new_cdp_session(page)
        await cdp.send("DOM.enable")
        await cdp.send("CSS.enable")
        root = (await cdp.send("DOM.getDocument", {"depth": 0}))["root"]["nodeId"]
    except Exception as error:  # noqa: BLE001
        cdp = None
        diagnostics.append(_diag("LUMI0543", "warning", f"pressed and focus states not measured (no CDP session): {error}"))
    deadline = time.monotonic() + STATE_PASS_DEADLINE_S
    try:
        for _key, candidates in targets:
            if time.monotonic() >= deadline:
                result["truncated"] = True
                break
            for idx in candidates:
                try:
                    result["styles"].append(await _probe_one(page, cdp, root, idx))
                    break
                except Exception:  # noqa: BLE001 — try the style's next element
                    continue
        if reveal_before:
            try:
                result["reveals"] = _reveals(reveal_before, await page.evaluate(REVEAL_AFTER_JS, reveal_before))
            except Exception:  # noqa: BLE001
                pass
        try:
            result["scripted"] = await page.evaluate(SCRIPTED_JS)
        except Exception:  # noqa: BLE001
            pass
    finally:
        try:
            await page.mouse.move(0, 0)
        except Exception:  # noqa: BLE001
            pass
        if cdp is not None:
            try:
                await cdp.detach()
            except Exception:  # noqa: BLE001
                pass
    if result["truncated"]:
        diagnostics.append(_diag(
            "LUMI0544", "info",
            f"interaction states measured for {len(result['styles'])} of {len(targets)} styles before the "
            f"{STATE_PASS_DEADLINE_S:.0f}s limit",
        ))
    return result
```

- [ ] **Step 7: Run the state pass on the entry page.** In `capture/rendered.py`:
  1. `from .geometry import GEOMETRY_JS` becomes
     `from .geometry import GEOMETRY_JS` plus a new line `from .states import REVEAL_BEFORE_JS, probe_states`.
  2. `async def _harvest_page(page, diagnostics: list[dict]) -> dict:` becomes
     `async def _harvest_page(page, diagnostics: list[dict], *, measure_states: bool = False) -> dict:`,
     and its first statement (before `await _scroll_until_settled(page)`) becomes:

```python
    # Entrance reveals can only be seen before the page is scrolled (Wave 2 A9): read-only, so the
    # captured pixels and HTML are untouched.
    reveal_before = None
    if measure_states:
        try:
            reveal_before = await page.evaluate(REVEAL_BEFORE_JS)
        except Exception:  # noqa: BLE001 — a reveal we cannot see is a reveal we do not record
            reveal_before = None
```
  3. After the `harvest["geometry"] = await page.evaluate(GEOMETRY_JS)` try/except block, before
     `return harvest`:

```python
    # Interaction states, motion and behaviour (Wave 2 A9), after everything that was captured. The
    # entry page only: it is the page the kit is about, and the pass costs up to ~10 s.
    if measure_states and isinstance(harvest["geometry"], dict):
        harvest["geometry"]["states"] = await probe_states(
            page, harvest["geometry"], reveal_before=reveal_before, diagnostics=diagnostics
        )
```
  4. `fetch_rendered(url, fetcher, reporter, *, fetched_at: str)` gains `measure_states: bool = False`
     and passes it to `_fetch_rendered_stealth(...)` and `_fetch_rendered_chromium(...)`, which each
     gain the same keyword and call `_harvest_page(page, diagnostics, measure_states=measure_states)`.
     In the stealth backend's comment "the generous timeout covers scroll-settle (<=12s) + hero dwell
     (3s)" add "+ the state pass (<=10s)".
  5. In `capture/__init__.py`, `_capture_page(...)` gains `measure_states: bool = False` and passes it
     to both `fetch_rendered(...)` calls; `capture_website` passes `measure_states=True` for the entry
     page only (the `entry = await _capture_page(pages[0], …)` call).

- [ ] **Step 8: Run the tests.**

Run: `CAPTURE_PYTEST test_capture_style_states.py test_ingestion_geometry.py`
Expected: PASS — the new tests on both engines (patchright skips only where its Chromium is not
installed), and every existing geometry test unchanged (the shape records are byte-identical).

- [ ] **Step 9: Record the fixture harvest** for the next tasks. Create
  `apps/api/tests/fixtures/capture/make_style_states_harvest.py`:

```python
"""Write style_states.harvest.json: the real probe's harvest of style_states.html (Wave 2 A9).

Run from subsystems/clue-design:
  PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python apps/api/tests/fixtures/capture/make_style_states_harvest.py
Offline (a file:// page). Deterministic: computed styles only; re-running writes the same bytes.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

from lumen_ingestion.capture.geometry import GEOMETRY_JS
from lumen_ingestion.capture.states import REVEAL_BEFORE_JS, probe_states

HERE = Path(__file__).resolve().parent


async def main() -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        await page.goto((HERE / "style_states.html").as_uri())
        reveal_before = await page.evaluate(REVEAL_BEFORE_JS)
        for y in range(0, 4200, 600):
            await page.evaluate(f"window.scrollTo(0, {y})")
            await page.wait_for_timeout(120)
        await page.wait_for_timeout(700)
        await page.evaluate("window.scrollTo(0, 0)")
        geometry = await page.evaluate(GEOMETRY_JS)
        geometry["fixture_ids"] = await page.evaluate(
            "() => Object.fromEntries([...document.querySelectorAll('[data-lumen-probe]')]"
            ".map((el) => [el.dataset.lumenProbe, el.id]))"
        )
        geometry["states"] = await probe_states(page, geometry, reveal_before=reveal_before, diagnostics=[])
        geometry["url"] = "https://fixture.test/"
        await browser.close()
    (HERE / "style_states.harvest.json").write_text(json.dumps(geometry, indent=1, sort_keys=True) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
```

Run it twice (command in its docstring) and `git diff --stat` the JSON between runs.
Expected: the second run changes nothing.

- [ ] **Step 10: Commit.**

```bash
git add subsystems/clue-design/apps/api/lumen_ingestion/capture/geometry.py subsystems/clue-design/apps/api/lumen_ingestion/capture/states.py \
  subsystems/clue-design/apps/api/lumen_ingestion/capture/rendered.py subsystems/clue-design/apps/api/lumen_ingestion/capture/__init__.py \
  subsystems/clue-design/apps/api/tests/fixtures/capture subsystems/clue-design/apps/api/tests/test_capture_style_states.py
git commit -m "capture: measure each button, link, card and control style in hover, pressed, focus and disabled, with its transitions, icon, the page's reveals and scripted motion"
```

### Task X3: Measured styles, motion and band text as evidence

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/evidence.py`
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/capture/geometry.py` (`GeometryHarvest`,
  `parse_geometry`, `_read_sections`, new `measured_styles`, `measured_motion`)
- Create: `subsystems/clue-design/apps/api/lumen_ingestion/capture/motion.py`
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/capture/evidence_builder.py:434`
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/brief_agent.py` (`build_brief_request`, `_dump`)
- Create: `subsystems/clue-design/apps/api/tests/test_ingestion_measured_styles.py`

**Interfaces:**
- Produces (evidence, additive, `schema_version` stays 1 like every earlier geometry addition):
  `StyleLook` (every field optional; a state look holds only what changed, and `"none"` for a
  shadow/transform/filter the state removes), `StyleTransition{target, property, duration_ms,
  easing, delay_ms}`, `StyleIcon{kind, position, glyph?, svg?, width?, height?}`,
  `MeasuredStyle{surface, variant, count, probed, rest, hover?, pressed?, focus?, disabled?,
  transitions, icon?, pointer}`, `KeyframeStep`, `MeasuredAnimation`, `MeasuredReveal`,
  `ScriptedMotion`, `MotionEvidence{animations, reveals, scripted}`; `GeometryEvidence.styles`,
  `GeometryEvidence.motion`; `SectionBackground.ink`. `capture.motion.keyframe_steps(stylesheets,
  name)`, `attach_keyframes(motion, stylesheets)`, `clean_icon_svg(markup)`, `safe_style_value(v)`,
  `KEYFRAME_PROPERTIES`, `MAX_ICON_SVG_BYTES`.
- The brief agent's evidence payload is byte-identical to today's for the same evidence (the new
  fields are not sent to it).

- [ ] **Step 1: Write the failing tests** `apps/api/tests/test_ingestion_measured_styles.py`:

```python
"""Measured styles and motion as evidence (Wave 2 A9, Task X3).

From the real probe's harvest of the fixture page (fixtures/capture/style_states.harvest.json, written
by make_style_states_harvest.py in Task X2), so every value here is one a browser computed.
"""

from __future__ import annotations

import json
from pathlib import Path

from lumen_ingestion.brief_agent import build_brief_request
from lumen_ingestion.capture.geometry import parse_geometry
from lumen_ingestion.capture.motion import attach_keyframes, clean_icon_svg, keyframe_steps
from lumen_ingestion.capture.snapshot import Stylesheet
from lumen_ingestion.evidence import BrandEvidence, MotionEvidence

TESTS = Path(__file__).resolve().parent
HARVEST = json.loads((TESTS / "fixtures" / "capture" / "style_states.harvest.json").read_text())
URL = "https://fixture.test/"


def _parsed():
    return parse_geometry(HARVEST, page_url=URL)


def _button(styles, background: str):
    return next(s for s in styles if s.surface == "button" and s.rest.background == background)


def test_each_measured_style_carries_its_states_motion_and_icon() -> None:
    styles = _parsed().styles
    solid = _button(styles, "#047464")
    assert solid.variant.startswith("solid.") and solid.probed == "pointer"
    assert solid.rest.text_transform == "uppercase" and solid.rest.letter_spacing == 0.28
    assert (solid.rest.font_family, solid.rest.font_size, solid.rest.font_weight) == ("Arial", 14, 500)
    assert solid.rest.pill is True and solid.rest.padding == [12, 24, 12, 24]
    assert solid.hover.background == "#035A4E"
    assert solid.pressed.transform == "matrix(0.98, 0, 0, 0.98, 0, 0)"
    assert (solid.focus.outline_color, solid.focus.outline_width, solid.focus.outline_offset) == ("#F5A623", 3, 2)
    assert (solid.disabled.opacity, solid.disabled.cursor) == (0.45, "not-allowed")
    assert [(t.target, t.property, t.duration_ms, t.delay_ms) for t in solid.transitions] == [
        ("self", "background-color", 200, 0), ("self", "transform", 150, 0), ("self", "box-shadow", 300, 50),
        ("icon", "transform", 200, 0),
    ]
    assert solid.icon.kind == "svg" and solid.icon.position == "end"
    assert solid.icon.svg.startswith('<svg width="12" height="12" viewBox="0 0 12 12"') and "<path" in solid.icon.svg
    assert solid.hover.icon_transform == "matrix(1, 0, 0, 1, 4, 0)"

    outline = next(s for s in styles if s.surface == "button" and s.variant == "outline.1")
    assert (outline.icon.kind, outline.icon.glyph) == ("glyph", "→")
    assert outline.hover.label_color == "#FFFFFF"
    js = _button(styles, "#7C4CFF")
    assert js.focus.browser_focus_ring is True and js.focus.outline_color is None
    assert _button(styles, "#0A4A8A").probed == "forced"

    link = next(s for s in styles if s.surface == "link")
    assert (link.hover.decoration_line, link.hover.decoration_thickness, link.hover.color) == ("underline", "2px", "#047464")
    assert next(s for s in styles if s.surface == "nav_link").hover.color == "#047464"
    assert next(s for s in styles if s.surface == "card").hover.box_shadow.startswith("rgba(0, 0, 0, 0.12)")


def test_links_and_nav_items_add_no_scale_samples_and_no_shape_records() -> None:
    parsed = _parsed()
    assert all(shape.surface not in ("link", "nav_link") for shape in parsed.surfaces)
    stripped = {**HARVEST, "surfaces": [s for s in HARVEST["surfaces"] if s["cls"] not in ("link", "nav_link")]}
    assert parse_geometry(stripped, page_url=URL).numbers == parsed.numbers


def test_motion_evidence_holds_the_animation_the_reveal_and_the_scripted_note() -> None:
    parsed = _parsed()
    pulse = next(a for a in parsed.motion.animations if a.name == "pulse")
    assert (pulse.duration_ms, pulse.easing, pulse.iterations, pulse.direction) == (1600, "ease-in-out", "infinite", "alternate")
    reveal = parsed.motion.reveals[0]
    assert (reveal.from_opacity, reveal.from_transform) == (0, "matrix(1, 0, 0, 1, 0, 24)")
    assert (reveal.duration_ms, reveal.easing, reveal.trigger) == (600, "ease-out", ["is-in"])
    assert [(n.kind, n.where) for n in parsed.motion.scripted] == [("scripted", "div#spin.spin")]
    band = next(b for b in parsed.background_sequence if b.background == "#014036")
    assert band.ink == "#FFFFFF"


def _sheet(text: str) -> Stylesheet:
    return Stylesheet(url="https://fixture.test/a.css", text=text)


def test_keyframes_come_from_the_captured_stylesheets_in_cascade_order() -> None:
    sheets = [
        _sheet("@keyframes pulse{from{opacity:1}to{opacity:.2}}"),
        _sheet(
            "@media (min-width:1px){@keyframes pulse{0%,100%{opacity:1;transform:scale(1)}"
            "50%{opacity:.5;background-image:url(x.png);color:var(--x)}}}"
        ),
    ]
    steps = keyframe_steps(sheets, "pulse")
    assert [(s.offset, s.declarations) for s in steps] == [
        (0.0, {"opacity": "1", "transform": "scale(1)"}),
        (50.0, {"opacity": ".5"}),
        (100.0, {"opacity": "1", "transform": "scale(1)"}),
    ]
    assert keyframe_steps(sheets, "missing") == []


def test_an_animation_without_a_usable_definition_is_dropped() -> None:
    motion = _parsed().motion
    assert attach_keyframes(motion, []).animations == []
    css = (TESTS / "fixtures" / "capture" / "style_states.html").read_text().split("<style>", 1)[1].split("</style>", 1)[0]
    attached = attach_keyframes(motion, [_sheet(css)])
    assert [step.offset for step in attached.animations[0].frames] == [0.0, 50.0, 100.0]


def test_an_icon_svg_keeps_only_drawing_elements_and_attributes() -> None:
    raw = (
        '<svg width="12" height="12" viewBox="0 0 12 12" fill="none" onload="x()"><script>x()</script>'
        '<path d="M1 6h9" stroke="currentColor" style="fill:url(#a)"/><use href="#b"/>'
        "<foreignObject><div>x</div></foreignObject></svg>"
    )
    assert clean_icon_svg(raw) == (
        '<svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M1 6h9" stroke="currentColor"></path></svg>'
    )
    assert clean_icon_svg("<div>no</div>") is None
    assert clean_icon_svg("<svg>" + '<path d="M0 0"></path>' * 400 + "</svg>") is None


def test_the_brief_agents_evidence_is_unchanged_by_the_new_measurements() -> None:
    evidence = BrandEvidence.model_validate(
        json.loads((TESTS / "fixtures" / "ingestion" / "evidence_website_insight.json").read_text())
    )
    geometry = _parsed().evidence()
    with_new = evidence.model_copy(update={"geometry": geometry})
    without = evidence.model_copy(update={"geometry": geometry.model_copy(update={
        "styles": [], "motion": MotionEvidence(),
        "background_sequence": [band.model_copy(update={"ink": None}) for band in geometry.background_sequence],
    })})
    assert build_brief_request(with_new, {}).evidence_json() == build_brief_request(without, {}).evidence_json()
```

- [ ] **Step 2: Run them to see them fail.**

Run: `CAPTURE_PYTEST test_ingestion_measured_styles.py`
Expected: FAIL at import — no module `lumen_ingestion.capture.motion`.

- [ ] **Step 3: Add the evidence types** to `evidence.py`. In `SectionBackground`, add
  `ink: str | None = None` after `has_image`, and widen its validator to
  `@field_validator("background", "ink")`. Before `class GeometryEvidence` add:

```python
class StyleLook(BaseModel):
    """One look of a measured element style (Wave 2 A9): what a browser computed for it.

    The rest look carries everything measured; a state's look carries only what changed from rest,
    with `"none"` for a shadow, transform or filter the state removes. Colours are normalized hex.
    """

    model_config = ConfigDict(extra="forbid")

    background: str | None = None
    color: str | None = None
    #: The colour of the element that paints the words, when it is not the element itself.
    label_color: str | None = None
    border_color: str | None = None
    border_width: list[float] = []
    border_style: str | None = None
    radius: list[float] = []
    pill: bool | None = None
    padding: list[float] = []
    height: float | None = None
    gap: float | None = None
    font_family: str | None = None
    font_size: float | None = None
    font_weight: float | None = None
    #: px, as computed.
    line_height: float | None = None
    #: px, as computed.
    letter_spacing: float | None = None
    text_transform: str | None = None
    decoration_line: str | None = None
    decoration_thickness: str | None = None
    underline_offset: str | None = None
    box_shadow: str | None = None
    opacity: float | None = None
    transform: str | None = None
    filter: str | None = None
    cursor: str | None = None
    outline_color: str | None = None
    outline_width: float | None = None
    outline_style: str | None = None
    outline_offset: float | None = None
    #: The browser's own focus ring showed: the site styles no focus look of its own.
    browser_focus_ring: bool | None = None
    icon_transform: str | None = None
    icon_color: str | None = None
    icon_opacity: float | None = None

    @field_validator("background", "color", "label_color", "border_color", "outline_color", "icon_color")
    @classmethod
    def _colors(cls, value: str | None) -> str | None:
        return _normalize_hex(value) if value else value


class StyleTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: Literal["self", "label", "icon"]
    property: str
    duration_ms: float
    easing: str = "ease"
    delay_ms: float = 0.0


class StyleIcon(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["svg", "glyph", "img"]
    position: Literal["start", "end"] = "end"
    glyph: str | None = None
    #: Cleaned to drawing elements only (`capture.motion.clean_icon_svg`).
    svg: str | None = None
    width: float | None = None
    height: float | None = None


class MeasuredStyle(BaseModel):
    """One visual variant of an element class, in every state the capture could reach (Wave 2 A9).

    `variant` is the same `<fill>.<n>` the shape records and the brief's recipes use, so a recipe
    and its measurement join by `(surface, variant)`. `probed` says how the hover was read: by a
    real pointer, forced through CSS (the element was covered), or not at all (rest only, beyond
    the state pass's caps or time).
    """

    model_config = ConfigDict(extra="forbid")

    surface: Literal["button", "link", "nav_link", "card", "chip", "input", "image"]
    variant: str
    count: int = 1
    probed: Literal["pointer", "forced", "rest-only"] = "rest-only"
    rest: StyleLook = StyleLook()
    hover: StyleLook | None = None
    pressed: StyleLook | None = None
    focus: StyleLook | None = None
    disabled: StyleLook | None = None
    transitions: list[StyleTransition] = []
    icon: StyleIcon | None = None
    pointer: EvidencePointer


class KeyframeStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offset: float
    declarations: dict[str, str] = {}


class MeasuredAnimation(BaseModel):
    """A CSS animation running on the page, with its `@keyframes` from the captured stylesheets."""

    model_config = ConfigDict(extra="forbid")

    name: str
    duration_ms: float
    easing: str = "ease"
    delay_ms: float = 0.0
    iterations: str = "1"
    direction: str = "normal"
    fill_mode: str = "none"
    count: int = 1
    where: str = ""
    frames: list[KeyframeStep] = []
    pointer: EvidencePointer


class MeasuredReveal(BaseModel):
    """An entrance reveal whose motion is CSS (a script only adds the class that starts it)."""

    model_config = ConfigDict(extra="forbid")

    where: str
    count: int = 1
    from_opacity: float | None = None
    from_transform: str | None = None
    duration_ms: float = 0.0
    easing: str = "ease"
    delay_ms: float = 0.0
    trigger: list[str] = []
    pointer: EvidencePointer


class ScriptedMotion(BaseModel):
    """Motion only a script can make (a canvas, a playing video, inline styles rewritten every
    frame): recorded so a page can say it exists, never reproduced."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["scripted", "canvas", "video"]
    where: str
    pointer: EvidencePointer


class MotionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    animations: list[MeasuredAnimation] = []
    reveals: list[MeasuredReveal] = []
    scripted: list[ScriptedMotion] = []
```
  and in `GeometryEvidence` add, after `background_sequence`:
  `styles: list[MeasuredStyle] = []` and `motion: MotionEvidence = MotionEvidence()`. Export the
  new names from `lumen_ingestion/__init__.py` beside `StateStyle`.

- [ ] **Step 4: Write `capture/motion.py`.**

```python
"""Motion and icons read out of what the capture already holds (Wave 2 A9).

The probe sees WHICH animations run and the icon each button draws; the `@keyframes` bodies live in
the stylesheets the capture fetched (cross-origin ones included, which the browser's CSSOM refuses
to show), and an icon arrives as the page's own SVG markup. Both are cut down here to values a
generated page may carry: keyframes animate compositing and paint properties only, with values that
cannot load anything (no `url()`, no `var()`); an icon keeps drawing elements and drawing attributes
only. The same rules are the engine's (`lumen-core` `validate_style_tokens`), so nothing kept here
is refused later.
"""

from __future__ import annotations

import html
import re
from typing import Any, Iterable, Iterator

import tinycss2
from selectolax.lexbor import LexborHTMLParser

from ..evidence import KeyframeStep, MotionEvidence

KEYFRAME_PROPERTIES = frozenset({
    "opacity", "transform", "translate", "scale", "rotate", "filter", "color",
    "background-color", "border-color", "box-shadow", "background-position",
})
MAX_KEYFRAME_STEPS = 32
MAX_KEYFRAME_DECLARATIONS = 12
MAX_ICON_SVG_BYTES = 4096
_SAFE_VALUE = re.compile(r"^[A-Za-z0-9 ,.()%#+\-/]{1,200}$")
_UNSAFE = ("url(", "var(", "expression")
_SVG_ELEMENTS = frozenset({"svg", "g", "path", "circle", "ellipse", "line", "polyline", "polygon", "rect"})
_SVG_ATTRIBUTES = {
    name.lower(): name
    for name in (
        "viewBox", "d", "fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin",
        "stroke-miterlimit", "fill-rule", "clip-rule", "cx", "cy", "r", "rx", "ry", "x", "y", "x1",
        "y1", "x2", "y2", "points", "width", "height", "transform", "opacity", "fill-opacity",
        "stroke-opacity",
    )
}
_ATTRIBUTE_VALUE = re.compile(r"^[A-Za-z0-9 ,.()%#+\-]{0,2000}$")


def safe_style_value(value: str) -> bool:
    """A CSS value that only draws: plain characters, nothing that loads or substitutes."""
    lower = value.lower()
    return bool(_SAFE_VALUE.match(value)) and not any(bad in lower for bad in _UNSAFE)


def _offsets(prelude: list) -> list[float]:
    out: list[float] = []
    for part in tinycss2.serialize(prelude).split(","):
        word = part.strip().lower()
        if word == "from":
            out.append(0.0)
        elif word == "to":
            out.append(100.0)
        elif word.endswith("%"):
            try:
                out.append(round(float(word[:-1]), 2))
            except ValueError:
                return []
        else:
            return []
    return out


def _keyframes_rules(rules: Iterable[Any]) -> Iterator[tuple[str, list]]:
    for rule in rules:
        if getattr(rule, "type", "") != "at-rule" or rule.content is None:
            continue
        keyword = rule.lower_at_keyword
        if keyword in ("keyframes", "-webkit-keyframes"):
            yield tinycss2.serialize(rule.prelude).strip().strip("\"'"), rule.content
        elif keyword in ("media", "supports", "layer", "container"):
            yield from _keyframes_rules(
                tinycss2.parse_rule_list(rule.content, skip_comments=True, skip_whitespace=True)
            )


def keyframe_steps(stylesheets: Iterable[Any], name: str) -> list[KeyframeStep]:
    """The last `@keyframes <name>` in cascade order, as clean steps; `[]` when absent or unusable."""
    found = None
    for sheet in stylesheets:
        text = getattr(sheet, "text", "") or ""
        if name not in text:
            continue
        parsed = tinycss2.parse_stylesheet(text, skip_comments=True, skip_whitespace=True)
        for rule_name, content in _keyframes_rules(parsed):
            if rule_name == name:
                found = content
    if found is None:
        return []
    steps: dict[float, dict[str, str]] = {}
    for rule in tinycss2.parse_rule_list(found, skip_comments=True, skip_whitespace=True):
        if getattr(rule, "type", "") != "qualified-rule":
            continue
        declarations: dict[str, str] = {}
        for decl in tinycss2.parse_declaration_list(rule.content, skip_comments=True, skip_whitespace=True):
            if getattr(decl, "type", "") != "declaration":
                continue
            value = tinycss2.serialize(decl.value).strip()
            if decl.lower_name in KEYFRAME_PROPERTIES and safe_style_value(value):
                declarations[decl.lower_name] = value
        if not declarations:
            continue
        for offset in _offsets(rule.prelude):
            steps.setdefault(offset, {}).update(declarations)
    ordered = [
        KeyframeStep(offset=offset, declarations=dict(list(decls.items())[:MAX_KEYFRAME_DECLARATIONS]))
        for offset, decls in sorted(steps.items())
    ]
    return ordered if 2 <= len(ordered) <= MAX_KEYFRAME_STEPS else []


def attach_keyframes(motion: MotionEvidence, stylesheets: Iterable[Any]) -> MotionEvidence:
    """The animations whose definition the capture holds, with it; the rest are dropped."""
    sheets = list(stylesheets)
    kept = []
    for animation in motion.animations:
        steps = keyframe_steps(sheets, animation.name)
        if steps:
            kept.append(animation.model_copy(update={"frames": steps}))
    return motion.model_copy(update={"animations": kept})


def clean_icon_svg(markup: object) -> str | None:
    """A button icon's SVG with drawing elements and drawing attributes only, or None."""
    if not isinstance(markup, str) or "<svg" not in markup.lower():
        return None
    root = LexborHTMLParser(markup).css_first("svg")
    if root is None:
        return None

    def emit(node: Any) -> str:
        tag = (node.tag or "").lower()
        if tag not in _SVG_ELEMENTS:
            return ""
        attributes = []
        for name, value in (node.attributes or {}).items():
            key = _SVG_ATTRIBUTES.get(str(name).lower())
            text = "" if value is None else str(value)
            if key is None or not _ATTRIBUTE_VALUE.match(text) or "url(" in text.lower():
                continue
            attributes.append(f'{key}="{html.escape(text, quote=True)}"')
        inner = "".join(emit(child) for child in node.iter(include_text=False))
        return f"<{' '.join([tag, *attributes])}>{inner}</{tag}>"

    cleaned = emit(root)
    return cleaned if len(cleaned.encode()) <= MAX_ICON_SVG_BYTES else None
```

- [ ] **Step 5: Parse the states into `MeasuredStyle`s.** In `capture/geometry.py`:
  1. Add to the evidence import: `MeasuredAnimation, MeasuredReveal, MeasuredStyle, MotionEvidence,
     ScriptedMotion, StyleIcon, StyleLook, StyleTransition`; add `import re` and
     `from .motion import clean_icon_svg` (`hex_alpha` is already imported from `..colorspace`).
  2. In `GeometryHarvest` add `styles: list[MeasuredStyle] = field(default_factory=list)` and
     `motion: MotionEvidence = field(default_factory=MotionEvidence)`, and in `evidence()` pass
     `styles=list(self.styles), motion=self.motion`.
  3. In `parse_geometry`, after the `except` block that guards the existing reads and before
     `return harvest`, add:

```python
    # Measured styles and motion (Wave 2 A9) in their own guard: a malformed state record costs
    # these, never the shapes and scales above.
    try:
        states = raw.get("states") if isinstance(raw.get("states"), dict) else None
        harvest.styles = measured_styles(surfaces, states, url)
        harvest.motion = measured_motion(raw, url)
    except Exception as error:  # noqa: BLE001 — measurement must never fail an ingest
        harvest.styles, harvest.motion = [], MotionEvidence()
        harvest.diagnostics.append(_diag(f"measured styles could not be read: {error}"))
```
  4. In `_read_sections`' `SectionBackground(...)` add `ink=_opaque_hex(entry.get("ink")),`.
  5. Add, after `_cluster_shapes`:

```python
#: Bounds the evidence: a real page has 15-25 style variants across these classes.
_MAX_MEASURED_STYLES = 40
_MAX_REVEALS = 6
_LOOK_COLORS = ("background", "color", "label_color", "border_color", "outline_color", "icon_color")
_LOOK_TEXTS = (
    "border_style", "text_transform", "decoration_line", "decoration_thickness", "underline_offset",
    "box_shadow", "transform", "filter", "cursor", "outline_style", "icon_transform",
)
_LOOK_NUMBERS = (
    "height", "gap", "font_size", "font_weight", "line_height", "letter_spacing", "opacity",
    "outline_width", "outline_offset", "icon_opacity",
)
_LOOK_LISTS = ("border_width", "radius", "padding")
_FONT = re.compile(r"^(\d+)\s+([\d.]+)px/(\S+)\s+(.+)$")


def _opaque_hex(value: object) -> str | None:
    """A measured colour, or None when it paints nothing (fully transparent)."""
    hex_value = _hex(value)
    return hex_value if hex_value and hex_alpha(hex_value) > 0 else None


def _family(value: object) -> str | None:
    text = _text(value)
    return text.split(",", 1)[0].strip().strip("\"'") or None if text else None


def _look_fields(look: dict) -> dict:
    """A probe look (or state delta) as `StyleLook` fields; absent and empty values left out."""
    out: dict = {}
    for key in _LOOK_COLORS:
        if key in look:
            out[key] = _opaque_hex(look.get(key))
    for key in _LOOK_TEXTS:
        if key in look:
            out[key] = _text(look.get(key))
    for key in _LOOK_NUMBERS:
        value = look.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            out[key] = round(float(value), 2)
    for key in _LOOK_LISTS:
        if key in look:
            out[key] = _numbers(look.get(key))
    if "font_family" in look:
        out["font_family"] = _family(look.get("font_family"))
    if look.get("browser_focus_ring"):
        out["browser_focus_ring"] = True
    return {key: value for key, value in out.items() if value is not None and value != []}


def _rest_look(entry: dict, probe: dict | None) -> StyleLook:
    font = _FONT.match(str(entry.get("font") or ""))
    drawn = str(entry.get("borderStyle") or "none").lower() not in ("none", "hidden") and any(
        v > 0 for v in _numbers(entry.get("border"))
    )
    gaps = _numbers(entry.get("gap"))
    data: dict = {
        "background": _opaque_hex(entry.get("bg")),
        "color": _opaque_hex(entry.get("color")),
        "border_color": _opaque_hex(entry.get("borderColor")) if drawn else None,
        "border_width": _numbers(entry.get("border")),
        "border_style": _text(entry.get("borderStyle")),
        "radius": _numbers(entry.get("radius")),
        "pill": bool(entry.get("pill")),
        "padding": _numbers(entry.get("padding")),
        "height": _float(entry.get("h")) or None,
        "gap": gaps[-1] if gaps else None,
    }
    if font:
        data.update({
            "font_weight": float(font.group(1)),
            "font_size": float(font.group(2)),
            "line_height": float(font.group(3)[:-2]) if font.group(3).endswith("px") else None,
            "font_family": _family(font.group(4)),
        })
    if probe:
        extra = _look_fields(probe)
        # Geometry comes from the rest harvest (it knows pills); the probe adds everything else.
        for key in ("background", "border_color", "border_width", "border_style", "radius", "padding", "height", "gap"):
            extra.pop(key, None)
        data.update(extra)
    return StyleLook(**{key: value for key, value in data.items() if value is not None})


def _state_look(record: dict | None, state: str) -> StyleLook | None:
    look = record.get(state) if record else None
    fields = _look_fields(look) if isinstance(look, dict) else {}
    return StyleLook(**fields) if fields else None


def _transitions(motion: dict | None) -> list[StyleTransition]:
    out: list[StyleTransition] = []
    for target, key in (("self", "transitions"), ("label", "label_transitions"), ("icon", "icon_transitions")):
        for item in _list((motion or {}).get(key)):
            if not isinstance(item, dict) or _float(item.get("duration_ms")) <= 0:
                continue
            out.append(StyleTransition(
                target=target, property=str(item.get("property") or "all")[:60],
                duration_ms=_float(item.get("duration_ms")), easing=str(item.get("easing") or "ease")[:120],
                delay_ms=_float(item.get("delay_ms")),
            ))
    return out


def _icon(motion: dict | None) -> StyleIcon | None:
    info = (motion or {}).get("icon")
    if not isinstance(info, dict):
        return None
    position = "start" if info.get("position") == "start" else "end"
    if info.get("kind") == "glyph" and isinstance(info.get("glyph"), str):
        return StyleIcon(kind="glyph", position=position, glyph=info["glyph"][:4])
    if info.get("kind") == "svg":
        svg = clean_icon_svg(info.get("svg"))
        if svg:
            return StyleIcon(kind="svg", position=position, svg=svg,
                             width=_float(info.get("width")) or None, height=_float(info.get("height")) or None)
    if info.get("kind") == "img":
        return StyleIcon(kind="img", position=position)
    return None


def measured_styles(surfaces: list[dict], states: dict | None, url: str) -> list[MeasuredStyle]:
    """One `MeasuredStyle` per variant of the state classes, buttons first, most frequent first."""
    records = {
        record["idx"]: record
        for record in _list((states or {}).get("styles"))
        if isinstance(record, dict) and isinstance(record.get("idx"), int)
    }
    order = list(STATE_TARGET_CAPS)
    groups = sorted(shape_groups(surfaces, tuple(STATE_TARGET_CAPS)), key=lambda g: order.index(str(g[1][0].get("cls"))))
    out: list[MeasuredStyle] = []
    for variant, members in groups[:_MAX_MEASURED_STYLES]:
        cls = str(members[0].get("cls") or "")
        record = next((records[m["idx"]] for m in members if m.get("idx") in records), None)
        entry = next((m for m in members if record is not None and m.get("idx") == record["idx"]), members[0])
        motion = record.get("motion") if record else None
        out.append(MeasuredStyle(
            surface=cls,  # type: ignore[arg-type]
            variant=variant,
            count=len(members),
            probed=str(record.get("how")) if record and record.get("how") in ("pointer", "forced") else "rest-only",  # type: ignore[arg-type]
            rest=_rest_look(entry, record.get("rest") if record else None),
            hover=_state_look(record, "hover"),
            pressed=_state_look(record, "pressed"),
            focus=_state_look(record, "focus"),
            disabled=_state_look(record, "disabled"),
            transitions=_transitions(motion),
            icon=_icon(motion),
            pointer=_pointer(url, f"{cls} {variant}"),
        ))
    return out


def _first(value: object) -> str:
    """The first entry of a computed comma list (`"pulse, spin"` → `"pulse"`), parentheses kept."""
    text, depth = str(value or ""), 0
    for index, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            return text[:index].strip()
    return text.strip()


def _ms(value: object) -> float:
    text = _first(value)
    try:
        return round(float(text[:-2]) if text.endswith("ms") else float(text.rstrip("s")) * 1000, 2)
    except ValueError:
        return 0.0


def measured_motion(raw: dict, url: str) -> MotionEvidence:
    """The page's CSS animations, its CSS reveals (deduplicated) and its scripted-motion notes."""
    animations: list[MeasuredAnimation] = []
    for entry in _list(raw.get("animations")):
        if not isinstance(entry, dict):
            continue
        name = _first(entry.get("name"))[:120]
        if not name or name == "none":
            continue
        animations.append(MeasuredAnimation(
            name=name, duration_ms=_ms(entry.get("duration")), easing=_first(entry.get("easing")) or "ease",
            delay_ms=_ms(entry.get("delay")), iterations=_first(entry.get("iterations")) or "1",
            direction=_first(entry.get("direction")) or "normal", fill_mode=_first(entry.get("fill")) or "none",
            count=max(1, int(_float(entry.get("count")) or 1)), where=str(entry.get("where") or "")[:120],
            pointer=_pointer(url, f"animation {name}"),
        ))
    states = raw.get("states") if isinstance(raw.get("states"), dict) else {}
    reveals: dict[tuple, MeasuredReveal] = {}
    scripted: list[ScriptedMotion] = []
    for entry in _list(states.get("reveals")):
        if not isinstance(entry, dict):
            continue
        where = str(entry.get("where") or "")[:120]
        if entry.get("kind") != "css":
            scripted.append(ScriptedMotion(kind="scripted", where=where, pointer=_pointer(url, f"reveal {where}")))
            continue
        main = max(
            (t for t in _list(entry.get("transitions")) if isinstance(t, dict)),
            key=lambda t: _float(t.get("duration_ms")), default={},
        )
        opacity = entry.get("from_opacity")
        opacity = float(opacity) if isinstance(opacity, (int, float)) and not isinstance(opacity, bool) else None
        key = (opacity, _text(entry.get("from_transform")), _float(main.get("duration_ms")), main.get("easing"))
        if key in reveals:
            reveals[key].count += 1
            continue
        reveals[key] = MeasuredReveal(
            where=where, from_opacity=opacity, from_transform=_text(entry.get("from_transform")),
            duration_ms=_float(main.get("duration_ms")), easing=str(main.get("easing") or "ease")[:120],
            delay_ms=_float(main.get("delay_ms")), trigger=[str(t)[:40] for t in _list(entry.get("trigger"))][:3],
            pointer=_pointer(url, f"reveal {where}"),
        )
    for entry in _list(states.get("scripted")):
        if isinstance(entry, dict) and entry.get("kind") in ("scripted", "canvas", "video"):
            where = str(entry.get("where") or "")[:120]
            scripted.append(ScriptedMotion(kind=entry["kind"], where=where, pointer=_pointer(url, f"{entry['kind']} {where}")))
    return MotionEvidence(animations=animations, reveals=list(reveals.values())[:_MAX_REVEALS], scripted=scripted[:12])
```

- [ ] **Step 6: Attach keyframes, and keep the brief agent's input as it was.**
  1. In `capture/evidence_builder.py`, add `from .motion import attach_keyframes` and, after
     `geometry = parse_geometry(snapshot.geometry, page_url=snapshot.final_url)`:

```python
    # Motion (Wave 2 A9): the probe saw which animations run; their @keyframes bodies are in the
    # stylesheets this capture fetched, cross-origin ones included.
    geometry_evidence = geometry.evidence()
    geometry_evidence = geometry_evidence.model_copy(
        update={"motion": attach_keyframes(geometry_evidence.motion, snapshot.stylesheets)}
    )
```
     and in the final `BrandEvidence(...)` replace `geometry=geometry.evidence(),` with
     `geometry=geometry_evidence,`.
  2. In `brief_agent.py`, `_dump(model)` becomes:

```python
def _dump(model: Any, exclude: set[str] | None = None) -> dict[str, Any]:
    return model.model_dump(exclude=exclude) if hasattr(model, "model_dump") else dict(model)
```
     and in `build_brief_request`, `background_sequence=[_dump(band) for band in …]` becomes
     `background_sequence=[_dump(band, exclude={"ink"}) for band in …]` with the comment
     `# The band text colour (Wave 2 A9) is minted into the kit, not sent to the model.`

- [ ] **Step 7: Run the tests.**

Run: `CAPTURE_PYTEST test_ingestion_measured_styles.py test_ingestion_geometry.py test_ingestion_brief.py test_capture_style_states.py`
Expected: PASS.

- [ ] **Step 8: Commit.**

```bash
git add subsystems/clue-design/apps/api/lumen_ingestion/evidence.py subsystems/clue-design/apps/api/lumen_ingestion/__init__.py \
  subsystems/clue-design/apps/api/lumen_ingestion/capture/geometry.py subsystems/clue-design/apps/api/lumen_ingestion/capture/motion.py \
  subsystems/clue-design/apps/api/lumen_ingestion/capture/evidence_builder.py subsystems/clue-design/apps/api/lumen_ingestion/brief_agent.py \
  subsystems/clue-design/apps/api/tests/test_ingestion_measured_styles.py
git commit -m "ingestion evidence: measured styles in every state, keyframe definitions, reveals, scripted-motion notes and band text colours; the brief agent's input is unchanged"
```

### Task X4: Every measured value becomes a token of this kit, and every section background a surface

**Files:**
- Create: `subsystems/clue-design/apps/api/lumen_ingestion/normalizer/component_tokens.py`
- Rewrite: `subsystems/clue-design/apps/api/lumen_ingestion/normalizer/bands.py`
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/normalizer/__init__.py`
  (`NormalizeResult`, the band block at `:141-154`, constraints, the mint after `builder.build`)
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/brief_agent.py` (`spacing_ladder`)
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/brief_agent_prompt.md:72-75` (T-A9-6)
- Create: `subsystems/clue-design/apps/api/tests/test_ingestion_component_tokens.py`
- Modify: `subsystems/clue-design/apps/api/tests/test_ingestion_geometry.py` (the band block,
  `:347-526`), `test_ingestion_brief.py` (`:64-72`, `:267-284`), `test_ingestion_grammar_audit.py:426`

**Interfaces:**
- Produces: `mint_component_tokens(kit, styles, motion) -> MintResult(section, minted, diagnostics)`
  (mutates `kit["tokens"]`; `section` is the `measured_components` payload, or `None` when nothing
  was measured); `is_component_token(name)`, `COMPONENT_ROOTS`, `TOKEN_ROOTS`, `MAX_MINTED_TOKENS`
  (192), `MAX_MINTED_COLORS` (48); predicates `keyword_ok`, `easing_ok`, `transform_ok`, `glyph_ok`,
  `svg_ok` (the engine's rules); `build_band_surfaces(sequence, surface_colors) -> (bands, skipped)`,
  `band_path(hex)`, `MAX_BAND_SURFACES` (12); `NormalizeResult.measured_components: dict | None`;
  diagnostic `LUMI0607` (a cap skipped values).
- Token names: `<component>.<variant>[.<state>].<slot>` with component ∈ `button link navlink card
  chip input image`, variant `solid-2` (the shape variant with `.`→`-`), state ∈ `hover pressed focus
  disabled`, slot ∈ `fill label border border-width[-side] border-style radius[-corner]
  padding-<side> height gap font case decoration decoration-thickness underline-offset shadow[-n]
  opacity transform filter cursor outline outline-width outline-style outline-offset icon icon-color
  icon-transform icon-opacity`; motion `motion.<component>.<variant>.(duration|easing|delay)-<n>`,
  `motion.keyframes.<slug>`, `motion.animation.<slug>[.duration|.easing|.delay]`,
  `motion.reveal.<8-hex>[.from-opacity|.from-transform|.duration|.easing]`; bands
  `surface.band.<rrggbb>` and, for a measured band text colour no token holds, `text.band.<rrggbb>`.

- [ ] **Step 1: Confirm T-A9-6 was approved**, then replace `brief_agent_prompt.md:72-75` ("A
  background color the page recurs on is minted … nearest approximation.") with the approved
  paragraph:

```markdown
  named by its surface token. Every flat section background the page shows is a surface token: an
  existing `surface.*` token when one holds exactly that colour, otherwise a `surface.band.<hex>`
  token minted from it (for example `surface.band.014036`) — name the bands by them rather than by
  the nearest approximation. Note whether
```
  (and, only if the optional sentence was approved, append to the `component_recipes[]` bullet:
  "The kit also carries tokens minted from those shape records, named for where they were measured
  (`button.solid-2.fill`, `card.solid-1.radius`); when a slot's measured value has one, name it.").

- [ ] **Step 2: Write the failing tests** `apps/api/tests/test_ingestion_component_tokens.py`:

```python
"""Measured styles become brand-scoped kit tokens (Wave 2 A9, Task X4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lumen_api.core import CoreClient
from lumen_ingestion.brief_agent import build_brief_request
from lumen_ingestion.capture.geometry import parse_geometry
from lumen_ingestion.capture.motion import attach_keyframes
from lumen_ingestion.capture.snapshot import Stylesheet
from lumen_ingestion.evidence import BrandEvidence
from lumen_ingestion.normalizer import component_tokens
from lumen_ingestion.normalizer.component_tokens import (
    easing_ok, glyph_ok, is_component_token, keyword_ok, mint_component_tokens, transform_ok,
)

TESTS = Path(__file__).resolve().parent
HARVEST = json.loads((TESTS / "fixtures" / "capture" / "style_states.harvest.json").read_text())
CSS = (TESTS / "fixtures" / "capture" / "style_states.html").read_text().split("<style>", 1)[1].split("</style>", 1)[0]
GARNER = TESTS.parents[4] / "trials" / "puck-spike" / "data" / "brands" / "garner" / "kit.json"


def _kit() -> dict:
    return {k: v for k, v in json.loads(GARNER.read_text()).items() if k not in ("brief", "grammar_audit")}


def _mint(kit: dict | None = None):
    kit = _kit() if kit is None else kit
    parsed = parse_geometry(HARVEST, page_url="https://fixture.test/")
    motion = attach_keyframes(parsed.motion, [Stylesheet(url="https://fixture.test/", text=CSS)])
    return kit, mint_component_tokens(kit, parsed.styles, motion)


def _value(kit: dict, group: str, name: str):
    return kit["tokens"][group][name]["value"]["default"]


def _recipe(kit: dict, result, component: str, fill: str | None = None):
    for recipe in result.section["styles"]:
        if recipe["component"] != component:
            continue
        if fill is None or (recipe["rest"].get("fill") and _value(kit, "colors", recipe["rest"]["fill"])["value"] == fill):
            return recipe
    raise AssertionError(f"no {component} recipe with fill {fill}")


def test_measured_values_become_tokens_named_for_where_they_were_measured() -> None:
    kit, result = _mint()
    solid = _recipe(kit, result, "button", "#047464")
    assert solid["rest"]["fill"] == "surface.brand", "Garner's surface.brand holds exactly #047464"
    assert solid["rest"]["label"] == "text.inverse"
    assert solid["rest"]["radius"] == "radius.full", "a pill is 9999px, radius.full exactly"
    slug = solid["variant"].replace(".", "-")
    hover_fill = f"button.{slug}.hover.fill"
    assert solid["states"]["hover"]["fill"] == hover_fill
    assert _value(kit, "colors", hover_fill) == {"kind": "hex", "value": "#035A4E"}
    entry = kit["tokens"]["colors"][hover_fill]
    assert entry["provenance"] == {"source": f"website:https://fixture.test/ :: button {solid['variant']} hover fill", "confidence": 0.8}
    assert entry["role"] == "component"
    assert _value(kit, "styles", solid["states"]["pressed"]["transform"]) == {"kind": "transform", "value": "matrix(0.98, 0, 0, 0.98, 0, 0)"}
    assert _value(kit, "styles", solid["rest"]["case"]) == {"kind": "keyword", "property": "text-transform", "value": "uppercase"}
    assert _value(kit, "colors", solid["states"]["focus"]["outline"]) == {"kind": "hex", "value": "#F5A623"}
    assert _value(kit, "opacity", solid["states"]["disabled"]["opacity"]) == {"kind": "number", "unit": "ratio", "value": 0.45}
    assert solid["icon"]["position"] == "end" and _value(kit, "styles", solid["icon"]["token"])["kind"] == "svg"
    assert [step["property"] for step in solid["motion"]] == ["background-color", "transform", "box-shadow", "transform"]
    assert [step["target"] for step in solid["motion"]] == ["self", "self", "self", "icon"]
    assert _value(kit, "styles", solid["motion"][0]["duration"]) == {"kind": "duration", "ms": 200.0}
    assert solid["motion"][2]["delay"] and _value(kit, "styles", solid["motion"][2]["delay"]) == {"kind": "duration", "ms": 50.0}
    js = _recipe(kit, result, "button", "#7C4CFF")
    assert js["browser_focus_ring"] is True and "focus" not in js["states"]
    link = _recipe(kit, result, "link")
    assert _value(kit, "styles", link["states"]["hover"]["decoration"])["value"] == "underline"
    assert _value(kit, "numbers", link["states"]["hover"]["decoration-thickness"]) == {"kind": "number", "unit": "px", "value": 2.0}
    pulse = _value(kit, "styles", "motion.animation.pulse")
    assert pulse["keyframes"] == "motion.keyframes.pulse" and pulse["iterations"] == "infinite"
    assert [f["offset"] for f in _value(kit, "styles", "motion.keyframes.pulse")["frames"]] == [0.0, 50.0, 100.0]
    (reveal,) = result.section["motion"]["reveals"]
    assert reveal.startswith("motion.reveal.") and _value(kit, "styles", reveal)["kind"] == "reveal"
    assert result.section["motion"]["scripted"] == [{"kind": "scripted", "where": "div#spin.spin"}]


def test_identical_values_share_one_token() -> None:
    kit, result = _mint()
    shadows = {
        recipe["states"]["hover"]["shadow-1"]
        for recipe in result.section["styles"]
        if recipe["component"] == "button" and "shadow-1" in recipe["states"].get("hover", {})
    }
    assert len(shadows) == 1, "every .btn hover casts the same shadow"
    assert len(result.minted) == len(set(result.minted))


def test_reuse_is_exact_with_no_tolerance() -> None:
    kit = _kit()
    kit["tokens"]["colors"]["surface.brand"]["value"]["default"]["value"] = "#047465"
    kit, result = _mint(kit)
    solid = _recipe(kit, result, "button", "#047464")
    assert solid["rest"]["fill"] == f"button.{solid['variant'].replace('.', '-')}.fill"


def test_minting_twice_over_the_same_page_names_the_same_tokens() -> None:
    first_kit, first = _mint()
    second_kit, second = _mint()
    assert first.section == second.section
    assert json.dumps(first_kit["tokens"], sort_keys=True) == json.dumps(second_kit["tokens"], sort_keys=True)


def test_the_cap_skips_values_loudly_and_reuse_still_works(monkeypatch) -> None:
    monkeypatch.setattr(component_tokens, "MAX_MINTED_TOKENS", 5)
    kit, result = _mint()
    assert len(result.minted) == 5
    (diagnostic,) = [d for d in result.diagnostics if d["code"] == "LUMI0607"]
    assert "cap of 5 tokens" in diagnostic["message"]
    assert _recipe(kit, result, "button", "#047464")["rest"]["fill"] == "surface.brand"
    monkeypatch.setattr(component_tokens, "MAX_MINTED_TOKENS", 192)
    monkeypatch.setattr(component_tokens, "MAX_MINTED_COLORS", 1)
    colour_kit, limited = _mint()
    assert sum(1 for name in limited.minted if name in colour_kit["tokens"]["colors"]) == 1


def test_a_kit_with_minted_tokens_comes_back_from_the_engine_whole() -> None:
    kit, _ = _mint()
    validation = CoreClient().validate_brand_kit(kit, product_ready=False, raise_on_error=False)
    assert validation["ok"] is True
    returned = validation["brand_kit"]["tokens"]
    for group in ("colors", "radii", "spacing", "stroke_widths", "opacity", "shadows", "typography", "numbers", "styles"):
        assert returned.get(group, {}) == kit["tokens"].get(group, {}), group


@pytest.mark.parametrize(
    "value,expected",
    [
        ({"kind": "keyword", "property": "cursor", "value": "pointer"}, True),
        ({"kind": "keyword", "property": "cursor", "value": "url(a), auto"}, False),
        ({"kind": "keyword", "property": "box-shadow", "value": "none"}, True),
        ({"kind": "keyword", "property": "box-shadow", "value": "0 0 1px red"}, False),
        ({"kind": "easing", "function": "cubic-bezier(0.2, 0.8, 0.2, 1)"}, True),
        ({"kind": "easing", "function": "spring(1)"}, False),
        ({"kind": "transform", "value": "matrix(1, 0, 0, 1, 0, -2)"}, True),
        ({"kind": "transform", "value": "rotate(4deg)"}, False),
        ({"kind": "glyph", "text": "→"}, True),
        ({"kind": "glyph", "text": "&"}, False),
    ],
)
def test_ingestion_and_the_engine_agree_on_every_style_value(value: dict, expected: bool) -> None:
    python_ok = {
        "keyword": lambda v: keyword_ok(v["property"], v["value"]),
        "easing": lambda v: easing_ok(v["function"]),
        "transform": lambda v: transform_ok(v["value"]),
        "glyph": lambda v: glyph_ok(v["text"]),
    }[value["kind"]](value)
    assert python_ok is expected
    kit = _kit()
    kit["tokens"]["styles"] = {"button.solid-1.x": {"value": {"default": value, "modes": {}}, "description": None, "provenance": None}}
    validation = CoreClient().validate_brand_kit(kit, product_ready=False, raise_on_error=False)
    engine_ok = not any(d["severity"] == "error" and d["code"].startswith("LUMB026") for d in validation["diagnostics"])
    assert engine_ok is expected


def test_component_tokens_are_known_by_their_root() -> None:
    assert is_component_token("button.solid-1.fill") and is_component_token("motion.reveal.ab12cd34")
    assert not is_component_token("surface.band.014036") and not is_component_token("space.card.padding")


def test_the_brief_agents_spacing_ladder_has_no_minted_tokens() -> None:
    kit, _ = _mint()
    evidence = BrandEvidence.model_validate(json.loads((TESTS / "fixtures" / "ingestion" / "evidence_website_insight.json").read_text()))
    request = build_brief_request(evidence, kit)
    assert request.spacing_ladder and not any(is_component_token(row["name"]) for row in request.spacing_ladder)
    assert any(is_component_token(row["name"]) for row in request.tokens), "the model may still name them"
```

- [ ] **Step 3: Run them to see them fail.**

Run: `CAPTURE_PYTEST test_ingestion_component_tokens.py`
Expected: FAIL at import — no module `lumen_ingestion.normalizer.component_tokens`.

- [ ] **Step 4: Write `normalizer/component_tokens.py`.**

```python
"""Measured component styles → brand-scoped kit tokens (Wave 2 A9; founder rulings 2026-10-12).

Every value the capture measured on a style — fill, label colour, border, corners, padding, font,
case, decoration, shadow, transform, opacity, cursor, outline, icon, in rest and in each state, and
the timing of its transitions — becomes a token of THIS kit, and the page's CSS animations and
reveals become named motion entries. Three rules, each enforced here:

* Exact-match reuse. A token of this kit that already holds exactly that value (same group, same
  value, no tolerance) is named instead of minting a second; among several, the one whose family
  suits the slot wins (a fill prefers `surface.*`, a label `text.*`, a border `border.*`), then a
  token that was not minted, then the name. Identical values used by several styles share one token.
* Stable names made by code from where the value was measured: `button.solid-2.fill`,
  `button.solid-2.hover.fill`, `motion.button.solid-2.duration-1`, `motion.keyframes.pulse`,
  `motion.reveal.<digest>`. The same page yields the same names on every extraction; no model names
  anything.
* A per-kit cap. The web author's prompt lists every colour token of the kit
  (`web_theme_token_names`) and the brief agent reads every token row, so a kit's ~60-token
  vocabulary may grow by at most `MAX_MINTED_TOKENS` (and `MAX_MINTED_COLORS` colours); buttons are
  minted first, so the cap costs the least-used styles, and what it skips is named (LUMI0607).

Values the engine cannot hold are refused here with the engine's own rules
(`crates/lumen-core/src/brand.rs` `validate_style_tokens`); a mint never fails a kit's validation.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from ..capture.geometry import PILL_RADIUS_PX, _parse_box_shadow
from ..capture.motion import KEYFRAME_PROPERTIES, MAX_ICON_SVG_BYTES, safe_style_value
from ..colorspace import hex_alpha
from ..evidence import EvidencePointer, MeasuredAnimation, MeasuredReveal, MeasuredStyle, MotionEvidence, StyleLook
from .emit import _color_value, _mode_value, _provenance
from .geometry import MEASURED_CONFIDENCE, _shadow_value

COMPONENT_ROOTS = {
    "button": "button", "link": "link", "nav_link": "navlink", "card": "card",
    "chip": "chip", "input": "input", "image": "image",
}
MOTION_ROOT = "motion"
TOKEN_ROOTS = frozenset({*COMPONENT_ROOTS.values(), MOTION_ROOT})
MAX_MINTED_TOKENS = 192
MAX_MINTED_COLORS = 48
STATES = ("hover", "pressed", "focus", "disabled")
SIDES = ("top", "right", "bottom", "left")
CORNERS = ("tl", "tr", "br", "bl")
STYLE_KEYWORD_PROPERTIES = frozenset({
    "text-transform", "text-decoration-line", "text-decoration-thickness", "text-underline-offset",
    "cursor", "border-style", "outline-style", "transition-property", "filter", "box-shadow",
})
_KEYWORD = re.compile(r"^[A-Za-z0-9 ,.()%#+\-/]{1,200}$")
_EASING_WORDS = frozenset({"linear", "ease", "ease-in", "ease-out", "ease-in-out", "step-start", "step-end"})
_MATRIX = re.compile(r"^(?:matrix|matrix3d)\([0-9 ,.\-e]+\)$")
_PROPERTY = re.compile(r"^(?:all|[a-z-]{1,60})$")
_DIRECTIONS = frozenset({"normal", "reverse", "alternate", "alternate-reverse"})
_FILL_MODES = frozenset({"none", "forwards", "backwards", "both"})
_SVG_BANNED = ("<script", "javascript:", "url(", "href", "<foreignobject", "<!", "<?", "<style", "<use", "<image", "<a ", "<a>")
_EVENT_ATTRIBUTE = re.compile(r" on[a-z]+\s*=")
_SLUG = re.compile(r"[^a-z0-9]+")
#: Values a rest look carries that are no choice of the brand's; never minted at rest. A rest
#: `text-decoration-line: none` IS a choice (the browser underlines links), so it is minted.
_REST_DEFAULTS = {"text-transform": {"none"}, "cursor": {"auto", "default"}, "filter": {"none"}}
_FAMILY_PREFERENCE = {
    "fill": ("surface.", "palette.", "border.", "text."),
    "label": ("text.", "surface.", "palette.", "border."),
    "border": ("border.", "text.", "surface.", "palette."),
    "outline": ("focus.", "border.", "text.", "surface."),
    "icon-color": ("text.", "surface.", "palette.", "border."),
}
#: Groups whose engine token has a `role` field (shadows and styles have none).
_ROLE_BY_GROUP = {
    "colors": "component", "spacing": "spacing", "radii": "radius", "stroke_widths": "stroke",
    "opacity": "visibility", "numbers": "dimension", "typography": "component",
}
_SHADOW_POINTER = EvidencePointer(source="website", locator="component style box-shadow")


def is_component_token(name: str) -> bool:
    """A token this module mints (`button.*`, `link.*`, … `motion.*`)."""
    return str(name).split(".", 1)[0] in TOKEN_ROOTS


def keyword_ok(prop: str, value: object) -> bool:
    return (
        prop in STYLE_KEYWORD_PROPERTIES and isinstance(value, str) and bool(_KEYWORD.match(value))
        and "url(" not in value.lower() and "var(" not in value.lower() and "expression" not in value.lower()
        and (prop != "box-shadow" or value == "none")
    )


def easing_ok(function: object) -> bool:
    return isinstance(function, str) and (
        function in _EASING_WORDS
        or (function.startswith(("cubic-bezier(", "steps(", "linear(")) and function.endswith(")")
            and len(function) <= 400 and safe_style_value(function))
    )


def transform_ok(value: object) -> bool:
    return value == "none" or (isinstance(value, str) and len(value) <= 400 and bool(_MATRIX.match(value)))


def glyph_ok(text: object) -> bool:
    return isinstance(text, str) and 1 <= len(text) <= 4 and not any(c in "<>&\"'" or ord(c) < 32 for c in text)


def svg_ok(markup: object) -> bool:
    if not isinstance(markup, str) or len(markup.encode()) > MAX_ICON_SVG_BYTES:
        return False
    lower = markup.lower()
    trimmed = lower.strip()
    return (
        trimmed.startswith("<svg") and trimmed.endswith("</svg>")
        and not any(bad in lower for bad in _SVG_BANNED) and not _EVENT_ATTRIBUTE.search(lower)
    )


def _px(value: float) -> dict:
    return {"kind": "number", "unit": "px", "value": round(float(value), 2)}


def _ratio(value: float) -> dict:
    return {"kind": "number", "unit": "ratio", "value": round(float(value), 4)}


def _keyword(prop: str, value: object) -> dict | None:
    return {"kind": "keyword", "property": prop, "value": value} if keyword_ok(prop, value) else None


def _same(group: str, a: Any, b: Any) -> bool:
    """Exact equality of two token values, as the engine stores them."""
    if not isinstance(a, dict) or not isinstance(b, dict):
        return False
    if group == "colors":
        return a.get("kind") == b.get("kind") == "hex" and str(a.get("value")).upper() == str(b.get("value")).upper()
    if a.get("kind") == b.get("kind") == "number":
        return a.get("unit") == b.get("unit") and float(a.get("value", "nan")) == float(b.get("value", "nan"))
    if group == "typography":
        keys = ("font_family", "font_size", "font_weight", "line_height", "letter_spacing")
        return a.get("kind") == b.get("kind") == "style" and all(a.get(k) == b.get(k) for k in keys)
    if group == "shadows":
        numbers = ("x", "y", "blur", "spread")
        return all(float(a.get(k, 0)) == float(b.get(k, 0)) for k in numbers) and str(a.get("color")).upper() == str(b.get("color")).upper()
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


@dataclass
class _Minter:
    kit: dict
    minted: list[str] = field(default_factory=list)
    colors: int = 0
    dropped: list[str] = field(default_factory=list)

    def entries(self, group: str) -> dict:
        return self.kit.setdefault("tokens", {}).setdefault(group, {})

    def name(self, path: str, group: str, value: dict, *, pointer: str, slot: str = "", description: str | None = None) -> str | None:
        """The token holding `value`: an existing exact match, a new token at `path`, or None (cap)."""
        existing = self._exact(group, value, slot)
        if existing:
            return existing
        if len(self.minted) >= MAX_MINTED_TOKENS or (group == "colors" and self.colors >= MAX_MINTED_COLORS):
            self.dropped.append(path)
            return None
        entries = self.entries(group)
        name, suffix = path, 2
        while name in entries:
            name, suffix = f"{path}-{suffix}", suffix + 1
        entry: dict[str, Any] = {"value": _mode_value(value, {})}
        if group in _ROLE_BY_GROUP:
            entry["role"] = _ROLE_BY_GROUP[group]
        entry["description"] = description
        entry["provenance"] = _provenance(pointer, MEASURED_CONFIDENCE)
        entries[name] = entry
        self.minted.append(name)
        if group == "colors":
            self.colors += 1
        return name

    def _exact(self, group: str, value: dict, slot: str) -> str | None:
        prefs = _FAMILY_PREFERENCE.get(slot, ())
        matches = [
            name for name, entry in self.entries(group).items()
            if isinstance(entry, dict) and _same(group, (entry.get("value") or {}).get("default"), value)
            # The type scale's size steps live in `numbers` too; a button's height is never one.
            and not (group == "numbers" and name.startswith("type."))
        ]
        if not matches:
            return None

        def rank(name: str) -> tuple:
            family = next((i for i, prefix in enumerate(prefs) if name.startswith(prefix)), len(prefs))
            return (is_component_token(name), family, name)

        return min(matches, key=rank)


def _font(look: StyleLook, fonts: dict[str, str]) -> dict | None:
    if not (look.font_family and look.font_size and look.font_weight):
        return None
    size, weight = round(look.font_size, 2), int(round(look.font_weight))
    if size <= 0 or not 0 < weight <= 1000:
        return None
    return {
        "kind": "style", "font_family": look.font_family, "font_size": size, "font_weight": weight,
        "line_height": round(look.line_height / size, 2) if look.line_height else None,
        "letter_spacing": round((look.letter_spacing or 0.0) / size, 3), "color": None,
        "font_asset": fonts.get(look.font_family.lower()),
    }


def _slots(look: StyleLook, *, at_rest: bool, fonts: dict[str, str]) -> list[tuple[str, str, dict]]:
    """`(slot, group, value)` for every measured value of one look, in a fixed order."""
    out: list[tuple[str, str, dict]] = []

    def color(slot: str, hex_value: str | None) -> None:
        if hex_value and hex_alpha(hex_value) > 0:
            out.append((slot, "colors", _color_value(hex_value)))

    color("fill", look.background)
    color("label", look.label_color or look.color)
    # A rest look carries a border colour only when a border is drawn and visible (a 1px
    # transparent border is no border); a state may recolour or re-weigh the rest border.
    color("border", look.border_color)
    widths = look.border_width
    if (look.border_color or not at_rest) and any(w > 0 for w in widths) \
            and (look.border_style or "solid") not in ("none", "hidden"):
        if len(set(widths)) == 1:
            out.append(("border-width", "stroke_widths", _px(widths[0])))
        else:
            out.extend((f"border-width-{side}", "stroke_widths", _px(w)) for side, w in zip(SIDES, widths))
        style = _keyword("border-style", look.border_style) if look.border_style else None
        if style:
            out.append(("border-style", "styles", style))
    if look.pill:
        out.append(("radius", "radii", _px(PILL_RADIUS_PX)))
    elif look.radius:
        if len(set(look.radius)) == 1:
            out.append(("radius", "radii", _px(look.radius[0])))
        else:
            out.extend((f"radius-{corner}", "radii", _px(r)) for corner, r in zip(CORNERS, look.radius))
    out.extend((f"padding-{side}", "spacing", _px(v)) for side, v in zip(SIDES, look.padding))
    if at_rest and look.height:
        out.append(("height", "numbers", _px(look.height)))
    if look.gap is not None:
        out.append(("gap", "spacing", _px(look.gap)))
    font = _font(look, fonts)
    if font:
        out.append(("font", "typography", font))
    for slot, prop, value in (
        ("case", "text-transform", look.text_transform), ("decoration", "text-decoration-line", look.decoration_line),
        ("cursor", "cursor", look.cursor), ("filter", "filter", look.filter),
    ):
        if value is None or (at_rest and value in _REST_DEFAULTS.get(prop, ())):
            continue
        keyword = _keyword(prop, value)
        if keyword:
            out.append((slot, "styles", keyword))
    for slot, prop, value in (
        ("decoration-thickness", "text-decoration-thickness", look.decoration_thickness),
        ("underline-offset", "text-underline-offset", look.underline_offset),
    ):
        if value is None or (at_rest and value == "auto"):
            continue
        if value.endswith("px"):
            try:
                out.append((slot, "numbers", _px(float(value[:-2]))))
                continue
            except ValueError:
                pass
        keyword = _keyword(prop, value)
        if keyword:
            out.append((slot, "styles", keyword))
    if look.box_shadow == "none":
        out.append(("shadow", "styles", {"kind": "keyword", "property": "box-shadow", "value": "none"}))
    elif look.box_shadow:
        for index, sample in enumerate(_parse_box_shadow(look.box_shadow, _SHADOW_POINTER), 1):
            out.append((f"shadow-{index}", "shadows", _shadow_value(sample)))
    if look.opacity is not None and not (at_rest and look.opacity == 1):
        out.append(("opacity", "opacity", _ratio(look.opacity)))
    if look.transform and transform_ok(look.transform) and not (at_rest and look.transform == "none"):
        out.append(("transform", "styles", {"kind": "transform", "value": look.transform}))
    if look.outline_style not in (None, "none", "auto"):
        color("outline", look.outline_color)
        if look.outline_width is not None:
            out.append(("outline-width", "stroke_widths", _px(look.outline_width)))
        style = _keyword("outline-style", look.outline_style)
        if style:
            out.append(("outline-style", "styles", style))
        if look.outline_offset is not None:
            out.append(("outline-offset", "numbers", _px(look.outline_offset)))
    if look.icon_color and (not at_rest or look.icon_color != (look.label_color or look.color)):
        color("icon-color", look.icon_color)
    if look.icon_transform and transform_ok(look.icon_transform):
        out.append(("icon-transform", "styles", {"kind": "transform", "value": look.icon_transform}))
    if look.icon_opacity is not None and not (at_rest and look.icon_opacity == 1):
        out.append(("icon-opacity", "opacity", _ratio(look.icon_opacity)))
    return out


def _state_font(rest: StyleLook, state: StyleLook, fonts: dict[str, str]) -> dict | None:
    """A state's font when the state changes one of its parts (a bolder hover)."""
    changed = {k: getattr(state, k) for k in ("font_family", "font_size", "font_weight", "line_height", "letter_spacing") if getattr(state, k) is not None}
    return _font(rest.model_copy(update=changed), fonts) if changed else None


def _mint_style(m: _Minter, style: MeasuredStyle, fonts: dict[str, str], page: str) -> dict:
    root = COMPONENT_ROOTS[style.surface]
    slug = style.variant.replace(".", "-")
    base, stem = f"{root}.{slug}", f"{MOTION_ROOT}.{root}.{slug}"
    where = f"website:{page} :: {style.surface} {style.variant}"
    recipe: dict[str, Any] = {
        "component": style.surface, "variant": style.variant, "count": style.count, "probed": style.probed,
        "source": f"website:{page}", "rest": {}, "states": {}, "motion": [], "icon": None, "browser_focus_ring": False,
    }
    for slot, group, value in _slots(style.rest, at_rest=True, fonts=fonts):
        token = m.name(f"{base}.{slot}", group, value, pointer=f"{where} rest {slot}", slot=slot)
        if token:
            recipe["rest"][slot] = token
    for state in STATES:
        look = getattr(style, state)
        if look is None:
            continue
        if state == "focus" and look.browser_focus_ring:
            recipe["browser_focus_ring"] = True
        slots: dict[str, str] = {}
        pairs = [s for s in _slots(look, at_rest=False, fonts=fonts) if s[0] != "font"]
        font = _state_font(style.rest, look, fonts)
        if font:
            pairs.append(("font", "typography", font))
        for slot, group, value in pairs:
            token = m.name(f"{base}.{state}.{slot}", group, value, pointer=f"{where} {state} {slot}", slot=slot)
            if token:
                slots[slot] = token
        if slots:
            recipe["states"][state] = slots
    for index, transition in enumerate(style.transitions, 1):
        if not _PROPERTY.match(transition.property) or not easing_ok(transition.easing):
            continue
        if not 0 < transition.duration_ms <= 60_000 or not 0 <= transition.delay_ms <= 60_000:
            continue
        at = f"{where} transition {transition.property}"
        duration = m.name(f"{stem}.duration-{index}", "styles", {"kind": "duration", "ms": transition.duration_ms}, pointer=at)
        easing = m.name(f"{stem}.easing-{index}", "styles", {"kind": "easing", "function": transition.easing}, pointer=at)
        delay = (
            m.name(f"{stem}.delay-{index}", "styles", {"kind": "duration", "ms": transition.delay_ms}, pointer=at)
            if transition.delay_ms > 0 else None
        )
        if duration and easing:
            recipe["motion"].append({
                "target": transition.target, "property": transition.property,
                "duration": duration, "easing": easing, "delay": delay,
            })
    icon, value = style.icon, None
    if icon and icon.kind == "glyph" and glyph_ok(icon.glyph):
        value = {"kind": "glyph", "text": icon.glyph}
    elif icon and icon.kind == "svg" and svg_ok(icon.svg) and icon.width and icon.height \
            and 1 <= icon.width <= 256 and 1 <= icon.height <= 256:
        value = {"kind": "svg", "markup": icon.svg, "width": round(icon.width, 2), "height": round(icon.height, 2)}
    if icon and value:
        token = m.name(f"{base}.icon", "styles", value, pointer=f"{where} icon", slot="icon")
        if token:
            recipe["icon"] = {"token": token, "position": icon.position}
    return recipe


def _slug(name: str, used: set[str]) -> str:
    slug = _SLUG.sub("-", name.lower()).strip("-")[:40] or "animation"
    candidate, n = slug, 2
    while candidate in used:
        candidate, n = f"{slug}-{n}", n + 1
    used.add(candidate)
    return candidate


def _iterations_ok(value: str) -> bool:
    if value == "infinite":
        return True
    try:
        return 0 < float(value) <= 1000
    except ValueError:
        return False


def _mint_animation(m: _Minter, animation: MeasuredAnimation, used: set[str], page: str) -> str | None:
    if (
        len(animation.frames) < 2 or not easing_ok(animation.easing) or not _iterations_ok(animation.iterations)
        or animation.direction not in _DIRECTIONS or animation.fill_mode not in _FILL_MODES
        or not 0 < animation.duration_ms <= 60_000 or not 0 <= animation.delay_ms <= 60_000
    ):
        return None
    frames = [
        {"offset": step.offset, "declarations": {k: v for k, v in step.declarations.items() if k in KEYFRAME_PROPERTIES and safe_style_value(v)}}
        for step in animation.frames
    ]
    if any(not frame["declarations"] for frame in frames):
        return None
    slug = _slug(animation.name, used)
    where = f"website:{page} :: animation {animation.name}"
    keyframes = m.name(f"motion.keyframes.{slug}", "styles", {"kind": "keyframes", "frames": frames}, pointer=f"{where} keyframes")
    duration = m.name(f"motion.animation.{slug}.duration", "styles", {"kind": "duration", "ms": animation.duration_ms}, pointer=f"{where} duration")
    easing = m.name(f"motion.animation.{slug}.easing", "styles", {"kind": "easing", "function": animation.easing}, pointer=f"{where} easing")
    delay = (
        m.name(f"motion.animation.{slug}.delay", "styles", {"kind": "duration", "ms": animation.delay_ms}, pointer=f"{where} delay")
        if animation.delay_ms > 0 else None
    )
    if not (keyframes and duration and easing):
        return None
    plural = "s" if animation.count != 1 else ""
    return m.name(
        f"motion.animation.{slug}", "styles",
        {"kind": "animation", "keyframes": keyframes, "duration": duration, "easing": easing, "delay": delay,
         "iterations": animation.iterations, "direction": animation.direction, "fill_mode": animation.fill_mode},
        pointer=where, description=f"{animation.count} element{plural}: {animation.where}",
    )


def _mint_reveal(m: _Minter, reveal: MeasuredReveal, page: str) -> str | None:
    if not easing_ok(reveal.easing) or not 0 < reveal.duration_ms <= 60_000:
        return None
    if reveal.from_transform is not None and not transform_ok(reveal.from_transform):
        return None
    digest = hashlib.sha256(
        json.dumps([reveal.from_opacity, reveal.from_transform, reveal.duration_ms, reveal.easing]).encode()
    ).hexdigest()[:8]
    base = f"motion.reveal.{digest}"
    where = f"website:{page} :: reveal {reveal.where}"
    opacity = (
        m.name(f"{base}.from-opacity", "opacity", _ratio(reveal.from_opacity), pointer=f"{where} from-opacity")
        if reveal.from_opacity is not None and reveal.from_opacity < 1 else None
    )
    transform = (
        m.name(f"{base}.from-transform", "styles", {"kind": "transform", "value": reveal.from_transform}, pointer=f"{where} from-transform")
        if reveal.from_transform else None
    )
    duration = m.name(f"{base}.duration", "styles", {"kind": "duration", "ms": reveal.duration_ms}, pointer=f"{where} duration")
    easing = m.name(f"{base}.easing", "styles", {"kind": "easing", "function": reveal.easing}, pointer=f"{where} easing")
    if not (duration and easing) or not (opacity or transform):
        return None
    plural = "s" if reveal.count != 1 else ""
    return m.name(
        base, "styles",
        {"kind": "reveal", "from_opacity": opacity, "from_transform": transform, "duration": duration, "easing": easing},
        pointer=where, description=f"{reveal.count} element{plural}: {reveal.where}",
    )


@dataclass
class MintResult:
    #: The `measured_components` payload (validated in `lumen_ingestion.measured_components`), or None.
    section: dict | None
    minted: list[str]
    diagnostics: list[dict]


def mint_component_tokens(kit: dict, styles: list[MeasuredStyle], motion: MotionEvidence) -> MintResult:
    """Mint every measured value into `kit["tokens"]` (in place) and return the measured recipes."""
    if not styles and not motion.animations and not motion.reveals and not motion.scripted:
        return MintResult(None, [], [])
    pointers = [s.pointer for s in styles] + [a.pointer for a in motion.animations] + [r.pointer for r in motion.reveals] + [n.pointer for n in motion.scripted]
    page = pointers[0].locator.split(" :: ", 1)[0] if pointers else ""
    fonts = {
        str(font.get("family") or "").lower(): key
        for key, font in ((kit.get("assets") or {}).get("fonts") or {}).items()
        if isinstance(font, dict) and font.get("family")
    }
    minter = _Minter(kit)
    recipes = [_mint_style(minter, style, fonts, page) for style in styles if style.surface in COMPONENT_ROOTS]
    used: set[str] = set()
    animations = [
        name for animation in sorted(motion.animations, key=lambda a: a.name)
        if (name := _mint_animation(minter, animation, used, page))
    ]
    reveal_order = sorted(motion.reveals, key=lambda r: (r.from_opacity is None, r.from_opacity or 0.0, r.from_transform or "", r.duration_ms, r.easing))
    reveals = sorted(name for reveal in reveal_order if (name := _mint_reveal(minter, reveal, page)))
    diagnostics: list[dict] = []
    if minter.dropped:
        diagnostics.append({
            "code": "LUMI0607", "severity": "warning",
            "message": (
                f"{len(minter.dropped)} measured value(s) were not minted as tokens (the kit's cap of "
                f"{MAX_MINTED_TOKENS} tokens, {MAX_MINTED_COLORS} colours): " + ", ".join(minter.dropped[:8])
            ),
        })
    section = {
        "schema_version": 1, "source": f"website:{page}", "styles": recipes,
        "motion": {
            "animations": animations, "reveals": reveals,
            "scripted": [{"kind": note.kind, "where": note.where} for note in motion.scripted],
        },
    }
    return MintResult(section, list(minter.minted), diagnostics)
```

- [ ] **Step 5: Rewrite `normalizer/bands.py`** (whole file):

```python
"""Measured section backgrounds → `surface.band.<hex>` colour tokens (rewritten, Wave 2 A9).

`capture/geometry.py` measures every page band's background into
`BrandEvidence.geometry.background_sequence`, and the text colour on it (`ink`). Every flat, opaque
band colour is a surface the seller's page stands on, so it reaches the kit as a surface token — and
through it, site-kit's extra surfaces and the agent's surfaces table (founder, 2026-10-12).

Rules, each a refusal or an exact match:

* a band whose background is a gradient, an image, or translucent names nothing: its hex is not
  what the page shows (a band painted `rgba(20, 40, 120, 0.04)` reads as barely-tinted white but
  arrives as `#1428780A`);
* a band colour an existing `surface.*` token holds EXACTLY is that token. Surface tokens only: a
  band named after an ink role (`text.inverse`) would teach the wrong vocabulary (the grammar
  audit's rule, `grammar_audit._surface_token`); near misses are minted, never merged (no tolerance);
* the name is the colour (`surface.band.014036`), so a band order that shifts between extractions
  never renames a surface and the same site always yields the same names;
* at most `MAX_BAND_SURFACES`, the most present first: each one adds a row to the agent's surfaces
  table and an option to the marketer's Surface field.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..colorspace import hex_alpha
from ..evidence import SectionBackground

MAX_BAND_SURFACES = 12


@dataclass(frozen=True)
class BandSurface:
    """One minted band token: where it goes, what it is, what measured it, the text on it."""

    path: str
    hex: str
    provenance: str
    description: str
    ink_hex: str | None


def band_path(hex_value: str) -> str:
    return f"surface.band.{hex_value[1:7].lower()}"


def build_band_surfaces(
    sequence: list[SectionBackground], surface_colors: dict[str, str]
) -> tuple[list[BandSurface], int]:
    """The band surfaces this background sequence supports, and how many the cap left out.

    `surface_colors` maps the kit's `surface.*` tokens to their hex.
    """
    usable = [
        band for band in sequence
        if band.background and not band.gradient and not band.has_image and hex_alpha(band.background) >= 1.0
    ]
    taken = {value[:7].upper() for value in surface_colors.values() if value}
    by_hex: dict[str, list[SectionBackground]] = {}
    for band in usable:
        by_hex.setdefault((band.background or "")[:7].upper(), []).append(band)
    ordered = sorted(
        ((hex_value, members) for hex_value, members in by_hex.items() if hex_value not in taken),
        key=lambda item: (-sum(_height(b) for b in item[1]), min(b.index for b in item[1])),
    )
    surfaces: list[BandSurface] = []
    for hex_value, members in ordered[:MAX_BAND_SURFACES]:
        tallest_first = sorted(members, key=lambda b: (-_height(b), b.index))
        representative = tallest_first[0]
        indices = ", ".join(str(i) for i in sorted(b.index for b in members))
        inks = [b.ink for b in tallest_first if b.ink and hex_alpha(b.ink) >= 1.0]
        count = len(members)
        surfaces.append(BandSurface(
            path=band_path(hex_value),
            hex=hex_value,
            provenance=f"{representative.pointer.source}:{_page(representative)} :: section background (sections {indices})",
            description=f"section background ({count} {'band' if count == 1 else 'bands'}, {int(sum(_height(b) for b in members))}px)",
            ink_hex=inks[0][:7].upper() if inks else None,
        ))
    return surfaces, max(0, len(ordered) - MAX_BAND_SURFACES)


def _height(band: SectionBackground) -> float:
    return max(0.0, band.height_px)


def _page(band: SectionBackground) -> str:
    """The page URL out of the band's `<url> :: section N (tag)` locator."""
    return band.pointer.locator.split(" :: ", 1)[0]
```

- [ ] **Step 6: Wire both into `normalize_evidence`.** In `normalizer/__init__.py`:
  1. Imports: `from .bands import build_band_surfaces` stays; add
     `from .component_tokens import mint_component_tokens`.
  2. `NormalizeResult` gains `measured_components: dict | None = None` (last field, with a default).
  3. Replace the band block (`# Measured band surfaces. …` through the end of its `for` loop) with:

```python
    # Measured section backgrounds (Wave 2 A9): every flat band colour no surface token holds
    # exactly becomes `surface.band.<hex>`, with the text measured on it as its contrast pair.
    # Geometry-gated: evidence without a measured band sequence mints nothing.
    surface_colors = {
        path: str(entry["value"]["default"].get("value") or "")
        for path, entry in builder.colors.items()
        if path.startswith("surface.") and entry["value"]["default"].get("kind") == "hex"
    }
    bands, skipped_bands = build_band_surfaces(evidence.geometry.background_sequence, surface_colors)
    band_pairs: list[dict] = []
    for band in bands:
        builder.add_color(
            band.path,
            RoleAssignment(band.hex, "measured", band.provenance),
            None,
            confidence=MEASURED_CONFIDENCE,
            description=band.description,
        )
        if band.ink_hex:
            band_pairs.append({"foreground": _band_ink(builder, band), "background": band.path, "min_ratio": 4.5})
    if skipped_bands:
        diagnostics.append({
            "code": "LUMI0607", "severity": "warning",
            "message": f"{skipped_bands} more section background colour(s) were not minted (the cap of 12 band surfaces)",
        })
```
  4. After `constraints = build_constraints(evidence, tone_override, cta_color=cta_color)` add
     `constraints["contrast_pairs"].extend(band_pairs)`.
  5. After `if description: brand_kit["description"] = description` add:

```python
    # Measured component styles and motion (Wave 2 A9): minted after every other token exists, so
    # exact-match reuse sees the whole kit, band surfaces included.
    mint = mint_component_tokens(brand_kit, evidence.geometry.styles, evidence.geometry.motion)
    diagnostics.extend(mint.diagnostics)
```
     and pass `measured_components=mint.section` to the returned `NormalizeResult(...)`.
  6. Add the helper below `_brand_text`:

```python
def _band_ink(builder: KitBuilder, band) -> str:
    """The colour token for the text measured on a band: an exact match (an ink first), else
    `text.band.<hex of the band>`."""
    matches = sorted(
        (
            path for path, entry in builder.colors.items()
            if entry["value"]["default"].get("kind") == "hex"
            and str(entry["value"]["default"].get("value") or "")[:7].upper() == band.ink_hex
        ),
        key=lambda path: (not path.startswith("text."), path),
    )
    if matches:
        return matches[0]
    path = "text.band." + band.path.rsplit(".", 1)[1]
    builder.add_color(
        path,
        RoleAssignment(band.ink_hex, "measured", band.provenance.replace("section background", "text on section background")),
        None,
        confidence=MEASURED_CONFIDENCE,
        description="text measured on that section background",
    )
    return path
```
  7. In `brief_agent.py`, `spacing_ladder=[row for row in tokens if row["group"] == "spacing"],`
     becomes
     `spacing_ladder=[row for row in tokens if row["group"] == "spacing" and not is_component_token(row["name"])],`
     with `from .normalizer.component_tokens import is_component_token` and the comment
     `# The ladder is the kit's scale; minted component paddings are not rungs of it.`

- [ ] **Step 7: Bring the band tests to the new rules.** In `test_ingestion_geometry.py`, replace
  the block from `# Emission: recurring band surfaces (surface.band.*)` through
  `test_a_kit_carrying_band_surfaces_still_validates_through_the_engine` with:

```python
# --------------------------------------------------------------------------- #
# Emission: section background surfaces (surface.band.<hex>), Wave 2 A9
# --------------------------------------------------------------------------- #


def _bands(kit: dict) -> dict[str, dict]:
    return {path: entry for path, entry in kit["tokens"]["colors"].items() if path.startswith("surface.band")}


def _band_values(kit: dict) -> dict[str, str]:
    return {path: entry["value"]["default"]["value"] for path, entry in _bands(kit).items()}


def test_every_flat_band_colour_no_surface_token_holds_exactly_is_minted_by_its_value() -> None:
    """Stripe: white (only `text.inverse` holds #FFFFFF, an ink), navy, and the 380px footer tint."""
    kit = _normalize(_with_geometry("evidence_website_insight", _harvest("stripe_home")))
    assert _band_values(kit) == {
        "surface.band.ffffff": "#FFFFFF", "surface.band.0d1738": "#0D1738", "surface.band.f8fafd": "#F8FAFD",
    }
    navy = kit["tokens"]["colors"]["surface.band.0d1738"]
    assert navy["role"] == "surface" and navy["value"]["modes"] == {}
    assert navy["provenance"]["source"].startswith("website:https://stripe.com")
    assert "section background (sections 3, 5)" in navy["provenance"]["source"]
    assert navy["provenance"]["confidence"] == MEASURED_CONFIDENCE
    assert navy["description"] == "section background (2 bands, 3318px)"
    assert kit["tokens"]["colors"]["surface.band.f8fafd"]["description"] == "section background (1 band, 380px)"


def test_a_band_an_existing_surface_token_holds_exactly_mints_nothing() -> None:
    kit = _normalize(_synthetic([_section(0, "rgb(245, 245, 245)", 900), _section(1, "rgb(20, 40, 120)", 900)]))
    assert set(_bands(kit)) == {"surface.band.142878"}, "#F5F5F5 is this kit's surface.page exactly"


def test_near_misses_are_minted_never_merged() -> None:
    """flat_brand's #111111 is within merge distance of surface.inverse #121212 — and not equal."""
    kit = _normalize(_with_geometry("evidence_website_insight", _harvest("flat_brand")))
    assert set(_bands(kit)) == {"surface.band.ffffff", "surface.band.111111"}


def test_band_names_do_not_move_when_the_band_order_does() -> None:
    forward = _normalize(_synthetic([
        _section(0, "rgb(255, 255, 255)", 900), _section(1, "rgb(1, 64, 54)", 700), _section(2, "rgb(255, 233, 196)", 600),
    ]))
    backward = _normalize(_synthetic([
        _section(0, "rgb(255, 233, 196)", 600), _section(1, "rgb(1, 64, 54)", 700), _section(2, "rgb(255, 255, 255)", 900),
    ]))
    assert set(_bands(forward)) == set(_bands(backward)) == {
        "surface.band.ffffff", "surface.band.014036", "surface.band.ffe9c4",
    }


def test_gradient_image_and_translucent_bands_name_nothing() -> None:
    kit = _normalize(_synthetic([
        _section(0, "rgb(255, 255, 255)", 900),
        _section(1, "rgb(200, 10, 10)", 900, gradient=True),
        _section(2, "rgb(200, 10, 10)", 900, image=True),
        _section(3, "rgba(20, 40, 120, 0.04)", 900),
    ]))
    assert set(_bands(kit)) == {"surface.band.ffffff"}
    flat = _normalize(_synthetic([_section(0, "rgb(200, 10, 10)", 900)]))
    assert _band_values(flat) == {"surface.band.c80a0a": "#C80A0A"}


def test_a_band_with_measured_text_gets_it_as_its_contrast_pair() -> None:
    kit = _normalize(_synthetic([
        _section(0, "rgb(255, 255, 255)", 900),
        {**_section(1, "rgb(1, 64, 54)", 700), "ink": "rgb(255, 255, 255)"},
        {**_section(2, "rgb(40, 36, 30)", 600), "ink": "rgb(250, 245, 230)"},
    ]))
    pairs = kit["constraints"]["contrast_pairs"]
    assert {"foreground": "text.inverse", "background": "surface.band.014036", "min_ratio": 4.5} in pairs
    assert {"foreground": "text.band.28241e", "background": "surface.band.28241e", "min_ratio": 4.5} in pairs
    assert kit["tokens"]["colors"]["text.band.28241e"]["value"]["default"]["value"] == "#FAF5E6"


def test_band_minting_is_deterministic() -> None:
    evidence = _with_geometry("evidence_website_insight", _harvest("stripe_home"))
    assert json.dumps(_normalize(evidence), sort_keys=True) == json.dumps(_normalize(evidence), sort_keys=True)


def test_a_kit_carrying_band_surfaces_still_validates_through_the_engine() -> None:
    kit = _normalize(_with_geometry("evidence_website_insight", _harvest("stripe_home")))
    assert "surface.band.0d1738" in kit["tokens"]["colors"]
    validated = CoreClient().validate_brand_kit(kit, product_ready=False)
    assert validated["ok"] is True
    assert [d for d in validated.get("diagnostics", []) if d.get("severity") == "error"] == []
```
  In `test_ingestion_brief.py`, change the `_kit_with_bands` docstring's `surface.band.statement` to
  `surface.band.0d1738` and every `"surface.band.statement"` in
  `test_a_band_the_kit_minted_is_a_name_the_brief_may_speak` to `"surface.band.0d1738"`. In
  `test_ingestion_grammar_audit.py:426` change `"surface.band.statement"` to `"surface.band.0d1738"`.

- [ ] **Step 8: Run the tests.**

Run: `CAPTURE_PYTEST test_ingestion_component_tokens.py test_ingestion_geometry.py test_ingestion_brief.py test_ingestion_grammar_audit.py test_ingestion_measured_styles.py`
Expected: PASS. If a grammar-audit test now also reports the white band as
`` (`surface.band.ffffff`) ``, that is the new exact surface for `#FFFFFF`; assert it there too.
Then run every other ingestion file once (`ls subsystems/clue-design/apps/api/tests/test_ingestion_*.py`,
each through `CAPTURE_PYTEST`, or `DESIGN_PYTEST` with the stack down where it needs the database):
any website evidence with a geometry harvest now mints component tokens even when it was captured
before the state pass (its rest values are measurements). A failure that compares a WHOLE token group
of such a kit is that new vocabulary: compare the group without `is_component_token` names and name
each such change in the commit message. Any other failure is analysed, never weakened.

- [ ] **Step 9: Commit.**

```bash
git add subsystems/clue-design/apps/api/lumen_ingestion/normalizer/component_tokens.py subsystems/clue-design/apps/api/lumen_ingestion/normalizer/bands.py \
  subsystems/clue-design/apps/api/lumen_ingestion/normalizer/__init__.py subsystems/clue-design/apps/api/lumen_ingestion/brief_agent.py \
  subsystems/clue-design/apps/api/lumen_ingestion/brief_agent_prompt.md subsystems/clue-design/apps/api/tests/test_ingestion_component_tokens.py \
  subsystems/clue-design/apps/api/tests/test_ingestion_geometry.py subsystems/clue-design/apps/api/tests/test_ingestion_brief.py \
  subsystems/clue-design/apps/api/tests/test_ingestion_grammar_audit.py
git commit -m "ingestion: mint every measured style value and section background as a token of the kit (exact-match reuse, stable names, a per-kit cap)"
```

### Task X5: The `measured_components` kit section, its place in the pipeline, kit sections kept across curation, and site-kit's test kits

**Files:**
- Create: `subsystems/clue-design/apps/api/lumen_ingestion/measured_components.py`
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/brief.py` (`_TOKEN_GROUPS`)
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/pipeline.py` (after the grammar audit, `:1095-1110`)
- Create: `subsystems/clue-design/apps/api/lumen_api/brand_kit_sections.py`
- Modify: `subsystems/clue-design/apps/api/lumen_api/main.py` (`set_brand_kit_logo` `:2349-2370`,
  `describe_brand_kit_assets` `:2446-2462`)
- Create: `subsystems/clue-design/scripts/build_site_kit_brand_fixtures.py` and the six files it
  writes under `apps/frontend/packages/site-kit/test/fixtures/kits/`
- Create: `subsystems/clue-design/apps/api/tests/test_measured_components.py`
- Modify: `subsystems/clue-design/apps/api/tests/test_api.py` (one route test, DB suite)

**Interfaces:**
- Produces: `MeasuredComponents@1` at `brand_kit_json.measured_components` =
  `{schema_version: 1, source, styles: [{component, variant, count, probed, source, rest: {slot: token},
  states: {state: {slot: token}}, motion: [{target, property, duration, easing, delay}], icon: {token,
  position} | null, browser_focus_ring}], motion: {animations: [token], reveals: [token], scripted:
  [{kind, where}]}}`; `validate_measured_components(payload, *, token_names) -> dict`,
  `MeasuredComponentsRefused`, `MEASURED_COMPONENTS_SCHEMA_VERSION`; `pipeline._attach_measured_components`;
  `brand_kit_sections.carry_kit_sections(stored, validated) -> dict`,
  `KIT_SECTIONS_OUTSIDE_ENGINE = ("brief", "grammar_audit", "measured_components")`; diagnostic `LUMI0608`.
- The brief's schema is untouched (`BrandBrief@1`, `schema_version` 1): the measured recipe lives
  beside the brief's recipe, joined by `(component, variant)`. A version bump was ruled out: both
  strict readers of the brief — the web/ad card (`lumen_agent/brand_brief.py:183`) and the
  brand-context page (`brand-brief.ts:36`, `z.literal(1)`) — drop any brief whose version they do
  not know, so every new kit would lose its brief in two lanes.

- [ ] **Step 1: Write the failing tests** `apps/api/tests/test_measured_components.py`:

```python
"""MeasuredComponents@1 (Wave 2 A9, Task X5): the measured recipes, their place on the kit, and the
kit sections kept across every re-validation."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from lumen_api.brand_kit_sections import KIT_SECTIONS_OUTSIDE_ENGINE, carry_kit_sections
from lumen_ingestion.brief import kit_token_names
from lumen_ingestion.capture.geometry import parse_geometry
from lumen_ingestion.capture.motion import attach_keyframes
from lumen_ingestion.capture.snapshot import Stylesheet
from lumen_ingestion.measured_components import MeasuredComponentsRefused, validate_measured_components
from lumen_ingestion.normalizer.component_tokens import mint_component_tokens
from lumen_ingestion.pipeline import _attach_measured_components

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parents[2]
HARVEST = json.loads((TESTS / "fixtures" / "capture" / "style_states.harvest.json").read_text())
CSS = (TESTS / "fixtures" / "capture" / "style_states.html").read_text().split("<style>", 1)[1].split("</style>", 1)[0]
GARNER = TESTS.parents[4] / "trials" / "puck-spike" / "data" / "brands" / "garner" / "kit.json"


def _minted() -> tuple[dict, dict]:
    kit = {k: v for k, v in json.loads(GARNER.read_text()).items() if k not in ("brief", "grammar_audit")}
    parsed = parse_geometry(HARVEST, page_url="https://fixture.test/")
    motion = attach_keyframes(parsed.motion, [Stylesheet(url="https://fixture.test/", text=CSS)])
    return kit, mint_component_tokens(kit, parsed.styles, motion).section


def test_the_minted_section_validates_and_every_name_resolves_in_the_kit() -> None:
    kit, section = _minted()
    assert "button.solid-1.case" in kit_token_names(kit), "style tokens are names the token law knows"
    checked = validate_measured_components(section, token_names=kit_token_names(kit))
    assert checked["schema_version"] == 1 and checked["source"] == "website:https://fixture.test/"
    assert {s["component"] for s in checked["styles"]} >= {"button", "link", "nav_link", "card"}
    assert checked["motion"]["animations"] == ["motion.animation.pulse"]


def test_a_name_the_kit_does_not_carry_refuses_the_whole_section() -> None:
    kit, section = _minted()
    section["styles"][0]["rest"]["fill"] = "button.ghost-9.fill"
    with pytest.raises(MeasuredComponentsRefused, match="button.ghost-9.fill"):
        validate_measured_components(section, token_names=kit_token_names(kit))


def test_a_slot_outside_the_vocabulary_is_refused() -> None:
    kit, section = _minted()
    section["styles"][0]["rest"]["background"] = "surface.brand"
    with pytest.raises(MeasuredComponentsRefused):
        validate_measured_components(section, token_names=kit_token_names(kit))


def test_the_pipeline_attaches_the_section_or_says_why_not() -> None:
    kit, section = _minted()
    diagnostics: list[dict] = []
    attached = _attach_measured_components(kit, section, diagnostics)
    assert attached["measured_components"]["styles"] and diagnostics == []
    broken = json.loads(json.dumps(section))
    broken["styles"][0]["rest"]["fill"] = "nope.fill"
    kept = _attach_measured_components(kit, broken, diagnostics)
    assert "measured_components" not in kept
    assert [d["code"] for d in diagnostics] == ["LUMI0608"]
    assert _attach_measured_components(kit, None, []) is kit


def test_kit_sections_outside_the_engine_are_carried_onto_the_validated_kit() -> None:
    stored = {"id": "k", "tokens": {}, "brief": {"schema_version": 1}, "grammar_audit": {"schema_version": 1},
              "measured_components": {"schema_version": 1}, "other": 1}
    validated = {"id": "k", "tokens": {"colors": {}}}
    carried = carry_kit_sections(stored, validated)
    assert carried == {"id": "k", "tokens": {"colors": {}}, "brief": {"schema_version": 1},
                       "grammar_audit": {"schema_version": 1}, "measured_components": {"schema_version": 1}}
    assert KIT_SECTIONS_OUTSIDE_ENGINE == ("brief", "grammar_audit", "measured_components")
    assert validated == {"id": "k", "tokens": {"colors": {}}}, "the engine's result is not mutated"


def test_site_kit_fixture_kits_are_current() -> None:
    spec = importlib.util.spec_from_file_location("fixtures", ROOT / "scripts" / "build_site_kit_brand_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name, text in module.build_all().items():
        committed = (module.KITS_DIR / name).read_text()
        assert committed == text, f"{name} is stale: run scripts/build_site_kit_brand_fixtures.py"
```

- [ ] **Step 2: Run them to see them fail.**

Run: `CAPTURE_PYTEST test_measured_components.py`
Expected: FAIL at import — no module `lumen_api.brand_kit_sections`.

- [ ] **Step 3: Write `lumen_ingestion/measured_components.py`.**

```python
"""`MeasuredComponents@1` — every measured style of the brand's site, in this kit's token names.

A code-owned kit section (`brand_kit_json.measured_components`, Wave 2 A9), the sibling of the
model-written `BrandBrief@1` and the arithmetic `BrandGrammarAudit@1`: it rides the kit the same way
(attached after the engine round trip, carried across every re-validation by
`lumen_api.brand_kit_sections`) and overlaps neither. The brief's `component_recipes` hold what the
model judged — which styles are page buttons, notes, confidence. This holds what the capture
MEASURED, as a complete recipe per `(component, variant)`: every slot of the rest look and of each
state names a token of this kit, and so does every transition's timing and the icon. site-kit joins
the two by `(component, variant)`.

No model writes it, so nothing here is judgement: the shapes below and the token law (every name
resolves in this kit) are checked, and a section that fails either is dropped with a diagnostic
(LUMI0608), never published half-true.
"""

from __future__ import annotations

from typing import Annotated, Any, Iterator, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from .brief import TOKEN_NAME_PATTERN

MEASURED_COMPONENTS_SCHEMA_VERSION = 1

TokenRef = Annotated[str, StringConstraints(pattern=TOKEN_NAME_PATTERN, max_length=160)]
Text = Annotated[str, StringConstraints(min_length=1, max_length=400)]
#: The slot vocabulary `normalizer/component_tokens.py` writes; site-kit's `looks.ts` reads the same.
SLOT_PATTERN = (
    r"^(fill|label|border|border-width(-(top|right|bottom|left))?|border-style|radius(-(tl|tr|br|bl))?"
    r"|padding-(top|right|bottom|left)|height|gap|font|case|decoration|decoration-thickness|underline-offset"
    r"|shadow(-\d+)?|opacity|transform|filter|cursor|outline|outline-width|outline-style|outline-offset"
    r"|icon-color|icon-transform|icon-opacity)$"
)
Slot = Annotated[str, StringConstraints(pattern=SLOT_PATTERN)]
State = Literal["hover", "pressed", "focus", "disabled"]


class MeasuredComponentsRefused(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MeasuredTransition(_Section):
    target: Literal["self", "label", "icon"]
    property: Annotated[str, StringConstraints(pattern=r"^(all|[a-z-]{1,60})$")]
    duration: TokenRef
    easing: TokenRef
    delay: TokenRef | None = None


class MeasuredIcon(_Section):
    token: TokenRef
    position: Literal["start", "end"]


class MeasuredRecipe(_Section):
    component: Literal["button", "link", "nav_link", "card", "chip", "input", "image"]
    variant: Annotated[str, StringConstraints(pattern=r"^(solid|outline|ghost)\.\d+$")]
    count: int = Field(ge=1)
    probed: Literal["pointer", "forced", "rest-only"]
    source: Text
    rest: dict[Slot, TokenRef] = {}
    states: dict[State, dict[Slot, TokenRef]] = {}
    motion: list[MeasuredTransition] = Field(default_factory=list, max_length=24)
    icon: MeasuredIcon | None = None
    browser_focus_ring: bool = False


class ScriptedNote(_Section):
    kind: Literal["scripted", "canvas", "video"]
    where: Text


class MeasuredMotion(_Section):
    animations: list[TokenRef] = Field(default_factory=list, max_length=12)
    reveals: list[TokenRef] = Field(default_factory=list, max_length=6)
    scripted: list[ScriptedNote] = Field(default_factory=list, max_length=12)


class MeasuredComponents(_Section):
    schema_version: Literal[1] = MEASURED_COMPONENTS_SCHEMA_VERSION
    source: Text
    styles: list[MeasuredRecipe] = Field(default_factory=list, max_length=40)
    motion: MeasuredMotion = MeasuredMotion()


def token_references(section: MeasuredComponents) -> Iterator[tuple[str, str]]:
    for index, style in enumerate(section.styles):
        where = f"styles[{index}]({style.component} {style.variant})"
        for slot, token in style.rest.items():
            yield f"{where}.rest.{slot}", token
        for state, slots in style.states.items():
            for slot, token in slots.items():
                yield f"{where}.{state}.{slot}", token
        for step, transition in enumerate(style.motion):
            for key in ("duration", "easing", "delay"):
                token = getattr(transition, key)
                if token:
                    yield f"{where}.motion[{step}].{key}", token
        if style.icon:
            yield f"{where}.icon", style.icon.token
    for index, token in enumerate(section.motion.animations):
        yield f"motion.animations[{index}]", token
    for index, token in enumerate(section.motion.reveals):
        yield f"motion.reveals[{index}]", token


def validate_measured_components(payload: Any, *, token_names: set[str]) -> dict:
    """The section as stored, or `MeasuredComponentsRefused` naming what is wrong."""
    try:
        section = MeasuredComponents.model_validate(payload)
    except ValidationError as error:
        first = error.errors()[0]
        raise MeasuredComponentsRefused(
            f"MeasuredComponents@1 validation failed at {'.'.join(str(p) for p in first['loc'])}: {first['msg']}"
        ) from error
    unresolved = sorted(f"{where}={token}" for where, token in token_references(section) if token not in token_names)
    if unresolved:
        raise MeasuredComponentsRefused("names tokens this kit does not carry: " + ", ".join(unresolved[:8]))
    return section.model_dump(mode="json")
```

- [ ] **Step 4: The token law knows style tokens; the pipeline attaches the section.**
  1. In `brief.py`, add `"styles",` to `_TOKEN_GROUPS` after `"aliases",`.
  2. In `pipeline.py`, add the imports
     `from .brief import kit_token_names` and
     `from .measured_components import MeasuredComponentsRefused, validate_measured_components`, add
     after `_maybe_extract_grammar_audit`:

```python
def _attach_measured_components(
    validated_kit: JsonObject, measured: "JsonObject | None", diagnostics: list
) -> JsonObject:
    """The kit with its `MeasuredComponents@1`, or the kit as it was with a diagnostic.

    It rides the validated kit for the brief's reason (the engine's BrandKit has no field for it);
    the tokens it names were minted into `tokens` before the engine round trip, so they are there.
    """
    if measured is None:
        return validated_kit
    try:
        section = validate_measured_components(measured, token_names=kit_token_names(validated_kit))
    except MeasuredComponentsRefused as refusal:
        diagnostics.append({
            "code": "LUMI0608", "severity": "warning",
            "message": f"measured component styles were not kept on the kit: {refusal.reason}",
        })
        return validated_kit
    return {**validated_kit, "measured_components": section}
```
     and in the website ingestion, right after the grammar audit's
     `validated_kit = {**validated_kit, "grammar_audit": audit}` block:

```python
    measured_diagnostics: list = []
    validated_kit = _attach_measured_components(
        validated_kit, result.measured_components, measured_diagnostics
    )
```
     then add `+ measured_diagnostics` after `+ audit_diagnostics` in the `diagnostics = (...)` sum.

- [ ] **Step 5: Keep the kit's own sections across curation.** Create
  `lumen_api/brand_kit_sections.py`:

```python
"""Kit sections the engine does not know survive every re-validation (Wave 2 A9).

`validate_brand_kit` re-serializes a kit through the typed Rust `BrandKit`, which has no field for
the brief, the grammar audit or the measured components, so they never come back. Ingestion attaches
them after the round trip (`lumen_ingestion/pipeline.py`); every route that re-validates a STORED kit
and publishes the result must carry them across the same way, or a logo choice silently deletes the
kit's brief. Verified 2026-10-12 by running the helper over Garner's kit.
"""

from __future__ import annotations

from typing import Any, Mapping

KIT_SECTIONS_OUTSIDE_ENGINE = ("brief", "grammar_audit", "measured_components")


def carry_kit_sections(stored: Mapping[str, Any], validated: Mapping[str, Any]) -> dict:
    """`validated` (the engine's kit) with the stored kit's own sections put back."""
    carried = dict(validated)
    for key in KIT_SECTIONS_OUTSIDE_ENGINE:
        if key in stored and key not in carried:
            carried[key] = stored[key]
    return carried
```
  In `main.py` add `from .brand_kit_sections import carry_kit_sections`, and in BOTH
  `set_brand_kit_logo` and `describe_brand_kit_assets` replace

```python
            validation = app.state.core.validate_brand_kit(
                brand_kit, product_ready=False
            )
            brand_kit = validation["brand_kit"]
            summary_response = app.state.core.summarize_brand_kit(
                brand_kit, raise_on_error=False
            )
```
  with

```python
            validation = app.state.core.validate_brand_kit(
                brand_kit, product_ready=False
            )
            summary_response = app.state.core.summarize_brand_kit(
                validation["brand_kit"], raise_on_error=False
            )
            # The engine returns only what its BrandKit knows; the kit's brief, grammar audit and
            # measured components ride on (Wave 2 A9 — every curated kit lost them before).
            brand_kit = carry_kit_sections(brand_kit, validation["brand_kit"])
```
  Then add to `test_api.py`, after `test_describe_assets_backfill_republishes_kit_with_metadata`:

```python
def test_logo_curation_keeps_the_kit_sections_the_engine_does_not_know(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wave 2 A9 (Task X5): the logo route publishes the engine's validated kit, which dropped the
    brief, the grammar audit and the measured components; they are carried across now."""
    compiled = client.post(
        "/brand-kits/compile-styles",
        json={"source": valid_styles_source(), "brand_kit_id": "brand_kit_insight_health", "version": 4, "name": "Insight Health"},
    )
    assert compiled.status_code == 200, compiled.text
    sections = {
        "brief": {"schema_version": 1, "characterization": {"words": ["calm", "clinical"], "support": "s", "confidence": "low"}},
        "grammar_audit": {"schema_version": 1},
        "measured_components": {"schema_version": 1, "source": "website:https://example.test/", "styles": [],
                                "motion": {"animations": [], "reveals": [], "scripted": []}},
    }
    original = HybridRepository.require_brand_kit

    def stored_with_sections(self, brand_kit_id, version=None):
        record = original(self, brand_kit_id, version)
        return {**record, "brand_kit": {**record["brand_kit"], **sections}} if version is None else record

    monkeypatch.setattr(HybridRepository, "require_brand_kit", stored_with_sections)
    uploaded = upload_logo(client, label="The real lockup")
    chosen = client.post(
        "/brand-kits/brand_kit_insight_health/logo",
        json={"asset_id": uploaded.json()["asset"]["id"], "slot": "primary"},
    )
    assert chosen.status_code == 200, chosen.text
    monkeypatch.setattr(HybridRepository, "require_brand_kit", original)
    kit_json = client.get("/brand-kits/brand_kit_insight_health").json()["brand_kit_json"]
    for key, value in sections.items():
        assert kit_json[key] == value, key
```

- [ ] **Step 6: Write site-kit's test kits from real values.** Create
  `scripts/build_site_kit_brand_fixtures.py`:

```python
"""Write site-kit's test kits from real values (Wave 2 A9, Task X5).

Run from subsystems/clue-design (offline: no browser, no model, no database):
  PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python scripts/build_site_kit_brand_fixtures.py
It writes apps/frontend/packages/site-kit/test/fixtures/kits/<name>.json, and
test_measured_components.test_site_kit_fixture_kits_are_current fails when a committed file differs.

* garner / conduit / altcarbon — the spike's copies of the three real kits, unchanged: kits made
  before measurement (no minted tokens, no measured_components). site-kit's fallback tests run on them.
* garner.minted / conduit.minted — the same kits with the tokens the REAL minting code makes from
  values already measured on those sites: each hero button as the spike measured it at 1440
  (trials/puck-spike/data/brands/<brand>/measured.json; rest only, states were never captured
  there) and the section backgrounds of each kit's stored ingestion evidence
  (design_ingestion_job.evidence_json, ingest_9808f81d655c44e4b037284b4e01b2b9 for Garner and
  ingest_3e85c884c7c5457285874e8c1d6f016b for Conduit, read 2026-10-12).
* probe.minted — Garner's kit with every style, state, transition, icon, animation, reveal and band
  the real probe measured on apps/api/tests/fixtures/capture/style_states.html (its committed
  harvest), and brief recipes naming those button and card variants — written here, not by a model;
  the kit's name says it is a fixture.
"""

from __future__ import annotations

import json
from pathlib import Path

from lumen_ingestion.brief import kit_token_names
from lumen_ingestion.capture.geometry import parse_geometry
from lumen_ingestion.capture.motion import attach_keyframes
from lumen_ingestion.capture.snapshot import Stylesheet
from lumen_ingestion.evidence import EvidencePointer, MeasuredStyle, MotionEvidence, SectionBackground, StyleLook
from lumen_ingestion.measured_components import validate_measured_components
from lumen_ingestion.normalizer.bands import build_band_surfaces
from lumen_ingestion.normalizer.component_tokens import mint_component_tokens
from lumen_ingestion.normalizer.emit import _color_value, _mode_value, _provenance
from lumen_ingestion.normalizer.geometry import MEASURED_CONFIDENCE

DESIGN = Path(__file__).resolve().parents[1]
REPO = DESIGN.parents[1]
BRANDS = REPO / "trials" / "puck-spike" / "data" / "brands"
KITS_DIR = REPO / "apps" / "frontend" / "packages" / "site-kit" / "test" / "fixtures" / "kits"
CAPTURE = DESIGN / "apps" / "api" / "tests" / "fixtures" / "capture"

#: (index, background, height px) per band, from each kit's stored ingestion evidence.
BANDS = {
    "garner": ("https://garnerhealth.com/", [
        (0, "#FFFFFF", 1048), (1, "#F9FAF8", 645), (2, "#FFFFFF", 1127), (3, "#FFFFFF", 2009), (4, "#014036", 733),
        (5, "#FFFFFF", 224), (6, "#FFFFFF", 776), (7, "#FFFFFF", 675), (8, "#FFFFFF", 522),
    ]),
    "conduit": ("https://www.conduit.ai/", [
        (0, "#FFFFFF", 419), (1, "#FFFFFF", 580), (2, "#FFFFFF", 223), (3, "#FFFFFF", 821), (4, "#FFFFFF", 1167),
        (5, "#28241E", 887), (6, "#FFFFFF", 741), (7, "#FFFFFF", 584), (8, "#FFFFFF", 440),
    ]),
}

#: Each hero button as measured.json records it, against the brief recipe it is (Garner solid.1:
#: "light pills on photo and forest grounds"; Conduit solid.2: "Primary demo CTA").
HERO_BUTTONS = {
    "garner": ("solid.1", 2, StyleLook(
        background="#FFFFFF", color="#0D2B25", border_color="#FFFFFF", border_width=[1, 1, 1, 1], border_style="solid",
        radius=[999.01, 999.01, 999.01, 999.01], pill=True, padding=[8, 24, 8, 24], height=42,
        font_family="Open Sans", font_size=14, font_weight=500, letter_spacing=0,
    )),
    "conduit": ("solid.2", 4, StyleLook(
        background="#28241E", color="#FFFFFF", border_width=[1, 1, 1, 1], border_style="solid",
        radius=[8, 8, 8, 8], pill=False, padding=[0, 10, 0, 10], height=32,
        font_family="bodyFont", font_size=16, font_weight=500, letter_spacing=0,
    )),
}


def _kit(brand: str) -> dict:
    return json.loads((BRANDS / brand / "kit.json").read_text())


def _add_bands(kit: dict, sequence: list[SectionBackground]) -> None:
    """The band surfaces and pairs `normalize_evidence` would add, applied to an existing kit."""
    colors = kit["tokens"]["colors"]
    surface_colors = {p: str(e["value"]["default"].get("value") or "") for p, e in colors.items()
                      if p.startswith("surface.") and e["value"]["default"].get("kind") == "hex"}
    bands, _ = build_band_surfaces(sequence, surface_colors)
    for band in bands:
        colors[band.path] = {"value": _mode_value(_color_value(band.hex), {}), "role": "surface",
                             "description": band.description, "provenance": _provenance(band.provenance, MEASURED_CONFIDENCE)}
        if band.ink_hex:
            ink = next((p for p, e in sorted(colors.items(), key=lambda item: (not item[0].startswith("text."), item[0]))
                        if str(e["value"]["default"].get("value") or "")[:7].upper() == band.ink_hex), None)
            if ink:
                kit["constraints"]["contrast_pairs"].append({"foreground": ink, "background": band.path, "min_ratio": 4.5})


def _finish(kit: dict, section: dict | None) -> dict:
    if section is not None:
        kit["measured_components"] = validate_measured_components(section, token_names=kit_token_names(kit))
    return kit


def _measured_real(brand: str) -> dict:
    kit = _kit(brand)
    url, rows = BANDS[brand]
    _add_bands(kit, [
        SectionBackground(index=i, background=hex_value, height_px=height,
                          pointer=EvidencePointer(source="website", locator=f"{url} :: section {i} (section)"))
        for i, hex_value, height in rows
    ])
    variant, count, look = HERO_BUTTONS[brand]
    style = MeasuredStyle(surface="button", variant=variant, count=count, probed="rest-only", rest=look,
                          pointer=EvidencePointer(source="website", locator=f"{url} :: button {variant}"))
    return _finish(kit, mint_component_tokens(kit, [style], MotionEvidence()).section)


def _probe() -> dict:
    kit = _kit("garner")
    kit["name"] = "Probe fixture (style_states.html)"
    harvest = json.loads((CAPTURE / "style_states.harvest.json").read_text())
    parsed = parse_geometry(harvest, page_url="https://fixture.test/")
    css = (CAPTURE / "style_states.html").read_text().split("<style>", 1)[1].split("</style>", 1)[0]
    motion = attach_keyframes(parsed.motion, [Stylesheet(url="https://fixture.test/", text=css)])
    _add_bands(kit, parsed.background_sequence)
    result = mint_component_tokens(kit, parsed.styles, motion)
    kit["brief"]["component_recipes"] = [
        {"component": s["component"], "variant": s["variant"], "radius": None, "padding": None, "border": None,
         "shadow": None, "background": None, "text": None, "unmapped": ["Probe fixture style."], "confidence": "high"}
        for s in result.section["styles"] if s["component"] in ("button", "card")
    ]
    return _finish(kit, result.section)


def build_all() -> dict[str, str]:
    kits = {
        "garner.json": _kit("garner"), "conduit.json": _kit("conduit"), "altcarbon.json": _kit("altcarbon"),
        "garner.minted.json": _measured_real("garner"), "conduit.minted.json": _measured_real("conduit"),
        "probe.minted.json": _probe(),
    }
    return {name: json.dumps(kit, indent=1, sort_keys=True, ensure_ascii=False) + "\n" for name, kit in kits.items()}


if __name__ == "__main__":
    KITS_DIR.mkdir(parents=True, exist_ok=True)
    for name, text in build_all().items():
        (KITS_DIR / name).write_text(text)
        print(f"wrote {KITS_DIR / name}")
```
  Run it (command in its docstring), then `jq '.measured_components.styles[0].rest' apps/frontend/packages/site-kit/test/fixtures/kits/conduit.minted.json`.
  Expected: `"fill": "surface.band.28241e"` (the procedures band and the demo button are the same
  warm dark, so the button names the band's token), `"label": "text.inverse"`, `"radius": "radius.button"`.

- [ ] **Step 7: Run the tests.**

Run: `CAPTURE_PYTEST test_measured_components.py test_ingestion_component_tokens.py test_ingestion_brief.py`
Expected: PASS.
Run (design stack down, DB `clue_trenton_wave1`): `DESIGN_PYTEST test_api.py -k "logo or describe_assets"`
Expected: PASS, including `test_logo_curation_keeps_the_kit_sections_the_engine_does_not_know`.

- [ ] **Step 8: Commit.**

```bash
git add subsystems/clue-design/apps/api/lumen_ingestion/measured_components.py subsystems/clue-design/apps/api/lumen_ingestion/brief.py \
  subsystems/clue-design/apps/api/lumen_ingestion/pipeline.py subsystems/clue-design/apps/api/lumen_api/brand_kit_sections.py \
  subsystems/clue-design/apps/api/lumen_api/main.py subsystems/clue-design/scripts/build_site_kit_brand_fixtures.py \
  subsystems/clue-design/apps/api/tests/test_measured_components.py subsystems/clue-design/apps/api/tests/test_api.py \
  apps/frontend/packages/site-kit/test/fixtures/kits
git commit -m "kits: a measured_components section naming every measured style's tokens; brief, grammar audit and measured components survive logo and description curation"
```

### Task X6: The brand-context panel keeps its designed groups (founder Q-A9-3, recommendation (a))

**Files:**
- Modify: `apps/frontend/src/features/brand-context/model/brand-context-mapping.ts` (`toColorGroups`, `toTextStyles`)
- Modify: `apps/frontend/src/features/brand-context/model/brand-context-mapping.test.ts`

- [ ] **Step 1: Write the failing test** (append to `brand-context-mapping.test.ts`):

```ts
test("tokens minted from measured component styles stay out of the designed panels", () => {
  const raw = structuredClone(HARVESTED_BRAND_KIT) as {
    brand_kit_json: { tokens: { colors: Record<string, unknown>; typography: Record<string, unknown> } };
  };
  raw.brand_kit_json.tokens.colors["button.solid-2.fill"] = {
    value: { default: { kind: "hex", value: "#28241E" }, modes: {} },
    role: "component",
    description: null,
    provenance: { source: "website:https://example.test/ :: button solid.2 rest fill", confidence: 0.8 },
  };
  raw.brand_kit_json.tokens.typography["button.solid-2.font"] = {
    value: {
      default: { kind: "style", font_family: "Inter", font_size: 16, font_weight: 500, line_height: 1.2, letter_spacing: 0, color: null, font_asset: null },
      modes: {},
    },
    role: "component",
    description: null,
    provenance: null,
  };
  const minted = toBrandContextWorkspace(BrandKitDetailSchema.parse(raw));
  const swatches = minted.colorGroups.flatMap((group) => group.swatches.map((swatch) => swatch.id));
  assert.ok(!swatches.includes("button.solid-2.fill"));
  assert.ok(!minted.textStyles.some((style) => style.id === "button.solid-2.font"));
  assert.deepEqual(
    minted.colorGroups.map((group) => group.swatches.length),
    workspace.colorGroups.map((group) => group.swatches.length),
  );
});
```

- [ ] **Step 2: Run it to see it fail.**

Run: `cd apps/frontend && npx tsx --test src/features/brand-context/model/brand-context-mapping.test.ts`
Expected: FAIL — `button.solid-2.fill` is listed under "Semantic roles".

- [ ] **Step 3: Filter them.** In `brand-context-mapping.ts`, above `toColorGroups` add:

```ts
/** Tokens ingestion mints from measured component styles (`button.solid-2.fill`, `motion.*`, Wave 2
 * A9). The panel's designed groups have no place for them, so they are left out until a design
 * gives them one; band surfaces (`surface.band.*`) are surfaces and stay. */
const COMPONENT_TOKEN_ROOTS = new Set(["button", "link", "navlink", "card", "chip", "input", "image", "motion"]);
const isComponentToken = (path: string) => COMPONENT_TOKEN_ROOTS.has(path.split(".", 1)[0]);
```
  In `toColorGroups`, `if (!colors[path]) continue;` becomes
  `if (!colors[path] || isComponentToken(path)) continue;`; in `toTextStyles`,
  `Object.keys(typography).flatMap(` becomes
  `Object.keys(typography).filter((path) => !isComponentToken(path)).flatMap(`.

- [ ] **Step 4: Run the brand-context tests, lint and build.**

Run: `cd apps/frontend && npx tsx --test src/features/brand-context/model/*.test.ts && npm run lint -- src/features/brand-context`
Expected: PASS; no lint errors.

- [ ] **Step 5: Commit.**

```bash
git add apps/frontend/src/features/brand-context/model/brand-context-mapping.ts apps/frontend/src/features/brand-context/model/brand-context-mapping.test.ts
git commit -m "brand context: leave minted component tokens out of the designed colour and type panels"
```

---

## A9-S — site-kit draws everything from the kit

### Task 4: Kit values, surfaces, looks and the theme, from measured tokens first

This replaces Lane A's Task 4. It keeps what that task got right — the kit's band and extra surfaces,
their inks and dark-surface rules, the per-brand Tailwind mapping (`tailwindThemeCss`) the server
CSS compile needs — and removes `secondaryButton()`, `brand.measured.primary_button` and every
literal style value (`theme.ts:83-84, :146-177, :212` today).

**Files:**
- Create: `apps/frontend/packages/site-kit/src/brand-values.ts`
- Create: `apps/frontend/packages/site-kit/src/surfaces.ts`
- Create: `apps/frontend/packages/site-kit/src/looks.ts`
- Rewrite: `apps/frontend/packages/site-kit/src/theme.ts`
- Modify: `apps/frontend/packages/site-kit/src/index.ts`
- Create: `apps/frontend/packages/site-kit/test/fixtures/kits.ts`
- Create: `apps/frontend/packages/site-kit/test/looks.test.ts`, `test/theme.test.ts`

**Interfaces:**
- `brand-values.ts`: `FALLBACKS` (the only literal style values in site-kit), `TokenEntry`,
  `tokenGroups`, `tokenEntry`, `isMeasured(entry)`, `isComponentToken(name)`,
  `colorOf/hexOf/numberOf/pxOf/ratioOf/typographyOf/fontStack/shadowOf/styleOf/durationOf/easingOf/transformOf/keywordOf`,
  `isSafeIconSvg`, `safeCss`, `luminance`, `contrast`, `alphaOf`, `chroma`, `fluid`, `trim`.
- `surfaces.ts`: `COLOR_ROLES`, `SURFACES` (the kit's nine), `CHOICE_ROLE`, `colorVar`,
  `extraSurfaceRoles(brand)` (beyond the nine; Lane A Task 6's lint takes it), `surfaceRoles`,
  `otherSurfaceRoles` (beyond our six), `inkRole(brand, surface)`, `isDarkSurface`,
  `surfaceChoices(brand) -> {value, label, role}[]`, `surfaceLabels(brand)`, `choiceName(role)`,
  `surfaceRoleOf(brand, choice)`.
- `looks.ts`: `MeasuredRecipe`, `Recipe`, `Look`, `State`, `STATES`, `Part`, `Parts`, `Drawn`,
  `measuredComponents`, `recipes`, `looks(brand, "button" | "card")`, `buttonLooks`, `cardLooks`,
  `lookNamed`, `buttonLookOptions(brand)`, `elementStyle(brand, "link" | "nav_link")`,
  `partsFromSlots`, `partsFromRecipe`, `standardButton`, `drawnButton`, `standardCard`, `drawnCard`,
  `drawnLink`, `transitionsOf`, `lookIcon`, `motionEntries(brand)`, `motionNotes(brand)`,
  `motionClassNames(brand)`.
- `theme.ts`: `themeCss(brand)`, `tailwindThemeCss(brand)`, `TYPE_ROLES`, `RADIUS_ROLES`,
  `SPACING_ROLES`, `typeVar`, `spacingVar`; re-exports `COLOR_ROLES`, `SURFACES`, `colorVar`,
  `extraSurfaceRoles`, `surfaceRoles` (Lane A Task 6 imports them from `./theme`).
- Classes the theme defines (components use only these and the Tailwind mapping): `brand-btn`,
  `brand-look-<n>`, `brand-btn-label`, `brand-btn-icon`, `brand-card`, `brand-card-look-<n>`,
  `brand-link`, `brand-navlink`, `brand-ink-<role>`, `brand-heading`, `brand-rule-t|b|v`,
  `brand-content`, `brand-logo-header|footer`, `brand-motion-<entry>`; Tailwind utilities
  `py-section`, `px-page-margin`, `mt-stack-tight|default|loose`, `gap-stack-*`, `p-card-padding`.

- [ ] **Step 1: The fixture loader** `test/fixtures/kits.ts` (the kit files were written by Task X5):

```ts
// The three real kits (garner, conduit, altcarbon: made before measurement) and their minted twins
// (written by subsystems/clue-design/scripts/build_site_kit_brand_fixtures.py from real measured
// values; probe.minted carries every state and motion the real probe measured on its fixture page).
import fs from "node:fs";
import { brandData, type BrandData } from "../../src/brand";

export type KitName = "garner" | "conduit" | "altcarbon" | "garner.minted" | "conduit.minted" | "probe.minted";

export function kitBrand(name: KitName): BrandData {
  const kit = JSON.parse(fs.readFileSync(new URL(`./kits/${name}.json`, import.meta.url), "utf-8"));
  return brandData({ slug: name, kit, fonts: [], kitAssets: {}, clones: [], measured: null });
}
```

- [ ] **Step 2: Write the failing tests.** `test/looks.test.ts`:

```ts
// Looks are the brief's recipes joined to the kit's measured recipes (Wave 2 A9). Measured first,
// the recipe's tokens second, the standard button's part third.
import assert from "node:assert/strict";
import { test } from "node:test";
import { colorOf } from "../src/brand-values";
import { buttonLookOptions, buttonLooks, drawnButton, drawnLink, lookNamed, motionEntries, motionNotes } from "../src/looks";
import { surfaceChoices } from "../src/surfaces";
import { kitBrand } from "./fixtures/kits";

test("a brand's looks are its button recipes, named for the dock by kind", () => {
  assert.deepEqual(buttonLookOptions(kitBrand("garner")).map((o) => [o.label, o.value]), [
    ["Standard", ""], ["Outline", "outline.1"], ["Text only", "ghost.1"],
    ["Filled 1", "solid.1"], ["Filled 2", "solid.2"], ["Filled 3", "solid.3"], ["Filled 4", "solid.4"],
  ]);
  assert.deepEqual(buttonLookOptions(kitBrand("altcarbon")).map((o) => o.label), ["Standard", "Filled"]);
});

test("an old kit draws a look from its recipe's tokens, and the standard button where the recipe has none", () => {
  const conduit = kitBrand("conduit");
  const look = lookNamed(conduit, "button", "solid.2")!;
  assert.equal(look.measured, null);
  const drawn = drawnButton(conduit, look);
  assert.equal(drawn.parts.fill, "#7CE4FC", "no fill in the kit: the standard button's surface.brand");
  assert.equal(drawn.source.fill, "standard");
  assert.equal(drawn.parts.label, "#FFFFFF");
  assert.equal(drawn.tokens.label, "text.inverse");
  assert.equal(drawn.parts.radius, "8px 8px 8px 8px");
});

test("a measured kit draws Conduit's demo button warm dark, never surface.brand", () => {
  const conduit = kitBrand("conduit.minted");
  const look = lookNamed(conduit, "button", "solid.2")!;
  const drawn = drawnButton(conduit, look);
  assert.equal(drawn.parts.fill, "#28241E");
  assert.equal(drawn.tokens.fill, "surface.band.28241e");
  assert.equal(drawn.source.fill, "measured");
  assert.equal(drawn.parts.padding, "0px 10px 0px 10px");
  assert.equal(drawn.parts.height, "32px");
});

test("outline and text-only looks never take the standard button's fill or label", () => {
  const garner = kitBrand("garner");
  const outline = drawnButton(garner, lookNamed(garner, "button", "outline.1"));
  assert.equal(outline.parts.fill, "transparent");
  assert.equal(outline.parts.label, colorOf(garner, "text.primary"));
  assert.equal(outline.parts.borderWidth, "1px 1px 1px 1px");
  const ghost = drawnButton(garner, lookNamed(garner, "button", "ghost.1"));
  assert.equal(ghost.parts.fill, "transparent");
  assert.equal(ghost.parts.label, colorOf(garner, "text.primary"));
});

test("a text link is the site's most measured link style, else underlined in its text's colour", () => {
  const probe = drawnLink(kitBrand("probe.minted"), "link");
  assert.equal(probe.parts.decoration, "none");
  assert.equal(probe.source.decoration, "measured");
  const old = drawnLink(kitBrand("garner"), "link");
  assert.deepEqual([old.parts.decoration, old.source.decoration], ["underline", "fallback"]);
});

test("the brand's surfaces: our six, then every other surface of the kit with a readable name", () => {
  const choices = surfaceChoices(kitBrand("garner.minted"));
  assert.deepEqual(choices.slice(0, 6).map((c) => c.value), ["page", "card", "muted", "brandSubtle", "brand", "inverse"]);
  const labels = Object.fromEntries(choices.slice(6).map((c) => [c.value, c.label]));
  assert.equal(labels["band-014036"], "Dark band");
  assert.equal(labels["band-ffffff"], "Light band");
  assert.equal(labels.canvas, "Canvas");
  assert.equal(labels.elevated, "Elevated");
  assert.equal(labels.accent, "Accent");
  assert.ok(!("band-014036" in Object.fromEntries(surfaceChoices(kitBrand("garner")).map((c) => [c.value, c.label]))));
});

test("motion entries come from the kit's measured animations and reveals", () => {
  const entries = motionEntries(kitBrand("probe.minted"));
  const pulse = entries.find((e) => e.className === "brand-motion-pulse")!;
  assert.equal(pulse.describe, "opacity 1 → .4, transform scale(1) → scale(1.2); repeats forever, alternating");
  assert.equal(pulse.timing, "1.6s ease-in-out");
  const reveal = entries.find((e) => e.kind === "reveal")!;
  assert.match(reveal.className, /^brand-motion-reveal-[0-9a-f]{8}$/);
  assert.equal(reveal.describe, "fades in from opacity 0 and moves into place from 24px below as it scrolls into view");
  assert.deepEqual(motionNotes(kitBrand("probe.minted")), [{ kind: "scripted", where: "div#spin.spin" }]);
  assert.deepEqual(motionEntries(kitBrand("garner")), []);
});
```

  and `test/theme.test.ts`:

```ts
// The theme is drawn from the kit (Wave 2 A9): measured recipes first, tokens second, named
// fallbacks last; states, dark surfaces, links, cards and motion included.
import assert from "node:assert/strict";
import { test } from "node:test";
import { colorOf } from "../src/brand-values";
import { buttonLooks, lookNamed } from "../src/looks";
import { tailwindThemeCss, themeCss } from "../src/theme";
import { kitBrand } from "./fixtures/kits";

const ruleOf = (css: string, selector: string) => {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return css.match(new RegExp(`(?:^|[}\\n])${escaped}\\{[^}]*\\}`))?.[0] ?? "";
};

test("Conduit's demo button: the kit's own fill when measured, surface.brand only in the old kit", () => {
  for (const [name, fill] of [["conduit.minted", "#28241E"], ["conduit", "#7CE4FC"]] as const) {
    const brand = kitBrand(name);
    const index = lookNamed(brand, "button", "solid.2")!.index;
    const css = themeCss(brand);
    const look = ruleOf(css, `.brand-btn.brand-look-${index}`);
    assert.match(look, new RegExp(`background-color:(var\\(--bs-${index}-fill,)?${fill}`), look);
    if (name === "conduit.minted") assert.doesNotMatch(look, /7CE4FC/);
  }
});

test("a filled look that would vanish on a dark surface takes the light version there, and only there", () => {
  const brand = kitBrand("conduit.minted");
  const index = lookNamed(brand, "button", "solid.2")!.index;
  const css = themeCss(brand);
  assert.match(ruleOf(css, ".bg-surface-band-28241e"), new RegExp(`--bs-${index}-fill:var\\(--brand-button-light-fill\\)`));
  assert.match(ruleOf(css, ".bg-surface-page"), new RegExp(`--bs-${index}-fill:initial`));
  assert.match(ruleOf(css, ".brand-root"), /--brand-button-light-fill:var\(--brand-surface-page\)/);
});

test("an outline look on a dark band takes the band's text colour", () => {
  const brand = kitBrand("garner.minted");
  const index = lookNamed(brand, "button", "outline.1")!.index;
  assert.match(ruleOf(themeCss(brand), ".bg-surface-band-014036"), new RegExp(`--bs-${index}-label:var\\(--brand-on-surface-band-014036\\)`));
});

test("every measured state is drawn: hover, press, focus, disabled, transitions and the icon", () => {
  const brand = kitBrand("probe.minted");
  const look = buttonLooks(brand).find((l) => colorOf(brand, l.measured?.rest.fill) === "#047464")!;
  const sel = `.brand-btn.brand-look-${look.index}`;
  const css = themeCss(brand);
  assert.match(ruleOf(css, `${sel}:hover`), /background-color:(var\(--bs-\d+-fill,)?#035A4E/);
  assert.match(ruleOf(css, `${sel}:hover`), /box-shadow:0px 4px 12px 0px #00000033/);
  assert.match(ruleOf(css, `${sel}:active`), /transform:matrix\(0\.98, 0, 0, 0\.98, 0, 0\)/);
  const focus = ruleOf(css, `${sel}:focus-visible`);
  for (const part of ["outline-color:#F5A623", "outline-width:3px", "outline-style:solid", "outline-offset:2px"]) assert.ok(focus.includes(part), focus);
  const disabled = ruleOf(css, `${sel}[aria-disabled="true"]`);
  assert.ok(disabled.includes("opacity:0.45") && disabled.includes("cursor:not-allowed"), disabled);
  assert.ok(ruleOf(css, sel).includes("transition:background-color 200ms ease-out 0ms, transform 150ms ease 0ms, box-shadow 300ms ease 50ms"));
  assert.ok(ruleOf(css, `${sel} .brand-btn-icon`).includes("transition:transform 200ms ease 0ms"));
  assert.ok(ruleOf(css, `${sel}:hover .brand-btn-icon`).includes("transform:matrix(1, 0, 0, 1, 4, 0)"));
  assert.ok(ruleOf(css, sel).includes("text-transform:uppercase"));
});

test("a look with no focus style of its own leaves the browser's focus ring alone", () => {
  const brand = kitBrand("probe.minted");
  const js = buttonLooks(brand).find((l) => colorOf(brand, l.measured?.rest.fill) === "#7C4CFF")!;
  assert.equal(ruleOf(themeCss(brand), `.brand-btn.brand-look-${js.index}:focus-visible`), "");
});

test("the standard button draws the kit's tokens and names its one fallback", () => {
  const std = ruleOf(themeCss(kitBrand("conduit")), ".brand-btn");
  assert.ok(std.includes("background-color:var(--bs-std-fill,#7CE4FC)") || std.includes("background-color:#7CE4FC"), std);
  assert.ok(std.includes("border-radius:8px 8px 8px 8px"), std);
  assert.ok(std.includes("padding:0.75em 1.5em 0.75em 1.5em"), std);
});

test("text links, cards, type colours and rules come from the kit", () => {
  const probe = themeCss(kitBrand("probe.minted"));
  assert.match(ruleOf(probe, ".brand-link"), /text-decoration-line:none/);
  const hover = ruleOf(probe, ".brand-link:hover");
  assert.match(hover, /color:(var\(--bs-link-color,)?#047464/);
  assert.ok(hover.includes("text-decoration-line:underline") && hover.includes("text-decoration-thickness:2px"), hover);
  const garner = themeCss(kitBrand("garner"));
  assert.match(ruleOf(garner, ".brand-link"), /text-decoration-line:underline/);
  assert.match(ruleOf(garner, ".bg-surface-page"), /--brand-ink-role-headline:var\(--brand-ink-primary\)/);
  assert.match(ruleOf(garner, ".bg-surface-page"), /--brand-ink-role-eyebrow:initial/, "text.brand is derived, not measured");
  assert.match(ruleOf(garner, ".bg-surface-inverse"), /--brand-ink-role-headline:initial/);
  assert.match(ruleOf(garner, ".brand-card"), /background-color:#F9FAF8/);
  assert.match(garner, /\.brand-rule-t\{border-top:var\(--brand-rule-width\) solid var\(--brand-rule-color\)\}/);
});

test("measured motion becomes classes, and nothing moves for visitors who ask for less", () => {
  const css = themeCss(kitBrand("probe.minted"));
  assert.ok(css.includes("@keyframes brand-kf-pulse{0%{opacity:1;transform:scale(1)}50%{opacity:.7}100%{opacity:.4;transform:scale(1.2)}}"), css);
  assert.match(css, /@media \(prefers-reduced-motion:no-preference\)\{\.brand-motion-pulse\{animation:brand-kf-pulse 1600ms ease-in-out 0ms infinite alternate none\}\}/);
  assert.match(css, /@supports \(animation-timeline:view\(\)\)\{@media \(prefers-reduced-motion:no-preference\)\{\.brand-motion-reveal-[0-9a-f]{8}\{animation:brand-kf-reveal-[0-9a-f]{8} ease-out both;animation-timeline:view\(\);animation-range:entry 0% entry 100%\}\}\}/);
  assert.match(css, /@media \(prefers-reduced-motion:reduce\),print\{[^}]*\{transition:none!important\}\[class\*="brand-motion-"\]\{animation:none!important\}\}/);
});

test("the Tailwind mapping covers every surface the kit has, the kit's spacing and nothing twice", () => {
  const css = tailwindThemeCss(kitBrand("garner.minted"));
  for (const line of [
    "--color-surface-band-014036: var(--brand-surface-band-014036);",
    "--color-on-surface-band-014036: var(--brand-on-surface-band-014036);",
    "--color-ink-secondary: var(--brand-ink-secondary);",
    "--text-body-small--line-height: var(--brand-text-body-small-lh);",
    "--radius-card: var(--brand-radius-card);",
    "--spacing-section: var(--brand-space-section);",
    "--spacing-stack-tight: var(--brand-space-stack-tight);",
    "--spacing-card-padding: var(--brand-space-card-padding);",
  ]) assert.ok(css.includes(line), line);
  assert.equal(css.split("--color-surface-page:").length, 2);
});
```

- [ ] **Step 3: Run them to see them fail.**

Run: `cd apps/frontend/packages/site-kit && npx tsx --test test/looks.test.ts test/theme.test.ts`
Expected: FAIL — `../src/looks` and `../src/brand-values` do not exist.

- [ ] **Step 4: Write `src/brand-values.ts`.**

```ts
// The brand kit's values, resolved. Every style value site-kit draws comes from here: a token of the
// kit (measured on the seller's site, or derived by the kit) or, only where the kit has none, one of
// FALLBACKS — each named where the agent can see it (brand.md). Components carry no style value of
// their own (test/style-literals.test.ts).
import type { BrandData } from "./brand";

type TokenDefault = { kind?: string; [key: string]: unknown };
export type TokenEntry = {
  value?: { default?: TokenDefault; modes?: Record<string, TokenDefault> };
  role?: string | null;
  description?: string | null;
  provenance?: { source?: string; confidence?: number } | null;
};
export type TokenGroups = Partial<Record<string, Record<string, TokenEntry>>>;

/** The only style values site-kit supplies itself, each used only where the kit has no value. */
export const FALLBACKS = {
  /** No kit token holds a button's padding (block, inline); brand.md says when it is drawn. */
  buttonPadding: ["0.75em", "1.5em"],
  /** An outline style whose border width the kit did not record. */
  outlineWidth: "1px",
  /** A button or a link card the kit gave no decoration is not underlined. */
  controlDecoration: "none",
  /** A text link the kit never measured stays visibly a link; brand.md says so. */
  linkDecoration: "underline",
  /** No kit token holds a page's content width. */
  contentWidth: "75rem",
  /** The kit records logos, not the size they are shown at in the header and footer. */
  headerLogoHeight: "1.75rem",
  footerLogoHeight: "1.25rem",
  /** Used only when the kit has no stroke.width.divider. */
  ruleWidth: "1px",
  /** Sizes are exact at the width the kit measured at; above `fixedUpToPx` they shrink on smaller
   * screens, to `minShare` of themselves at the least. */
  fluid: { fixedUpToPx: 24, minShare: 0.5, measuredAtPx: 1440 },
} as const;

export const COMPONENT_TOKEN_ROOTS = ["button", "link", "navlink", "card", "chip", "input", "image", "motion"] as const;
export const isComponentToken = (name: string) => (COMPONENT_TOKEN_ROOTS as readonly string[]).includes(name.split(".")[0]);

export function tokenGroups(brand: BrandData): TokenGroups {
  return ((brand.kit as { tokens?: TokenGroups }).tokens ?? {}) as TokenGroups;
}

export function tokenEntry(brand: BrandData, group: string, name: string | null | undefined): TokenEntry | undefined {
  return name ? tokenGroups(brand)[group]?.[name] : undefined;
}

/** Measured on the seller's site (any capture source), rather than derived or defaulted by the kit. */
export function isMeasured(entry: TokenEntry | undefined): boolean {
  const source = entry?.provenance?.source ?? "";
  return source !== "" && !source.startsWith("derived:") && !source.startsWith("default:");
}

export const trim = (n: number) => String(Math.round(n * 1000) / 1000);
const HEX = /^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$/;
const MAX_ALIAS_HOPS = 8;

function resolved(brand: BrandData, group: string, name: string | null | undefined, hops = 0): TokenDefault | undefined {
  const value = tokenEntry(brand, group, name)?.value?.default;
  if (!value || hops > MAX_ALIAS_HOPS) return undefined;
  if (value.kind === "alias" && typeof value.token === "string") return resolved(brand, group, value.token, hops + 1);
  return value;
}

/** A colour token as CSS: hex, or oklch(). */
export function colorOf(brand: BrandData, name: string | null | undefined): string | undefined {
  const value = resolved(brand, "colors", name);
  if (value?.kind === "hex" && typeof value.value === "string" && HEX.test(value.value)) return value.value.toUpperCase();
  if (value?.kind === "oklch" && [value.l, value.c, value.h].every((n) => typeof n === "number")) {
    return `oklch(${value.l} ${value.c} ${value.h} / ${typeof value.alpha === "number" ? value.alpha : 1})`;
  }
  return undefined;
}

/** The hex behind a colour token, for contrast maths. */
export function hexOf(brand: BrandData, name: string | null | undefined): string | undefined {
  const value = colorOf(brand, name);
  return value?.startsWith("#") ? value : undefined;
}

const NUMBER_GROUPS = ["spacing", "radii", "stroke_widths", "opacity", "numbers"] as const;

export function numberOf(brand: BrandData, name: string | null | undefined): { value: number; unit: string } | undefined {
  for (const group of NUMBER_GROUPS) {
    const value = resolved(brand, group, name);
    if (value?.kind === "number" && typeof value.value === "number" && Number.isFinite(value.value)) {
      return { value: value.value, unit: String(value.unit ?? "unitless") };
    }
  }
  return undefined;
}

export function pxOf(brand: BrandData, name: string | null | undefined): string | undefined {
  const n = numberOf(brand, name);
  return n && n.unit === "px" ? `${trim(n.value)}px` : undefined;
}

export function ratioOf(brand: BrandData, name: string | null | undefined): string | undefined {
  const n = numberOf(brand, name);
  return n && (n.unit === "ratio" || n.unit === "unitless") ? trim(n.value) : undefined;
}

export type TypeStyle = {
  family: string; size: number; weight: number; lineHeight: number | null; letterSpacing: number | null;
  color: string | null; asset: string | null;
};

export function typographyOf(brand: BrandData, name: string | null | undefined): TypeStyle | undefined {
  const value = resolved(brand, "typography", name);
  if (value?.kind !== "style" || typeof value.font_family !== "string" || typeof value.font_size !== "number") return undefined;
  return {
    family: value.font_family,
    size: value.font_size,
    weight: Number(value.font_weight ?? 400),
    lineHeight: typeof value.line_height === "number" ? value.line_height : null,
    letterSpacing: typeof value.letter_spacing === "number" ? value.letter_spacing : null,
    color: typeof value.color === "string" ? value.color : null,
    asset: typeof value.font_asset === "string" ? value.font_asset : null,
  };
}

/** The family, then the kit's own fallback stack for that font; nothing invented. */
export function fontStack(brand: BrandData, style: TypeStyle): string {
  const fonts = (brand.kit as { assets?: { fonts?: Record<string, { family?: string; fallback_stack?: string[] }> } }).assets?.fonts ?? {};
  const font = (style.asset ? fonts[style.asset] : undefined) ?? Object.values(fonts).find((f) => f.family === style.family);
  const names = [style.family, ...(font?.fallback_stack ?? [])].filter((name, i, all) => name && all.indexOf(name) === i);
  return names.map((name) => (/^[a-z-]+$/.test(name) ? name : `"${name.replace(/"/g, "")}"`)).join(", ");
}

export function shadowOf(brand: BrandData, name: string | null | undefined): string | undefined {
  const value = tokenEntry(brand, "shadows", name)?.value?.default as
    | { x?: number; y?: number; blur?: number; spread?: number; color?: string } | undefined;
  if (!value || typeof value.color !== "string" || !HEX.test(value.color)) return undefined;
  return `${trim(value.x ?? 0)}px ${trim(value.y ?? 0)}px ${trim(value.blur ?? 0)}px ${trim(value.spread ?? 0)}px ${value.color.toUpperCase()}`;
}

export type StyleValue =
  | { kind: "keyword"; property: string; value: string }
  | { kind: "duration"; ms: number }
  | { kind: "easing"; function: string }
  | { kind: "transform"; value: string }
  | { kind: "keyframes"; frames: { offset: number; declarations: Record<string, string> }[] }
  | { kind: "animation"; keyframes: string; duration: string; easing: string; delay: string | null; iterations: string; direction: string; fill_mode: string }
  | { kind: "reveal"; from_opacity: string | null; from_transform: string | null; duration: string; easing: string }
  | { kind: "glyph"; text: string }
  | { kind: "svg"; markup: string; width: number; height: number };

const SAFE_CSS = /^[A-Za-z0-9 ,.()%#+\-/]{1,400}$/;
/** A CSS value that only draws: plain characters, nothing that loads or substitutes. */
export const safeCss = (value: string) => SAFE_CSS.test(value) && !/url\(|var\(|expression/i.test(value);
const SVG_BANNED = ["<script", "javascript:", "url(", "href", "<foreignobject", "<!", "<?", "<style", "<use", "<image", "<a ", "<a>"];

/** The engine's own icon rule, checked again where the markup is drawn. */
export function isSafeIconSvg(markup: string): boolean {
  const lower = markup.toLowerCase().trim();
  return markup.length <= 4096 && lower.startsWith("<svg") && lower.endsWith("</svg>")
    && !SVG_BANNED.some((bad) => lower.includes(bad)) && !/ on[a-z]+\s*=/.test(lower);
}

/** A `styles` token, re-checked here too: these values go into generated CSS and markup. */
export function styleOf(brand: BrandData, name: string | null | undefined): StyleValue | undefined {
  const value = resolved(brand, "styles", name);
  if (!value) return undefined;
  switch (value.kind) {
    case "keyword": return typeof value.value === "string" && safeCss(value.value) ? (value as StyleValue) : undefined;
    case "easing": return typeof value.function === "string" && safeCss(value.function) ? (value as StyleValue) : undefined;
    case "transform": return typeof value.value === "string" && /^(none|matrix(3d)?\([0-9 ,.\-e]+\))$/.test(value.value) ? (value as StyleValue) : undefined;
    case "duration": return typeof value.ms === "number" && value.ms >= 0 ? (value as StyleValue) : undefined;
    case "glyph": return typeof value.text === "string" && !/[<>&"']/.test(value.text) ? (value as StyleValue) : undefined;
    case "svg": return typeof value.markup === "string" && isSafeIconSvg(value.markup) ? (value as StyleValue) : undefined;
    case "keyframes":
    case "animation":
    case "reveal":
      return value as StyleValue;
    default:
      return undefined;
  }
}

export function keywordOf(brand: BrandData, name: string | null | undefined): string | undefined {
  const value = styleOf(brand, name);
  return value?.kind === "keyword" ? value.value : undefined;
}

export function durationOf(brand: BrandData, name: string | null | undefined): string | undefined {
  const value = styleOf(brand, name);
  return value?.kind === "duration" ? `${trim(value.ms)}ms` : undefined;
}

export function easingOf(brand: BrandData, name: string | null | undefined): string | undefined {
  const value = styleOf(brand, name);
  return value?.kind === "easing" ? value.function : undefined;
}

export function transformOf(brand: BrandData, name: string | null | undefined): string | undefined {
  const value = styleOf(brand, name);
  return value?.kind === "transform" ? value.value : undefined;
}

export function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrast(a: string, b: string): number {
  const [x, y] = [luminance(a), luminance(b)].sort((m, n) => n - m);
  return (x + 0.05) / (y + 0.05);
}

export const alphaOf = (hex: string) => (hex.length === 9 ? parseInt(hex.slice(7, 9), 16) / 255 : 1);

/** OKLCH chroma of a hex colour, through OKLab. */
export function chroma(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  const a = 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s;
  const bb = 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s;
  return Math.sqrt(a * a + bb * bb);
}

/** A kit size as CSS: exact at the width the kit measured at, shrinking on smaller screens. */
export function fluid(px: number): string {
  const { fixedUpToPx, minShare, measuredAtPx } = FALLBACKS.fluid;
  if (px <= fixedUpToPx) return `${trim(px)}px`;
  const min = Math.max(fixedUpToPx, Math.round(px * minShare));
  return `clamp(${min}px, ${((px / measuredAtPx) * 100).toFixed(3)}vw, ${trim(px)}px)`;
}
```

- [ ] **Step 5: Write `src/surfaces.ts`.**

```ts
// The brand's surfaces: the kit's nine surface roles, every other `surface.*` token it carries (the
// section backgrounds minted from the seller's site included), the text colour on each, and the
// names the agent and the marketer choose them by (Wave 2 A9; founder Q4 = (b)).
import type { BrandData } from "./brand";
import { chroma, colorOf, contrast, hexOf, luminance, tokenGroups } from "./brand-values";
import { SURFACES as CHOICES, SURFACE_LABELS } from "./schemas";

export const COLOR_ROLES = [
  "text.primary", "text.secondary", "text.muted", "text.inverse", "text.brand", "text.accent",
  "surface.page", "surface.canvas", "surface.card", "surface.muted", "surface.elevated",
  "surface.brand", "surface.brand.subtle", "surface.accent", "surface.inverse",
  "border.subtle", "border.default", "border.strong", "border.brand", "focus.ring",
] as const;

/** The kit's nine surface roles. */
export const SURFACES = [
  "surface.page", "surface.canvas", "surface.card", "surface.muted", "surface.elevated",
  "surface.brand", "surface.brand.subtle", "surface.accent", "surface.inverse",
] as const;

/** Our six choices and the kit role each one is. */
export const CHOICE_ROLE: Record<(typeof CHOICES)[number], string> = {
  page: "surface.page", card: "surface.card", muted: "surface.muted",
  brandSubtle: "surface.brand.subtle", brand: "surface.brand", inverse: "surface.inverse",
};

/** `text.primary` -> `ink-primary`, `surface.brand.subtle` -> `surface-brand-subtle`. */
export function colorVar(role: string): string {
  return role.replace(/^text\./, "ink.").replace(/^border\./, "line.").replace(/^focus\.ring$/, "focus").replace(/\./g, "-");
}

/** Every surface the kit has beyond its nine roles (band surfaces and any other `surface.<x>`). */
export function extraSurfaceRoles(brand: BrandData): string[] {
  const known = new Set<string>(SURFACES);
  return Object.keys(tokenGroups(brand).colors ?? {})
    .filter((role) => role.startsWith("surface.") && !known.has(role) && colorOf(brand, role) !== undefined)
    .sort();
}

/** The nine (those the kit has) and the extras. */
export function surfaceRoles(brand: BrandData): string[] {
  return [...SURFACES.filter((role) => colorOf(brand, role) !== undefined), ...extraSurfaceRoles(brand)];
}

const OUR_ROLES = new Set(Object.values(CHOICE_ROLE));
/** The kit's surfaces beyond our six: canvas, elevated, accent, then the extras. */
export const otherSurfaceRoles = (brand: BrandData) => surfaceRoles(brand).filter((role) => !OUR_ROLES.has(role));

/** The colour role text takes on a surface: the kit's contrast pair first, else the better of
 * text.primary and text.inverse. */
export function inkRole(brand: BrandData, surface: string): string | undefined {
  const bg = hexOf(brand, surface);
  if (!bg) return undefined;
  const pairs = (brand.kit as { constraints?: { contrast_pairs?: { background: string; foreground: string }[] } }).constraints?.contrast_pairs ?? [];
  const pair = pairs.find((p) => p.background === surface && hexOf(brand, p.foreground));
  if (pair) return pair.foreground;
  const primary = hexOf(brand, "text.primary");
  const inverse = hexOf(brand, "text.inverse");
  if (!primary || !inverse) return primary ? "text.primary" : inverse ? "text.inverse" : undefined;
  return contrast(bg, primary) >= contrast(bg, inverse) ? "text.primary" : "text.inverse";
}

/** A surface is dark when the text on it is lighter than it. */
export function isDarkSurface(brand: BrandData, surface: string): boolean {
  const bg = hexOf(brand, surface);
  const ink = hexOf(brand, inkRole(brand, surface));
  return !!bg && !!ink && luminance(ink) > luminance(bg);
}

export const choiceName = (role: string) => colorVar(role).replace(/^surface-/, "");
const BAND_HEX = /^surface\.band\.[0-9a-f]{6}$/;
const sentence = (words: string[]) => {
  const text = words.filter(Boolean).join(" ");
  return text ? text[0].toUpperCase() + text.slice(1) : text;
};

/** Marketer- and agent-facing names for the kit's other surfaces (rule approved as T-A9-7). */
export function surfaceLabels(brand: BrandData): Map<string, string> {
  const labels = new Map<string, string>();
  const bands = new Map<string, string[]>();
  for (const role of otherSurfaceRoles(brand)) {
    if (BAND_HEX.test(role)) {
      const hex = hexOf(brand, role);
      const kind = isDarkSurface(brand, role) ? "Dark band" : hex && chroma(hex) >= 0.04 ? "Tinted band" : "Light band";
      bands.set(kind, [...(bands.get(kind) ?? []), role]);
      continue;
    }
    const words = role.replace(/^surface\./, "").split(/[.-]/);
    if (words[0] === "band") {
      const rest = words.slice(1);
      const number = /^\d+$/.test(rest[rest.length - 1] ?? "") ? rest.pop() : undefined;
      labels.set(role, `${sentence([...rest, "band"])}${number ? ` ${number}` : ""}`);
    } else {
      labels.set(role, sentence(words));
    }
  }
  for (const [kind, roles] of bands) roles.forEach((role, i) => labels.set(role, roles.length > 1 ? `${kind} ${i + 1}` : kind));
  return labels;
}

export type SurfaceChoice = { value: string; label: string; role: string };

/** Every surface a section may stand on: our six as today, then the kit's others. */
export function surfaceChoices(brand: BrandData): SurfaceChoice[] {
  const labels = surfaceLabels(brand);
  return [
    ...CHOICES.map((value) => ({ value: value as string, label: SURFACE_LABELS[value], role: CHOICE_ROLE[value] })),
    ...otherSurfaceRoles(brand).map((role) => ({ value: choiceName(role), label: labels.get(role) ?? role, role })),
  ];
}

export const surfaceRoleOf = (brand: BrandData, choice: string) => surfaceChoices(brand).find((c) => c.value === choice)?.role;
```

- [ ] **Step 6: Write `src/looks.ts`.**

```ts
// Button and card looks, text links and motion (Wave 2 A9). A look is one of the brief's recipes
// (what the model judged: which styles are page buttons, notes, confidence) joined by (component,
// variant) to the kit's measured recipe (what the capture measured, as token names). Each part is
// drawn from the measured token first, the recipe's token second, the standard part third, a named
// fallback last — and `Drawn.source` says which, for brand.md.
import type { BrandData } from "./brand";
import {
  FALLBACKS, colorOf, durationOf, easingOf, fluid, fontStack, keywordOf, numberOf, pxOf, ratioOf, shadowOf,
  styleOf, transformOf, trim, typographyOf,
} from "./brand-values";
import { inkRole } from "./surfaces";

export type State = "hover" | "pressed" | "focus" | "disabled";
export const STATES: State[] = ["hover", "pressed", "focus", "disabled"];

export type MeasuredRecipe = {
  component: string; variant: string; count: number; probed: string; source: string;
  rest: Record<string, string>;
  states: Partial<Record<State, Record<string, string>>>;
  motion: { target: "self" | "label" | "icon"; property: string; duration: string; easing: string; delay?: string | null }[];
  icon: { token: string; position: "start" | "end" } | null;
  browser_focus_ring?: boolean;
};
export type Recipe = {
  component: string; variant: string; radius?: string | null; padding?: string | null; border?: string | null;
  shadow?: string | null; background?: string | null; text?: string | null; unmapped?: string[]; confidence?: string;
};
export type Look = { name: string; kind: "outline" | "ghost" | "solid" | "other"; label: string; index: number; recipe: Recipe; measured: MeasuredRecipe | null };
type Motion = { animations?: string[]; reveals?: string[]; scripted?: { kind: string; where: string }[] };
type Section = { schema_version?: number; styles?: MeasuredRecipe[]; motion?: Motion };

export function measuredComponents(brand: BrandData): Section | null {
  const section = (brand.kit as { measured_components?: Section }).measured_components;
  return section && section.schema_version === 1 ? section : null;
}

export function recipes(brand: BrandData): Recipe[] {
  const list = (brand.kit as { brief?: { component_recipes?: unknown[] } }).brief?.component_recipes ?? [];
  return list.filter((r): r is Recipe => !!r && typeof (r as Recipe).component === "string" && typeof (r as Recipe).variant === "string");
}

const KIND_ORDER = ["outline", "ghost", "solid", "other"] as const;
const KIND_LABEL = { outline: "Outline", ghost: "Text only", solid: "Filled" } as const;
export const kindOf = (variant: string): Look["kind"] => {
  const head = variant.split(".")[0];
  return head === "outline" || head === "ghost" || head === "solid" ? head : "other";
};
const ordinal = (variant: string) => Number(variant.split(".")[1]) || 0;
const words = (variant: string) => {
  const text = variant.replace(/[._-]+/g, " ").trim();
  return text ? text[0].toUpperCase() + text.slice(1) : variant;
};

/** The brand's looks for a component, in dock order (outline, text only, filled; by number). */
export function looks(brand: BrandData, component: "button" | "card"): Look[] {
  const measured = measuredComponents(brand)?.styles ?? [];
  const seen = new Set<string>();
  const list = recipes(brand).filter((r) => r.component === component && !seen.has(r.variant) && !!seen.add(r.variant));
  list.sort((a, b) =>
    KIND_ORDER.indexOf(kindOf(a.variant)) - KIND_ORDER.indexOf(kindOf(b.variant)) || ordinal(a.variant) - ordinal(b.variant) || a.variant.localeCompare(b.variant));
  const totals = new Map<string, number>();
  for (const r of list) totals.set(kindOf(r.variant), (totals.get(kindOf(r.variant)) ?? 0) + 1);
  const counters = new Map<string, number>();
  return list.map((recipe, index) => {
    const kind = kindOf(recipe.variant);
    const n = (counters.get(kind) ?? 0) + 1;
    counters.set(kind, n);
    const label = kind === "other" ? words(recipe.variant) : (totals.get(kind) ?? 0) > 1 ? `${KIND_LABEL[kind]} ${n}` : KIND_LABEL[kind];
    return { name: recipe.variant, kind, label, index, recipe, measured: measured.find((s) => s.component === component && s.variant === recipe.variant) ?? null };
  });
}

export const buttonLooks = (brand: BrandData) => looks(brand, "button");
export const cardLooks = (brand: BrandData) => looks(brand, "card");
export const lookNamed = (brand: BrandData, component: "button" | "card", name?: string | null) =>
  (name ? looks(brand, component).find((look) => look.name === name) : undefined) ?? null;

/** The dock's "Button style" options (T-A9-7). */
export function buttonLookOptions(brand: BrandData): { label: string; value: string }[] {
  return [{ label: "Standard", value: "" }, ...buttonLooks(brand).map((look) => ({ label: look.label, value: look.name }))];
}

/** The site's most measured style of an element the kit draws without a choice (styles are stored
 * most frequent first). */
export function elementStyle(brand: BrandData, component: "link" | "nav_link"): MeasuredRecipe | null {
  return measuredComponents(brand)?.styles?.find((style) => style.component === component) ?? null;
}

export type Part =
  | "fill" | "label" | "border" | "borderWidth" | "borderStyle" | "radius" | "padding" | "height" | "gap"
  | "fontFamily" | "fontSize" | "fontWeight" | "lineHeight" | "tracking" | "case" | "decoration"
  | "decorationThickness" | "underlineOffset" | "shadow" | "opacity" | "transform" | "filter" | "cursor"
  | "outlineColor" | "outlineWidth" | "outlineStyle" | "outlineOffset" | "iconColor" | "iconTransform" | "iconOpacity";
/** CSS values; four-sided parts list top right bottom left (corners: tl tr br bl). */
export type Parts = Partial<Record<Part, string>>;
export type Source = "measured" | "kit" | "standard" | "fallback" | "none" | "inherit";
export type Drawn = { parts: Parts; tokens: Partial<Record<Part, string>>; source: Partial<Record<Part, Source>> };

const SIDES = ["top", "right", "bottom", "left"] as const;
const CORNERS = ["tl", "tr", "br", "bl"] as const;
const four = (value: string) => `${value} ${value} ${value} ${value}`;
const distinct = (names: (string | undefined)[]) => [...new Set(names.filter((n): n is string => !!n))].join(" / ");

/** The parts a set of measured slots names, resolved through the kit. */
export function partsFromSlots(brand: BrandData, slots: Record<string, string> | undefined): { parts: Parts; tokens: Partial<Record<Part, string>> } {
  const parts: Parts = {};
  const tokens: Partial<Record<Part, string>> = {};
  if (!slots) return { parts, tokens };
  const set = (part: Part, value: string | undefined, token: string) => {
    if (value !== undefined) {
      parts[part] = value;
      tokens[part] = token;
    }
  };
  const padding = SIDES.map((side) => pxOf(brand, slots[`padding-${side}`]));
  const borders = SIDES.map((side) => pxOf(brand, slots[`border-width-${side}`]));
  const corners = CORNERS.map((corner) => pxOf(brand, slots[`radius-${corner}`]));
  if (padding.some(Boolean)) {
    parts.padding = padding.map((v) => v ?? "0").join(" ");
    tokens.padding = distinct(SIDES.map((side) => slots[`padding-${side}`]));
  }
  if (borders.some(Boolean)) {
    parts.borderWidth = borders.map((v) => v ?? "0").join(" ");
    tokens.borderWidth = distinct(SIDES.map((side) => slots[`border-width-${side}`]));
  }
  if (corners.some(Boolean)) {
    parts.radius = corners.map((v) => v ?? "0").join(" ");
    tokens.radius = distinct(CORNERS.map((corner) => slots[`radius-${corner}`]));
  }
  const shadows = Object.keys(slots).filter((slot) => /^shadow-\d+$/.test(slot)).sort((a, b) => Number(a.slice(7)) - Number(b.slice(7)));
  const layers = shadows.map((slot) => shadowOf(brand, slots[slot])).filter((s): s is string => !!s);
  if (layers.length) {
    parts.shadow = layers.join(", ");
    tokens.shadow = distinct(shadows.map((slot) => slots[slot]));
  }
  for (const [slot, token] of Object.entries(slots)) {
    switch (slot) {
      case "fill": set("fill", colorOf(brand, token), token); break;
      case "label": set("label", colorOf(brand, token), token); break;
      case "border": set("border", colorOf(brand, token), token); break;
      case "border-width": { const w = pxOf(brand, token); set("borderWidth", w && four(w), token); break; }
      case "border-style": set("borderStyle", keywordOf(brand, token), token); break;
      case "radius": { const r = pxOf(brand, token); set("radius", r && four(r), token); break; }
      case "height": set("height", pxOf(brand, token), token); break;
      case "gap": set("gap", pxOf(brand, token), token); break;
      case "font": {
        const style = typographyOf(brand, token);
        if (!style) break;
        set("fontFamily", fontStack(brand, style), token);
        set("fontSize", `${trim(style.size)}px`, token);
        set("fontWeight", String(style.weight), token);
        if (style.lineHeight !== null) set("lineHeight", trim(style.lineHeight), token);
        if (style.letterSpacing !== null) set("tracking", `${trim(style.letterSpacing)}em`, token);
        break;
      }
      case "case": set("case", keywordOf(brand, token), token); break;
      case "decoration": set("decoration", keywordOf(brand, token), token); break;
      case "decoration-thickness": set("decorationThickness", pxOf(brand, token) ?? keywordOf(brand, token), token); break;
      case "underline-offset": set("underlineOffset", pxOf(brand, token) ?? keywordOf(brand, token), token); break;
      case "shadow": set("shadow", keywordOf(brand, token), token); break; // "none": a state that removes the rest shadow
      case "opacity": set("opacity", ratioOf(brand, token), token); break;
      case "transform": set("transform", transformOf(brand, token), token); break;
      case "filter": set("filter", keywordOf(brand, token), token); break;
      case "cursor": set("cursor", keywordOf(brand, token), token); break;
      case "outline": set("outlineColor", colorOf(brand, token), token); break;
      case "outline-width": set("outlineWidth", pxOf(brand, token), token); break;
      case "outline-style": set("outlineStyle", keywordOf(brand, token), token); break;
      case "outline-offset": set("outlineOffset", pxOf(brand, token), token); break;
      case "icon-color": set("iconColor", colorOf(brand, token), token); break;
      case "icon-transform": set("iconTransform", transformOf(brand, token), token); break;
      case "icon-opacity": set("iconOpacity", ratioOf(brand, token), token); break;
      default: break;
    }
  }
  return { parts, tokens };
}

/** The parts a brief recipe names (token names the model chose; measured values outrank them). */
export function partsFromRecipe(brand: BrandData, recipe: Recipe): { parts: Parts; tokens: Partial<Record<Part, string>> } {
  const parts: Parts = {};
  const tokens: Partial<Record<Part, string>> = {};
  const set = (part: Part, value: string | undefined, token: string | null | undefined) => {
    if (value !== undefined && token) {
      parts[part] = value;
      tokens[part] = token;
    }
  };
  set("fill", colorOf(brand, recipe.background), recipe.background);
  set("label", colorOf(brand, recipe.text), recipe.text);
  const width = pxOf(brand, recipe.border);
  set("borderWidth", width && four(width), recipe.border);
  if (width) parts.borderStyle = "solid";
  const radius = pxOf(brand, recipe.radius);
  set("radius", radius && four(radius), recipe.radius);
  const padding = pxOf(brand, recipe.padding);
  set("padding", padding && four(padding), recipe.padding);
  set("shadow", shadowOf(brand, recipe.shadow), recipe.shadow);
  return { parts, tokens };
}

function put(drawn: Drawn, part: Part, value: string | undefined, token: string | undefined, source: Source) {
  if (value === undefined) return;
  drawn.parts[part] = value;
  drawn.source[part] = source;
  if (token) drawn.tokens[part] = token;
  else delete drawn.tokens[part];
}

function apply(drawn: Drawn, from: { parts: Parts; tokens: Partial<Record<Part, string>> }, source: Source, skip: readonly Part[] = []) {
  for (const [part, value] of Object.entries(from.parts) as [Part, string][]) {
    if (!skip.includes(part)) put(drawn, part, value, from.tokens[part], source);
  }
}

function putType(drawn: Drawn, brand: BrandData, role: string, source: Source) {
  const style = typographyOf(brand, role);
  if (!style) return;
  put(drawn, "fontFamily", fontStack(brand, style), role, source);
  put(drawn, "fontSize", `${trim(style.size)}px`, role, source);
  put(drawn, "fontWeight", String(style.weight), role, source);
  if (style.lineHeight !== null) put(drawn, "lineHeight", trim(style.lineHeight), role, source);
  if (style.letterSpacing !== null) put(drawn, "tracking", `${trim(style.letterSpacing)}em`, role, source);
}

/** The kit's standard button: its brand surface with its pair, its button corners, its cta type;
 * the padding is site-kit's one fallback (no kit token holds it). */
export function standardButton(brand: BrandData): Drawn {
  const drawn: Drawn = { parts: {}, tokens: {}, source: {} };
  const ink = inkRole(brand, "surface.brand");
  put(drawn, "fill", colorOf(brand, "surface.brand"), "surface.brand", "kit");
  put(drawn, "label", colorOf(brand, ink), ink, "kit");
  const radius = pxOf(brand, "radius.button");
  put(drawn, "radius", radius && four(radius), "radius.button", "kit");
  const [block, inline] = FALLBACKS.buttonPadding;
  put(drawn, "padding", `${block} ${inline} ${block} ${inline}`, undefined, "fallback");
  put(drawn, "decoration", FALLBACKS.controlDecoration, undefined, "fallback");
  putType(drawn, brand, "type.cta", "kit");
  const disabled = ratioOf(brand, "opacity.disabled");
  if (disabled) drawn.tokens.opacity = "opacity.disabled";
  return drawn;
}

/** How a look is drawn at rest. */
export function drawnButton(brand: BrandData, look: Look | null): Drawn {
  const drawn = standardButton(brand);
  if (!look) return drawn;
  for (const part of Object.keys(drawn.source) as Part[]) if (drawn.source[part] !== "fallback") drawn.source[part] = "standard";
  delete drawn.tokens.opacity;
  if (look.kind === "outline" || look.kind === "ghost") {
    put(drawn, "fill", "transparent", undefined, "none");
    put(drawn, "label", "inherit", undefined, "inherit");
  }
  if (look.kind === "outline") {
    put(drawn, "borderWidth", four(FALLBACKS.outlineWidth), undefined, "fallback");
    put(drawn, "borderStyle", "solid", undefined, "fallback");
    put(drawn, "border", "currentColor", undefined, "inherit");
  }
  apply(drawn, partsFromRecipe(brand, look.recipe), "kit");
  apply(drawn, partsFromSlots(brand, look.measured?.rest), "measured");
  return drawn;
}

/** The kit's standard card. */
export function standardCard(brand: BrandData): Drawn {
  const drawn: Drawn = { parts: {}, tokens: {}, source: {} };
  const ink = inkRole(brand, "surface.card");
  put(drawn, "fill", colorOf(brand, "surface.card"), "surface.card", "kit");
  put(drawn, "label", colorOf(brand, ink), ink, "kit");
  const radius = pxOf(brand, "radius.card");
  put(drawn, "radius", radius && four(radius), "radius.card", "kit");
  const padding = numberOf(brand, "space.card.padding");
  put(drawn, "padding", padding && padding.unit === "px" ? fluid(padding.value) : undefined, "space.card.padding", "kit");
  put(drawn, "decoration", FALLBACKS.controlDecoration, undefined, "fallback");
  return drawn;
}

const CARD_SKIP: readonly Part[] = ["height", "gap", "fontFamily", "fontSize", "fontWeight", "lineHeight", "tracking", "case"];

export function drawnCard(brand: BrandData, look: Look | null): Drawn {
  const drawn = standardCard(brand);
  if (!look) return drawn;
  for (const part of Object.keys(drawn.source) as Part[]) if (drawn.source[part] !== "fallback") drawn.source[part] = "standard";
  if (look.kind === "ghost" || look.kind === "outline") {
    put(drawn, "fill", "transparent", undefined, "none");
    put(drawn, "label", "inherit", undefined, "inherit");
  }
  if (look.kind === "outline") {
    put(drawn, "borderWidth", four(FALLBACKS.outlineWidth), undefined, "fallback");
    put(drawn, "borderStyle", "solid", undefined, "fallback");
    put(drawn, "border", "currentColor", undefined, "inherit");
  }
  apply(drawn, partsFromRecipe(brand, look.recipe), "kit", CARD_SKIP);
  apply(drawn, partsFromSlots(brand, look.measured?.rest), "measured", CARD_SKIP);
  return drawn;
}

/** A text link takes its paragraph's font and box; a nav item keeps the measured font. */
const LINK_SKIP: readonly Part[] = ["fill", "border", "borderWidth", "borderStyle", "radius", "padding", "height", "gap", "fontFamily", "fontSize", "lineHeight"];
const NAV_SKIP: readonly Part[] = ["fill", "border", "borderWidth", "borderStyle", "radius", "padding", "height", "gap"];

export function drawnLink(brand: BrandData, component: "link" | "nav_link"): Drawn & { style: MeasuredRecipe | null } {
  const style = elementStyle(brand, component);
  const drawn: Drawn = { parts: {}, tokens: {}, source: {} };
  if (component === "link") put(drawn, "decoration", FALLBACKS.linkDecoration, undefined, "fallback");
  else putType(drawn, brand, "type.body", "kit");
  apply(drawn, partsFromSlots(brand, style?.rest), "measured", component === "link" ? LINK_SKIP : NAV_SKIP);
  return { ...drawn, style };
}

/** A recipe's measured transitions as one CSS `transition` value, for the box or for its icon. */
export function transitionsOf(brand: BrandData, recipe: MeasuredRecipe | null | undefined, target: "box" | "icon"): string | undefined {
  const steps = (recipe?.motion ?? [])
    .filter((m) => (target === "icon" ? m.target === "icon" : m.target !== "icon"))
    .flatMap((m) => {
      const duration = durationOf(brand, m.duration);
      const easing = easingOf(brand, m.easing);
      const delay = m.delay ? durationOf(brand, m.delay) : "0ms";
      return duration && easing && delay && /^(all|[a-z-]{1,60})$/.test(m.property) ? [`${m.property} ${duration} ${easing} ${delay}`] : [];
    });
  return steps.length ? steps.join(", ") : undefined;
}

export type DrawnIcon = { position: "start" | "end"; glyph?: string; svg?: string };

/** The icon the seller's site draws in this button style, if the kit kept one. */
export function lookIcon(brand: BrandData, look: Look | null): DrawnIcon | null {
  const icon = look?.measured?.icon;
  if (!icon) return null;
  const value = styleOf(brand, icon.token);
  if (value?.kind === "glyph") return { position: icon.position, glyph: value.text };
  if (value?.kind === "svg") return { position: icon.position, svg: value.markup };
  return null;
}

export type MotionEntry = { className: string; token: string; kind: "animation" | "reveal"; css: string; describe: string; timing: string; where: string };
const KEYFRAME_PROPERTIES = new Set(["opacity", "transform", "translate", "scale", "rotate", "filter", "color", "background-color", "border-color", "box-shadow", "background-position"]);
const SAFE_VALUE = /^[A-Za-z0-9 ,.()%#+\-/]{1,200}$/;
const seconds = (ms: string) => (Number.parseFloat(ms) >= 1000 ? `${trim(Number.parseFloat(ms) / 1000)}s` : ms);

function describeMove(transform: string | null): string {
  const m = transform?.match(/^matrix\(([^)]+)\)$/);
  if (!m) return "";
  const [a, , , d, tx, ty] = m[1].split(",").map((n) => Number.parseFloat(n));
  const moves: string[] = [];
  if (ty) moves.push(`from ${trim(Math.abs(ty))}px ${ty > 0 ? "below" : "above"}`);
  if (tx) moves.push(`from ${trim(Math.abs(tx))}px to the ${tx > 0 ? "right" : "left"}`);
  const parts = moves.length ? [`moves into place ${moves.join(" and ")}`] : [];
  if (a === d && a && a !== 1) parts.push(`grows from ${trim(a * 100)}%`);
  return parts.join(" and ");
}

/** The kit's measured motion as classes an agent section may add (Wave 2 A9). Script-free CSS
 * only: keyframe animations as measured; a reveal as a scroll-driven animation from its measured
 * starting look (a published page cannot run the seller's script that started it). */
export function motionEntries(brand: BrandData): MotionEntry[] {
  const motion = measuredComponents(brand)?.motion;
  const entries: MotionEntry[] = [];
  for (const token of motion?.animations ?? []) {
    const value = styleOf(brand, token);
    const keyframes = value?.kind === "animation" ? styleOf(brand, value.keyframes) : undefined;
    if (value?.kind !== "animation" || keyframes?.kind !== "keyframes") continue;
    const slug = token.replace(/^motion\.animation\./, "");
    const duration = durationOf(brand, value.duration);
    const easing = easingOf(brand, value.easing);
    const delay = value.delay ? durationOf(brand, value.delay) : "0ms";
    if (!duration || !easing || !delay || !/^[a-z0-9-]+$/.test(slug)) continue;
    const frames = keyframes.frames.map((frame) => {
      const decls = Object.entries(frame.declarations).filter(([p, v]) => KEYFRAME_PROPERTIES.has(p) && SAFE_VALUE.test(v) && !/url\(|var\(/i.test(v));
      return `${trim(frame.offset)}%{${decls.map(([p, v]) => `${p}:${v}`).join(";")}}`;
    });
    const first = keyframes.frames[0]?.declarations ?? {};
    const last = keyframes.frames[keyframes.frames.length - 1]?.declarations ?? {};
    const changes = [...new Set([...Object.keys(first), ...Object.keys(last)])]
      .filter((p) => first[p] !== undefined && last[p] !== undefined && first[p] !== last[p])
      .map((p) => `${p} ${first[p]} → ${last[p]}`);
    const repeat = value.iterations === "infinite" ? "repeats forever" : Number(value.iterations) > 1 ? `plays ${value.iterations} times` : "plays once";
    const direction = value.direction.startsWith("alternate") ? ", alternating" : "";
    entries.push({
      className: `brand-motion-${slug}`, token, kind: "animation",
      css: `@keyframes brand-kf-${slug}{${frames.join("")}}`
        + `@media (prefers-reduced-motion:no-preference){.brand-motion-${slug}{animation:brand-kf-${slug} ${duration} ${easing} ${delay} ${value.iterations} ${value.direction} ${value.fill_mode}}}`,
      describe: `${changes.join(", ")}; ${repeat}${direction}`,
      timing: `${seconds(duration)} ${easing}`,
      where: (brand.kit as { tokens?: { styles?: Record<string, { description?: string | null }> } }).tokens?.styles?.[token]?.description ?? "",
    });
  }
  for (const token of motion?.reveals ?? []) {
    const value = styleOf(brand, token);
    if (value?.kind !== "reveal") continue;
    const slug = token.replace(/^motion\.reveal\./, "");
    const easing = easingOf(brand, value.easing);
    const opacity = value.from_opacity ? ratioOf(brand, value.from_opacity) : undefined;
    const transform = value.from_transform ? transformOf(brand, value.from_transform) : undefined;
    if (!easing || !/^[0-9a-f]{8}$/.test(slug) || (opacity === undefined && !transform)) continue;
    const from = [opacity !== undefined ? `opacity:${opacity}` : "", transform ? `transform:${transform}` : ""].filter(Boolean).join(";");
    const said = [opacity !== undefined ? `fades in from opacity ${opacity}` : "", describeMove(transform ?? null)].filter(Boolean).join(" and ");
    entries.push({
      className: `brand-motion-reveal-${slug}`, token, kind: "reveal",
      css: `@keyframes brand-kf-reveal-${slug}{from{${from}}}`
        + `@supports (animation-timeline:view()){@media (prefers-reduced-motion:no-preference){.brand-motion-reveal-${slug}{animation:brand-kf-reveal-${slug} ${easing} both;animation-timeline:view();animation-range:entry 0% entry 100%}}}`,
      describe: `${said} as it scrolls into view`,
      timing: easing,
      where: (brand.kit as { tokens?: { styles?: Record<string, { description?: string | null }> } }).tokens?.styles?.[token]?.description ?? "",
    });
  }
  return entries;
}

export const motionClassNames = (brand: BrandData) => motionEntries(brand).map((entry) => entry.className);

/** Motion the seller's site has that a script-free page cannot carry: named, never reproduced. */
export const motionNotes = (brand: BrandData) => measuredComponents(brand)?.motion?.scripted ?? [];
```

- [ ] **Step 7: Rewrite `src/theme.ts`.**

```ts
// Brand kit -> one theme stylesheet (Wave 2 A9).
//
// Per-brand values are emitted as `--brand-*` custom properties on `.brand-root`; tailwindThemeCss()
// maps them into Tailwind v4 theme variables (`@theme inline`), so sections use fixed class names
// (`text-headline`, `bg-surface-brand`, `py-section`) and the brand decides the values. Buttons,
// cards, links and motion are drawn from the kit's measured recipes (looks.ts). Every value is the
// kit's (brand-values.ts) or one of FALLBACKS; clones keep their own captured CSS.
import type { BrandData } from "./brand";
import {
  FALLBACKS, alphaOf, colorOf, contrast, fluid, fontStack, hexOf, isComponentToken, isMeasured, numberOf,
  pxOf, ratioOf, tokenEntry, tokenGroups, trim, typographyOf,
} from "./brand-values";
import {
  STATES, buttonLooks, cardLooks, drawnButton, drawnCard, drawnLink, elementStyle, motionEntries,
  partsFromSlots, transitionsOf, type Drawn, type Look, type Part, type Parts, type State,
} from "./looks";
import { COLOR_ROLES, SURFACES, colorVar, extraSurfaceRoles, inkRole, isDarkSurface, surfaceRoles } from "./surfaces";

export { COLOR_ROLES, SURFACES, colorVar, extraSurfaceRoles, surfaceRoles };

export const TYPE_ROLES = [
  "display", "headline", "title", "subtitle", "body", "body.small",
  "eyebrow", "cta", "stat", "label", "caption", "legal",
] as const;
export const RADIUS_ROLES = ["none", "xs", "sm", "md", "lg", "xl", "card", "button", "badge", "full"] as const;
/** The kit's named spacing, as Tailwind utilities (`py-section`, `mt-stack-tight`, `p-card-padding`). */
export const SPACING_ROLES = ["section", "page.margin", "stack.tight", "stack.default", "stack.loose", "card.padding"] as const;
export const typeVar = (role: string) => role.replace(/\./g, "-");
export const spacingVar = typeVar;

const STATE_SELECTOR: Record<State, string> = { hover: ":hover", pressed: ":active", focus: ":focus-visible", disabled: '[aria-disabled="true"]' };
const CSS_OF: Record<Part, string> = {
  fill: "background-color", label: "color", border: "border-color", borderWidth: "border-width", borderStyle: "border-style",
  radius: "border-radius", padding: "padding", height: "min-height", gap: "gap", fontFamily: "font-family",
  fontSize: "font-size", fontWeight: "font-weight", lineHeight: "line-height", tracking: "letter-spacing",
  case: "text-transform", decoration: "text-decoration-line", decorationThickness: "text-decoration-thickness",
  underlineOffset: "text-underline-offset", shadow: "box-shadow", opacity: "opacity", transform: "transform",
  filter: "filter", cursor: "cursor", outlineColor: "outline-color", outlineWidth: "outline-width",
  outlineStyle: "outline-style", outlineOffset: "outline-offset", iconColor: "color", iconTransform: "transform",
  iconOpacity: "opacity",
};
const ICON_PARTS = new Set<Part>(["iconColor", "iconTransform", "iconOpacity"]);
const OUTLINE_PARTS = new Set<Part>(["outlineColor", "outlineWidth", "outlineStyle", "outlineOffset"]);
type Swap = Partial<Record<"fill" | "label" | "border", string>>;
type Swaps = { parts: Set<Part>; bySurface: Map<string, Swap> };

function body(props: Record<string, string | undefined>): string {
  return Object.entries(props).filter(([, v]) => v !== undefined && v !== "").map(([k, v]) => `${k}:${v}`).join(";");
}
function rule(selector: string, props: Record<string, string | undefined>): string {
  const text = body(props);
  return text ? `${selector}{${text}}` : "";
}

/** CSS declarations for a set of parts: the box's and its icon's. A colour that a dark surface swaps
 * reads that surface's value first (`--bs-<id>-<part>`), so the NEAREST surface decides. Outlines are
 * drawn on :focus-visible only, so a look with no focus style leaves the browser's ring alone. */
function declarations(parts: Parts, opts: { swaps?: Swaps; id?: string; outline?: boolean } = {}) {
  const box: Record<string, string> = {};
  const icon: Record<string, string> = {};
  for (const [part, value] of Object.entries(parts) as [Part, string][]) {
    if (OUTLINE_PARTS.has(part) && !opts.outline) continue;
    const css = opts.swaps?.parts.has(part) ? `var(--bs-${opts.id}-${part},${value})` : value;
    (ICON_PARTS.has(part) ? icon : box)[CSS_OF[part]] = css;
  }
  return { box, icon };
}

/** Where a button would not stand out on a dark surface (text 4.5:1, WCAG 1.4.3; a filled shape 3:1,
 * WCAG 1.4.11): outline and text-only styles take the surface's text colour; filled styles take the
 * light version (the kit's page colour with its text colour). */
function buttonSwaps(brand: BrandData, drawn: Drawn, dark: string[]): Swaps {
  const swaps: Swaps = { parts: new Set(), bySurface: new Map() };
  const fill = drawn.parts.fill;
  const clear = !fill || fill === "transparent" || (fill.startsWith("#") && alphaOf(fill) === 0);
  for (const surface of dark) {
    const bg = hexOf(brand, surface);
    if (!bg) continue;
    const on = `var(--brand-on-${colorVar(surface)})`;
    let swap: Swap | null = null;
    const label = drawn.parts.label;
    if (clear && label?.startsWith("#") && contrast(label.slice(0, 7), bg) < 4.5) {
      swap = { label: on, ...(drawn.parts.border === label ? { border: on } : {}) };
    } else if (!clear && fill?.startsWith("#") && contrast(fill.slice(0, 7), bg) < 3) {
      swap = {
        fill: "var(--brand-button-light-fill)", label: "var(--brand-button-light-label)",
        ...(drawn.parts.border ? { border: "var(--brand-button-light-fill)" } : {}),
      };
    }
    if (!swap) continue;
    swaps.bySurface.set(surface, swap);
    for (const part of Object.keys(swap) as Part[]) swaps.parts.add(part);
  }
  return swaps;
}

export function themeCss(brand: BrandData): string {
  const lines: string[] = [];
  for (const face of brand.fonts) {
    lines.push(`@font-face{font-family:"${face.family}";src:url("${face.file}");font-weight:${face.weight ?? 400};font-style:${face.style};font-display:swap}`);
  }

  const root: Record<string, string> = {};
  // Every colour of the kit, except the minted component colours (drawn inline below).
  for (const role of Object.keys(tokenGroups(brand).colors ?? {})) {
    const value = isComponentToken(role) ? undefined : colorOf(brand, role);
    if (value) root[`--brand-${colorVar(role)}`] = value;
  }
  for (const role of TYPE_ROLES) {
    const style = typographyOf(brand, `type.${role}`);
    if (!style) continue;
    const name = typeVar(role);
    root[`--brand-font-${name}`] = fontStack(brand, style);
    root[`--brand-text-${name}`] = fluid(style.size);
    if (style.lineHeight !== null) root[`--brand-text-${name}-lh`] = trim(style.lineHeight);
    root[`--brand-text-${name}-weight`] = String(style.weight);
    if (style.letterSpacing !== null) root[`--brand-text-${name}-tracking`] = `${trim(style.letterSpacing)}em`;
  }
  for (const role of RADIUS_ROLES) {
    const value = pxOf(brand, `radius.${role}`);
    if (value) root[`--brand-radius-${role}`] = value;
  }
  for (const role of SPACING_ROLES) {
    const value = numberOf(brand, `space.${role}`);
    if (value && value.unit === "px") root[`--brand-space-${spacingVar(role)}`] = fluid(value.value);
  }
  const surfaces = surfaceRoles(brand);
  for (const surface of surfaces) {
    const ink = inkRole(brand, surface);
    if (ink && colorOf(brand, ink)) root[`--brand-on-${colorVar(surface)}`] = `var(--brand-${colorVar(ink)})`;
  }
  root["--brand-content-width"] = FALLBACKS.contentWidth;
  root["--brand-rule-width"] = pxOf(brand, "stroke.width.divider") ?? FALLBACKS.ruleWidth;
  root["--brand-button-light-fill"] = "var(--brand-surface-page)";
  root["--brand-button-light-label"] = "var(--brand-on-surface-page)";

  // Per surface: type colours, the rule colour, and every swap a dark surface needs.
  const dark = surfaces.filter((surface) => isDarkSurface(brand, surface));
  const local = new Map<string, Record<string, string>>(surfaces.map((surface) => [surface, {}]));
  const mutedShare = ratioOf(brand, "opacity.muted");
  for (const surface of surfaces) {
    const vars = local.get(surface)!;
    const isDark = dark.includes(surface);
    for (const role of TYPE_ROLES) {
      const colorRole = typographyOf(brand, `type.${role}`)?.color;
      const usable = !isDark && !!colorRole && !!colorOf(brand, colorRole) && isMeasured(tokenEntry(brand, "colors", colorRole));
      vars[`--brand-ink-role-${typeVar(role)}`] = usable ? `var(--brand-${colorVar(colorRole!)})` : "initial";
    }
    vars["--brand-rule-color"] = isDark
      ? mutedShare ? `color-mix(in srgb, currentColor ${trim(Number(mutedShare) * 100)}%, transparent)` : "currentColor"
      : colorOf(brand, "border.subtle") ? "var(--brand-line-subtle)" : "currentColor";
  }
  const buttons: { id: string; selector: string; drawn: Drawn; look: Look | null }[] = [
    { id: "std", selector: ".brand-btn", drawn: drawnButton(brand, null), look: null },
    ...buttonLooks(brand).map((look) => ({ id: String(look.index), selector: `.brand-btn.brand-look-${look.index}`, drawn: drawnButton(brand, look), look })),
  ];
  const swaps = new Map(buttons.map((b) => [b.id, buttonSwaps(brand, b.drawn, dark)]));
  const link = drawnLink(brand, "link");
  const linkSwap = new Map<string, string>();
  for (const surface of dark) {
    const bg = hexOf(brand, surface);
    const color = link.parts.label;
    if (bg && color?.startsWith("#") && contrast(color.slice(0, 7), bg) < 4.5) linkSwap.set(surface, `var(--brand-on-${colorVar(surface)})`);
  }
  for (const surface of surfaces) {
    const vars = local.get(surface)!;
    for (const [id, s] of swaps) for (const part of s.parts) vars[`--bs-${id}-${part}`] = s.bySurface.get(surface)?.[part as keyof Swap] ?? "initial";
    if (linkSwap.size) vars["--bs-link-color"] = linkSwap.get(surface) ?? "initial";
  }

  lines.push(rule(".brand-root", { ...root, ...(local.get("surface.page") ?? {}) }));
  for (const surface of surfaces) lines.push(rule(`.bg-${colorVar(surface)}`, local.get(surface)!));
  for (const role of TYPE_ROLES) lines.push(`.brand-ink-${typeVar(role)}{color:var(--brand-ink-role-${typeVar(role)},currentColor)}`);
  lines.push(
    ".brand-heading{color:var(--brand-ink-role-headline,currentColor)}",
    ".brand-rule-t{border-top:var(--brand-rule-width) solid var(--brand-rule-color)}",
    ".brand-rule-b{border-bottom:var(--brand-rule-width) solid var(--brand-rule-color)}",
    ".brand-rule-v{align-self:stretch;width:var(--brand-rule-width);background-color:var(--brand-rule-color)}",
    ".brand-content{max-width:var(--brand-content-width);margin-inline:auto}",
    `.brand-logo-header{height:${FALLBACKS.headerLogoHeight}}`,
    `.brand-logo-footer{height:${FALLBACKS.footerLogoHeight}}`,
  );

  // Components live in the components layer so Tailwind utilities (hidden, sm:inline-flex…) can
  // still override them, as they would any component class.
  const components: string[] = [".brand-btn-icon{display:inline-flex}"];
  for (const b of buttons) {
    const s = swaps.get(b.id)!;
    const rest = declarations(b.drawn.parts, { swaps: s, id: b.id });
    const layout = b.look ? {} : { display: "inline-flex", "align-items": "center", "justify-content": "center", "white-space": "nowrap" };
    components.push(rule(b.selector, { ...layout, ...rest.box, transition: transitionsOf(brand, b.look?.measured, "box") }));
    components.push(rule(`${b.selector} .brand-btn-icon`, { ...rest.icon, transition: transitionsOf(brand, b.look?.measured, "icon") }));
    if (!b.look) {
      const disabled = ratioOf(brand, "opacity.disabled");
      if (disabled) components.push(rule(`${b.selector}[aria-disabled="true"]`, { opacity: disabled }));
      continue;
    }
    for (const state of STATES) {
      const parts = partsFromSlots(brand, b.look.measured?.states?.[state]).parts;
      const drawn = declarations(parts, { swaps: s, id: b.id, outline: state === "focus" });
      components.push(rule(`${b.selector}${STATE_SELECTOR[state]}`, drawn.box), rule(`${b.selector}${STATE_SELECTOR[state]} .brand-btn-icon`, drawn.icon));
    }
  }
  components.push(rule(".brand-card", { display: "block", ...declarations(drawnCard(brand, null).parts).box }));
  for (const look of cardLooks(brand)) {
    const selector = `.brand-card.brand-card-look-${look.index}`;
    components.push(rule(selector, { ...declarations(drawnCard(brand, look).parts).box, transition: transitionsOf(brand, look.measured, "box") }));
    for (const state of ["hover", "pressed", "focus"] as State[]) {
      const parts = partsFromSlots(brand, look.measured?.states?.[state]).parts;
      components.push(rule(`a${selector}${STATE_SELECTOR[state]}`, declarations(parts, { outline: state === "focus" }).box));
    }
  }
  const linkParts: Parts = { ...link.parts };
  const linkDecl = declarations(linkParts).box;
  if (linkParts.label) linkDecl.color = linkSwap.size ? `var(--bs-link-color,${linkParts.label})` : linkParts.label;
  components.push(rule(".brand-link", { ...linkDecl, transition: transitionsOf(brand, link.style, "box") }));
  const nav = drawnLink(brand, "nav_link");
  components.push(rule(".brand-navlink", { ...declarations(nav.parts).box, transition: transitionsOf(brand, nav.style, "box") }));
  for (const [selector, style] of [[".brand-link", elementStyle(brand, "link")], [".brand-navlink", elementStyle(brand, "nav_link")]] as const) {
    for (const state of ["hover", "pressed", "focus"] as State[]) {
      const parts = partsFromSlots(brand, style?.states?.[state]).parts;
      const decl = declarations(parts, { outline: state === "focus" }).box;
      if (selector === ".brand-link" && parts.label && linkSwap.size) decl.color = `var(--bs-link-color,${parts.label})`;
      components.push(rule(`${selector}${STATE_SELECTOR[state]}`, decl));
    }
  }
  lines.push(`@layer components{${components.filter(Boolean).join("")}}`);

  for (const entry of motionEntries(brand)) lines.push(entry.css);
  lines.push(
    '@media (prefers-reduced-motion:reduce),print{.brand-btn,.brand-btn-icon,.brand-link,.brand-navlink,.brand-card{transition:none!important}[class*="brand-motion-"]{animation:none!important}}',
  );
  return lines.filter(Boolean).join("\n");
}

/** The Tailwind v4 mapping of the `--brand-*` variables this theme emits, as one `@theme inline`
 * block (per brand: the kit's extra surfaces and spacing add utilities). The design API's server CSS
 * compile prepends `@import "tailwindcss";` and compiles it over a site's rendered HTML (Task 17). */
export function tailwindThemeCss(brand: BrandData): string {
  const lines: string[] = [];
  for (const surface of surfaceRoles(brand)) lines.push(`--color-on-${colorVar(surface)}: var(--brand-on-${colorVar(surface)});`);
  for (const role of [...COLOR_ROLES, ...extraSurfaceRoles(brand)]) lines.push(`--color-${colorVar(role)}: var(--brand-${colorVar(role)});`);
  for (const role of TYPE_ROLES) {
    const name = typeVar(role);
    lines.push(
      `--font-${name}: var(--brand-font-${name});`,
      `--text-${name}: var(--brand-text-${name});`,
      `--text-${name}--line-height: var(--brand-text-${name}-lh);`,
      `--text-${name}--font-weight: var(--brand-text-${name}-weight);`,
      `--text-${name}--letter-spacing: var(--brand-text-${name}-tracking);`,
    );
  }
  for (const role of RADIUS_ROLES) lines.push(`--radius-${role}: var(--brand-radius-${role});`);
  for (const role of SPACING_ROLES) {
    if (numberOf(brand, `space.${role}`)) lines.push(`--spacing-${spacingVar(role)}: var(--brand-space-${spacingVar(role)});`);
  }
  return `@theme inline {\n${lines.map((line) => `  ${line}`).join("\n")}\n}\n`;
}
```

- [ ] **Step 8: Export the new names.** In `src/index.ts`, replace `export { themeCss } from "./theme";` with:

```ts
export { FALLBACKS, isComponentToken } from "./brand-values";
export { extraSurfaceRoles, surfaceChoices, surfaceLabels, surfaceRoles, type SurfaceChoice } from "./surfaces";
export { buttonLookOptions, buttonLooks, cardLooks, motionClassNames, motionEntries, type Look } from "./looks";
export { SPACING_ROLES, tailwindThemeCss, themeCss } from "./theme";
```

- [ ] **Step 9: Run the tests and the type check.**

Run: `cd apps/frontend/packages/site-kit && npx tsx --test test/*.test.ts && cd ../.. && npm run typecheck -w @clue/site-kit`
Expected: the new tests pass; every older test still passes (the older brand.md test still reads
`brand.measured`, which is untouched until Task 7); no type errors.

- [ ] **Step 10: Commit.**

```bash
git add apps/frontend/packages/site-kit/src/brand-values.ts apps/frontend/packages/site-kit/src/surfaces.ts \
  apps/frontend/packages/site-kit/src/looks.ts apps/frontend/packages/site-kit/src/theme.ts apps/frontend/packages/site-kit/src/index.ts \
  apps/frontend/packages/site-kit/test/fixtures/kits.ts apps/frontend/packages/site-kit/test/looks.test.ts apps/frontend/packages/site-kit/test/theme.test.ts
git commit -m "site-kit theme: buttons, cards, links, surfaces, type colours, spacing and motion drawn from the kit's measured tokens, then its tokens, then named fallbacks"
```

### Task 5: Our sections, the shell and the agent kit draw only kit classes; `buttonLook`, the brand's surfaces, and a guard against new literals

This replaces Lane A's Task 5 (it keeps whole logos, `kit.Link`, `fit="contain"`, `logoFiles`,
`makeKit(href, brand)` and the kit's extra surfaces) and carries the schema, field and validator
changes of founder rulings 4 and 6 and Q4 = (b).

**Files:**
- Rewrite: `apps/frontend/packages/site-kit/src/sections.tsx`, `src/shell.tsx`, `src/agent-kit.tsx`
- Modify: `apps/frontend/packages/site-kit/src/schemas.ts` (`Surface`, FeatureSplit, CtaBand, the shell header)
- Modify: `apps/frontend/packages/site-kit/src/config.tsx` (`makeKit(href, brand)`, the header's
  fields, the clone placeholder, `TokenProbe` removed)
- Modify: `apps/frontend/packages/site-kit/src/validate.ts` (surfaces and looks are the brand's)
- Modify: `apps/frontend/packages/site-kit/src/catalog.ts` (`sectionsFile(brand)`)
- Modify: `apps/frontend/packages/site-kit/src/index.ts`, `package.json` (`test` script)
- Create: `apps/frontend/packages/site-kit/test/agent-kit.test.tsx`, `test/sections.test.tsx`,
  `test/style-literals.test.ts`
- Modify: `apps/frontend/packages/site-kit/test/contracts.test.ts:47-54`, `test/catalog.test.ts:46-53`

**Interfaces:**
- `schemas.ts`: `Surface = z.string().min(1)` (a choice name; the validator checks it against the
  brand); `FeatureSplitSchema.buttonLook`, `CtaBandSchema.buttonLook` = `z.string().default("")`;
  shell `header.ctaLook = z.string().default("")` (Q-A9-1 (a)). Stored sites keep working: every
  stored surface is one of the six, and the new fields default.
- `sections.tsx`: `type AnySurface`, `surfaceClass(surface)`, `Button({brand, label, href, surface, look?, disabled?})`.
- `shell.tsx`: `logoFiles(brand)`; `HeaderProps.ctaLook?`.
- `agent-kit.tsx`: `Kit = {Shell, Button{look?, disabled?}, Card{look?, href?}, Eyebrow, Link, Image{fit?}}`, `makeKit(href, brand)`.
- `validate.ts` refusals T-A9-3 (surface, button style).
- Puck fields: `surface` select over `surfaceChoices(brand)`; `buttonLook` "Button style" select over
  `buttonLookOptions(brand)`, left out when the brand has no button styles (T-A9-7). Lane C's dock
  receives them through `describeField` (`select` → `FieldDescription.options`) with no code change.

- [ ] **Step 1: Confirm T-A9-2, T-A9-3 and T-A9-7 were approved** (sections.md rows, the two
  validator refusals for our sections, the dock's labels and label rule).

- [ ] **Step 2: Write the failing tests.** `test/agent-kit.test.tsx`:

```tsx
// The agent kit (Wave 2 A9): logos whole, looks by name, the seller's own icon, links and cards drawn
// like the seller's, and any of the brand's surfaces.
import assert from "node:assert/strict";
import { test } from "node:test";
import type { ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { makeKit } from "../src/agent-kit";
import { colorOf } from "../src/brand-values";
import { buttonLooks, cardLooks } from "../src/looks";
import { logoFiles } from "../src/shell";
import { garner } from "./fixtures/garner";
import { kitBrand } from "./fixtures/kits";

const href = (value: string) => (value.startsWith("/") && !value.startsWith("//") ? `/s/x${value === "/" ? "" : value}` : value);
const html = (node: ReactNode) => renderToStaticMarkup(<>{node}</>);

test("a logo from the kit is shown whole; fit decides for every other image", () => {
  const brand = garner();
  const kit = makeKit(href, brand);
  const logo = [...logoFiles(brand)][0];
  assert.match(html(kit.Image({ src: logo })), /class="h-full w-full object-contain"/);
  const photo = Object.values(brand.assets).find((asset) => asset.kind === "raster_image" && !logoFiles(brand).has(asset.file))!.file;
  assert.match(html(kit.Image({ src: photo })), /class="w-full rounded-card object-cover"/);
  assert.match(html(kit.Image({ src: photo, fit: "contain" })), /class="h-full w-full object-contain"/);
  assert.match(html(kit.Image({ src: photo, fit: "fill" })), /class="absolute inset-0 h-full w-full object-cover"/);
});

test("a button is the standard button or a look by name, with no arrow of site-kit's own", () => {
  const brand = kitBrand("garner.minted");
  const kit = makeKit(href, brand);
  const standard = html(kit.Button({ label: "Request the analysis", href: "/analysis", surface: "page" }));
  assert.ok(standard.includes('href="/s/x/analysis"') && standard.includes('class="brand-btn"'), standard);
  assert.ok(!standard.includes("→"), standard);
  const outline = buttonLooks(brand).find((look) => look.name === "outline.1")!;
  assert.ok(html(kit.Button({ label: "See how", href: "/", surface: "page", look: "outline.1" })).includes(`class="brand-btn brand-look-${outline.index}"`));
  assert.ok(html(kit.Button({ label: "x", href: "/", surface: "page", look: "solid.9" })).includes('class="brand-btn"'), "an unknown look draws the standard button");
  const disabled = html(kit.Button({ label: "Soon", href: "/", surface: "page", disabled: true }));
  assert.ok(disabled.includes('aria-disabled="true"') && !disabled.includes("href="), disabled);
});

test("a look draws the seller's own icon where the site has one", () => {
  const brand = kitBrand("probe.minted");
  const kit = makeKit(href, brand);
  const solid = buttonLooks(brand).find((look) => colorOf(brand, look.measured?.rest.fill) === "#047464")!;
  const markup = html(kit.Button({ label: "Go", href: "/", surface: "page", look: solid.name }));
  assert.match(markup, /<span class="brand-btn-label">Go<\/span><span aria-hidden="true" class="brand-btn-icon"><svg [^>]*viewBox="0 0 12 12"/);
  const outline = buttonLooks(brand).find((look) => look.name === "outline.1")!;
  assert.ok(html(kit.Button({ label: "More", href: "/", surface: "page", look: outline.name })).includes('<span aria-hidden="true" class="brand-btn-icon">→</span>'));
});

test("kit.Link and kit.Card are drawn like the seller's links and cards", () => {
  const brand = kitBrand("probe.minted");
  const kit = makeKit(href, brand);
  assert.equal(html(kit.Link({ href: "/analysis", children: "Read" })), '<a href="/s/x/analysis" class="brand-link">Read</a>');
  const card = cardLooks(brand)[0];
  assert.equal(html(kit.Card({ look: card.name, children: "x" })), `<div class="brand-card brand-card-look-${card.index}">x</div>`);
  assert.equal(html(kit.Card({ href: "#proof", children: "x" })), '<a href="#proof" class="brand-card">x</a>');
});

test("a section may stand on any of the brand's surfaces by its choice name", () => {
  const kit = makeKit(href, kitBrand("garner.minted"));
  assert.ok(html(kit.Shell({ surface: "band-014036", children: "x" })).includes('class="bg-surface-band-014036 text-on-surface-band-014036"'));
  assert.ok(html(kit.Shell({ surface: "brandSubtle", children: "x" })).includes('class="bg-surface-brand-subtle text-on-surface-brand-subtle"'));
});
```
  `test/sections.test.tsx`:

```tsx
// Our sections take the brand's surfaces and button styles by name (founder rulings 4, 6; Q4 = (b)).
import assert from "node:assert/strict";
import { test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { lookNamed } from "../src/looks";
import { makeConfig } from "../src/config";
import { makeSections } from "../src/sections";
import { validateSite } from "../src/validate";
import { garner, site } from "./fixtures/garner";
import { kitBrand } from "./fixtures/kits";

const href = (v: string) => v;
type Field = { label: string; options?: { label: string; value: string }[] };
const fields = (brand: ReturnType<typeof kitBrand>) => makeSections(brand, href).FeatureSplit.fields as unknown as Record<string, Field>;

test("the Button style field lists Standard and then this brand's styles, by kind", () => {
  assert.deepEqual(fields(kitBrand("garner")).buttonLook.options!.map((o) => o.label), ["Standard", "Outline", "Text only", "Filled 1", "Filled 2", "Filled 3", "Filled 4"]);
  assert.equal(fields(kitBrand("garner")).buttonLook.label, "Button style");
  const bare = kitBrand("garner");
  (bare.kit as { brief: { component_recipes: unknown[] } }).brief.component_recipes = [];
  assert.equal(fields(bare).buttonLook, undefined, "nothing to choose: no field");
  assert.ok((makeSections(kitBrand("garner"), href).CtaBand.fields as unknown as Record<string, Field>).buttonLook);
});

test("the Surface field lists the six and then this brand's other surfaces", () => {
  const options = fields(kitBrand("garner.minted")).surface.options!;
  assert.deepEqual(options.slice(0, 6).map((o) => o.label), ["Page", "Card", "Muted", "Brand, subtle", "Brand", "Inverse"]);
  assert.ok(options.some((o) => o.value === "band-014036" && o.label === "Dark band"));
});

test("a FeatureSplit draws the look it names", () => {
  const brand = kitBrand("conduit.minted");
  const index = lookNamed(brand, "button", "solid.2")!.index;
  const split = makeSections(brand, href).FeatureSplit;
  const markup = renderToStaticMarkup(
    <>{split.render({ id: "f", surface: "page", eyebrow: "", heading: "H", headingRole: "title", body: "B", image: "", imageSide: "left", buttonLabel: "Book a demo", buttonHref: "/", buttonLook: "solid.2" } as never)}</>,
  );
  assert.ok(markup.includes(`class="brand-btn brand-look-${index}"`), markup);
});

test("the shell header's button takes a look too", () => {
  const config = makeConfig(kitBrand("garner"), { mode: "shell" }) as unknown as { components: { SiteHeader: { fields: Record<string, Field> } } };
  assert.equal(config.components.SiteHeader.fields.ctaLook.label, "Button style");
});

test("the validator holds surfaces and looks to this brand's", () => {
  const brand = garner();
  const pages = structuredClone(site("garner-syracuse").pages) as Record<string, { content: { type: string; props: Record<string, unknown> }[] }>;
  const split = { type: "CtaBand", props: { id: "cta-check", surface: "canvas", heading: "H", body: "", buttonLabel: "Go", buttonHref: "/", buttonLook: "outline.1" } };
  pages["/"].content.push(split);
  const shell = site("garner-syracuse").shell;
  assert.equal(validateSite({ pages, shell }, brand, {}).valid, true, validateSite({ pages, shell }, brand, {}).errors.join("\n"));
  split.props.buttonLook = "solid.9";
  split.props.surface = "green";
  const errors = validateSite({ pages, shell }, brand, {}).errors;
  assert.ok(errors.some((e) => e.endsWith(`.buttonLook: "solid.9" is not one of this brand's button styles; its styles are outline.1, ghost.1, solid.1, solid.2, solid.3, solid.4, or leave it empty for the standard button (brand/brand.md, Buttons)`)), errors.join("\n"));
  assert.ok(errors.some((e) => e.includes('.surface: "green" is not one of this brand\'s surfaces; its surfaces are page, card, muted, brandSubtle, brand, inverse, canvas,')), errors.join("\n"));
});
```
  `test/style-literals.test.ts`:

```ts
// No component in site-kit carries a style value of its own (founder, 2026-10-12): every class in a
// component file is structure (layout) or the brand's (theme.ts and its Tailwind mapping), and the
// only literal colours and lengths in site-kit are its named FALLBACKS (src/brand-values.ts).
import assert from "node:assert/strict";
import fs from "node:fs";
import { test } from "node:test";

const read = (file: string) => fs.readFileSync(new URL(`../src/${file}`, import.meta.url), "utf-8");
const COMPONENTS = ["sections.tsx", "shell.tsx", "agent-kit.tsx", "config.tsx"];
const GENERATORS = ["theme.ts", "looks.ts", "surfaces.ts", "brand-values.ts"];

/** Layout: where things go, never how the brand looks. */
const STRUCTURE = [
  /^(flex|inline-flex|grid|block|inline-block|inline|hidden|contents)$/,
  /^flex-(row|col|wrap|1|none)$/, /^(grow|shrink-0|min-w-0)$/, /^self-(start|center|end)$/,
  /^grid-cols-(\d+|\[[0-9a-z(),_.]+\])$/, /^order-\d+$/,
  /^items-(start|center|end|baseline|stretch)$/, /^justify-(start|center|end|between)$/,
  /^text-(left|center|right)$/, /^(truncate|whitespace-nowrap|sr-only)$/,
  /^(w|h)-(full|auto)$/, /^max-w-\[\d+ch\]$/, /^mx-auto$/,
  /^(relative|absolute|inset-0|overflow-hidden)$/, /^object-(cover|contain)$/,
  /^\[&>\*\]:mx-auto$/, /^\[&_dd\]:mx-auto$/,
  /^lumen-fragment$/, // a clone's wrapper: its own captured CSS styles it
];
/** The brand's: theme.ts classes and the Tailwind names mapped to kit values. */
const BRAND = [
  /^brand-[a-z0-9-]+$/, /^(bg-surface|text-on-surface)-[a-z0-9-]*$/, /^text-ink-[a-z]+$/,
  /^(font|text)-(display|headline|title|subtitle|body|body-small|eyebrow|cta|stat|label|caption|legal)$/,
  /^rounded-(none|xs|sm|md|lg|xl|card|button|badge|full)$/,
  /^(m|p)[xytrbl]?-(section|page-margin|stack-tight|stack-default|stack-loose|card-padding)$/,
  /^gap(-[xy])?-(section|page-margin|stack-tight|stack-default|stack-loose|card-padding)$/,
];
const RESPONSIVE = /^(sm|md|lg|xl|2xl):/;
const CLASS_TOKEN = /^[a-z0-9!\[\]&>*_:/.()%,-]+$/;

function strings(source: string): string[] {
  return [...source.matchAll(/"([^"\n]*)"|'([^'\n]*)'|`([^`]*)`/g)].flatMap((m) => (m[1] ?? m[2] ?? m[3] ?? "").split(/\$\{[^}]*\}/));
}

/** Every token of every string that reads as a class list (lower-case, hyphenated, no paths). */
function classTokens(source: string): string[] {
  return strings(source).flatMap((text) => {
    const tokens = text.split(/\s+/).filter(Boolean);
    const classLike = tokens.length > 0
      && tokens.every((t) => CLASS_TOKEN.test(t) && !t.startsWith("/") && !t.startsWith(".") && !t.startsWith("#") && !t.includes("//"))
      && tokens.some((t) => t.includes("-") || t.includes(":"));
    return classLike ? tokens : [];
  });
}

const allowed = (token: string) => [...STRUCTURE, ...BRAND].some((pattern) => pattern.test(token.replace(RESPONSIVE, "")));

test("every class in a component file is structure or the brand's", () => {
  const offenders = COMPONENTS.flatMap((file) => classTokens(read(file)).filter((t) => !allowed(t)).map((t) => `${file}: ${t}`));
  assert.deepEqual(offenders, []);
  assert.ok(classTokens(read("sections.tsx")).length > 40, "the scan sees the sections' classes");
});

test("no component writes an inline style, a colour or an arrow of its own", () => {
  for (const file of COMPONENTS) {
    const source = read(file);
    assert.doesNotMatch(source, /\bstyle=\{/, file);
    assert.doesNotMatch(source, /#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(/, file);
    assert.doesNotMatch(source, /→/, `${file}: an arrow is the seller's icon or the agent's words`);
  }
});

test("the only literal colours and lengths in site-kit are its named fallbacks", () => {
  const value = /(^|[^\w$])\d+(\.\d+)?(px|rem|em)\b|#[0-9a-fA-F]{3,8}\b|rgba?\(/;
  for (const file of GENERATORS) {
    let source = read(file);
    if (file === "brand-values.ts") source = source.replace(/export const FALLBACKS = \{[\s\S]*?\} as const;/, "");
    assert.deepEqual(strings(source).filter((text) => value.test(text)), [], file);
  }
});
```

- [ ] **Step 3: Run them to see them fail.**

Run: `cd apps/frontend/packages/site-kit && npx tsx --test test/agent-kit.test.tsx test/sections.test.tsx test/style-literals.test.ts`
Expected: FAIL — `makeKit` takes one argument, there is no `buttonLook` field, and the guard lists
`opacity-80`, `uppercase`, `py-16`, `font-semibold`, `border-current/20`, `opacity-70` … and the `→`
in `sections.tsx`.

- [ ] **Step 4: The schema.** In `src/schemas.ts`: replace `export const Surface = z.enum(SURFACES);` with

```ts
/** A surface by its choice name: one of our six, or one of this brand's other surfaces ("canvas",
 * "band-014036"). The validator checks it against the brand (founder Q4 = (b)). */
export const Surface = z.string().min(1);
/** A button style by its recipe's name ("outline.1"); empty is the kit's standard button. The
 * validator checks it against the brand (founder ruling 4). */
const buttonLook = z.string().default("");
```
  add `buttonLook,` after `buttonHref: optionalLink,` in `FeatureSplitSchema` and after
  `buttonHref: link,` in `CtaBandSchema`, and `ctaLook: buttonLook,` after `ctaHref: link,` in the
  shell header.

- [ ] **Step 5: Replace `src/sections.tsx`.**

```tsx
// Our own sections (Wave 2 A9). Every style choice is a name from the brand kit — a surface, a
// heading role, a button style — and every value is the kit's: the theme (theme.ts) draws buttons,
// links, type colours, spacing and rules from its measured tokens. No style value lives in this file
// (test/style-literals.test.ts). Text fields are `contentEditable`, so they edit in place on the canvas.
import type { ComponentConfig } from "@puckeditor/core";
import type { ReactNode } from "react";
import type { BrandData } from "./brand";
import { buttonLookOptions, lookIcon, lookNamed } from "./looks";
import { HEADING_ROLES } from "./schemas";
import { surfaceChoices } from "./surfaces";

export type Surface = "page" | "card" | "muted" | "brandSubtle" | "brand" | "inverse";
/** One of our six, or one of this brand's other surfaces by its choice name. */
export type AnySurface = Surface | (string & {});
export type HeadingRole = "display" | "headline" | "title";
type Text = string | ReactNode;

export const SURFACE_CLASS: Record<Surface, string> = {
  page: "bg-surface-page text-on-surface-page",
  card: "bg-surface-card text-on-surface-card",
  muted: "bg-surface-muted text-on-surface-muted",
  brandSubtle: "bg-surface-brand-subtle text-on-surface-brand-subtle",
  brand: "bg-surface-brand text-on-surface-brand",
  inverse: "bg-surface-inverse text-on-surface-inverse",
};

export function surfaceClass(surface: AnySurface): string {
  return SURFACE_CLASS[surface as Surface] ?? `bg-surface-${surface} text-on-surface-${surface}`;
}

const HEADING_CLASS: Record<HeadingRole, string> = {
  display: "font-display text-display brand-ink-display",
  headline: "font-headline text-headline brand-ink-headline",
  title: "font-title text-title brand-ink-title",
};

const headingRoleField = {
  type: "select" as const,
  label: "Heading size",
  options: HEADING_ROLES.map((value) => ({ label: value[0].toUpperCase() + value.slice(1), value })),
};
const text = (label: string) => ({ type: "text" as const, label, contentEditable: true });
const area = (label: string) => ({ type: "textarea" as const, label, contentEditable: true });

export const Shell = ({ surface, children }: { surface: AnySurface; children: ReactNode }) => (
  <section className={surfaceClass(surface)}>
    <div className="brand-content px-page-margin py-section">{children}</div>
  </section>
);

export const Eyebrow = ({ children }: { children: Text }) =>
  children ? <p className="font-eyebrow text-eyebrow brand-ink-eyebrow">{children}</p> : null;

/** The kit's standard button, or one of the brand's looks by name, with that look's own icon. */
export function Button({ brand, label, href, surface, look, disabled }: {
  brand: BrandData; label: Text; href: string; surface: AnySurface; look?: string; disabled?: boolean;
}) {
  if (!label) return null;
  const chosen = lookNamed(brand, "button", look);
  const icon = lookIcon(brand, chosen);
  const mark = icon
    ? icon.svg
      ? <span aria-hidden className="brand-btn-icon" dangerouslySetInnerHTML={{ __html: icon.svg }} />
      : <span aria-hidden className="brand-btn-icon">{icon.glyph}</span>
    : null;
  return (
    <a
      href={disabled ? undefined : href || "#"}
      aria-disabled={disabled || undefined}
      className={chosen ? `brand-btn brand-look-${chosen.index}` : "brand-btn"}
      data-surface={surface}
    >
      {icon?.position === "start" ? mark : null}
      <span className="brand-btn-label">{label}</span>
      {icon?.position === "end" ? mark : null}
    </a>
  );
}

export type Href = (value: string) => string;

export function makeSections(
  brand: BrandData,
  href: Href,
  AssetPicker?: (props: { assets: BrandData["assets"]; value: string; onChange: (v: string) => void }) => ReactNode,
) {
  const imageField = {
    type: "custom" as const,
    label: "Image (brand assets)",
    render: ({ value, onChange }: { value: string; onChange: (v: string) => void }) =>
      AssetPicker ? <AssetPicker assets={brand.assets} value={value} onChange={onChange} /> : <span />,
  };
  const surfaceField = {
    type: "select" as const,
    label: "Surface",
    options: surfaceChoices(brand).map((choice) => ({ label: choice.label, value: choice.value })),
  };
  const lookOptions = buttonLookOptions(brand);
  /** Left out when the brand has no button styles: there would be nothing to choose. */
  const buttonLookField = lookOptions.length > 1 ? { buttonLook: { type: "select" as const, label: "Button style", options: lookOptions } } : {};

  const StatsBand: ComponentConfig<{
    surface: AnySurface; align: "left" | "center"; eyebrow: Text; heading: Text; intro: Text;
    stats: { value: string; label: string }[]; source: Text;
  }> = {
    label: "Stats band",
    fields: {
      surface: surfaceField,
      align: { type: "radio", label: "Alignment", options: [{ label: "Left", value: "left" }, { label: "Centre", value: "center" }] },
      eyebrow: text("Eyebrow"), heading: text("Heading"), intro: area("Intro"),
      stats: {
        type: "array", label: "Stats", max: 4,
        arrayFields: { value: { type: "text" }, label: { type: "textarea" } },
        getItemSummary: (item: { value?: string }) => item.value || "Stat",
      },
      source: text("Source line"),
    } as never,
    defaultProps: {
      surface: "brandSubtle", align: "left", eyebrow: "", heading: "A headline about the result", intro: "",
      stats: [{ value: "7.4%", label: "What the number means" }], source: "",
    },
    render: ({ surface, align, eyebrow, heading, intro, stats, source }) => {
      const centered = align === "center";
      const columns = ["", "sm:grid-cols-1", "sm:grid-cols-2", "sm:grid-cols-3", "sm:grid-cols-2 lg:grid-cols-4"][stats.length] ?? "sm:grid-cols-3";
      return (
        <Shell surface={surface}>
          <div className={centered ? "mx-auto text-center [&>*]:mx-auto" : ""}>
            <Eyebrow>{eyebrow}</Eyebrow>
            <h2 className="mt-stack-tight max-w-[24ch] font-title text-title brand-ink-title">{heading}</h2>
            {intro ? <p className="mt-stack-default max-w-[60ch] font-body text-body brand-ink-body">{intro}</p> : null}
          </div>
          <dl className={`mt-stack-loose grid gap-stack-loose ${columns} ${centered ? "text-center [&_dd]:mx-auto" : ""}`}>
            {stats.map((stat, index) => (
              <div key={index} className="brand-rule-t pt-stack-default">
                <dt className="font-headline text-headline brand-ink-headline">{stat.value}</dt>
                <dd className="mt-stack-tight max-w-[32ch] font-body text-body brand-ink-body">{stat.label}</dd>
              </div>
            ))}
          </dl>
          {source ? <p className={`mt-stack-loose font-caption text-caption brand-ink-caption ${centered ? "text-center" : ""}`}>{source}</p> : null}
        </Shell>
      );
    },
  };

  const FeatureSplit: ComponentConfig<{
    surface: AnySurface; eyebrow: Text; heading: Text; headingRole: HeadingRole; body: Text;
    image: string; imageSide: "left" | "right"; buttonLabel: Text; buttonHref: string; buttonLook: string;
  }> = {
    label: "Feature split",
    fields: {
      surface: surfaceField, eyebrow: text("Eyebrow"), heading: text("Heading"),
      headingRole: headingRoleField, body: area("Body"), image: imageField,
      imageSide: { type: "radio", label: "Image side", options: [{ label: "Left", value: "left" }, { label: "Right", value: "right" }] },
      buttonLabel: text("Button label"), buttonHref: { type: "text", label: "Button link" }, ...buttonLookField,
    } as never,
    defaultProps: {
      surface: "page", eyebrow: "", heading: "What this does for them", headingRole: "title",
      body: "One or two plain sentences.", image: "", imageSide: "left", buttonLabel: "", buttonHref: "", buttonLook: "",
    },
    render: ({ surface, eyebrow, heading, headingRole, body, image, imageSide, buttonLabel, buttonHref, buttonLook }) => (
      <Shell surface={surface}>
        {/* No image: one text column, not an empty frame beside the words. */}
        <div className={image ? "grid items-center gap-stack-loose md:grid-cols-2" : "max-w-[60ch]"}>
          {image ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={image} alt="" className={`w-full rounded-card object-cover ${imageSide === "right" ? "md:order-2" : ""}`} />
          ) : null}
          <div>
            <Eyebrow>{eyebrow}</Eyebrow>
            <h2 className={`mt-stack-tight ${HEADING_CLASS[headingRole]}`}>{heading}</h2>
            <p className="mt-stack-default max-w-[52ch] font-body text-body brand-ink-body">{body}</p>
            <div className="mt-stack-loose">
              <Button brand={brand} label={buttonLabel} href={href(buttonHref)} surface={surface} look={buttonLook} />
            </div>
          </div>
        </div>
      </Shell>
    ),
  };

  const ProofCard: ComponentConfig<{
    surface: AnySurface; kicker: Text; metric: Text; metricLabel: Text; heading: Text; body: Text;
    source: Text; linkLabel: Text; linkHref: string;
  }> = {
    label: "Proof card",
    fields: {
      surface: surfaceField, kicker: text("Kicker (whose result)"), metric: text("Metric"),
      metricLabel: text("Metric label"), heading: text("Heading"), body: area("Body"),
      source: text("Source line"), linkLabel: text("Link label"), linkHref: { type: "text", label: "Link" },
    } as never,
    defaultProps: {
      surface: "card", kicker: "Customer or study", metric: "13%", metricLabel: "what changed",
      heading: "What they did", body: "", source: "", linkLabel: "", linkHref: "",
    },
    render: ({ surface, kicker, metric, metricLabel, heading, body, source, linkLabel, linkHref }) => (
      <Shell surface="page">
        <div className={`grid gap-stack-loose rounded-card p-card-padding md:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] ${surfaceClass(surface)}`}>
          <div>
            <Eyebrow>{kicker}</Eyebrow>
            <p className="mt-stack-default font-display text-display brand-ink-display">{metric}</p>
            <p className="mt-stack-tight font-body text-body brand-ink-body">{metricLabel}</p>
          </div>
          <div className="self-end">
            <h3 className="font-title text-title brand-ink-title">{heading}</h3>
            {body ? <p className="mt-stack-default font-body text-body brand-ink-body">{body}</p> : null}
            {source ? <p className="mt-stack-default font-caption text-caption brand-ink-caption">{source}</p> : null}
            {linkLabel ? (
              <a href={href(linkHref) || "#"} className="brand-link mt-stack-default inline-block font-cta text-cta">{linkLabel}</a>
            ) : null}
          </div>
        </div>
      </Shell>
    ),
  };

  const CtaBand: ComponentConfig<{
    surface: AnySurface; heading: Text; body: Text; buttonLabel: Text; buttonHref: string; buttonLook: string;
  }> = {
    label: "Call to action band",
    fields: {
      surface: surfaceField, heading: text("Heading"), body: area("Body"),
      buttonLabel: text("Button label"), buttonHref: { type: "text", label: "Button link" }, ...buttonLookField,
    } as never,
    defaultProps: { surface: "brand", heading: "The one next step", body: "", buttonLabel: "Get started", buttonHref: "", buttonLook: "" },
    render: ({ surface, heading, body, buttonLabel, buttonHref, buttonLook }) => (
      <Shell surface={surface}>
        <div className="mx-auto max-w-[60ch] text-center">
          <h2 className="font-headline text-headline brand-ink-headline">{heading}</h2>
          {body ? <p className="mt-stack-default font-body text-body brand-ink-body">{body}</p> : null}
          <div className="mt-stack-loose">
            <Button brand={brand} label={buttonLabel} href={href(buttonHref)} surface={surface} look={buttonLook} />
          </div>
        </div>
      </Shell>
    ),
  };

  return { StatsBand, FeatureSplit, ProofCard, CtaBand };
}
```

- [ ] **Step 6: Replace `src/shell.tsx`.**

```tsx
// The site shell: one campaign header and one footer, stored once per site and rendered around every
// page. "Prepared for <account>" sits beside the seller's logo, not under it. Every value is the
// kit's (theme.ts); the logo heights are site-kit's named fallbacks (the kit records logos, not the
// size a header shows them at).
import type { BrandData } from "./brand";
import { Button } from "./sections";

export type HeaderProps = {
  preparedFor: string;
  accountLogo: string;
  ctaLabel: string;
  ctaHref: string;
  /** A button style of the brand's (brand.md, Buttons); empty is the standard button. */
  ctaLook?: string;
  /** Links to the site's other pages; shown on wider screens beside the button. */
  nav?: { label: string; href: string }[];
};
export type FooterProps = { legal: string; privacyHref: string; termsHref: string };
export type ShellData = { header: HeaderProps; footer: FooterProps };

type Logos = Record<string, { variants: { name: string; asset_id: string }[] }>;

export function sellerLogo(brand: BrandData, variant: "primary" | "reversed" = "primary"): string | null {
  const logos = (brand.kit as { assets?: { logos?: Logos } }).assets?.logos ?? {};
  const primary = logos.primary?.variants ?? [];
  const pick =
    (variant === "reversed" && primary.find((v) => v.name === "reversed")) ||
    primary.find((v) => v.name !== "reversed") ||
    logos.mark?.variants?.[0];
  return pick ? brand.assets[pick.asset_id]?.file ?? null : null;
}

/** Every file of the kit's logos, all variants (mark, primary, reversed…). kit.Image shows these whole. */
export function logoFiles(brand: BrandData): Set<string> {
  const logos = (brand.kit as { assets?: { logos?: Logos } }).assets?.logos ?? {};
  const files = new Set<string>();
  for (const logo of Object.values(logos)) {
    for (const variant of logo?.variants ?? []) {
      const file = brand.assets[variant.asset_id]?.file;
      if (file) files.add(file);
    }
  }
  return files;
}

export function SiteHeader({ brand, header, href }: { brand: BrandData; header: HeaderProps; href: (v: string) => string }) {
  const logo = sellerLogo(brand);
  return (
    <header className="brand-rule-b bg-surface-page text-on-surface-page">
      <div className="brand-content flex items-center justify-between gap-stack-default px-page-margin py-stack-tight">
        <div className="flex min-w-0 items-center gap-stack-tight">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          {logo ? <img src={logo} alt="" className="brand-logo-header w-auto shrink-0" /> : null}
          <span aria-hidden className="brand-rule-v shrink-0" />
          {header.accountLogo ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={header.accountLogo} alt="" className="brand-logo-header w-auto shrink-0" />
          ) : null}
          <span className="min-w-0 truncate font-body text-body text-ink-secondary">
            <span className="hidden sm:inline">Prepared for </span>
            <span className="text-ink-primary">{header.preparedFor}</span>
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-stack-default">
          {header.nav?.length ? (
            <nav className="hidden items-center gap-stack-default md:flex">
              {header.nav.map((item) => (
                <a key={item.href + item.label} href={href(item.href)} className="brand-navlink">
                  {item.label}
                </a>
              ))}
            </nav>
          ) : null}
          {/* On phones the hero carries the same action, so the account name gets the room. */}
          <span className="hidden shrink-0 sm:inline-flex">
            <Button brand={brand} label={header.ctaLabel} href={href(header.ctaHref)} surface="page" look={header.ctaLook} />
          </span>
        </div>
      </div>
    </header>
  );
}

export function SiteFooter({ brand, footer, href }: { brand: BrandData; footer: FooterProps; href: (v: string) => string }) {
  const logo = sellerLogo(brand);
  return (
    <footer className="brand-rule-t bg-surface-page text-on-surface-page">
      <div className="brand-content flex flex-col gap-stack-default px-page-margin py-stack-loose md:flex-row md:items-center md:justify-between">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        {logo ? <img src={logo} alt="" className="brand-logo-footer w-auto self-start" /> : null}
        <p className="font-caption text-caption text-ink-muted">{footer.legal}</p>
        <div className="flex gap-stack-default font-caption text-caption">
          {footer.privacyHref ? <a href={href(footer.privacyHref)} className="brand-link">Privacy policy</a> : null}
          {footer.termsHref ? <a href={href(footer.termsHref)} className="brand-link">Terms</a> : null}
        </div>
      </div>
    </footer>
  );
}
```

- [ ] **Step 7: Replace `src/agent-kit.tsx`.**

```tsx
// The kit a section written by the agent (E5) builds with (Wave 2 A9): the same Shell, Button and
// Eyebrow our own sections use, plus Link and Card, so a new section takes the brand's surfaces,
// buttons, links, cards and motion exactly as the seller's site draws them. Image takes only files
// from the brand's assets (the validator checks the path); Link, Button and Card point a /route at
// wherever the site is served.
import type { ReactNode } from "react";
import type { BrandData } from "./brand";
import { lookNamed } from "./looks";
import { Button as BrandButton, Eyebrow, Shell, type AnySurface, type Href } from "./sections";
import { logoFiles } from "./shell";

export type Kit = {
  /** surface: any surface brand.md lists ("page", "canvas", "band-014036"). */
  Shell: (props: { surface: AnySurface; children: ReactNode }) => ReactNode;
  /** look: a button style brand.md lists (Buttons); none is the kit's standard button. */
  Button: (props: { label: string; href: string; surface: AnySurface; look?: string; disabled?: boolean }) => ReactNode;
  /** look: a card style brand.md lists (Cards); href makes the whole card a link. */
  Card: (props: { look?: string; href?: string; children: ReactNode }) => ReactNode;
  Eyebrow: (props: { children: ReactNode }) => ReactNode;
  /** A text link (an https:// URL, a /route of this site or a #anchor), drawn like the seller's links. */
  Link: (props: { href: string; children: ReactNode }) => ReactNode;
  /** fit="fill": covers its positioned parent (a background photo). fit="contain": the whole image
   * inside its box, never cropped or rounded (a logo). Neither: full width with the brand's corners.
   * A logo from the brand kit is always shown whole. */
  Image: (props: { src: string; alt?: string; fit?: "fill" | "contain"; className?: never }) => ReactNode;
};

export type AgentSectionModule = {
  schema: { safeParse: (value: unknown) => { success: boolean } };
  render: (props: never, kit: Kit) => ReactNode;
};

const IMAGE_CLASS = {
  fill: "absolute inset-0 h-full w-full object-cover",
  contain: "h-full w-full object-contain",
  standard: "w-full rounded-card object-cover",
} as const;

export function makeKit(href: Href, brand: BrandData): Kit {
  const logos = logoFiles(brand);
  return {
    Shell,
    Button: ({ label, href: target, surface, look, disabled }) => (
      <BrandButton brand={brand} label={label} href={href(target)} surface={surface} look={look} disabled={disabled} />
    ),
    Card: ({ look, href: target, children }) => {
      const chosen = lookNamed(brand, "card", look);
      const className = chosen ? `brand-card brand-card-look-${chosen.index}` : "brand-card";
      return target ? <a href={href(target) || "#"} className={className}>{children}</a> : <div className={className}>{children}</div>;
    },
    Eyebrow,
    Link: ({ href: target, children }) => <a href={href(target) || "#"} className="brand-link">{children}</a>,
    // eslint-disable-next-line @next/next/no-img-element
    Image: ({ src, alt, fit }) =>
      src ? <img src={src} alt={alt ?? ""} className={IMAGE_CLASS[fit ?? (logos.has(src) ? "contain" : "standard")]} /> : null,
  };
}
```

- [ ] **Step 8: `config.tsx`.**
  1. `import { makeKit, type AgentSectionModule } from "./agent-kit";` stays; add
     `import { buttonLookOptions } from "./looks";`.
  2. In the shell config's `SiteHeader.fields`, after `ctaHref: { type: "text", label: "Button link" },` add
     `...(buttonLookOptions(brand).length > 1 ? { ctaLook: { type: "select", label: "Button style", options: buttonLookOptions(brand) } } : {}),`.
  3. `const kit = makeKit(href);` becomes `const kit = makeKit(href, brand);`.
  4. The missing-clone placeholder's class
     `"m-6 rounded border border-dashed border-slate-300 p-10 text-center text-slate-500"` becomes
     `"p-card-padding text-center font-body text-body text-ink-muted"`.
  5. Delete the `TokenProbe` component and its entry in the `Config<{ … }>` type: it is the spike's
     G3 fixture (`trials/puck-spike/export/check_tokens.py` keeps its own copy in
     `trials/puck-spike/puck/config.tsx`), is not offered in the menu, and the validator refuses it
     (`COMPONENT_SCHEMAS` has no `TokenProbe`). Lane B's reserved-name list may keep the name.

- [ ] **Step 9: The validator holds our sections to the brand.** In `src/validate.ts`:
  1. Imports: add `import { buttonLooks } from "./looks";` and `import { surfaceChoices } from "./surfaces";`.
  2. After `const assetFiles = …` add:

```ts
  // Surfaces and button styles are the brand's (founder rulings 4 and Q4 = (b)): a contract, like
  // clone ids. The refusals name what this brand has.
  const surfaceNames = surfaceChoices(brand).map((choice) => choice.value);
  const lookNames = buttonLooks(brand).map((look) => look.name);
  const surfaceError = (where: string, value: string) =>
    `${where}: "${value}" is not one of this brand's surfaces; its surfaces are ${surfaceNames.join(", ")} (brand/brand.md, Surfaces)`;
  const lookError = (where: string, value: string) =>
    lookNames.length
      ? `${where}: "${value}" is not one of this brand's button styles; its styles are ${lookNames.join(", ")}, or leave it empty for the standard button (brand/brand.md, Buttons)`
      : `${where}: this brand's kit records no button styles; leave it empty for the standard button (brand/brand.md, Buttons)`;
  const OURS = new Set(["StatsBand", "FeatureSplit", "ProofCard", "CtaBand"]);
```
  3. At the top of the `(page.content ?? []).forEach((item, index) => {` body, after `const at = …`:

```ts
      if (OURS.has(item.type)) {
        const surface = item.props.surface;
        if (typeof surface === "string" && !surfaceNames.includes(surface)) errors.push(surfaceError(`${at}.surface`, surface));
        const look = item.props.buttonLook;
        if (typeof look === "string" && look && !lookNames.includes(look)) errors.push(lookError(`${at}.buttonLook`, look));
      }
```
  4. After the `accountLogo` check:

```ts
  const ctaLook = shell.header?.ctaLook;
  if (typeof ctaLook === "string" && ctaLook && !lookNames.includes(ctaLook)) errors.push(lookError("shell.header.ctaLook", ctaLook));
```

- [ ] **Step 10: sections.md names the brand's choices (T-A9-2).** In `src/catalog.ts`:
  `function sectionsFile(): string {` becomes `function sectionsFile(brand: BrandData): string {`;
  its intro sentence "Style options are fixed choices; …" becomes "Style options are names from
  brand/brand.md; there are no colour, size, class or style fields."; import
  `surfaceChoices` from `./surfaces` and `buttonLooks` from `./looks`, and replace the `choices`
  computation with:

```ts
      const surfaces = surfaceChoices(brand).map((choice) => `${choice.value} (${choice.label})`).join(", ");
      const looks = buttonLooks(brand).map((look) => look.name);
      const choices =
        field === "surface"
          ? `one of this brand's surfaces (brand/brand.md, Surfaces): ${surfaces}`
          : field === "buttonLook"
            ? looks.length
              ? `default ""; empty is the standard button, or a button style from brand/brand.md (Buttons): ${looks.join(", ")}`
              : `default ""; this brand's kit records no button styles, so leave it empty`
            : spec.enum
              ? spec.enum.join(", ")
              : spec.default !== undefined
                ? `default ${JSON.stringify(spec.default)}`
                : "";
```
  and call `sectionsFile(brand)` in `buildCatalog`.

- [ ] **Step 11: Bring the two older tests to the new contract.** In `test/contracts.test.ts`, the
  test "a surface outside the brand's choices is refused, listing the allowed choices" becomes:

```ts
test("a surface outside the brand's choices is refused by the validator, listing the brand's surfaces", () => {
  const page = garnerHome();
  const stats = page.content.find((item: { type: string }) => item.type === "StatsBand");
  stats.props.surface = "green";
  const syracuse = site("garner-syracuse");
  const { errors } = validateSite({ pages: { ...syracuse.pages, "/": page }, shell: syracuse.shell }, garner(), {});
  assert.ok(errors.some((e) => e.includes('.surface: "green" is not one of this brand\'s surfaces') && e.includes("brandSubtle")), errors.join("\n"));
});
```
  (with `import { validateSite } from "../src/validate";`; `garner` and `site` are already imported there). In `test/catalog.test.ts`, "sections.md gives each section's fields and the
  allowed token choices" additionally asserts `assert.match(sections, /buttonLook/)` and
  `assert.ok(sections.includes("a button style from brand/brand.md (Buttons): outline.1"))`.

- [ ] **Step 12: Exports and the test script.** In `src/index.ts`: the shell line becomes
  `export { SiteFooter, SiteHeader, logoFiles, sellerLogo, type FooterProps, type HeaderProps, type ShellData } from "./shell";`
  and add `export { surfaceClass, type AnySurface } from "./sections";`. In `package.json`, `"test"`
  becomes `"tsx --test test/*.test.ts test/*.test.tsx"`.

- [ ] **Step 13: Run everything in site-kit, then the type check.**

Run: `cd apps/frontend/packages/site-kit && npx tsx --test test/*.test.ts test/*.test.tsx && cd ../.. && npm run typecheck -w @clue/site-kit`
Expected: all pass (the guard finds no offenders); no type errors.

- [ ] **Step 14: Commit.**

```bash
git add apps/frontend/packages/site-kit/src apps/frontend/packages/site-kit/test apps/frontend/packages/site-kit/package.json
git commit -m "site-kit: sections, shell and agent kit use only kit classes; buttonLook and the brand's surfaces by name, validated against the brand; a guard against new style literals"
```

### Task 6 — as written in the Lane A plan

Run Lane A's Task 6 unchanged at this point (raw `<a>` refusal, brand colour classes, agent-section
links, section ids). It imports `COLOR_ROLES`, `SURFACES`, `colorVar` from `./theme`, which Task 4
re-exports.

### Task 6b: The validator and the section check hold agent sections to the brand's looks, surfaces and motion

**Files:**
- Modify: `apps/frontend/packages/site-kit/src/validate.ts` (Task 6's agent-section walk)
- Modify: `apps/frontend/packages/site-kit/src/check-section.ts` (`LintOptions`, look literals,
  motion classes, `lintOptionsFor`)
- Modify: `apps/frontend/packages/site-kit/test/check-section.test.ts`, `test/multipage.test.ts`

**Interfaces:**
- `LintOptions = { extraSurfaces?, buttonLooks?, cardLooks?, motions? }`;
  `lintOptionsFor(brand): LintOptions` (Lane B Task 15 passes it to `lint`); refusals T-A9-3 (card
  styles) and T-A9-4. An agent section's prop named `surface` or `…Surface` must be one of the
  brand's surfaces, `…CardLook` one of its card styles, any other `…Look` one of its button styles
  (the convention mirrors Task 6's `…Href`).

- [ ] **Step 1: Confirm T-A9-3 and T-A9-4 were approved.**

- [ ] **Step 2: Write the failing tests.** Append to `test/check-section.test.ts` (import
  `lintOptionsFor` beside `lint`, and `kitBrand` from `./fixtures/kits`):

```ts
test("a look named in the source must be one of the brand's", () => {
  const options = lintOptionsFor(kitBrand("garner"));
  const withButton = (look: string) => EXAMPLE.replace("</kit.Shell>", `<kit.Button label="Go" href="/" surface="page" look="${look}" /></kit.Shell>`);
  assert.deepEqual(lint(withButton("outline.1"), options), []);
  assert.ok(lint(withButton("solid.9"), options).includes('look "solid.9" on kit.Button is not one of this brand\'s button styles; the styles are outline.1, ghost.1, solid.1, solid.2, solid.3, solid.4 (brand/brand.md, Buttons)'));
  const withCard = EXAMPLE.replace("</kit.Shell>", '<kit.Card look="solid.7">x</kit.Card></kit.Shell>');
  assert.ok(lint(withCard, options).some((e) => e.startsWith('look "solid.7" on kit.Card is not one of this brand\'s card styles')));
});

test("motion of the section's own is refused; the brand's motion classes pass", () => {
  const options = lintOptionsFor(kitBrand("probe.minted"));
  for (const cls of ["transition", "duration-300", "ease-in-out", "animate-spin", "hover:scale-105", "group-hover:-translate-y-1", "focus:opacity-80"]) {
    assert.ok(lint(withClass(`mt-6 ${cls}`), options).some((e) => e.startsWith(`class "${cls}" is motion of your own`)), cls);
  }
  assert.deepEqual(lint(withClass("mt-6 brand-motion-pulse hover:bg-surface-muted -translate-x-1/2"), options), []);
  assert.ok(lint(withClass("mt-6 brand-motion-wobble"), options).some((e) => e.startsWith('class "brand-motion-wobble" is not one of this brand\'s motion classes')));
});
```
  Append to `test/multipage.test.ts`:

```ts
test("an agent section's surface and look props are held to the brand's", () => {
  const sections = { QuoteBand: { schema: { safeParse: () => ({ success: true }) } } };
  const home = structuredClone(site.pages["/"]);
  home.content.push({ type: "QuoteBand", props: { id: "quote", surface: "canvas", ctaLook: "outline.1", cardLook: "" } });
  const pages = () => ({ "/": home, "/analysis": site.pages["/analysis"] });
  assert.deepEqual(validateSite({ pages: pages(), shell: site.shell }, brand, sections).errors, []);
  home.content[home.content.length - 1].props = { id: "quote", surface: "green", ctaLook: "solid.9", cardLook: "solid.7" };
  const errors = validateSite({ pages: pages(), shell: site.shell }, brand, sections).errors;
  assert.ok(errors.some((e) => e.includes('(quote).surface: "green" is not one of this brand\'s surfaces')), errors.join("\n"));
  assert.ok(errors.some((e) => e.includes('(quote).ctaLook: "solid.9" is not one of this brand\'s button styles')), errors.join("\n"));
  assert.ok(errors.some((e) => e.includes('(quote).cardLook: "solid.7" is not one of this brand\'s card styles')), errors.join("\n"));
});
```

- [ ] **Step 3: Run them to see them fail.**

Run: `cd apps/frontend/packages/site-kit && npx tsx --test test/check-section.test.ts test/multipage.test.ts`
Expected: FAIL — `lintOptionsFor` is not exported; agent props are not checked.

- [ ] **Step 4: The validator.** In Task 6's agent-section `walk`, in the `typeof value === "string"`
  branch, before the `IMAGE_PATH` test, add:

```ts
            if (/^surface$|Surface$/.test(key) && !surfaceNames.includes(value)) {
              errors.push(surfaceError(where, value));
              return;
            }
            if (/cardlook$/i.test(key)) {
              if (value && !cardNames.includes(value)) {
                errors.push(`${where}: "${value}" is not one of this brand's card styles; its styles are ${cardNames.join(", ")}, or leave it out for the standard card (brand/brand.md, Cards)`);
              }
              return;
            }
            if (/look$/i.test(key)) {
              if (value && !lookNames.includes(value)) errors.push(lookError(where, value));
              return;
            }
```
  and beside `lookNames` add `const cardNames = cardLooks(brand).map((look) => look.name);` (import
  `cardLooks` from `./looks`).

- [ ] **Step 5: The section check.** In `src/check-section.ts`:
  1. `export type LintOptions = { extraSurfaces?: string[] };` becomes:

```ts
/** What the brand has, so a section is checked against it (B6 passes lintOptionsFor(brand)).
 * Without a brand only the brand-independent rules run. */
export type LintOptions = { extraSurfaces?: string[]; buttonLooks?: string[]; cardLooks?: string[]; motions?: string[] };

export function lintOptionsFor(brand: BrandData): LintOptions {
  return {
    extraSurfaces: extraSurfaceRoles(brand),
    buttonLooks: buttonLooks(brand).map((look) => look.name),
    cardLooks: cardLooks(brand).map((look) => look.name),
    motions: motionClassNames(brand),
  };
}
```
     with imports `import type { BrandData } from "./brand";`,
     `import { buttonLooks, cardLooks, motionClassNames } from "./looks";` and `extraSurfaceRoles`
     added to the `./theme` import.
  2. Add, after `brandColourNames`:

```ts
const STATE_VARIANT = /^(hover|focus|focus-visible|focus-within|active|group-hover|group-focus|peer-hover|peer-focus)$/;
const MOTION_UTILITY = /^(transition(-[a-z]+)?|duration-.+|ease-.+|delay-.+|animate-.+)$/;
const STATE_MOTION = /^-?(translate|scale|rotate|skew)(-[xy])?-|^(opacity|shadow|blur|brightness|contrast|saturate|drop-shadow)(-|$)/;

/** Class tokens with their variants (`group-hover:-translate-y-1` → variants ["group-hover"]). */
function variantTokens(source: string): { token: string; base: string; variants: string[] }[] {
  const strings = [...source.matchAll(/"([^"\n]*)"|'([^'\n]*)'|`([^`]*)`/g)].map((m) => m[1] ?? m[2] ?? m[3] ?? "");
  return strings.flatMap((s) => s.split(/\s+/)).filter(Boolean).map((token) => {
    const parts = token.split(":");
    return { token, base: parts[parts.length - 1], variants: parts.slice(0, -1) };
  });
}
```
  3. At the end of `lint`, before `return errors;`, add:

```ts
  for (const { token, base, variants } of variantTokens(source)) {
    if (seen.has(token)) continue;
    const ownMotion = MOTION_UTILITY.test(base) || (variants.some((v) => STATE_VARIANT.test(v)) && STATE_MOTION.test(base));
    if (ownMotion) {
      seen.add(token);
      errors.push(`class "${token}" is motion of your own; motion comes from the brand: kit.Button, kit.Link and kit.Card carry it, and a class from brand/brand.md (Motion) adds it to an element`);
    } else if (options.motions && /^brand-motion-/.test(base) && !options.motions.includes(base)) {
      seen.add(token);
      errors.push(`class "${token}" is not one of this brand's motion classes; its motion classes are ${options.motions.join(", ") || "none"} (brand/brand.md, Motion)`);
    }
  }
  for (const m of source.matchAll(/<kit\.(Button|Card)\b[^>]*?\blook=["']([^"']+)["']/g)) {
    const [, component, look] = m;
    const known = component === "Button" ? options.buttonLooks : options.cardLooks;
    if (known && !known.includes(look)) {
      errors.push(component === "Button"
        ? `look "${look}" on kit.Button is not one of this brand's button styles; the styles are ${known.join(", ") || "none"} (brand/brand.md, Buttons)`
        : `look "${look}" on kit.Card is not one of this brand's card styles; the styles are ${known.join(", ") || "none"} (brand/brand.md, Cards)`);
    }
  }
```
  4. Nothing to add to `src/index.ts`: `@clue/site-kit/check-section` (its own entry point) exports
     `lintOptionsFor` with `lint`.

- [ ] **Step 6: Run the tests and the type check.**

Run: `cd apps/frontend/packages/site-kit && npx tsx --test test/*.test.ts test/*.test.tsx && cd ../.. && npm run typecheck -w @clue/site-kit`
Expected: all pass, Task 6's own tests included (`hover:border-line-subtle/50` is a brand colour on a
state, not motion, and still passes).

- [ ] **Step 7: Commit.**

```bash
git add apps/frontend/packages/site-kit/src/validate.ts apps/frontend/packages/site-kit/src/check-section.ts \
  apps/frontend/packages/site-kit/test/check-section.test.ts apps/frontend/packages/site-kit/test/multipage.test.ts
git commit -m "site-kit: agent sections' surfaces, looks and motion are held to the brand's; lintOptionsFor for write_section"
```

### Task 7: brand.md shows every surface, type role, spacing step, button, card, link and motion with its token names

This replaces Lane A's Task 7. It keeps that task's type-role table (`typeRoleBasis`), the kit's
rules, the logos and the assets, and writes the rest from Tasks 4–6b. BrandData loses `measured`
here, with its last reader. **The whole file is agent-facing: nothing is written before the
founder approves T-A9-1.**

**Files:**
- Modify: `apps/frontend/packages/site-kit/src/catalog.ts` (`brandFile`, new `typeRoleBasis`)
- Modify: `apps/frontend/packages/site-kit/src/brand.ts` (`measured` and `MeasuredButton` removed),
  `src/index.ts`
- Modify: `apps/frontend/packages/site-kit/test/fixtures/garner.ts`, `test/fixtures/kits.ts`; delete
  `test/fixtures/measured.json`
- Modify: `apps/frontend/packages/site-kit/test/catalog.test.ts`
- Create: `apps/frontend/packages/site-kit/test/brand-md.test.ts`

**Interfaces:**
- `typeRoleBasis(source)` (as Lane A's Task 7 specified); `buildCatalog(brand, seller)` returns the
  T-A9-1 `brand/brand.md`.
- `BrandData = { slug, kit, fonts, assets, clones }`; `brandData(input)` takes no `measured`.
  **Lane B Task 8** drops `"measured": None` from `site_brand_data` in the same wave.

- [ ] **Step 1: Confirm T-A9-1 was approved** (generate Garner's, Conduit's and the probe kit's
  files from the code below in a scratch branch if the founder wants to read real ones first).

- [ ] **Step 2: Write the failing tests** `test/brand-md.test.ts`:

```ts
// brand.md over the three real kits and their minted twins (Wave 2 A9, T-A9-1).
import assert from "node:assert/strict";
import { test } from "node:test";
import { brandData } from "../src/brand";
import { buildCatalog, typeRoleBasis } from "../src/catalog";
import { garner } from "./fixtures/garner";
import { kitBrand, type KitName } from "./fixtures/kits";

const md = (name: KitName) => buildCatalog(kitBrand(name), "Seller")["brand/brand.md"];
const row = (text: string, first: string) => text.split("\n").find((line) => line.startsWith(`| ${first} |`)) ?? "";

test("typeRoleBasis reads measured or derived from a token's provenance", () => {
  assert.equal(typeRoleBasis("website:rendered :: h1"), "measured");
  assert.equal(
    typeRoleBasis("derived:type.headline; measured=font_family,font_size,font_weight,line_height @ website:rendered :: h1"),
    "measured: family, size, weight, line height",
  );
  assert.equal(typeRoleBasis("derived:type.eyebrow; measured=none"), "derived");
  assert.equal(typeRoleBasis("default:type-scale"), "derived");
  assert.equal(typeRoleBasis(undefined), "derived");
});

test("Buttons: the standard button and each style with its values and token names", () => {
  const garnerMd = buildCatalog(garner(), "Garner Health")["brand/brand.md"];
  assert.ok(garnerMd.includes('`look`: `kit.Button look="outline.1"` in a section you write, or `"buttonLook": "outline.1"` on'), garnerMd);
  assert.equal(row(garnerMd, "(none)"), "| (none) | the kit's standard button | #047464 (surface.brand) | #FFFFFF (text.inverse) | none | 16px (radius.button) | — | Used when you name no look. |");
  assert.ok(row(garnerMd, "outline.1").startsWith("| outline.1 | outline | none | #0E1110 (text.primary) | 1px (stroke.width.thin) in the label colour | 9999px (radius.full) | high |"), row(garnerMd, "outline.1"));
  assert.ok(row(garnerMd, "solid.2").includes("| not in the kit; drawn: #047464 (surface.brand), the standard button's fill |"));
  assert.ok(garnerMd.includes("This kit was made before button styles were measured"));
  assert.ok(garnerMd.includes("On a dark surface, a button whose text or fill would not stand out from the surface changes"));
});

test("Conduit's demo button reads warm dark once measured, and says what is drawn before", () => {
  assert.ok(row(md("conduit"), "solid.2").includes("| not in the kit; drawn: #7CE4FC (surface.brand), the standard button's fill |"));
  const minted = row(md("conduit.minted"), "solid.2");
  assert.ok(minted.startsWith("| solid.2 | filled | #28241E (surface.band.28241e) | #FFFFFF (text.inverse) |"), minted);
  assert.ok(!minted.includes("#7CE4FC"));
  assert.ok(!md("conduit.minted").includes("This kit was made before button styles were measured"));
  assert.ok(md("altcarbon").includes('kit.Button look="solid.1"'));
});

test("Surfaces: one table, our six and every other surface with where it came from", () => {
  const text = md("garner.minted");
  assert.ok(!text.includes("Our sections take only the six choices above"));
  assert.equal(row(text, "page"), "| page | Page | surface.page | #F9FAF8 | #0E1110 (text.primary) | measured |");
  assert.equal(
    row(text, "band-014036"),
    "| band-014036 | Dark band | surface.band.014036 | #014036 | #FFFFFF (text.inverse), chosen by contrast | measured: a section background on the seller's site (1 band, 733px tall) |",
  );
  assert.ok(row(md("probe.minted"), "band-014036").includes("#FFFFFF (text.inverse), measured on the band"));
});

test("Type roles carry their measured colour; Spacing names the kit's classes", () => {
  const text = buildCatalog(garner(), "Garner Health")["brand/brand.md"];
  assert.ok(row(text, "headline").startsWith("| headline | `font-headline text-headline` | Stix Two Text | 87px | 500 | 1 | #0E1110 (text.primary) |"), row(text, "headline"));
  assert.ok(row(text, "eyebrow").includes("| the surface's text colour |"), "text.brand is derived");
  assert.match(text, /## Spacing\nThe seller's spacing, as classes you can use: `py-section` \(space\.section, \d+px at 1440\)/);
});

test("Cards, Links and Motion come from the measured kit, with plain fallbacks", () => {
  const probe = md("probe.minted");
  assert.match(probe, /## Cards\n`kit\.Card` draws a card/);
  assert.match(probe, /Text links look like the seller's own: #0D2B25 \([a-z.0-9-]+\), underlined on hover, #047464 \([a-z.0-9-]+\) on hover\./);
  assert.ok(probe.includes("| `brand-motion-pulse` | opacity 1 → .4, transform scale(1) → scale(1.2); repeats forever, alternating | 1.6s ease-in-out | 1 element: div#pulse.pulse |"), probe);
  assert.match(probe, /\| `brand-motion-reveal-[0-9a-f]{8}` \| fades in from opacity 0 and moves into place from 24px below as it scrolls into view \| ease-out \|/);
  assert.ok(probe.includes("The seller's site also moves in ways a published page cannot, because they need a script: a scripted animation (div#spin.spin). Do not imitate them."));
  assert.ok(probe.includes("Each style's hover, pressed and focus looks, and the motion between them, come from the seller's"));
  const old = md("garner");
  assert.ok(old.includes("The kit recorded no text-link style, so text links are underlined in the surrounding text's"));
  assert.ok(old.includes("The seller's site shows no motion a page can reuse"));
});

test("BrandData has no spike-only measurement", () => {
  const brand = brandData({ slug: "x", kit: {}, fonts: [], kitAssets: {}, clones: [] });
  assert.ok(!("measured" in brand));
});
```
  In `test/catalog.test.ts`, keep the older brand.md test (Stix Two Text, `#047464`, "button", an asset file).

- [ ] **Step 3: Run them to see them fail.**

Run: `cd apps/frontend/packages/site-kit && npx tsx --test test/brand-md.test.ts`
Expected: FAIL — `typeRoleBasis` is not exported; brand.md has no surfaces table of this shape.

- [ ] **Step 4: Remove the spike-only measurement.** In `src/brand.ts`, delete `MeasuredButton`,
  the `measured` field of `BrandData`, the `measured` input of `brandData` and its line in the
  returned object; in `src/index.ts`, drop `type MeasuredButton` from the brand export; in
  `test/fixtures/garner.ts` and `test/fixtures/kits.ts`, drop the `measured` argument; delete
  `test/fixtures/measured.json`.

- [ ] **Step 5: Rewrite `brandFile` in `src/catalog.ts`.** Imports at the top become:

```ts
import { parse, TextNode, type HTMLElement } from "node-html-parser";
import { z } from "zod";
import type { BrandData } from "./brand";
import { colorOf, isMeasured, pxOf, tokenEntry, typographyOf } from "./brand-values";
import type { Clone } from "./clone";
import {
  buttonLooks, cardLooks, drawnButton, drawnCard, drawnLink, measuredComponents, motionEntries, motionNotes,
  partsFromSlots, type Drawn, type Look, type Part,
} from "./looks";
import { COMPONENT_SCHEMAS } from "./schemas";
import { inkRole, surfaceChoices } from "./surfaces";
import { SPACING_ROLES, TYPE_ROLES, spacingVar, typeVar } from "./theme";
```
  (the `SURFACE_ROLE` map in `catalog.ts` is gone: `surfaces.ts` owns `CHOICE_ROLE`), and everything
  from `type Token = …` through the end of `brandFile` becomes:

```ts
type TypeToken = { value: { default: { font_family: string; font_size: number; font_weight: number; line_height: number } }; provenance?: { source?: string } };
type Constraint = { rule?: string; scope?: string } | string;
type LogoEntry = { title?: string; variants?: { name: string; asset_id: string }[]; allowed_backgrounds?: string[] };

const FIELD_WORDS: Record<string, string> = {
  font_family: "family", font_size: "size", font_weight: "weight", line_height: "line height", letter_spacing: "letter spacing",
};
const KIND_WORD: Record<Look["kind"], string> = { outline: "outline", ghost: "text only", solid: "filled", other: "other" };
const SPACING_CLASS: Record<string, string> = {
  section: "`py-section`", "page.margin": "`px-page-margin`", "stack.tight": "`mt-stack-tight` or `gap-stack-tight`",
  "stack.default": "`mt-stack-default`", "stack.loose": "`mt-stack-loose`", "card.padding": "`p-card-padding`",
};

/** Whether a type role was measured on the seller's site, read from its token's provenance.source
 * (lumen_ingestion/normalizer): "<source>:<locator>" is measured; "derived:type.X; measured=<fields>
 * …" is measured for those fields, or derived when the list is "none"; "default:type-scale" is derived. */
export function typeRoleBasis(source: string | undefined): string {
  if (!source || source.startsWith("default:")) return "derived";
  const derived = /^derived:[^;]*;\s*measured=([^\s@]+)/.exec(source);
  if (!derived) return source.startsWith("derived:") ? "derived" : "measured";
  if (derived[1] === "none") return "derived";
  return `measured: ${derived[1].split(",").map((field) => FIELD_WORDS[field.trim()] ?? field.trim()).join(", ")}`;
}

const cellText = (text: string) => text.replace(/\s+/g, " ").replace(/\|/g, "\\|").trim();
const uniform = (value: string | undefined) => (value && new Set(value.split(" ")).size === 1 ? value.split(" ")[0] : value);

/** One drawn part as brand.md says it: the value and its token, or what is drawn instead. */
function partCell(brand: BrandData, drawn: Drawn, part: Part, what: string): string {
  let value = uniform(drawn.parts[part]);
  const token = drawn.tokens[part];
  if (!value || value === "transparent") return "none";
  if (value === "inherit" || value === "currentColor") return "the surrounding text's colour";
  if (value.startsWith("clamp(") && token) value = pxOf(brand, token) ?? value;
  const named = token ? `${value} (${token})` : value;
  if (drawn.source[part] === "standard") return `not in the kit; drawn: ${named}, the standard ${what}`;
  if (drawn.source[part] === "fallback") return `not in the kit; drawn: ${named}, site-kit's default`;
  return named;
}

function borderCell(brand: BrandData, drawn: Drawn, what: string): string {
  const width = uniform(drawn.parts.borderWidth);
  if (!width || /^0(px)?$/.test(width) || drawn.parts.borderStyle === "none") return "none";
  const colour = drawn.parts.border;
  const tint = !colour || colour === "currentColor" ? "in the label colour" : partCell(brand, drawn, "border", `${what} colour`);
  return `${partCell(brand, drawn, "borderWidth", what)} ${tint}`;
}

function surfacesSection(brand: BrandData): string[] {
  const pairs = (brand.kit as { constraints?: { contrast_pairs?: { background: string; foreground: string }[] } }).constraints?.contrast_pairs ?? [];
  const rows = surfaceChoices(brand).map((choice) => {
    const ink = inkRole(brand, choice.role);
    const paired = pairs.some((pair) => pair.background === choice.role && pair.foreground === ink);
    const how = paired ? (choice.role.startsWith("surface.band.") ? ", measured on the band" : "") : ", chosen by contrast";
    const entry = tokenEntry(brand, "colors", choice.role);
    const band = /^section background \((.*)\)$/.exec(entry?.description ?? "");
    const from = band ? `measured: a section background on the seller's site (${band[1]} tall)` : isMeasured(entry) ? "measured" : "derived";
    return `| ${choice.value} | ${choice.label} | ${choice.role} | ${colorOf(brand, choice.role) ?? "not in this kit"} | ${ink ? `${colorOf(brand, ink)} (${ink})${how}` : "chosen by contrast"} | ${from} |`;
  });
  return [
    "## Surfaces",
    "Every section stands on one of these surfaces. Choose one by its name: `\"surface\": \"brand\"` on one",
    "of our sections, or `kit.Shell surface=\"<choice>\"` (or the classes",
    "`bg-surface-<choice> text-on-surface-<choice>`) in a section you write. Text on a surface takes the",
    "colour under \"text on it\".",
    "| choice | name | kit name | colour | text on it | from |",
    "|---|---|---|---|---|---|",
    ...rows,
    "",
  ];
}

function typeSection(brand: BrandData): string[] {
  const typography = ((brand.kit as { tokens?: { typography?: Record<string, TypeToken> } }).tokens?.typography) ?? {};
  const rows = TYPE_ROLES.map((role) => {
    const classes = `\`font-${typeVar(role)} text-${typeVar(role)}\``;
    const token = typography[`type.${role}`];
    if (!token) return `| ${role} | ${classes} | not in this kit | | | | | |`;
    const style = token.value.default;
    const colourRole = typographyOf(brand, `type.${role}`)?.color;
    const colour = colourRole && colorOf(brand, colourRole) && isMeasured(tokenEntry(brand, "colors", colourRole))
      ? `${colorOf(brand, colourRole)} (${colourRole})` : "the surface's text colour";
    return `| ${role} | ${classes} | ${style.font_family} | ${style.font_size}px | ${style.font_weight} | ${style.line_height} | ${colour} | ${typeRoleBasis(token.provenance?.source)} |`;
  });
  return [
    "## Type roles",
    "Each role is a pair of classes, `font-<role> text-<role>` (for example `font-title text-title`).",
    "\"measured\" means the seller's own site showed it, for the fields listed; \"derived\" means the kit",
    "worked it out from the measured roles. On a light surface a role takes the colour shown when the kit",
    "measured that colour; otherwise, and on every dark surface, it takes the surface's text colour.",
    "| role | classes | font | size at 1440 | weight | line height | colour | from |",
    "|---|---|---|---|---|---|---|---|",
    ...rows,
    "",
    "Our sections' headings choose from display, headline and title (`headingRole`).",
    "",
  ];
}

function spacingSection(brand: BrandData): string[] {
  const items = SPACING_ROLES.flatMap((role) => {
    const px = pxOf(brand, `space.${role}`);
    return px ? [`${SPACING_CLASS[role]} (space.${role}, ${px}${role === "section" ? " at 1440" : ""})`] : [];
  });
  if (!items.length) return [];
  const list = items.length > 1 ? `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}` : items[0];
  return ["## Spacing", `The seller's spacing, as classes you can use: ${list}. Values above 24px shrink on smaller screens.`, ""];
}

function buttonsSection(brand: BrandData): string[] {
  const looks = buttonLooks(brand);
  const std = drawnButton(brand, null);
  const fill = partCell(brand, std, "fill", "button's fill");
  const label = partCell(brand, std, "label", "button's label");
  const corners = partCell(brand, std, "radius", "button's corners");
  const dark = [
    "On a dark surface, a button whose text or fill would not stand out from the surface changes: outline",
    "and text-only styles take the surface's text colour, and filled styles and the standard button take",
    "their light version (the kit's page colour, with its text colour). Every other button is drawn as the",
    "seller's site draws it.",
  ];
  if (!looks.length) {
    return ["## Buttons", `This brand's kit records no button styles, so every button is the kit's standard button: ${fill}, ${label}, ${corners}.`, "", ...dark, ""];
  }
  const first = looks[0].name;
  const rows = looks.map((look) => {
    const drawn = drawnButton(brand, look);
    return `| ${look.name} | ${KIND_WORD[look.kind]} | ${partCell(brand, drawn, "fill", "button's fill")} | ${partCell(brand, drawn, "label", "button's label")} | ${borderCell(brand, drawn, "button's border")} | ${partCell(brand, drawn, "radius", "button's corners")} | ${look.recipe.confidence ?? "low"} | ${cellText((look.recipe.unmapped ?? []).join(" "))} |`;
  });
  const measuredStates = looks.some((look) => look.measured && (Object.keys(look.measured.states ?? {}).length || look.measured.motion?.length));
  return [
    "## Buttons",
    "`kit.Button` draws a button. Below are the button styles the seller's own site uses, as its brand kit",
    "recorded them, and the kit's standard button. You choose the style of each button by its name, with",
    `\`look\`: \`kit.Button look="${first}"\` in a section you write, or \`"buttonLook": "${first}"\` on`,
    "a FeatureSplit or a CtaBand. A button with no look is the standard button.",
    "| look | kind | fill | label | border | corners | confidence | notes from the brand kit |",
    "|---|---|---|---|---|---|---|---|",
    `| (none) | the kit's standard button | ${fill} | ${label} | none | ${corners} | — | Used when you name no look. |`,
    ...rows,
    ...(measuredStates ? ["Each style's hover, pressed and focus looks, and the motion between them, come from the seller's", "site; `kit.Button` draws them."] : []),
    ...(measuredComponents(brand) ? [] : ["This kit was made before button styles were measured: their values come from the kit's tokens, and", "a part the kit has no value for is drawn as the standard button's part."]),
    "",
    "How to choose:",
    "- For the page's main ask, use the style the seller's site uses for its own main call to action (the",
    "  notes and the brand's rules below say which); if none is clear, use the standard button.",
    "- For quieter actions, use an outline or text-only style the site uses.",
    "- Leave out styles the notes say are not page buttons (for example \"inside product screenshots\"), and",
    "  be careful with low-confidence styles.",
    "- Where the kit has no value for a part, the table says what is drawn instead.",
    "- Add `disabled` for a button that cannot be used yet; it takes the style's disabled look.",
    "",
    ...dark,
    "",
  ];
}

function cardsSection(brand: BrandData): string[] {
  const looks = cardLooks(brand);
  const std = drawnCard(brand, null);
  const fill = partCell(brand, std, "fill", "card's fill");
  const corners = partCell(brand, std, "radius", "card's corners");
  const padding = partCell(brand, std, "padding", "card's padding");
  if (!looks.length) {
    return ["## Cards", `This brand's kit records no card styles; \`kit.Card\` draws the kit's standard card: ${fill}, ${corners}, ${padding}.`, ""];
  }
  const rows = looks.map((look) => {
    const drawn = drawnCard(brand, look);
    return `| ${look.name} | ${KIND_WORD[look.kind]} | ${partCell(brand, drawn, "fill", "card's fill")} | ${borderCell(brand, drawn, "card's border")} | ${partCell(brand, drawn, "radius", "card's corners")} | ${partCell(brand, drawn, "padding", "card's padding")} | ${look.recipe.confidence ?? "low"} | ${cellText((look.recipe.unmapped ?? []).join(" "))} |`;
  });
  return [
    "## Cards",
    "`kit.Card` draws a card on a section's surface. Below are the card styles the seller's site uses, as",
    `its brand kit recorded them, and the kit's standard card. Choose one with \`look\``,
    `(\`kit.Card look="${looks[0].name}"\`), or leave it out for the standard card. Give it \`href\` to make`,
    "the whole card a link; it then takes the style's hover and focus looks from the seller's site.",
    "| look | kind | fill | border | corners | padding | confidence | notes from the brand kit |",
    "|---|---|---|---|---|---|---|---|",
    `| (none) | the kit's standard card | ${fill} | none | ${corners} | ${padding} | — | Used when you name no look. |`,
    ...rows,
    "",
  ];
}

function linksSection(brand: BrandData): string[] {
  const lines = [
    "## Links",
    "Write every link with `kit.Link` (a text link) or `kit.Button`, never a bare `<a>`. A link to another",
    "page of this site is written `/` or `/<page>`; the kit points it at the right address wherever the",
    "site is published.",
  ];
  const link = drawnLink(brand, "link");
  if (!link.style) return [...lines, "The kit recorded no text-link style, so text links are underlined in the surrounding text's", "colour.", ""];
  const colour = link.parts.label ? partCell(brand, link, "label", "link colour") : "the surrounding text's colour";
  const hover = partsFromSlots(brand, link.style.states?.hover);
  const underline = link.parts.decoration === "underline" ? "underlined" : hover.parts.decoration === "underline" ? "underlined on hover" : "not underlined";
  const hoverColour = hover.parts.label ? `, ${hover.parts.label}${hover.tokens.label ? ` (${hover.tokens.label})` : ""} on hover` : "";
  return [...lines, `Text links look like the seller's own: ${colour}, ${underline}${hoverColour}.`, ""];
}

function motionSection(brand: BrandData): string[] {
  const entries = motionEntries(brand);
  const notes = motionNotes(brand);
  const lines = ["## Motion"];
  if (!entries.length) {
    lines.push("The seller's site shows no motion a page can reuse; nothing moves except the kit's buttons,", "links and cards.");
  } else {
    lines.push(
      "`kit.Button`, `kit.Link` and `kit.Card` already move the way the seller's site does on hover and",
      "press. Nothing else moves unless you add one of these classes to an element; write no transition or",
      "animation of your own.",
      "| class | what it does | timing | where the seller's site uses it |",
      "|---|---|---|---|",
      ...entries.map((entry) => `| \`${entry.className}\` | ${cellText(entry.describe)} | ${entry.timing} | ${cellText(entry.where)} |`),
      "Visitors who ask their device for less motion see every element still, in its final place.",
    );
  }
  if (notes.length) {
    const words: Record<string, string> = { canvas: "a canvas animation", video: "a video", scripted: "a scripted animation" };
    const list = notes.map((note) => `${words[note.kind] ?? note.kind} (${note.where})`).join("; ");
    lines.push(`The seller's site also moves in ways a published page cannot, because they need a script: ${list}. Do not imitate them.`);
  }
  return [...lines, ""];
}

function brandFile(brand: BrandData, seller?: string): string {
  const kit = brand.kit as {
    name?: string;
    brief?: { constraints?: Constraint[] };
    assets?: { logos?: Record<string, LogoEntry> };
  };
  const rules = (kit.brief?.constraints ?? [])
    .map((entry) => (typeof entry === "string" ? { rule: entry, scope: "" } : { rule: entry.rule ?? "", scope: entry.scope ?? "" }))
    .filter((entry) => entry.rule)
    .map((entry) => `- ${entry.rule.replace(/\s+/g, " ")}${entry.scope ? ` (${entry.scope})` : ""}`);
  const logos = Object.values(kit.assets?.logos ?? {}).flatMap((logo) =>
    (logo.variants ?? [])
      .map((variant) => {
        const file = brand.assets[variant.asset_id]?.file;
        const on = logo.allowed_backgrounds?.length ? `; on ${logo.allowed_backgrounds.join(", ")}` : "";
        return file ? `- \`${file}\`: ${logo.title ?? "logo"}, ${variant.name.replace(/_/g, " ")}${on}` : "";
      })
      .filter(Boolean),
  );
  const assets = Object.entries(brand.assets).map(
    ([key, asset]) => `- \`${asset.file}\` (${asset.kind}${key.startsWith("asset_") ? `, ${key}` : ""}): ${(asset.description ?? asset.label ?? "").replace(/\s+/g, " ").slice(0, 220)}`,
  );
  return [
    `# Brand: ${seller ?? kit.name ?? brand.slug}`,
    "",
    "Every brand section takes its colours, type, spacing, buttons and motion from these values. You",
    "choose by name (for example `surface: \"brand\"`); you never write a colour or a size.",
    "",
    ...surfacesSection(brand),
    ...typeSection(brand),
    ...spacingSection(brand),
    ...buttonsSection(brand),
    ...cardsSection(brand),
    ...linksSection(brand),
    ...motionSection(brand),
    ...(rules.length
      ? ["## The brand's own rules (from its brand kit)", "Where a rule names a kit colour such as `surface.brand`, the matching choice is in the surfaces table.", ...rules, ""]
      : []),
    "## Logos (always shown whole)",
    "`kit.Image` shows a logo whole: never cropped, never rounded.",
    ...(logos.length ? logos : ["This kit has no logo files."]),
    "",
    "## Assets (the only images and logos a page may use)",
    ...assets,
    "",
  ].join("\n");
}
```
- [ ] **Step 6: Run the tests and the type check.**

Run: `cd apps/frontend/packages/site-kit && npx tsx --test test/*.test.ts test/*.test.tsx && cd ../.. && npm run typecheck -w @clue/site-kit`
Expected: all pass, including the older brand.md test; no type errors.

- [ ] **Step 7: Commit** (only after the founder's yes in Step 1).

```bash
git add apps/frontend/packages/site-kit/src/catalog.ts apps/frontend/packages/site-kit/src/brand.ts apps/frontend/packages/site-kit/src/index.ts \
  apps/frontend/packages/site-kit/test/brand-md.test.ts apps/frontend/packages/site-kit/test/catalog.test.ts \
  apps/frontend/packages/site-kit/test/fixtures/garner.ts apps/frontend/packages/site-kit/test/fixtures/kits.ts
git rm apps/frontend/packages/site-kit/test/fixtures/measured.json
git commit -m "site-kit brand.md: every surface, type role, spacing step, button, card, link and motion with its token names; BrandData drops the spike-only measurement"
```

### Task 16b: The state and motion CSS survives the cleaner and the published policy; screenshots show revealed content

Runs after Lane A Tasks 16 (`sanitize_site_html`) and 17 (`capture_site_screenshot`).

**Files:**
- Create: `apps/frontend/packages/site-kit/test/fixtures/write-probe-page.tsx`, `test/probe-page.test.tsx`
- Create: `subsystems/clue-design/apps/api/tests/fixtures/site/probe_page.html` (written by the above)
- Modify: `subsystems/clue-design/apps/api/lumen_api/site_render.py` (`capture_site_screenshot`'s context)
- Create: `subsystems/clue-design/apps/api/tests/test_site_state_css.py`

- [ ] **Step 1: A page drawn by site-kit from the probe kit.** `test/fixtures/write-probe-page.tsx`:

```tsx
// The design API's state-CSS fixture (Wave 2 A9, Task 16b): a page site-kit draws from the probe kit
// (its theme, a measured button look with its icon, and a measured reveal below the fold).
// Run: cd apps/frontend/packages/site-kit && npx tsx test/fixtures/write-probe-page.tsx
import fs from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { colorOf } from "../../src/brand-values";
import { buttonLooks, motionEntries } from "../../src/looks";
import { Button } from "../../src/sections";
import { themeCss } from "../../src/theme";
import { kitBrand } from "./kits";

export const PROBE_PAGE = new URL("../../../../../../subsystems/clue-design/apps/api/tests/fixtures/site/probe_page.html", import.meta.url);

export function probePage(): string {
  const brand = kitBrand("probe.minted");
  const solid = buttonLooks(brand).find((look) => colorOf(brand, look.measured?.rest.fill) === "#047464")!;
  const reveal = motionEntries(brand).find((entry) => entry.kind === "reveal")!;
  const body = renderToStaticMarkup(
    <div className="brand-root">
      <style dangerouslySetInnerHTML={{ __html: themeCss(brand) }} />
      <section className="bg-surface-page text-on-surface-page">
        <Button brand={brand} label="Request the analysis" href="/analysis" surface="page" look={solid.name} />
      </section>
      <div data-test="spacer" />
      <div data-test="reveal" className={reveal.className}>Revealed</div>
    </div>,
  );
  // The fixture's own layout (a tall spacer, a coloured box) is test scaffolding, not site-kit's.
  return `<!doctype html><html><head><meta charset="utf-8"><title>probe</title><style>[data-test=spacer]{height:2400px}[data-test=reveal]{height:200px;background:#014036}</style></head><body>${body}</body></html>\n`;
}

if (process.argv[1]?.endsWith("write-probe-page.tsx")) fs.writeFileSync(PROBE_PAGE, probePage());
```
  `test/probe-page.test.tsx`:

```tsx
import assert from "node:assert/strict";
import fs from "node:fs";
import { test } from "node:test";
import { PROBE_PAGE, probePage } from "./fixtures/write-probe-page";

test("the design API's probe page is what site-kit draws today", () => {
  assert.equal(fs.readFileSync(PROBE_PAGE, "utf-8"), probePage(), "run: npx tsx test/fixtures/write-probe-page.tsx");
});
```
  Run the writer (command in its header), then `npx tsx --test test/probe-page.test.tsx`.
  Expected: PASS.

- [ ] **Step 2: Screenshots are taken as a visitor who asks for less motion would see the page.** In
  `lumen_api/site_render.py`, `capture_site_screenshot`'s `browser.new_context(...)` gains
  `reduced_motion="reduce",` with the comment
  `# A scroll-driven reveal leaves below-the-fold content at its starting look in a full-page
  # capture (verified 2026-10-12); the theme's reduced-motion rule shows everything in place.`
  Every caller (thumbnails, Task 18; Lane B's `render_page` and `compare_section`) inherits it. The
  PDF path needs nothing: the theme's rule also covers `print`.

- [ ] **Step 3: Write the test** `apps/api/tests/test_site_state_css.py`:

```python
"""The kit's state and motion CSS survives the published-page cleaner and the script-free policy, and
a screenshot shows revealed content where a visitor sees it (Wave 2 A9, Task 16b)."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

from lumen_api.site_render import RenderedPage, capture_site_screenshot
from lumen_api.site_sanitize import sanitize_site_html

PAGE = (Path(__file__).resolve().parent / "fixtures" / "site" / "probe_page.html").read_text()
#: Contract 3's published-page policy, verbatim.
CSP = (
    "default-src 'none'; script-src 'none'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "font-src 'self' data:; media-src 'self'; connect-src 'none'; form-action 'none'; base-uri 'none'; "
    "frame-ancestors 'self'"
)


def test_the_cleaner_keeps_every_state_and_motion_rule_and_the_icon() -> None:
    cleaned = sanitize_site_html(PAGE)
    for needle in (
        ":hover{", ":active{", ":focus-visible{", '[aria-disabled="true"]{', "@keyframes brand-kf-",
        "@media (prefers-reduced-motion:reduce),print", "@supports (animation-timeline:view())",
        '<span aria-hidden="true" class="brand-btn-icon"><svg',
    ):
        assert needle in cleaned.html, needle
    assert not [note for note in cleaned.removed if "css" in note or "@import" in note]


def test_hover_is_drawn_under_the_published_policy() -> None:
    cleaned = sanitize_site_html(PAGE).html
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
            page.route("https://site.test/", lambda route: route.fulfill(
                status=200, headers={"content-type": "text/html", "content-security-policy": CSP}, body=cleaned,
            ))
            page.goto("https://site.test/")
            button = page.locator("a.brand-btn")
            rest = button.evaluate("e => getComputedStyle(e).backgroundColor")
            button.hover()
            page.wait_for_timeout(400)
            hovered = button.evaluate("e => getComputedStyle(e).backgroundColor")
            icon = page.locator(".brand-btn-icon").evaluate("e => getComputedStyle(e).transform")
        finally:
            browser.close()
    assert (rest, hovered, icon) == ("rgb(4, 116, 100)", "rgb(3, 90, 78)", "matrix(1, 0, 0, 1, 4, 0)")


def test_a_screenshot_shows_revealed_content_in_place() -> None:
    cleaned = sanitize_site_html(PAGE).html
    png = capture_site_screenshot(RenderedPage(route="/", html=cleaned), "", width=1440, full_page=True)
    image = Image.open(io.BytesIO(png)).convert("RGB")
    inside_box = image.height - max(1, round(60 * image.width / 1440))
    assert image.getpixel((image.width // 2, inside_box)) == (1, 64, 54)
```

- [ ] **Step 4: Run it.**

Run: `CAPTURE_PYTEST test_site_state_css.py test_site_render.py`
Expected: PASS (the third test fails without Step 2: the box stays at opacity 0).

- [ ] **Step 5: Commit.**

```bash
git add apps/frontend/packages/site-kit/test/fixtures/write-probe-page.tsx apps/frontend/packages/site-kit/test/probe-page.test.tsx \
  subsystems/clue-design/apps/api/tests/fixtures/site/probe_page.html subsystems/clue-design/apps/api/lumen_api/site_render.py \
  subsystems/clue-design/apps/api/tests/test_site_state_css.py
git commit -m "site render: measured state and motion CSS survives the cleaner and the script-free policy; screenshots show revealed content"
```

---

## Follow-up, not in this plan: the web and ad lanes using minted tokens

Recorded so it is planned on purpose, not discovered. None of it blocks the site lane.

1. **Colours already work.** A minted colour (`button.solid-2.fill`, `surface.band.014036`) is a kit
   colour token: the web theme compiles it into a class (`bg-button-solid-2-fill`) and lists it in the
   author's THEME TOKENS (`tools/web_substrate.py:652-682`, `crates/lumen-web/src/theme.rs`); the scene
   DSL resolves `fill($surface.band.014036)`. That is founder question Q-A9-5.
2. **Geometry needs an engine change.** Web geometry classes come from a fixed table
   (`crates/lumen-web/src/theme.rs` `GEOMETRY_UTILITIES`, mirrored by
   `lumen_agent/brand_brief.py` `GEOMETRY_TOKEN_UTILITIES`), so a minted radius, padding or stroke
   (`button.solid-2.radius`) has no web class. Either generate per-component utilities from
   `measured_components` (`btn-solid-2` drawing every rest part and state, like site-kit's
   `.brand-look-<n>`) or open the table to every token of those groups. A Rust change in
   `lumen-web` with its own goldens.
3. **States and motion need the `styles` group in the web theme compile and lint**: keyword, duration,
   easing, transform, keyframes tokens → CSS, and the lint's allow-list for them.
4. **Agent-facing text.** The web/ad brief card's recipe lines (`brand_brief.py:696` `_recipe_line`)
   show only the model's six slots; showing the measured recipe (values, tokens, states) is new
   agent-facing text for the founder to approve, and only useful once 2 and 3 exist.

## Self-review notes

- **Rulings covered:** fetched styles used, no hard-coded values (Tasks 4–5, guard test); exact
  measured colours saved per style (X4/X5) with old kits on token fallbacks that brand.md names
  (Task 7); rest, hover, pressed, focus-visible and disabled captured (X2) and drawn (Task 4); no code
  picks "the secondary" (`secondaryButton()` is not written; looks are the brief's recipes, `look`
  names one, the validator checks membership only); judgement stays in prompts (every agent-facing
  line is listed in T-A9-1…7 and every step that writes one starts with "confirm approved"); no new
  UI (the dock's existing select, options from the brand; the brand-context panel unchanged).
- **Scope additions covered:** motion and behaviour (transitions, transforms, cursor, decoration
  changes, icons, keyframes, CSS reveals, scripted notes) captured, minted, drawn script-free with
  reduced motion respected; minted tokens with exact reuse, stable names, a cap (X4); section
  backgrounds as value-keyed surfaces with paired text (X4) offered by our sections (Task 5).
- **Placeholders:** none; every code step carries the code. Two places name exact edits in files
  this plan does not own whole (Lane A Task 6's walk in Task 6b; `site_render.py` in 16b), with the
  lines to add.
- **Type consistency:** `MeasuredRecipe` (TS) mirrors `MeasuredRecipe` (Python) field for field;
  slot names are one vocabulary (`SLOT_PATTERN` in Python, `partsFromSlots` in TS); `component`
  keeps the evidence names (`nav_link`) while token roots use `navlink` (`COMPONENT_ROOTS`).
- **Known limits, said plainly:** a state that only a script drives on press (pointer-down handlers)
  is not captured (pressed is forced through CSS); a reveal is reproduced as a scroll-driven
  animation, so its timing follows scrolling, not the measured duration; variants renumber if a
  re-extracted site changes which style is most common (as shape variants and recipes already do);
  inputs, chips and images are measured and minted but site-kit draws no form fields, chips or image
  hovers yet (stored for agent-made sections and clones); a briefless kit offers no looks (Q-A9-2).
