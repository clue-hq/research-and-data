# Site element inspector, plan 2: highlighted words, links on text, more fonts — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (the founder's rule since 2026-10-17: the plan is implemented directly, one whole-branch review at the end). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In the Puck site editor a marketer highlights some words in a piece of text and styles just those words (colour, font, size, weight, bold, italic, underline) with the panel saying "N words selected"; edits an existing text link or turns highlighted words (or a whole text box) into a link to a web address or a page of the site, in the same tab or a new one; and picks from the brand's fonts and then the ad editor's font library. Copied-section text replacements the check accepts are always applied (S1-3).

**Architecture:** Text the marketer edits in place becomes *rich text*: a small, closed, inline-only HTML grammar (`strong em u s br`, `a[href][data-new-tab]`, `span[data-s]`), validated where it is written and drawn by one site-kit function on the published page and by Puck's `richtext` field (TipTap) in the editor. Highlighted-word styling never stores CSS in the text: a word range is wrapped in `<span data-s="<element key>~<n>">` and the span's look is an ordinary `_edits` entry, so plan 1's strict override schema, stylesheet and panel logic apply unchanged. The frame reports the highlighted range as character offsets inside the selected element; the app turns (stored text, offsets, change) into the new text and `_edits` with pure site-kit functions and writes both in one save. Library fonts reach the site through the brand data; a section that uses one carries its `@font-face` rules, and publishing ships those faces as WOFF2 like the brand's.

**Tech Stack:** TypeScript, React 19, Puck 0.23.0 (pinned) and its TipTap 3.31.4, Zod 4, node-html-parser, node:test via tsx, Python 3 + pytest + Playwright.

**Spec:** `docs/superpowers/specs/2026-10-17-site-element-inspector-design.md`. This is **plan 2**; §7 is the source of truth (§7.2 plan 2 scope, §7.3 coverage). Update §7.1 when this plan starts and finishes, and §7.7 for every ruling below that changes §2/§4.

## Rulings (decisions this plan makes where the spec leaves a choice)

