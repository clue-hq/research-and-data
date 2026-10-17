# Site element inspector, plan 3: buttons — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (the founder's rule since 2026-10-17: the plan is implemented directly, one whole-branch review at the end). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A marketer clicks any button on a Puck microsite — in our sections, in a copied seller section, the header's call-to-action, or an agent's section — and the right-hand panel edits everything about it, as in the approved mockup (`.superpowers/brainstorm/95737-1792238115/content/site-inspector-button.html`, "4 · Button selected"): its label (words and typography, highlighted words too), fill, stroke (colour, width, corner radius: pill, a number, custom corners), layout (padding, width: fit / fill / fixed) and link (a web address or a page of this site; same tab or new tab). Every change shows on the canvas, is one save and one undo step, and looks the same on the published page.

**Architecture:** A button is two keyed elements: its **box** (the `<a>`/`<button>`, key `<k>`) and its **label** (key `<k>.label` for our buttons and kit buttons; for a clone, the text element inside it, or the box itself when the words are its own). Box styling is new `_edits` properties on the box key (`fill`, `borderColor`, `borderWidth`, `radius`, `padding`, `width`), drawn by the same scoped stylesheet; label typography is plan 1's text override on the label key; label words are rich text without links (plan 2's grammar, `links: false`). The frame classifies a keyed link-or-button as a button when the browser draws it as a box, reports it with its label and its computed box, and the app writes box, label and link through the existing one-save path. The one-primary-destination rule moves into one shared site-kit function the save check and the panel both use.

**Tech Stack:** TypeScript, React 19, Puck 0.23.0 (pinned), TipTap 3.31.4, Zod 4, node-html-parser, node:test via tsx, Python 3 + pytest + Playwright.

**Spec:** `docs/superpowers/specs/2026-10-17-site-element-inspector-design.md`. This is **plan 3**; §7 is the source of truth (§7.2 plan 3, §7.3 coverage). Update §7.1 when this plan starts and finishes, and §7.7 for every ruling below that changes §2/§4.

## Rulings (decisions this plan makes where the spec leaves a choice — for the founder to check)

- **R1 — A button is a box and a label.** Box properties go on the box's key; the label's colour, font, size, weight, B/I/U go on the label's key. Our sections key their button `button` (label `button.label`), the header's is `cta` (`cta.label`), an agent's button takes `kit.Button`'s new `el` (`<el>`, `<el>.label`). A clone's button is keyed by its place in the captured markup like every clone element.
- **R2 — What counts as a button.** Our `Button` and the header's; `kit.Button` when the agent names it; in a clone, an `<a>` or `<button>` whose content is inline only (words, icons, no blocks or images) **and** which the browser draws as a box (not `display: inline`, or with a background or a border). A plain text link stays a text link (plan 2). A link wrapping a whole card is a container (plan 4).
- **R3 — Button labels are rich text without links** (the mockup: "Highlighting words inside the label styles just those words"). `buttonLabel` and `ctaLabel` join `RICH_PROPS` with the no-links grammar; a clone text slot whose element sits inside a link refuses `<a>` too (a link may not hold a link — plan 2's review finding 2, closed at the save check as well).
- **R4 — Hand-set fill and stroke also hold on hover and focus.** The brand's hover change is replaced for that button (our rules are `!important` on the element in every state). The Fill row says so in one line.
- **R5 — One primary destination stays the rule.** Every button that leaves the site goes to one place (the existing save check). When a button's new address leaves the site and differs from the page's destination, the Link section refuses with a note naming the current destination and offers **"Use for every button"**, which moves every primary button to the new address in one save.
- **R6 — An agent's button:** box, label typography and highlighted words are styleable (when named); its words and its link are the agent's props, which the editor cannot name from the element, so those two rows show disabled with "The agent's section sets this button's words and link; ask the agent to change them." (as plan 2 for agent links).
- **R7 — A clone button's words** are edited through its text slot when it has one; else through a text replacement when the words are one replaceable text (S1-3's `replaceableTexts`); else the Text row shows disabled with "This button's words are copied from the seller's page and have no slot." Its link: href slot, else link replacement (plan 2), with new tab by element key.
- **R8 — The Link section takes the mockup's layout for every link**, text links included: "Goes to" (Web address · Page on this site), the address or the page, "Open in" (Same tab · New tab), Remove where a link can be removed. Plan 2's row behaviour is unchanged; only its controls change.
- **R9 — Shapes of the new `_edits` properties:** `fill` and `borderColor` a colour (brand token or hex + opacity); `borderWidth` 0–200 px; `radius` 0–200 px, `"pill"`, or four corners `[topLeft, topRight, bottomRight, bottomLeft]` each 0–200; `padding` 0–200 px or `{ "y": 0–200, "x": 0–200 }`; `width` `"fit"`, `"fill"` or 1–2000 px. `fill` also clears a background image (a gradient button turns flat); `borderWidth` sets a solid border.

