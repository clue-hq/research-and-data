# Site element inspector, plan 4: boxes (containers) and Arrange — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (the founder's rule since 2026-10-17: the plan is implemented directly, one whole-branch review at the end). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A marketer clicks any box on a Puck microsite (a section, a card, a row, a column, a list item, a div, or the header or footer) in our sections, a copied seller section, an agent's section, or the shell. The right-hand panel then styles it as in the approved mockup (`.superpowers/brainstorm/95737-1792238115/content/site-inspector-panels.html`, "2 · Container selected"): Fill, Stroke (colour, width, corner radius), Layout (padding, gap, width: fill / fit / fixed), Arrange (move up / move down among its neighbours, content alignment), and Layers as the section's full nested tree. Header and footer parts can be hidden. Every change shows on the canvas, is one save and one undo step, and looks the same on the published page.

**Architecture:** Plan 4 keys every box the same way plans 1–3 keyed text and buttons. Our code stamps names (`root`, `card`, `stats.0`). A copied section's elements are keyed by their place in the captured markup. The agent names its own boxes (`kit.Card el`, `data-clue-el`). Box styling is plan 3's box properties plus three new `_edits` properties (`gap`, `contentAlign`, `hidden`), drawn by the same scoped stylesheet. Moving an element either reorders a prop array (our sections, agent sections, the header's menu), remapping the moved items' `_edits` keys with them, or writes the parent's `order` list (copied sections, the shell). The clone filler and `shell.tsx` apply `order` before the markup is produced. The frame classifies a keyed element as text, button, container or image, reports its drawn box and its siblings, and lists the section as a tree.

**Tech Stack:** TypeScript, React 19, Puck 0.23.0 (pinned), Zod 4, node-html-parser, node:test via tsx, Python 3 + pytest + Playwright.

**Spec:** `docs/superpowers/specs/2026-10-17-site-element-inspector-design.md`. This is **plan 4**, and §7 is the source of truth (§7.2 plan 4, §7.3 coverage). When this plan starts, set §7.1 to "started"; when it finishes, set "finished". Add a §7.7 line for each ruling below that changes §2, §4 or §7.3 (R1, R2, R6, R8, R9).

## Rulings (decisions this plan makes where the spec leaves a choice; the founder checks them before Task 1)

- **R1: Clicking blank space in a section still selects the section.** A click selects the smallest keyed text, button, image or box under the pointer, **except the section's own box**. A click on nothing inside it selects the section, as today. The Section panel then shows the section's Content fields (as today) **and** Fill / Stroke / Layout for the section's own box. The same applies to the header and footer: clicking blank space selects "Header", and the panel shows its box controls plus its words.
- **R2: A section's box is two keys, like a button's box and label.** `root` is the outer box (our `<section>`, the header, the footer, an agent's `kit.Shell`): it takes fill, stroke and corners. `root.inner` is the box holding the brand's section padding (`.brand-content`): it takes padding, gap and content alignment, so a changed padding replaces the brand's padding instead of doubling it. Neither is ever a click target of its own. A copied section's box is its fragment's top element (key `0`), one key for everything. "Width" is disabled on a section's box with the note "A section always spans the page."
- **R3: Content alignment is the horizontal line-up of the box's contents, as drawn now.** It is stored with the CSS it set, so it means the same thing on the published page: `{ "along": "row" | "stack" | "grid" | "text", "to": "start" | "center" | "end" }`. In a row (`flex`, row direction) it sets `justify-content`. In a stack (`flex` column) it sets `align-items`. In a grid it sets `justify-items`. In a plain block it sets `text-align`. The frame reports which one the box is at the width the canvas is drawn at. A box that turns from a row into a stack on a phone keeps the same CSS property, as the seller's own CSS would.
- **R4: Gap works only where the browser uses it.** The Gap row is live only when the box is drawn as `flex` or `grid`. Otherwise it is disabled with the note "This box stacks its contents with the brand's spacing; gap applies to rows and grids."
- **R5: How a move is written, decided from the stored site (never from the drawn page).**
  - When the moved element's key is `<prop>.<n>`, the section's stored `<prop>` is an array, and every sibling is `<prop>.<m>`, the array is reordered. Every `_edits` key under `<prop>.<n>` and `<prop>.<n±1>` (the item itself, `<prop>.<n>.<sub>`, and styled spans `<prop>.<n>.<sub>~k`) swaps with it, and so does every `data-s="…"` naming them inside the two items' rich text. This covers our StatsBand stats, the header's `nav`, and an agent's array items.
  - Otherwise, in a copied section or the shell, the parent's `_edits[<parentKey>].order` is written as the full list of sibling keys in their new order.
  - Otherwise (our fixed layouts, an agent's plain layout) Move up and Move down are disabled with "This part's place is set by the section's design; ask the agent to move it."
- **R6: Arrange is offered for every selected element that has neighbours to move among,** including text, buttons, boxes and images, not only boxes (the mockup shows it on a box). Otherwise a menu link, the logo or a copied card's heading could not be moved. Content alignment stays on boxes only.
- **R7: The panel's title names what was clicked,** from the element as drawn, first rule that matches:
  - a section's box → "Section", or "Header" / "Footer";
  - `nav` → "Menu";
  - `li` → "List item";
  - `ul` / `ol` → "List";
  - `brand-card` or `stats.<n>` → "Card";
  - a box with a visible fill or stroke and corner radius > 0 → "Card";
  - `flex` row → "Row";
  - `flex` column → "Column";
  - `grid` → "Grid";
  - anything else → "Box".
  Layers uses the same names.
- **R8: Images become selectable in this plan** (keys on images; `kit.Image` takes `el`), with only what plan 4 owns: Arrange, Hide (shell only) and a Layers row. Otherwise the header's logo could not be hidden or moved. Plan 5 adds the image panel itself (replace, fit, alt text, stroke, corners). §7.2 and §7.3 move "selection for images" from plan 5 to plan 4 in the same commit as this plan.
- **R9: Hidden header and footer parts stay hidden in the editor too** (identical to the published page). They stay in Layers, dimmed with "(hidden)", and selecting that row offers "Show". `hidden` is refused on a page section with "`hidden` is for the header and footer; to drop a part of a section, rewrite the section". Agent sections can simply not draw a part.
- **R10: Pass-through wrappers are not listed and not clickable.** These are copied markup's wrapper divs: a box with exactly one element child, no words of its own, no visible fill or stroke, and the same drawn box as that child within 1px. They keep their key, so `order` and their siblings' keys are unchanged. Without this rule, a Webflow section's Layers would read "Box › Box › Box › Card".
- **R11: Shapes of the new `_edits` properties.** `gap` is 0–200 px. `contentAlign` is as in R3. `order` is 1–200 unique element keys (spans `~n` refused). `hidden` is `true` only (to show a part again, remove the property). Plan 3's `fill`, `borderColor`, `borderWidth`, `radius`, `padding` and `width` apply to boxes unchanged.

## Global Constraints

- Puck stays pinned at `@puckeditor/core` 0.23.0; no new dependencies.
- No free CSS: every value passes the strict override schema and is validated where it is written (`site_doc_validate.py` → site-kit validator → schema); colours are brand tokens or hex + opacity.
- `site-kit/src/sections.tsx` and `shell.tsx` carry no style values (`test/style-literals.test.ts`).
- Element keys never shift: a clone's keys come from the captured markup before slots, replacements or `order` apply; adding container keys never changes an existing text or button key (same child-index paths).
- A control that cannot act is shown disabled with a one-line note, never live and inert. Number boxes commit on blur / Enter; a colour drag settles 400 ms before it saves; every change is one save and one undo step.
- No new runtime flag. Nothing outside `subsystems/clue-design/` imports design internals.
- Tests: named files only; never the `subsystems/clue-design/apps/api/tests` folder; never `*_live.py` or broad suites with real keys. Python via `.superpowers/review/2026-10-13-wave2/pytest-keyless.sh <file>`. Browser tests: `CLUE_SITE_EDITOR_BROWSER=1` after `npm run build -w @clue/site-kit && npm run build -w @clue/site-editor` (from `apps/frontend`).
- Skill / prompt text is shown to the founder before it is written (Task 8).
- Commits: local only (push only when asked), no AI attribution, explicit paths, never `git stash`.

## Review Focus

1. **A copied Webflow section, three wrappers deep around a grid of cards.** Expected: a click between cards selects the grid, a click on a card's padding selects the card, and Layers shows Section › Grid › Card › texts without the wrappers. Restyling or moving a card never changes the key of any text inside it, and its `_edits` still apply after a reload. Pinned in Task 3 (keys + order) and Task 4 (pruning, click).
2. **Moving the second stat of a StatsBand up after its value was coloured and one word of its label styled.** Expected: the stat moves with its colour and its styled word; the stat it swapped with keeps its own styling; one save; undo restores both. Pinned in Task 5.
3. **Hiding the header's logo, reloading, then showing it again from Layers.** Expected: hidden in the editor and on the published page, listed as "Logo (hidden)", "Show" removes the property (the stored header equals the starting one). Pinned in Task 5 and Task 7.
4. **Content alignment on the footer's link group, which is a stack on phones and a row on desktop.** Expected: set on desktop → stored `along: "row"`, links centred along the row; on a phone the same `justify-content` applies to the stack (no surprise reflow of other parts). Pinned in Task 1 (CSS) and Task 9 (browser at 390 and 1440).
5. **An `order` naming a key the section no longer has (the agent rewrote the copied section's slots) or missing a new child.** Expected: unknown keys are ignored, unlisted children keep their places, the page draws, the save check accepts it. Pinned in Task 3.

---

### Task 1: The box properties in the `_edits` contract

**Files:**
- Modify: `apps/frontend/packages/site-kit/src/edits.ts` (schema, `declarations`, new `orderOf`)
- Modify: `apps/frontend/packages/site-kit/src/validate.ts:128-132` (`hidden` refused outside the shell)
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/site/workspace.py` (`_styled_by_hand`)
- Test: `apps/frontend/packages/site-kit/test/edits.test.ts`, `apps/frontend/packages/site-kit/test/validate-site.test.ts`, `subsystems/clue-design/apps/agent_runtime/tests/test_site_workspace.py`

**Interfaces:**
- Produces: `StyleOverrideSchema` gains `gap?: number (0–200)`, `contentAlign?: { along: "row"|"stack"|"grid"|"text"; to: "start"|"center"|"end" }` (strict), `order?: string[]` (1–200, each `ElementKeySchema` without `~`, unique), `hidden?: true`. `orderOf(edits: Edits): Record<string, string[]>` (every key with an `order`). `SHELL_ONLY_PROPS = ["hidden"] as const`.
- CSS (each `!important`, after plan 3's, in this order): `gap:Npx`. `contentAlign`: row → `justify-content:flex-start|center|flex-end`; stack → `align-items:flex-start|center|flex-end`; grid → `justify-items:start|center|end`; text → `text-align:left|center|right`. `hidden` → `display:none`. `order` emits no CSS.

- [ ] **Step 1: Write the failing tests** in `edits.test.ts`:
  - `gap, contentAlign, order and hidden parse; out-of-range and wrong shapes are refused`. Asserts `gap: 201` refused, `contentAlign: { along: "column", to: "center" }` refused, `order: ["a", "a"]` refused ("each key once"), `order: ["a~1"]` refused, `order: []` refused, `hidden: false` refused.
  - `box CSS for containers`: `editsCss("s1", { card: { gap: 12, contentAlign: { along: "stack", to: "center" }, hidden: true } }, brand)` equals `[data-clue-section="s1"] [data-clue-el="card"]{gap:12px !important;align-items:center !important;display:none !important}`. Also one assertion per `along` value with its exact property.
  - `orderOf lists the order of every key that has one; an order emits no CSS`.
  In `validate-site.test.ts`, `hidden is refused on a page section and accepted on the shell` asserts the message `pages./.content[0].props._edits.logo: hidden is for the header and footer; to drop a part of a section, rewrite the section`.

- [ ] **Step 2: Run them; expect FAIL** (`gap` is not in the strict schema).
  Run: `cd apps/frontend && npx tsx --test packages/site-kit/test/edits.test.ts packages/site-kit/test/validate-site.test.ts`

- [ ] **Step 3: Implement** the schema additions (a `.refine` on `order` for uniqueness, message `each key once in an order`), the declarations, `orderOf`, and in `validate.ts` the page-section loop's `hidden` refusal (the shell's `_edits` keep the plain `addEditsProblems`).

- [ ] **Step 4: Write the failing agent test** `test_site_md_reads_box_edits`: a section with `{"stats.1": {"gap": 12, "contentAlign": {"along": "row", "to": "center"}}, "0.2": {"order": ["0.2.1", "0.2.0"]}}` and the header `{"logo": {"hidden": True}}`. Expected `site.md` lines: `stats.1 — gap 12 px, contents centred along the row`, `0.2 — children in the order 0.2.1, 0.2.0`, `logo — hidden`. The words for `along` and `to` are: row "along the row", stack "in the stack", grid "in the grid", text "text"; start "to the start", center "centred", end "to the end".

- [ ] **Step 5: Run; expect FAIL; implement** in `_styled_by_hand`; **run; expect PASS** (both test files above and `pytest-keyless.sh subsystems/clue-design/apps/agent_runtime/tests/test_site_workspace.py`).

- [ ] **Step 6: Commit**
```bash
git add apps/frontend/packages/site-kit/src/edits.ts apps/frontend/packages/site-kit/src/validate.ts apps/frontend/packages/site-kit/test/edits.test.ts apps/frontend/packages/site-kit/test/validate-site.test.ts subsystems/clue-design/apps/agent_runtime/lumen_agent/site/workspace.py subsystems/clue-design/apps/agent_runtime/tests/test_site_workspace.py
git commit -m "site-kit: gap, content alignment, order and hidden in _edits (inspector plan 4)"
```

### Task 2: Keys on our boxes, the shell's parts and agent kit pieces; the shell applies `order`

**Files:**
- Modify: `apps/frontend/packages/site-kit/src/sections.tsx` (`Shell` stamps `root` / `root.inner`; per-section box and image keys)
- Modify: `apps/frontend/packages/site-kit/src/shell.tsx` (keys on every part, groups drawn in `order`)
- Modify: `apps/frontend/packages/site-kit/src/agent-kit.tsx` (`Card` and `Image` take `el`)
- Test: `apps/frontend/packages/site-kit/test/element-keys.test.tsx`, `apps/frontend/packages/site-kit/test/agent-kit.test.tsx`, `apps/frontend/packages/site-kit/test/style-literals.test.ts` (unchanged, must stay green)

**Interfaces:**
- Consumes: `orderOf` (Task 1).
- Produces these keys (each unique in its scope; existing text and button keys unchanged):
  - **Every `Shell`:** `root` on `<section>`, `root.inner` on `.brand-content`.
  - **StatsBand:** `lead` (eyebrow/heading/intro block), `stats` (the `dl`), `stats.<n>` (each stat).
  - **FeatureSplit:** `row` (the grid, or the one-column div), `image` (the `img`), `column` (the text column).
  - **ProofCard:** `card`, `figure` (its left half), `story` (its right half).
  - **CtaBand:** `column`.
  - **Header:** `root` (`<header>`), `root.inner`, `brand` (left group), `logo`, `divider`, `accountLogo`, `prepared` (the "Prepared for" line; `preparedFor` stays the name), `actions` (right group), `nav` (the `<nav>`; `nav.<n>` stay), `ctaArea` (the span around the button; `cta` stays).
  - **Footer:** `root`, `root.inner`, `logo`, `legal` (stays), `links`, `privacy`, `terms` (stay).
  - **Agent kit:** `kit.Card({ el })` → `data-clue-el` on its `a`/`div`; `kit.Image({ el })` → on its `img`. A hostile `el` gives no key (the existing `elementKey`).
  - `inOrder(parts: [key: string, node: ReactNode][], order: string[] | undefined): ReactNode[]` (shell.tsx, not exported from the package). Listed keys go into the positions listed parts occupy, in the list's order. Unknown keys are ignored. Unlisted parts keep their places. Applied to `brand`, `actions`, the footer's `root.inner` and `links`.

- [ ] **Step 1: Write the failing tests** in `element-keys.test.tsx`:
  - `our sections key their boxes`: render each section and assert the exact key list from `keys(html)`. StatsBand with an eyebrow and 2 stats gives, in document order, `root, root.inner, lead, eyebrow, heading, stats, stats.0, stats.0.value, stats.0.label, stats.1, stats.1.value, stats.1.label`.
  - `the header and footer key every part`: the two key lists above.
  - `the header draws its groups in order`: header `_edits: { brand: { order: ["prepared", "logo", "divider", "accountLogo"] }, actions: { order: ["ctaArea", "nav"] } }` → `prepared` comes before `logo` in the HTML, and `ctaArea` before `nav`.
  - `an order with unknown and missing keys keeps the rest in place`: `{ brand: { order: ["accountLogo", "ghost"] } }` leaves `logo, divider, accountLogo, prepared` unchanged (one listed part keeps its own position; "ghost" is ignored), and `["prepared", "logo"]` gives `prepared, divider, accountLogo, logo` (the two listed parts trade positions; the others stay).
  In `agent-kit.test.tsx`, `kit.Card and kit.Image take el` asserts `data-clue-el="cards.0"` on a valid `el` and no attribute for `el="x\" onclick"`.

- [ ] **Step 2: Run; expect FAIL.** `cd apps/frontend && npx tsx --test packages/site-kit/test/element-keys.test.tsx packages/site-kit/test/agent-kit.test.tsx`

- [ ] **Step 3: Implement.** `Shell` gains no prop (every Shell is a section box). The header's and footer's `order` come from `editsOf(header)` / `editsOf(footer)` through `orderOf`. Hidden parts need no React change: their `display:none` comes from the scoped stylesheet.

- [ ] **Step 4: Run; expect PASS,** plus `npx tsx --test packages/site-kit/test/style-literals.test.ts packages/site-kit/test/sections.test.tsx packages/site-kit/test/render-core.test.tsx` green.

- [ ] **Step 5: Commit** (`sections.tsx`, `shell.tsx`, `agent-kit.tsx`, both tests): `site-kit: keys on boxes, images and shell parts; the shell draws its parts in order (inspector plan 4)`.

### Task 3: Copied sections: every element keyed, `order` applied by the filler

**Files:**
- Modify: `apps/frontend/packages/site-kit/src/clone.ts` (`keyElements` replaces `keyTextElements`; `applyOrder`; `CloneExtras.order`; `cloneSiblingsAt`)
- Modify: `apps/frontend/packages/site-kit/src/config.tsx` (the section wrapper hands each render its edits; `ClonedSection` passes `order` to the filler)
- Test: `apps/frontend/packages/site-kit/test/clone-editing.test.tsx`, `apps/frontend/packages/site-kit/test/element-keys.test.tsx`, `apps/frontend/packages/site-kit/test/live-page.test.tsx`

**Interfaces:**
- Consumes: `orderOf` (Task 1).
- Produces:
  - `keyElements(root, slots)`. Every element child gets its child-index path key, except `script`, `style`, `noscript` and `template`. `svg`, `img`, `picture` and `video` are keyed but not walked into. A text element is keyed and not walked into (as today). An inline control is keyed and walked into (as today). Every other element is keyed and walked into. Existing text and button keys must not change.
  - `CloneExtras.order?: Record<string, readonly string[]>`. Applied right after keying, before slots: `applyOrder(root, order)` uses the same positions rule as Task 2's `inOrder`, over the parent's element children.
  - `cloneOrderOf(clone: Clone, parentKey: string): string[] | null` gives the captured order of a parent's keyed children (null when the key is not an element). Task 5 uses it to drop an `order` equal to the captured one.
  - `config.tsx`: `SectionScope` takes `children: (edits: Edits) => ReactNode`. The wrapper calls `render(withoutEdits(props), { edits })`. `ClonedSection`'s render passes `order: orderOf(context.edits)` in `extras` (both the editor's `CloneEditor` `htmlFor` and the plain render).

- [ ] **Step 1: Write the failing tests:**
  - `keys are unchanged for text and buttons when boxes are keyed` (`element-keys.test.tsx`): for `fixtures/garner-syracuse.json` and `fixtures/conduit-atrium.json`, every key the previous `keyTextElements` produced is still on the same element (compare against a key-to-text snapshot taken with the current code before the change, committed as `fixtures/clone-text-keys.json` in this step).
  - `wrapper divs, images and svgs are keyed by path; scripts are not`.
  - `order rearranges a parent's children before slots apply, and keys travel with their elements` (`clone-editing.test.tsx`): `fillClone(clone, {headline: "New"}, [], [], { order: { "0.1": ["0.1.2", "0.1.0", "0.1.1"] } })` gives the children of `[data-clue-el="0.1"]` in the order `0.1.2, 0.1.0, 0.1.1`, with the slot filled in its moved element.
  - `an order naming gone keys or leaving children out keeps the others in place` (Review Focus 5).
  - `a live page and the editor draw the same order` (`live-page.test.tsx`): `renderSitePages({ live: true })` with a ClonedSection carrying `_edits.order` records `cloneHtml` in that order, and the static render matches.

- [ ] **Step 2: Run; expect FAIL.** `cd apps/frontend && npx tsx --test packages/site-kit/test/element-keys.test.tsx packages/site-kit/test/clone-editing.test.tsx packages/site-kit/test/live-page.test.tsx`

- [ ] **Step 3: Implement.** `cloneLinkAt`, `cloneButtonAt` and `slotsInsideLinks` switch to `keyElements` (their keys are unchanged by construction; their tests stay green).

- [ ] **Step 4: Run the three files plus `clone-text.test.ts`, `element-sources.test.ts`, `rich-render.test.tsx`; expect PASS.**

- [ ] **Step 5: Commit** (`clone.ts`, `config.tsx`, tests, the fixture): `site-kit: every copied element keyed; order rearranges copied sections in the editor and on published pages (inspector plan 4)`.

### Task 4: The frame selects boxes and images, reports siblings and the tree

**Files:**
- Modify: `apps/frontend/packages/site-kit/src/editor-protocol.ts`
- Modify: `apps/frontend/packages/site-editor/src/client/dom.ts`
- Modify: `apps/frontend/packages/site-editor/src/client/editor-app.tsx` (describer)
- Modify: `apps/frontend/packages/site-editor/src/client/frame-controller.ts` (`selected` carries `sectionBox`)
- Test: `apps/frontend/packages/site-editor/test/dom.test.ts`, `apps/frontend/packages/site-kit/test/editor-protocol.test.ts`, `apps/frontend/packages/site-editor/test/frame-controller.test.ts`

**Interfaces:**
- Produces (protocol, all additive):
  - `ElementSummary.kind: "text" | "button" | "container" | "image"`, plus `parent: ElementKey | null` (its nearest listed ancestor; `null` at the top) and `hidden?: true`.
  - `ComputedContainerSchema = ComputedBoxSchema.extend({ gap: number (0–10 000), layout: "row" | "stack" | "grid" | "text", contentAlign: "start" | "center" | "end", name: string (≤ 40) })`.
  - `ArrangeSchema = { item: ElementKey; parent: ElementKey; siblings: ElementKey[] (2–200) }`. `item` is the selected element, or its keyed ancestor that is a direct child of `parent`.
  - `ElementSelection` gains `container?: ComputedContainer | null` and `arrange?: Arrange | null`.
  - `SectionBoxSchema = { outer: { key; box: ComputedBox }; inner: { key; container: ComputedContainer } }` (type `SectionBox`); the `selected` payload gains `sectionBox?: SectionBox | null`. For our sections, agent `kit.Shell` and the shell, these are `root` and `root.inner`; for a clone, both are key `0`; null for an agent section that draws no `kit.Shell` (its panel shows Content only).
- `dom.ts`:
  - `isImageElement(el)`: a keyed `img`, `picture`, `video` or `svg`.
  - `isContainerElement(el, view)`: keyed, not text, button or image; drawn with a box (`display` not `inline`/`contents`, width and height > 0); not a pass-through wrapper (R10).
  - `containerName(el, view): string` (R7).
  - `computedContainer(el, view, toHex): ComputedContainer` (layout: `flex` with `flex-direction` row → row, column → stack; `grid`/`inline-grid` → grid; else text; `contentAlign` read back from the matching property).
  - `arrangeOf(el, scope): Arrange | null`. Climb from the element until the parent element is keyed; that child is `item` and must be keyed. `siblings` are the parent's keyed element children in DOM order. Null when the climb reaches the scope, or when there are fewer than 2 siblings.
  - `inspectableElementsIn` returns `{ element, kind, parent }`, with containers and images added and the section box keys (`root`, `root.inner`, a clone's `0`) left out. It is capped at 500 in document order.
  - `elementKeyAt` picks the smallest box among all inspectable kinds (a button still wins over its words; the section box never wins).
  - Hidden shell parts (stored `_edits[key].hidden`) are listed with `hidden: true` even with no box. The frame reads the stored site for this.

- [ ] **Step 1: Write the failing tests** in `dom.test.ts` (the existing jsdom-style fake view):
  - `a card, a row, a stack and a grid are containers with their names and layouts`.
  - `a click between two cards selects their grid; on a card's padding the card; on blank section space nothing (the section)`.
  - `a pass-through wrapper is neither listed nor clickable; a wrapper with its own fill is`.
  - `the tree: each element's parent is its nearest listed ancestor`.
  - `arrangeOf: a stat among stats; the header's button via its ctaArea; a heading in our fixed layout has none`.
  - `a hidden header part is listed hidden; an inline span is not a container`.
  In `editor-protocol.test.ts`: `container and arrange round-trip; a sibling list with a span key or over 200 keys is refused`. In `frame-controller.test.ts`: `selected for a section carries its section box`.

- [ ] **Step 2: Run; expect FAIL.** `cd apps/frontend && npx tsx --test packages/site-editor/test/dom.test.ts packages/site-editor/test/frame-controller.test.ts packages/site-kit/test/editor-protocol.test.ts`

- [ ] **Step 3: Implement.** In `editor-app.tsx`:
  - `describeContainer` gives summary, computed typography (as for any element), `container`, `arrange`;
  - `describeImage` gives summary, `arrange`;
  - text and buttons gain `arrange`;
  - the describer returns `sectionBox` when no element is asked for.
  `shownElements` includes `parent` and `hidden`, so a change to the tree re-posts.

- [ ] **Step 4: Run; expect PASS.** Then the full `npm test -w @clue/site-editor` and `npx tsx --test packages/site-kit/test/editor-protocol.test.ts`.

- [ ] **Step 5: Commit:** `site editor: the frame selects boxes and images, reports their siblings and the section tree (inspector plan 4)`.

### Task 5: The app: box, move and hide commits; Layers as a tree

**Files:**
- Modify: `apps/frontend/src/features/site-editor/model/site-selection.ts`
- Create: `apps/frontend/src/features/site-editor/model/site-arrange.ts` (+ `site-arrange.test.ts`)
- Modify: `apps/frontend/src/features/site-editor/model/site-layers.ts`, `apps/frontend/src/features/site-editor/hooks/use-site-editing-session.ts`
- Test: `site-selection.test.ts`, `site-layers.test.ts`, `use-site-editing-session.scenario.test.ts`

**Interfaces:**
- Consumes: `Arrange`, `ElementSummary.parent/hidden`, `sectionBox` (Task 4); `cloneOrderOf` (Task 3).
- Produces:
  - `moveWrite(site, selection: { target; componentId; componentType }, arrange: Arrange): { kind: "array"; prop: string } | { kind: "order" } | { kind: "fixed"; reason: string }` (R5; the reason text verbatim from R5).
  - `commitMove(site, selection, arrange, direction: "up" | "down"): { props; site } | null`. Null at the ends, or when `fixed`. For an array, it swaps the items, renames `_edits` keys and `data-s` spans with `remapItemKeys`, and does all of this in one save. For an order, it writes `_edits[parent].order`, and drops `order` when it equals `cloneOrderOf` for a clone.
  - `remapItemKeys(props: Record<string, unknown>, prop: string, a: number, b: number): Record<string, unknown>`. It swaps the `<prop>.<a>` and `<prop>.<b>` prefixes in `_edits` keys (exact, or followed by `.` or `~`) and in `data-s="…"` attributes inside every string under the two items.
  - `commitHidden(site, selection, key, hidden: boolean)` writes `{ hidden: true }`, or removes it, via `commitStyleEdit`.
  - `SiteInspectorBinding` gains:
    - `arrange: { canUp: boolean; canDown: boolean; note: string | null } | null`, `onMove(direction)`;
    - `hide: { hidden: boolean } | null` (shell parts only), `onHideCommit(hidden)`;
    - `sectionBox: SectionBox | null`, `sectionBoxOverrides: { outer: StyleOverride | null; inner: StyleOverride | null }`.
  - `siteLayerRows` nests the selected section's elements by `parent`, `depth = 1 + ancestors`. Icons: text `type`, button `rectangle`, container `div`, image `image`. The label for a hidden row is `"<label> (hidden)"`; container labels are their `name` (R7).

- [ ] **Step 1: Write the failing tests** (`site-arrange.test.ts` unless noted):
  - `moving stat 1 up swaps the array and carries its edits and styled spans` (Review Focus 2). Start with `_edits: { "stats.1.value": {color}, "stats.1.label~1": {fontWeight:700}, "stats.0": {fill} }` and `stats[1].label` containing `data-s="stats.1.label~1"`. After the move, `stats[0]` is the old stat 1; `_edits` has `stats.0.value`, `stats.0.label~1` and `stats.1` (the fill moved with the old stat 0); the label's `data-s` reads `stats.0.label~1`.
  - `the header's menu link moves by reordering nav; its new-tab flag moves with it`.
  - `a copied card moves by writing order on its parent; moving it back drops the order`.
  - `a heading in FeatureSplit is fixed with the R5 note`.
  - `ends: the first cannot move up, the last cannot move down`.
  - `hide and show a header logo; showing restores the stored header exactly` (`site-selection.test.ts`).
  - `Layers nests boxes, texts and images by parent, names boxes, marks hidden parts` (`site-layers.test.ts`).
  - `a move is one save and one undo step` (`use-site-editing-session.scenario.test.ts`).

- [ ] **Step 2: Run; expect FAIL.** `cd apps/frontend && npx tsx --test src/features/site-editor/model/site-arrange.test.ts src/features/site-editor/model/site-selection.test.ts src/features/site-editor/model/site-layers.test.ts src/features/site-editor/hooks/use-site-editing-session.scenario.test.ts`

- [ ] **Step 3: Implement.** Save intents: `inspector: move <key> up|down`, `inspector: hide <key>` / `inspector: show <key>`, `inspector: style <key>` (box edits reuse `commitStyle`).

- [ ] **Step 4: Run; expect PASS.** Then `npm test` (app) green.

- [ ] **Step 5: Commit:** `site editor app: move, hide and box commits; Layers as the section's tree (inspector plan 4)`.

### Task 6: The box panel, Arrange, Hide and the Section panel

**Files:**
- Create: `apps/frontend/src/features/chat-shell/components/site-box-panel.tsx` (+ `site-box-panel.logic.ts`, `site-box-panel.logic.test.ts`)
- Create: `apps/frontend/src/features/chat-shell/components/site-arrange-section.tsx`
- Modify: `apps/frontend/src/features/chat-shell/components/site-button-panel.logic.ts` (its Fill / Stroke / Layout decisions move to `site-box-panel.logic.ts`, and the button panel imports them; no behaviour change), `site-button-panel.tsx`, `site-inspector.tsx`, `inspector-primitives.tsx` (only if `arrow-up` / `arrow-down` icons are missing)
- Test: `site-box-panel.logic.test.ts`, `site-button-panel.logic.test.ts` (unchanged, must stay green)

**Interfaces:**
- Consumes: binding fields from Task 5.
- Produces:
  - `boxPanelValues(override: StyleOverride | null, box: ComputedBox | ComputedContainer, palette): BoxPanelValues`. It is plan 3's `ButtonPanelValues` plus `gap: string`, `gapLive: boolean`, `layout`, `contentAlign: "start" | "center" | "end"`.
  - `boxPanelPatch(override, change: BoxPanelChange, box): StyleOverride | null`. It is plan 3's change set plus `{ kind: "gap"; value: string }` and `{ kind: "contentAlign"; to: "start" | "center" | "end" }`. The latter writes `{ along: box.layout, to }`. Out-of-range input is refused with a note, and no change returns the same override.
  - Panels, in the mockup's order:
    - **Box selected:** Fill · Stroke (Color, Width, Corner radius: Pill · number · Custom) · Layout (Padding Y · X, Gap (R4), Width Fill · Fit · Fixed) · Arrange (Order: ↑ Move up, ↓ Move down; Content alignment: three-option `TextAlignment`) · Hide (shell parts: "Show in the header/footer" switch) · Layers.
    - **Text, button, image:** their panels plus the Arrange section (Order only) and Hide where it applies.
    - **Image (plan 4):** Arrange, Hide and Layers, with the line "Image settings (replace, fit, alt text, corners) come in the next update." as a plain note, not a control.
    - **Section / Header / Footer selected (R1, R2):** the title is the section's name; then Content (as today); then Fill and Stroke on the outer key; then Layout (padding, gap, content alignment) on the inner key, with Width disabled with "A section always spans the page."

- [ ] **Step 1: Write the failing tests** in `site-box-panel.logic.test.ts`:
  - `values come from the override over the drawn box`;
  - `gap is live only for row, stack and grid`;
  - `content alignment writes the drawn layout with it`;
  - `padding, gap and radius refuse 201 with a note`;
  - `no change returns the same override`;
  - `the section box splits fill/stroke (outer) from padding/gap/alignment (inner)`.

- [ ] **Step 2: Run; expect FAIL.** `cd apps/frontend && npx tsx --test src/features/chat-shell/components/site-box-panel.logic.test.ts src/features/chat-shell/components/site-button-panel.logic.test.ts`

- [ ] **Step 3: Implement** the logic, the panels and the Arrange section. Disabled controls carry their note in the section, as plan 3's do.

- [ ] **Step 4: Run; expect PASS;** `npm run lint` (0 errors), `npx tsc --noEmit -p .` clean.

- [ ] **Step 5: Commit:** `site inspector: the box panel, Arrange, Hide and the Section panel (inspector plan 4)`.

### Task 7: Scenario tests through the real routes

**Files:**
- Create: `subsystems/clue-design/apps/api/tests/test_site_container_scenarios.py` (pattern: `test_site_button_scenarios.py`)

- [ ] **Step 1: Write the scenarios.** Each one goes through save → read → undo → redo → publish, and each checks the published HTML:
  1. A ProofCard's `card` with fill, stroke 2 px, corners 16, padding `{y: 24, x: 32}`, gap 12, `contentAlign {along: "grid", to: "center"}`, plus the section's `root` fill and `root.inner` padding. The published HTML carries the keys and the exact rules.
  2. StatsBand: stat 1 moved up with its edits remapped (the stored props as Review Focus 2), published in the new order.
  3. A copied section (Conduit fixture clone, minted as plan 3's test mints): `order` on a parent, published HTML children in that order with their keys.
  4. The header: `actions.order = ["ctaArea", "nav"]`, `logo.hidden = true`, a `nav` reorder. Published: the button before the menu, the logo drawn with `display:none`. Undo returns the stored header to its start.
  5. Refusals with their messages: `hidden` on a page section; `order: ["a","a"]`; `gap: 300`; `contentAlign {along: "column"}`.
- [ ] **Step 2: Run** `.superpowers/review/2026-10-13-wave2/pytest-keyless.sh subsystems/clue-design/apps/api/tests/test_site_container_scenarios.py`. Expected: 5 passed (after Tasks 1–3; fix the code, not the test, on a failure).
- [ ] **Step 3: Commit:** `api: scenario tests for boxes, moves and hidden header parts (inspector plan 4)`.

### Task 8: The agent's view and skill text (founder gate)

**Files:** `subsystems/clue-design/apps/agent_runtime/lumen_agent/site/skills-e5/writing-a-section/SKILL.md`, `.../site/skills/building-with-puck/SKILL.md`, `.../site/SKILLS-CHANGELOG.md`; `workspace.py` was done in Task 1.

- [ ] **Step 1: Draft and show the founder** (in chat, not written):
  - **writing-a-section:** name each box the marketer may style (`kit.Card el`, `data-clue-el` on your own `div`/`ul`/`li`), and name images (`kit.Image el`). To let the marketer reorder items, draw them from an array prop and name each `<prop>.<index>` (`el={`cards.${i}`}`).
  - **building-with-puck:** box properties in `_edits` (fill, stroke, corners, padding, gap, width, `contentAlign`) and what each does. `order` on copied sections and the shell (the full list of child keys). `hidden` on header/footer parts (drop the logo or a link). Our boxes' keys (`root`, `root.inner`, `card`, `stats.<n>` …). The header's rearranging and hiding is the agent's to do too.
- [ ] **Step 2: Write it only after the founder approves;** add the changelog line; commit `agent skills: boxes, order and hiding (inspector plan 4)`.

### Task 9: Browser proof, gates, live check

- [ ] **Step 1: Browser test** `tests/site_editor/test_editor_containers.py` (pattern: `test_editor_buttons.py`):
  - click a ProofCard card → `selected` kind container named "Card", with its container box;
  - click between StatsBand stats → "Grid"; blank section space → the section with `sectionBox`;
  - a copied Conduit section's card through three wrappers → the card, and Layers without the wrappers;
  - `set_props` fill / gap / contentAlign → computed styles;
  - footer links group `contentAlign` at 1440 and 390 (Review Focus 4);
  - header logo hidden → `display:none`, still listed.
- [ ] **Step 2: Gates:**
  - site-kit, site-editor and app test suites;
  - frontend gate (`npm run design-system:build && npm run lint && npm run build`, with the lane stack down; this also pays plan 3's and the responsive type's owed build);
  - bundles rebuilt;
  - the named API files: render, publish package, publish routes, write routes, validation, element-edits, rich-text, button and container scenarios.
- [ ] **Step 3: Live check on Garner** (Carmel Clay: a ProofCard card, the StatsBand move, the header logo hide/show, the footer links alignment) **and on Conduit** (a copied card move and restyle). Do every control, reload, then undo back to the starting version and verify the stored site equals it. Clue has no microsite in the lane: report it, as plans 1–3 did. Update spec §7.1 (finished, with the date), §7.7 and `_memory`.