- **R1 — Rich text is inline only.** The stored grammar is `strong em u s br`, `a` and `span[data-s]` (optionally inside one outer `<p>`, which is what the editor writes and which the render drops). No bullet lists and no second paragraph inside one text box: Enter makes a line break. Spec §4.4 listed `p ul ol li` from the R5 spike; block markup inside a heading or a `<p>` breaks the published HTML (`<p>` inside `<p>` is split by the browser) and would force every section's and every agent section's wrappers to change. Today's text has no lists, so nothing is lost. *Cost if wrong:* lists later need a block-level text kind.
- **R2 — Panel styling of words goes through styled spans.** Bold / weight / italic / underline / colour / font / size on highlighted words set the span's `_edits` override (plan 1's `textPanelPatch` on the span). ⌘B / ⌘I / ⌘U typed in the text still make `<strong>` / `<em>` / `<u>` (TipTap's own marks). One span key covers one run of words; restyling part of a styled run splits it.
- **R3 — Alignment belongs to the whole box.** With words highlighted, Alignment is shown disabled with the note "Alignment applies to the whole text box."
- **R4 — Which text takes word-level edits:** brand-section text edited in place today except link and button labels (`linkLabel` is the link itself; button labels are plan 3); agent props marked `.meta({ edit: "inline" })` whose element's `data-clue-el` is the prop's own name (the skill tells the agent so); clone text slots. Everything else (clone text with no slot, header and footer words until plan 6, stats values) shows the word and new-link controls disabled with a one-line note.
- **R5 — Links.** An existing link is edited where it lives: ProofCard `linkHref` (+ new `linkNewTab`), header `nav[i].href` (+ new `nav[i].newTab`), footer `privacyHref` / `termsHref` (+ new `privacyNewTab` / `termsNewTab`), a clone link through its `href` slot, else a `links` replacement (the panel says when that changes every link with the same address in the section); a clone link's new tab is the new ClonedSection prop `newTab: string[]` (element keys). A link inside rich text is the `<a>` itself. New links are made only in rich text.
- **R6 — The dock shows rich fields read-only** (their words, with "Edit these words on the page"): a plain text box cannot edit markup without losing it.
- **R7 — Library fonts:** the Font list shows the brand's families, then the library's under "Other fonts". A section (or the header/footer) whose `_edits` name a library family carries that family's `@font-face` rules in its own scoped stylesheet; publishing re-encodes those faces to WOFF2 into the workspace store like the brand's fonts.

## Global Constraints

- Puck stays pinned at `@puckeditor/core` 0.23.0; site-kit adds `@tiptap/core` at exactly the version Puck resolves (3.31.4), imported only from the editor entry (`@clue/site-kit/editor`), never from the published runtime.
- No free CSS and no inline `style` anywhere in stored text: rich text is validated by the closed grammar (Task 2) where it is written; a span's look is an `_edits` entry.
- The published page's runtime carries no HTML parser: the render-time transform is a small grammar-specific tokenizer (Task 2).
- A control that cannot act is shown disabled with a one-line note, never live and inert.
- Every change in the panel is one save and one undo step; number boxes commit on blur / Enter.
- No new runtime flag (none needed). Nothing outside `subsystems/clue-design/` imports design internals.
- Tests: named files only; never the `subsystems/clue-design/apps/api/tests` folder; never `*_live.py` or broad suites with real keys. Browser tests: `CLUE_SITE_EDITOR_BROWSER=1` after `npm run build -w @clue/site-kit && npm run build -w @clue/site-editor`, via `.superpowers/review/2026-10-13-wave2/pytest-keyless.sh`.
- Skill / prompt text is shown to the founder before it is written (Task 10).
- Commits: local only, no AI attribution, explicit paths, never `git stash`.

## Review Focus

1. **Typing after styling words.** Expected: the styled span and links survive the next keystroke in the TipTap editor (the span and link marks are in the editor's schema), and a save of the typed text keeps them. Pinned in Task 5 (browser).
2. **Text pasted from another site** (a `<p style="text-align:center">`, a `<div>`, a `<script>`, a `target` attribute). Expected: the save never fails; what is saved is the grammar's (`normalizeRich`), the rest dropped. Pinned in Task 2 and Task 5.
3. **Restyling words that overlap an already styled run.** Expected: every highlighted word ends with the new property; words outside the highlight keep theirs. Pinned in Task 2.
4. **The selection after a save.** Expected: after a word style is written and the canvas redraws, the panel still acts on the same words (a redraw never clears the frame's word selection; only the marketer's own click or keystroke does). Pinned in Task 6 and Task 9.
5. **A link to a page that is later deleted, or a malformed address.** Expected: the panel refuses with a note before saving; the validator refuses it on any write with a fix hint. Pinned in Task 3 and Task 8.

---

### Task 1: S1-3 — clone text replacements are applied exactly when the check accepts them

**Files:** Modify `site-kit/src/clone.ts`, `catalog.ts`, `validate.ts`. Test `site-kit/test/clone-text.test.ts`.

**Interfaces:** Produces `replaceableTexts(clone: Clone): string[]` (clone.ts) — every text node outside a text slot and outside `script style svg noscript template`, entity-decoded, whitespace collapsed, trimmed, deduplicated, Webflow `{{wf` placeholders skipped. `fillClone`'s replacement matches a text node whose decoded, collapsed text equals `find` collapsed, and keeps the node's leading and trailing whitespace.

- [ ] Tests: on a fragment with `&amp;`, a `<br>`-wrapped phrase, a bold-spanning phrase and a phrase that is half a paragraph — the catalog lists the decoded texts; the validator accepts exactly `replaceableTexts` and refuses the wrapped, partial and bold-spanning phrases with the catalog hint; every accepted replacement appears in `fillClone`'s output.
- [ ] Implement; run `npm test -w @clue/site-kit`; commit.

### Task 2: The rich text grammar and its pure functions (site-kit)

**Files:** Create `site-kit/src/rich.ts`; modify `edits.ts` (key grammar, span selector); test `site-kit/test/rich.test.ts`, extend `edits.test.ts`.

**Interfaces (all from `rich.ts`, isomorphic, no DOM, no parser dependency):**
- `type Run = { text: string; br?: true; strong?: true; em?: true; u?: true; s?: true; link?: { href: string; newTab: boolean }; style?: string }`.
- `parseRich(html: string): Run[] | { error: string }` — accepts the grammar (tags case-insensitive; `b`/`i` read as `strong`/`em`; one optional outer `<p>`; entities decoded); refuses anything else with a sentence a writer can act on.
- `serializeRich(runs: Run[]): string` — canonical inline HTML: marks nest `a > span > strong > em > u > s`, adjacent runs with equal marks merge, text escaped (`& < >`, `"` in attributes).
- `richText(html: string): string` — the visible characters (for offsets, Layers and the agent's view); `<br>` counts as nothing (as DOM `textContent` does).
- `richProblems(html: string, isLink: (href: string) => string | null): string[]`.
- `normalizeRich(html: string): string` — anything into the grammar, dropping disallowed tags (keeping their text) and attributes; idempotent; `normalizeRich(x) === x` for canonical input.
- `richHtml(html: string, href: (value: string) => string): string` — the published markup: outer `<p>` dropped, `data-new-tab` becomes `target="_blank" rel="noopener"`, internal hrefs through `href`; an unparseable input is escaped as text (never raw markup).
- `styleWords(html, start, end, apply: (old: StyleOverride) => StyleOverride, edits: Edits, elementKey: string): { html: string; edits: Edits }` — runs in `[start, end)` get `apply(their override)`; a span key wholly inside is updated in place, others get new keys `<elementKey>~<n>` (next free n); spans no longer present are dropped from `edits`.
- `linkWords(html, start, end, link: { href: string; newTab: boolean } | null): string` — sets or removes the link on the range (a range inside a link edits that whole link).
- `linkAt(html, start, end): { href: string; newTab: boolean; start: number; end: number } | null`.
- `edits.ts`: `ElementKeySchema` also allows one `~<digits>` suffix; `editsCss` writes `[data-s="k"]` for a key with `~`; `isSpanKey(key)`.

- [ ] Tests (one per behaviour): round trips of every mark; entities; one outer `<p>`; refusal sentences for `<div>`, `style=`, `<a href="javascript:…">`, unknown attribute, unclosed tag; `normalizeRich` on TipTap's output, a pasted `<p style="text-align:center">`, `<script>`; `richHtml` new-tab and base path; `styleWords` on plain text, inside an existing span (key reused), across a span boundary (split, every highlighted word gets the property, outside words keep theirs), dropping orphaned keys; `linkWords` add / edit / remove; `richText` offsets equal DOM `textContent` offsets for `<br>`.
- [ ] Implement; run; commit.

### Task 3: Rich props in the contract — schemas, validator, catalog, new link props

**Files:** Modify `site-kit/src/schemas.ts`, `validate.ts`, `catalog.ts`, `agent-props.ts`, `shell.tsx` types; tests `validate-site.test.ts`, `catalog.test.ts`, new `rich-props.test.ts`.

**Interfaces:** `RICH_PROPS: Record<"StatsBand"|"FeatureSplit"|"ProofCard"|"CtaBand", readonly string[]>` (= R4's list); `richPropPaths(schema: JsonSchema): string[]` (agent inline props, nested as `cards.*.title`); `richValuesOf(type, props, brand, agentSchemas): { path: string; value: string }[]` (brand, agent and clone text slots). New props: ProofCard `linkNewTab?: boolean`; shell `nav[].newTab?: boolean`, footer `privacyNewTab?`, `termsNewTab?`; ClonedSection `newTab?: string[]` (element keys).

- [ ] Tests: a rich value with a disallowed tag is refused at `content.N(id).<path>` with the grammar sentence; an internal `<a href="/missing">` is refused like every other internal link; the new props validate; the catalog prints rich fields as `rich text (bold, italic, underline, links, styled words)`.
- [ ] Implement; run site-kit tests; commit.

### Task 4: Drawing rich text and new tabs everywhere it appears

**Files:** Modify `site-kit/src/sections.tsx`, `config.tsx` (agent rich props, ClonedSection), `clone.ts` (rich slot values, `newTab`), `shell.tsx` (new tab), `theme.ts` (no change expected); tests `render-core.test.tsx`, `clone-editing.test.tsx`, `live-page.test.tsx`.

**Interfaces:** `rich(value: unknown, href: Href): ReactNode` — a ReactNode passes through (the editor's widget); a string becomes `<span data-clue-rich="" dangerouslySetInnerHTML={{__html: richHtml(value, href)}}/>` only when it holds markup (`/[<&]/`), else stays the string. Agent sections: rich prop strings are converted the same way before `module.render` (published and preview only). `fillClone(clone, values, replacements, links, newTab?)` writes a text slot's value as rich markup; `newTab` keys get `target="_blank" rel="noopener"`.

- [ ] Tests: static render of each brand section with a styled span and a link shows the markup and the scoped rule; a live page hydrates to the same HTML; an agent section with a plain inline prop still receives a string; a clone slot holding rich text keeps its key and its words styled; new-tab links render with `target`/`rel`.
- [ ] Implement; run; commit.

### Task 5: The editor's rich text fields

**Files:** Create `site-kit/src/editor/rich-text.ts` (TipTap extensions); modify `site-kit/src/sections.tsx` + `config.tsx` (`EditorParts.richText`), `site-kit/src/editor/clone-editor.tsx` (rich slots), `site-kit/package.json` (`@tiptap/core` 3.31.4), `site-editor/src/client/fields.ts` (agent inline props → richtext; dock kind), `site-editor/src/client/frame-controller.ts` (`pageEdited` normalizes rich props), `site-editor/src/client/keys.ts` (⌘B/⌘I/⌘U pass inside editable text), `site-editor/src/client/styles.css`, `site-kit/src/editor-protocol.ts` (`FieldKind` `"richtext"`); app dock component for `richtext`; tests `site-editor/test/fields.test.ts`, `keys.test.ts`, `frame-controller.test.ts`, browser `tests/site_editor/test_editor_rich_text.py`.

**Interfaces:** `richTextField(label: string): RichtextField` — `contentEditable: true`, options turning off heading, code, codeBlock, blockquote, horizontalRule, lists, link (ours replaces it); `tiptap.extensions`: a one-paragraph document, Enter as a line break, `ClueLink` mark (`a[href]`, `data-new-tab`), `ClueStyle` mark (`span[data-s]`). `richFromDom(element: Element): string` (clone slots; browser). `normalizeRichProps(type, props, …)` used by `pageEdited`.

- [ ] Tests: field mapping (brand rich props and agent inline props become `richtext`, the rest unchanged; the dock gets `richtext`); ⌘I inside editable text is not swallowed; `pageEdited` saves `normalizeRich` output.
- [ ] Browser: type in a brand heading, ⌘B a word, reload — `<strong>` kept; a stored styled span survives typing; a clone slot keeps bold typed with ⌘B; pasting a centred paragraph saves without error.
- [ ] Implement; run; commit.

### Task 6: The frame reports highlighted words and link information

**Files:** Modify `site-kit/src/editor-protocol.ts` (`ElementSummary.rich`, `ElementSelection.words`, `ElementSelection.link`), `site-editor/src/client/dom.ts`, `frame-controller.ts`, `editor-app.tsx`; tests `dom.test.ts`, `frame-controller.test.ts`, `editor-protocol.test.ts`.

**Interfaces:** `ElementSummary.rich?: { prop: string; fallback?: string } | null` (prop path holding the words; `fallback` = `richFromDom` of an unset clone slot); `ElementSelection.words?: { start: number; end: number; count: number; text: string; computed: ComputedTypography } | null`; `ElementSelection.link?: { href: string; newTab: boolean; source: LinkSource } | null` where `LinkSource` names where the link is written (`{kind:"prop", href, newTab}` / `{kind:"slot", slot}` / `{kind:"replacement", find, shared}` / `{kind:"rich"}`). `selectionOffsets(element, selection): {start,end} | null` (dom.ts). `FrameController.wordsSelected(target, componentId, key, words | null, userAction: boolean)`: a non-collapsed range posts `selected` with `words`; a collapse posts `words: null` only after a pointer or key action in the frame (a redraw never clears it).

- [ ] Tests: offsets over `<br>`, nested marks and ProseMirror's trailing break; the controller's post rules (redraw collapse kept, user collapse cleared, same range not re-posted).
- [ ] Implement; run; commit.

### Task 7: The panel — words mode

**Files:** Modify `features/site-editor/model/site-selection.ts`, `hooks/use-site-editing-session.ts`, `chat-shell/components/site-text-panel.tsx` + `.logic.ts`; tests `site-selection.test.ts`, `site-text-panel.logic.test.ts`, `use-site-editing-session` test bridge.

**Interfaces:** `commitWordStyle(site, selection, words, override patch fn) → {props, site} | null` and `wordsOverride(site, selection)` (site-selection.ts); binding gains `words`, `onWordStyleCommit`. The panel header reads "N words selected"; values from the words' override over `words.computed`; Alignment disabled with R3's note; a stale range (stored text no longer matches the frame's text) is refused with "The text changed — highlight the words again."

- [ ] Tests: one commit writes the prop and `_edits` together; restyling the same words reuses the key; the lock disables; stale text refused.
- [ ] Implement; run; commit.

### Task 8: The Link row

**Files:** Create `chat-shell/components/site-link-row.tsx` + `.logic.ts`; modify `site-text-panel.tsx`, `site-selection.ts`, session hook; tests `site-link-row.logic.test.ts`, `site-selection.test.ts`.

**Interfaces:** `linkPatch(site, selection, link: { href: string; newTab: boolean } | null) → {props, site} | {refused: string}` for each `LinkSource`; page choices = the site's routes. The row: address (a page of this site, or a web address), "Open in a new tab", Remove; disabled with R4's notes where no link can be made.

- [ ] Tests: each source writes the right prop; a missing page and a malformed address are refused with a note; a shared replacement says so; removing a rich link unwraps it.
- [ ] Implement; run; commit.

### Task 9: Library fonts

**Files:** Modify `site-kit/src/brand.ts` (`libraryFonts`), `edits.ts` (`editsProblems`, `editsCss` font faces, `libraryFontFamilies`), `subsystems/clue-design/apps/api/lumen_api/site_brand.py` + `site_workspace_view.py` (manifest → `library_fonts`), `site_publish.py` (`gated_brand` ships used library faces as WOFF2), app font list (`site-text-panel.tsx`, `inspector-primitives` select groups if needed); tests `edits.test.ts`, `test_site_brand*.py`, `test_site_publish_*` named files.

- [ ] Tests: a library family validates with its own weights; its `@font-face` rules ride in the section's stylesheet only when used; publish ships the face from the workspace store; the Font list orders brand then library.
- [ ] Implement; run; commit.

### Task 10: The agent's view and skill text (founder gate)

**Files:** `lumen_agent/site/workspace.py` (`site.md` shows rich text as words with "(bold: …; link: … → …)" and styled spans), tests `test_site_workspace.py`; skills `writing-a-section` and `building-with-puck` (rich text grammar, names = prop names for inline props, links and `data-new-tab`, library fonts in `_edits`), `SKILLS-CHANGELOG`.

- [ ] Draft the skill text, show it to the founder, write it only after approval.

### Task 11: Scenario tests, browser proof, gates, live check

- [ ] API scenario `apps/api/tests/test_site_rich_text_scenarios.py`: save → read → undo → redo → publish of a styled span, a new-tab link and a library font; refusals.
- [ ] Browser `tests/site_editor/test_editor_words_and_links.py`: highlight → style → reload; link create / edit / remove; selection survives the redraw.
- [ ] Gates: site-kit, site-editor, app tests, pin tests, frontend gate (`design-system:build`, `lint`, `build` with the lane stack down), bundles rebuilt.
- [ ] Live on Garner and Conduit (Clue has no microsite in the lane): style words, link words, library font; reload; publish; undo. Update spec §7.1, `_memory`.