## Global Constraints

- Puck stays pinned at `@puckeditor/core` 0.23.0; no new dependencies.
- No free CSS: every box value passes the strict override schema and is validated where it is written; colours go through brand tokens or hex + opacity.
- `site-kit/src/sections.tsx` and `shell.tsx` carry no style values (`test/style-literals.test.ts`).
- A control that cannot act is shown disabled with a one-line note, never live and inert.
- Every change in the panel is one save and one undo step; number boxes commit on blur / Enter; a colour drag settles before it saves (plan 1's 400 ms).
- No new runtime flag. Nothing outside `subsystems/clue-design/` imports design internals.
- Tests: named files only; never the `subsystems/clue-design/apps/api/tests` folder; never `*_live.py` or broad suites with real keys. Browser tests: `CLUE_SITE_EDITOR_BROWSER=1` after `npm run build -w @clue/site-kit && npm run build -w @clue/site-editor`, via `.superpowers/review/2026-10-13-wave2/pytest-keyless.sh`.
- Skill / prompt text is shown to the founder before it is written (Task 8).
- Commits: local only (push only when asked), no AI attribution, explicit paths, never `git stash`.

## Review Focus

1. **A button whose brand look has hover and focus states.** Expected: a hand-set fill / stroke / radius holds in every state and the note says so; untouched buttons keep the brand's hover. Pinned in Task 1 (CSS) and Task 9 (browser, `:hover` computed style).
2. **A clone button whose words sit in a `<span>` inside the `<a>`, with an icon `<svg>`.** Expected: the click selects the button (not the span); the label is the span; styling the box never moves the icon; the key survives a slot fill. Pinned in Task 2 and Task 4.
3. **Changing a button to an external address that differs from the page's destination.** Expected: refused before saving with the note and "Use for every button"; that action moves every primary button in one save, and the save check passes. Pinned in Task 3 and Task 6.
4. **Width "fill" on a button inside a row of buttons, and on the header's button.** Expected: the button stretches to its own container's width and nothing else moves; the header keeps one row. Pinned in Task 9 (browser geometry).
5. **A label with highlighted words styled, then the label retyped in the Text box.** Expected: the Text box shows the words; retyping replaces the words and drops styled spans whose words are gone (their `_edits` entries are dropped with them); one save. Pinned in Task 5.

---

### Task 1: The box properties in the `_edits` contract

**Files:** `site-kit/src/edits.ts`, `site-kit/test/edits.test.ts`; `lumen_agent/site/workspace.py` (`_styled_by_hand` words), `apps/agent_runtime/tests/test_site_workspace.py`.

**Interfaces:** `StyleOverrideSchema` gains `fill`, `borderColor` (`ColorValueSchema`), `borderWidth` (0–200), `radius` (0–200 | `"pill"` | 4-tuple 0–200), `padding` (0–200 | `{y, x}` strict), `width` (`"fit"` | `"fill"` | 1–2000). `editsProblems` checks `fill` and `borderColor` tokens like `color`. `declarations` writes, in schema order: `background-color` + `background-image:none`; `border-color`; `border-width` + `border-style:solid`; `border-radius` (`9999px` for pill, four values for corners); `padding` (`Ypx Xpx`); `width` (`fit-content` / `100%` / `Npx`) — each `!important`.

- [ ] Tests: each property parses and refuses its out-of-range and wrong-shape values; the exact CSS for each; an unknown `fill` token is reported at its key; `site.md` reads them ("fill text.inverse, stroke 2 px #0F59B0 100%, corners pill, padding 12 × 22 px, full width").
- [ ] Implement; run site-kit and agent workspace tests; commit.

### Task 2: Keys, labels and new-tab props on every button

**Files:** `site-kit/src/sections.tsx` (`Button` takes `el`; FeatureSplit / CtaBand pass `button`), `shell.tsx` (`cta`), `agent-kit.tsx` (`kit.Button` `el`), `clone.ts` (`keyElements`: inline-only `a`/`button` keyed too, walking into them so their words keep their own key; `cloneButtonAt`), `schemas.ts` (`buttonNewTab` on FeatureSplit / CtaBand, `ctaNewTab` on the header; `buttonLabel` / `ctaLabel` rich without links), `rich.ts` (`richProblems(html, { links: false })`, `normalizeRich(html, { links: false })`), `rich-props.ts` (no-links props; a clone text slot inside a captured link is no-links), `validate.ts`, `config.tsx` (editor fields), tests `element-keys.test.tsx`, `rich-props.test.ts`, `rich.test.ts`, `rich-render.test.tsx`.

**Interfaces:** `Button({ …, el?: string, newTab?: boolean })` renders `data-clue-el={el}` on the `<a>` and `data-clue-el={`${el}.label`}` on its words. `cloneButtonAt(clone: Clone, key: string): { labelKey: string; labelSlot: string | null; labelText: string | null; href: string | null; hrefSlot: string | null; shared: boolean } | null`. `RICH_PROPS_NO_LINKS = { FeatureSplit: ["buttonLabel"], CtaBand: ["buttonLabel"] }` and the header's `ctaLabel`.

- [ ] Tests: our sections' and the header's buttons carry `button`/`button.label` and `cta`/`cta.label`; `kit.Button` with a valid `el` carries `<el>`/`<el>.label`, a hostile one none; a clone's `<a class="btn"><svg/><span>Book</span></a>` keys the `<a>` and the span with stable paths and never shifts a sibling's key; `cloneButtonAt` for slot, replacement and no-source cases; a link inside a button label (ours, the header's, a clone slot inside a link) is refused with "a button's words may not hold a link"; new-tab props render `target`/`rel`.
- [ ] Implement; run; commit.

### Task 3: One primary destination, one function

**Files:** create `site-kit/src/destinations.ts`; modify `validate.ts`; test `site-kit/test/destinations.test.ts`.

**Interfaces:** `primaryDestinations(site: { pages; shell }, brand: BrandData, propsSchemaOf: PropsSchemaOf): { href: string; where: string; set: (href: string) => SiteChange }[]` — every button that leaves the site (our buttons, the header's, clone `cta*` href slots, agent `*cta*`/`*button*` href props), with a pure setter for "Use for every button". The validator's rule calls it (same messages as today).

- [ ] Tests: the same destinations the validator found before (Garner and Conduit fixtures); the rule's error text unchanged; the setters move every destination and the result validates.
- [ ] Implement; run site-kit tests (all, the rule's old tests included); commit.

### Task 4: The frame selects buttons

**Files:** `site-kit/src/editor-protocol.ts` (`ElementSummary.kind: "text" | "button"`; `ElementSelection.label?: { key; computed; rich }`, `box?: ComputedBox`, `labelSource?: LabelSource`); `site-editor/src/client/dom.ts` (`isButtonElement`, `computedBox`, `buttonAround`; `elementKeyAt` prefers the button over its label); `editor-app.tsx` (describeElement for buttons: label, box, label source, link source, primary flag); tests `dom.test.ts`, `editor-protocol.test.ts`, `frame-controller.test.ts`.

**Interfaces:** `ComputedBox = { fill: string /* #RRGGBB or "" */; borderColor: string; borderWidth: number; radius: [number, number, number, number]; paddingY: number; paddingX: number; width: number }`. `LabelSource = { kind: "prop"; prop: string } | { kind: "slot"; slot: string } | { kind: "replacement"; find: string } | { kind: "fixed"; reason: string }`. `ElementSelection.primary?: boolean` (a button that leaves the site counts toward the destination).

- [ ] Tests: classification (boxed `a`, inline text link, card link, `<button>`); a click on a button's words selects the button; the computed box read from styles; the protocol refuses a bad label key or source.
- [ ] Implement; run; commit.

### Task 5: The app — button selection, box, label and link commits

**Files:** `features/site-editor/model/site-selection.ts` (`commitButtonBox`, `commitLabelText`, binding fields), `hooks/use-site-editing-session.ts`, `chat-shell/components/site-link-row.logic.ts` (button link sources, destination check, `useForEveryButton`); `model/site-layers.ts` (button rows, icon "button"); tests `site-selection.test.ts`, `site-link-row.logic.test.ts`, `site-layers.test.ts`.

**Interfaces:** `commitButtonBox(site, selection, override)` writes the box key's override (one save); label typography reuses `commitStyleEdit` on `label.key` and `commitWordStyle` on the label's words; `commitLabelText(site, selection, text)` writes the label source (prop / slot / replacement), keeping styled spans whose words survive and dropping orphaned `~n` entries; `linkPatch` gains the button sources (`buttonHref`/`buttonNewTab`, `ctaHref`/`ctaNewTab`, clone slot / replacement) and returns `{ refused, useForEveryButton: href }` when the destination rule would break.

- [ ] Tests: each commit is one save and one undo step; a stale label refused; the destination refusal and the every-button change; Layers lists buttons under their section.
- [ ] Implement; run; commit.

### Task 6: The button panel and the Link section's new layout

**Files:** create `chat-shell/components/site-button-panel.tsx` + `.logic.ts`; modify `site-inspector.tsx`, `site-text-panel.tsx` (label mode: Text box first, typography on the label), `site-link-row.tsx` (R8 layout); tests `site-button-panel.logic.test.ts`.

**Interfaces:** sections in the mockup's order — Typography (Text box, colour, font, size, weight, B/I/U), Fill (`ColorControl`; R4 note), Stroke (colour, width, corner radius: Pill · number · Custom with four corners via `RadiusControls`), Layout (padding Y · X, width Fit · Fill · Fixed with a px box), Link, Layers. `buttonPanelValues(override, box, palette)` and `buttonPanelPatch(override, change)` (refuses out-of-range input with a note, returns the same override for no change).

- [ ] Tests: values from override over computed box; each change's patch; refusals; pill / custom corners round-trip; width fixed needs a number.
- [ ] Implement; run app tests and lint; commit.

### Task 7: Scenario tests through the real routes

**Files:** create `apps/api/tests/test_site_button_scenarios.py`.

- [ ] Save → read → undo → redo → publish: a FeatureSplit button with fill, stroke, pill corners, padding, full width and a styled label word; the header's button with a new-tab link; a clone button's words through its slot. The published HTML carries the keys, the rules and `target`/`rel`. Refusals: radius 300, a link inside a button label, two external destinations.
- [ ] Run; commit.

### Task 8: The agent's view and skill text (founder gate)

**Files:** `lumen_agent/site/workspace.py` (`site.md`: buttons with their look and new tab), tests; skills `writing-a-section` (name every button: `kit.Button el`), `building-with-puck` (button `_edits` properties, `buttonNewTab` / `ctaNewTab`, labels take rich text without links), `SKILLS-CHANGELOG`.

- [ ] Draft the skill text, show it to the founder, write it only after approval.

### Task 9: Browser proof, gates, live check

- [ ] Browser `tests/site_editor/test_editor_buttons.py`: click a brand button, a clone button (span + svg) and the header's button → `selected` kind button with label and box; set fill / radius / width through `set_props` → computed styles, hover included; the label's words styled.
- [ ] Gates: site-kit, site-editor, app tests; frontend gate (`design-system:build`, `lint`, `build` with the lane stack down); bundles rebuilt; named API files (render, publish package, publish routes, write routes, validation, element-edits and rich-text scenarios).
- [ ] Live on Garner (Carmel Clay: the CTA band's button, the header's) and Conduit (a clone hero button): every control, reload, undo back to the starting version (verify the stored site equals it). Update spec §7.1, `_memory`.
