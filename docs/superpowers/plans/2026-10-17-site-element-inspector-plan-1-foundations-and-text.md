# Site element inspector, plan 1: foundations and whole-box text styling — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In the Puck site editor, a marketer clicks a piece of text inside any section (brand, agent, cloned) or in the header/footer, and the right-hand panel styles that whole text box — colour (brand or custom), font (brand families), size, weight, bold / italic / underline, alignment — with the change shown on the canvas, saved as one undo step, and identical on the published page.

**Architecture:** Every styleable text element carries `data-clue-el="<key>"` (stamped by our sections, the shell and the clone filler; written by the agent in its own sections). A section's manual styling lives in one reserved prop, `_edits` (element key → a strict style override), validated with the page and turned by one site-kit function into a scoped `<style>` emitted with the section in the editor and the published render alike. The frame resolves a click to the keyed element under the pointer, reports it with its computed typography, and the app's inspector writes `_edits` through the existing `set_props` + save path.

**Tech Stack:** TypeScript, React 19, Puck 0.23.0 (pinned), Zod 4, node:test via tsx, Python 3 + pytest + Playwright (browser and API scenario tests).

**Spec:** `docs/superpowers/specs/2026-10-17-site-element-inspector-design.md` (approved by the founder 2026-10-17). This plan delivers spec §7 step 0 (foundations, text elements only) and step 1's first part (whole-box typography). Later plans: 2 = rich text, highlighted words, links on text, library fonts, S1-3; 3 = buttons; 4 = containers and Arrange; 5 = images.

## Global Constraints

- Puck stays pinned at `@puckeditor/core` 0.23.0.
- No free CSS anywhere: every stored style value passes the strict `StyleOverrideSchema` (Task 1) and is validated where it is written.
- Props still may not be named `className` or `style` (`site-kit/src/schemas.ts:4-6`, `render-core.tsx:130`); `_edits` is the one sanctioned styling prop.
- `site-kit/src/sections.tsx` carries no style values (`test/style-literals.test.ts`); keys are data attributes, not styles.
- A control that cannot act is shown disabled with a one-line note, never live and inert (spec §3 anti-goals).
- Every runtime flag goes in `.env.example` with its default. This plan adds none.
- Nothing outside `subsystems/clue-design/` imports design internals.
- Tests: named files only. Never run `subsystems/clue-design/apps/api/tests` as a folder (7–8 h). Never run `*_live.py` or broad suites with real keys. Browser tests: `CLUE_SITE_EDITOR_BROWSER=1` after `npm run build -w @clue/site-editor`, via `.superpowers/review/2026-10-13-wave2/pytest-keyless.sh`.
- Skill or prompt text (`writing-a-section`, `building-with-puck`) is drafted and shown to the founder before it is written (Task 10).
- Commits: local only, no AI attribution, explicit paths, never `git stash`.

## Review Focus

1. **A style edit on a cloned section must not rebuild its DOM** (images reload, editable slots stop being editable — `config.tsx` / `clone-markup.tsx` notes). Expected: changing `_edits` re-renders only the `<style>`; the clone's markup node is the same node. Pinned in Task 9 (browser).
2. **An `_edits` entry whose key no longer matches an element** (the agent rewrote the section). Expected: no error on save or render; the rule matches nothing. Pinned in Task 1 and Task 2.
3. **A token the brand no longer has** (a kit re-capture renamed it) in stored `_edits`. Expected: the validator reports it on the next write with a fix hint; the render skips that one declaration and the page still renders. Pinned in Task 1 and Task 2.
4. **A hostile or malformed key written by the agent** (`data-clue-el='"]{}body{color:red'`). Expected: the frame ignores keys failing `ElementKeySchema`; `editsCss` emits only schema-valid keys and values. Pinned in Task 2 and Task 4.
5. **Editing while the agent-run lock holds.** Expected: every text-panel control is disabled (the existing `display: contents` fieldset) and no `set_props` is sent. Pinned in Task 7.

---

### Task 1: The `_edits` contract (site-kit)

**Files:**
- Create: `apps/frontend/packages/site-kit/src/edits.ts`
- Modify: `apps/frontend/packages/site-kit/src/schemas.ts` (`pageSchemaWith` ~L124-170; `ShellSchema` L182-205)
- Modify: `apps/frontend/packages/site-kit/src/validate.ts` (brand checks next to the surface/look checks)
- Modify: `apps/frontend/packages/site-kit/package.json` `exports` if subpath exports are listed (add `./edits`)
- Test: `apps/frontend/packages/site-kit/test/edits.test.ts`

**Interfaces:**
- Produces (all exported from `site-kit/src/edits.ts`):
  - `EDITS_PROP = "_edits"`, `ELEMENT_KEY_ATTR = "data-clue-el"`, `SECTION_SCOPE_ATTR = "data-clue-section"`, `SHELL_SCOPE = { header: "shell-header", footer: "shell-footer" } as const`
  - `ElementKeySchema = z.string().regex(/^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$/)`
  - `ColorValueSchema`: `{ token: string(1..100) }` strict **or** `{ hex: /^#[0-9A-Fa-f]{6}$/, opacity: int 0..100 }` strict
  - `StyleOverrideSchema` strict, all optional: `color: ColorValue`, `fontFamily: string(1..100)`, `fontSize: number 8..200`, `fontWeight: int 100..900, multipleOf 100`, `italic: boolean`, `underline: boolean`, `textAlign: "left"|"center"|"right"|"justify"`
  - `EditsSchema = z.record(ElementKeySchema, StyleOverrideSchema)`; types `ColorValue`, `StyleOverride`, `Edits`
  - `editsOf(props: Record<string, unknown>): Edits` — the parsed `_edits`, or `{}` when absent or invalid
  - `withoutEdits<T extends Record<string, unknown>>(props: T): Omit<T, "_edits">`
  - `withStyleOverride(edits: Edits, key: string, override: StyleOverride): Edits` — drops properties set to `undefined`, drops the key when its override is empty
  - `brandColorChoices(brand: BrandData): { token: string; hex: string }[]` — every colour token of the kit, kit order (reuse `theme.ts`'s token readers; export them if private)
  - `brandFontFamilies(brand: BrandData): { family: string; weights: number[] }[]` — distinct `brand.fonts` families, weights ascending
  - `editsProblems(edits: Edits, brand: BrandData): string[]` — `"<key>: <message>"` lines: unknown colour token; `fontFamily` not a brand family; `fontWeight` not one of that family's weights (only checked when the override names `fontFamily`)

- [ ] **Step 1: Write the failing tests** in `test/edits.test.ts` (use the Garner fixture kit `test/fixtures/kits/garner.v3.json` where a brand is needed):

```ts
test("a valid override parses and an unknown property is refused", () => {
  assert.ok(StyleOverrideSchema.safeParse({ color: { token: "text.heading" }, fontSize: 48, fontWeight: 600, italic: true, textAlign: "center" }).success);
  assert.equal(StyleOverrideSchema.safeParse({ fontSize: 48, letterSpacing: 2 }).success, false);
  assert.equal(StyleOverrideSchema.safeParse({ color: { hex: "#0F59B0" } }).success, false); // opacity required
  assert.equal(StyleOverrideSchema.safeParse({ fontWeight: 650 }).success, false);
  assert.equal(StyleOverrideSchema.safeParse({ fontSize: 7 }).success, false);
});
test("element keys refuse anything that could break out of a selector", () => {
  for (const bad of ['"]{}body{', "", "-x", "a b", "x".repeat(101)]) assert.equal(ElementKeySchema.safeParse(bad).success, false, bad);
  for (const good of ["heading", "stats.2.value", "0.2.1", "nav.0", "my_title-2"]) assert.ok(ElementKeySchema.safeParse(good).success, good);
});
test("withStyleOverride removes cleared properties and empty entries", () => {
  const a = withStyleOverride({}, "heading", { fontSize: 48, italic: true });
  assert.deepEqual(withStyleOverride(a, "heading", { fontSize: 48, italic: undefined }), { heading: { fontSize: 48 } });
  assert.deepEqual(withStyleOverride(a, "heading", {}), {});
});
test("the page schema validates _edits beside any section's own props, including a strict agent schema", () => {
  const agent = { Hero: z.object({ id: z.string(), surface: z.string(), headline: z.string() }).strict() };
  const page = (edits: unknown) => ({ root: { props: {} }, content: [{ type: "Hero", props: { id: "hero", surface: "page", headline: "Hi", _edits: edits } }] });
  assert.ok(pageSchemaWith(agent).safeParse(page({ headline: { fontSize: 40 } })).success);
  const bad = pageSchemaWith(agent).safeParse(page({ headline: { fontSize: 1 } }));
  assert.equal(bad.success, false);
  assert.deepEqual(bad.error!.issues[0].path.slice(0, 5), ["content", 0, "props", "_edits", "headline"]);
});
test("the shell's header and footer accept _edits", () => { /* ShellSchema.safeParse with header._edits and footer._edits → success */ });
test("an entry for a key no element has is valid (the agent may have rewritten the section)", () => { /* pageSchemaWith(...) with _edits: { gone: { italic: true } } → success */ });
test("brand checks: unknown token, non-brand family, missing weight", () => {
  const problems = editsProblems({ heading: { color: { token: "no.such" } }, body: { fontFamily: "Comic Sans" }, lead: { fontFamily: "<a garner family>", fontWeight: 100 } }, garner);
  assert.equal(problems.length, 3);
  assert.match(problems[0], /^heading: /);
});
test("validateSite reports _edits brand problems with their place", () => { /* a page.json whose section has a bad token → an error line containing "_edits.heading" */ });
```

- [ ] **Step 2: Run to verify they fail** — `cd apps/frontend/packages/site-kit && npx tsx --test test/edits.test.ts` → FAIL (module `../src/edits` not found).
- [ ] **Step 3: Implement** `edits.ts` per the Interfaces block. In `pageSchemaWith`, parse each entry with `withoutEdits(entry.props)` against its section schema, and when `_edits` is present parse it with `EditsSchema`, reporting issues at `["content", index, "props", "_edits", ...]`. Add `_edits: EditsSchema.optional()` to `ShellSchema`'s header and footer objects. In `validate.ts`, run `editsProblems` for every section's and the shell's `_edits` and report each line at the existing place format (`page.content.3(proof)._edits.<key>: …`, `shell.header._edits.<key>: …`), each ending with how to fix it.
- [ ] **Step 4: Run** `npx tsx --test test/edits.test.ts test/validate-site.test.ts test/contracts.test.ts` → PASS.
- [ ] **Step 5: Commit** — `git add apps/frontend/packages/site-kit/src/edits.ts apps/frontend/packages/site-kit/src/schemas.ts apps/frontend/packages/site-kit/src/validate.ts apps/frontend/packages/site-kit/test/edits.test.ts` (+ package.json if changed); message `site-kit: the _edits contract — one validated style override per element key`.

### Task 2: Applying `_edits` — the scoped stylesheet, in the editor and the published render

**Files:**
- Modify: `apps/frontend/packages/site-kit/src/edits.ts` (add `editsCss`)
- Modify: `apps/frontend/packages/site-kit/src/config.tsx` (wrap every page component render; strip `_edits` before `module.render`)
- Modify: `apps/frontend/packages/site-kit/src/shell.tsx` (scope attribute + style on `<header>` / `<footer>`)
- Modify: `apps/frontend/packages/site-kit/src/theme.ts` (`themeCss`: one rule `.clue-section{display:contents}`)
- Test: `apps/frontend/packages/site-kit/test/edits.test.ts`, `apps/frontend/packages/site-kit/test/render-core.test.tsx`

**Interfaces:**
- Consumes: Task 1's schema, constants, `editsOf`, `withoutEdits`.
- Produces: `editsCss(scope: string, edits: Edits, brand: BrandData): string`. One rule per key: `[data-clue-section="<scope>"] [data-clue-el="<key>"]{…}`; every declaration `!important` (the clones' own CSS is unlayered, so a layered rule would lose — builder check, spec §4.5). Mapping: `color` token → `var(--brand-<colorVar(token)>)` when the token has a root variable, else the kit's literal colour; unknown token → declaration skipped; hex + opacity → `#RRGGBBAA`; `fontFamily` → `"<family>", <generic from the brand's type stack or sans-serif>` (quoted with theme.ts's `cssString`); `fontSize` → `px`; `fontWeight`; `italic` → `font-style:italic`; `underline` → `text-decoration-line:underline`; `textAlign`. A key failing `ElementKeySchema` or an override failing `StyleOverrideSchema` emits nothing. Empty result → `""`.
- Produces: page sections render inside `<div data-clue-section="<id>" class="clue-section">{style?}{section}</div>`; the shell's `<header data-clue-section="shell-header">` / `<footer data-clue-section="shell-footer">` render their `<style>` as first child. The style element is `<style data-clue-edits="">` and is omitted when `editsCss` returns `""`.

- [ ] **Step 1: Failing tests.**

```ts
test("editsCss: tokens through the theme's variables, hex with opacity, important declarations", () => {
  const css = editsCss("hero", { heading: { color: { token: "text.heading" }, fontSize: 48, fontWeight: 600, italic: true, textAlign: "center" }, lead: { color: { hex: "#0F59B0", opacity: 80 } } }, garner);
  assert.match(css, /\[data-clue-section="hero"\] \[data-clue-el="heading"\]\{[^}]*color:var\(--brand-[^)]+\) !important/);
  assert.match(css, /font-size:48px !important/);
  assert.match(css, /\[data-clue-el="lead"\]\{color:#0F59B0CC !important\}/);
});
test("editsCss skips an unknown token and every invalid key or value, and returns '' for nothing", () => {
  assert.equal(editsCss("s", { heading: { color: { token: "gone" } } }, garner), "");
  assert.equal(editsCss("s", { '"]{}body{': { italic: true } } as never, garner), "");
  assert.equal(editsCss("s", {}, garner), "");
});
// render-core.test.tsx
test("a static render carries the section's edits next to it and never passes _edits to an agent section", () => { /* renderSitePages with a CtaBand having _edits.heading and an agent section whose render throws if props._edits exists → html contains data-clue-section="cta" and the rule; no throw */ });
test("a live render carries the same stylesheet the browser will draw", () => { /* renderSitePages({live:true}) → the same <style data-clue-edits> text as a static render of that section */ });
test("the header's edits are scoped to the header", () => { /* shell.header._edits.preparedFor → css under [data-clue-section="shell-header"] */ });
test("a section with no _edits has no style element", () => { /* no data-clue-edits in the html */ });
```

- [ ] **Step 2: Run** `npx tsx --test test/edits.test.ts test/render-core.test.tsx` → FAIL.
- [ ] **Step 3: Implement** `editsCss`; in `makeConfig` wrap every page component's `render` (brand sections, `ClonedSection`, agent sections) once, centrally; pass `withoutEdits(props)` to `module.render`; in `SiteHeader` / `SiteFooter` read `editsOf(header)` / `editsOf(footer)`. Add `.clue-section{display:contents}` to `themeCss`.
- [ ] **Step 4: Run** the two files plus `test/live-page.test.tsx test/hydration-spike.test.tsx test/sections.test.tsx test/style-literals.test.ts test/clone-editing.test.tsx` → PASS (update only expectations that pinned the old exact HTML, and say which in the commit message).
- [ ] **Step 5: Commit** `site-kit: a section's _edits drawn as a scoped stylesheet beside it, editor and published page alike`.

### Task 3: Element keys on text elements

**Files:**
- Modify: `apps/frontend/packages/site-kit/src/sections.tsx`, `src/shell.tsx`, `src/agent-kit.tsx`, `src/clone.ts`
- Test: `apps/frontend/packages/site-kit/test/sections.test.tsx`, `test/agent-kit.test.tsx`, `test/clone-editing.test.tsx` (or a new `test/element-keys.test.tsx`)

**Interfaces:**
- Consumes: `ELEMENT_KEY_ATTR` (Task 1).
- Produces:
  - Brand sections stamp `data-clue-el` with exactly these keys: StatsBand `eyebrow`, `heading`, `intro`, `stats.<i>.value`, `stats.<i>.label`, `source`; FeatureSplit `eyebrow`, `heading`, `body`; ProofCard `kicker`, `metric`, `metricLabel`, `heading`, `body`, `source`, `linkLabel`; CtaBand `heading`, `body`. (Button labels are plan 3.) `Eyebrow` takes an optional `el` prop.
  - Shell: header `preparedFor` (the account-name span), `nav.<i>`; footer `legal`, `privacy`, `terms`.
  - Kit: `kit.Eyebrow` and `kit.Link` take optional `el?: string`, stamped as `data-clue-el` only when it passes `ElementKeySchema`. (`kit.Button`/`Card`/`Image` get `el` in their plans.)
  - Clones: `fillClone` stamps `data-clue-el="<path>"` on every **text element** of the captured markup — an element (outside `script`, `style`, `svg`, `noscript`) with at least one non-whitespace direct text child, not inside an already-keyed element. `<path>` is the element's child-index chain from the fragment root (`0.2.1`), computed on the captured markup **before** any slot is applied, so hiding a slot never shifts another element's key.

- [ ] **Step 1: Failing tests.** For each brand section, render with the fixture brand and assert the exact set of `data-clue-el` values in the HTML (e.g. FeatureSplit → `["eyebrow","heading","body"]` when all three have text). For the shell, `["preparedFor","nav.0"]` and `["legal","privacy","terms"]`. For a clone fixture with `<div><p>One</p><p>Two <b>bold</b></p></div>`: keys `0.0` and `0.1`, and `b` unkeyed; the same clone with its first `<p>` behind a `visibility:false` slot keeps `0.1` on the second `<p>`. `kit.Link({ el: '"]{}x', … })` renders no `data-clue-el`.
- [ ] **Step 2: Run** the test files → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the site-kit suite (`npm test -w @clue/site-kit`) → PASS.
- [ ] **Step 5: Commit** `site-kit: text elements carry stable keys — brand sections, the shell, kit pieces and clones`.

### Task 4: The frame — element selection

**Files:**
- Modify: `apps/frontend/packages/site-kit/src/editor-protocol.ts`
- Modify: `apps/frontend/packages/site-editor/src/client/dom.ts`, `editor-app.tsx`, `frame-controller.ts`, `styles.css`
- Test: `apps/frontend/packages/site-kit/test/editor-protocol.test.ts`, `apps/frontend/packages/site-editor/test/dom.test.ts`, `test/frame-controller.test.ts`

**Interfaces:**
- Produces (editor-protocol):
  - `ComputedTypographySchema = { color: /^#[0-9A-F]{6}$/, fontFamily: string(max 200), fontSize: number, fontWeight: number, italic: boolean, underline: boolean, textAlign: "left"|"center"|"right"|"justify" }`
  - `ElementSummarySchema = { key: ElementKeySchema, kind: z.literal("text"), label: string(max 80) }` (label = the element's text, whitespace-collapsed, cut at 60 characters)
  - `ElementSelectionSchema = ElementSummarySchema.extend({ computed: ComputedTypographySchema })`
  - `selected` payload gains `element: ElementSelectionSchema.nullable().default(null)` and `elements: z.array(ElementSummarySchema).max(500).default([])` (the keyed text elements of the selected section, document order)
  - `select` payload gains `elementKey: ElementKeySchema.nullable().optional()`
  - Protocol version stays 2 (additive, both sides ship together).
- Produces (dom.ts, DOM-only, tested with fake elements):
  - `keyedElementsIn(scope: Element): Element[]` — `[data-clue-el]` descendants with a schema-valid key and kind text
  - `keyedElementAt(scope: Element, point: { x: number; y: number }): Element | null` — the smallest-area keyed element whose bounding rect contains the point. (Puck sets `pointer-events: none` on everything inside `[data-puck-component]`, so the click target is the section itself; hit-testing is the only way.)
  - `elementSummary(element: Element): ElementSummary`; `computedTypography(element: Element, view: Pick<Window, "getComputedStyle">): ComputedTypography` (rgb → `#RRGGBB`; weight number; `italic` from font-style; `underline` from text-decoration-line; `start`→`left`, `end`→`right`)
  - `clickIntent`'s `component` and `shell` actions carry `elementKey: string | null`
- Produces (frame-controller): `FrameSelection = { componentId: string; target: SiteTarget; elementKey: string | null }`. `componentSelected(componentId, componentType, fields, props, elements: ElementSummary[], element: ElementSelection | null)` and `shellSelected(part, elements, element)` post `selected` with both; a click on another element of the already-selected section posts `selected` again with the new element (today's early return only skips an identical `(componentId, elementKey)`). `select` with `elementKey` selects the section and then the element.
- The selected element gets the attribute `data-clue-el-selected`; `styles.css` outlines it like the shell's selection (`[data-site-shell-selected]`, `styles.css:19`). The attribute is set imperatively and re-applied after every page re-render (`state.site` / `mountKey` change), never via React state on `<Puck>` (`editor-app.tsx:123-126`).

- [ ] **Step 1: Failing tests.** editor-protocol: a `selected` with `element` and `elements` round-trips; a `select` with `elementKey: '"]{}'` is refused. dom.test: `keyedElementAt` picks the inner `<span data-clue-el="b">` over its keyed parent when both rects contain the point, returns null outside every rect, ignores an element whose key fails the schema; `computedTypography` maps `rgb(15, 89, 176)` → `#0F59B0`, `700` → 700, `text-align: start` → `left`. frame-controller.test: clicking element `heading` then `body` in the same selected section posts two `selected` messages with `element.key` `heading` then `body`; `select({ componentId: "cta", elementKey: "heading" })` ends with selection `{ componentId: "cta", elementKey: "heading" }`.
- [ ] **Step 2: Run** `npx tsx --test test/dom.test.ts test/frame-controller.test.ts` (site-editor) and `npx tsx --test test/editor-protocol.test.ts` (site-kit) → FAIL.
- [ ] **Step 3: Implement.** In `editor-app.tsx`'s capture click handler, resolve `keyedElementAt(component, {x: event.clientX, y: event.clientY})` (shell: within the `<header>`/`<footer>`), compute its summary and typography, and hand them to the controller; `PuckBridge` passes `keyedElementsIn` of the selected component when Puck reports a selection.
- [ ] **Step 4: Run** `npm test -w @clue/site-editor` and `npm test -w @clue/site-kit` → PASS.
- [ ] **Step 5: Commit** `site editor: a click selects the text element under the pointer and the frame reports its typography`.

### Task 5: The app — selection, Layers and the style commit

**Files:**
- Modify: `apps/frontend/src/features/site-editor/model/site-selection.ts`, `model/site-layers.ts`, `hooks/use-site-editing-session.ts`
- Test: `apps/frontend/src/features/site-editor/hooks/use-site-editing-session.test.ts`, a new `model/site-selection.test.ts`, `model/site-layers` tests if present (else add `model/site-layers.test.ts`)

**Interfaces:**
- Consumes: Task 4's message fields; Task 1's `withStyleOverride`, `editsOf`, `EDITS_PROP`.
- Produces:
  - `SiteSelection` gains `element: ElementSelection | null` and `elements: ElementSummary[]`.
  - `commitStyleEdit(site: SiteDocument, selection: { componentId: string; target: string }, key: string, override: StyleOverride): { props: Record<string, unknown>; site: SiteDocument } | null` — writes `props._edits = withStyleOverride(editsOf(props), key, override)`, removing `_edits` when it becomes `{}`; null when nothing changes.
  - `SiteLayerRow` gains `elementKey?: string` and `depth?: 0 | 1`; `siteLayerRows` lists the selected section's `elements` as depth-1 rows (icon `"type"`, label = the element's label) right under that section's row; the active row is the selected element when there is one.
  - `SiteInspectorBinding` gains `element: ElementSelection | null`, `elementOverride: StyleOverride | null` (read from the app's own copy, never from the message), `onStyleCommit: (key: string, override: StyleOverride) => void`, `palette: { label: string; value: string }[]` (from `brandColorChoices`, label = token, value = hex), `fonts: { family: string; weights: number[] }[]` (from `brandFontFamilies`).
  - `onStyleCommit` follows `commitField` exactly (current copy, lock check, `copy.edit`, `set_props`, `save(edit.site, "inspector: style <key>")`), so each commit is one save and one server undo step.
  - `selectLayer` on a depth-1 row posts `select` with `elementKey`.

- [ ] **Step 1: Failing tests.** `commitStyleEdit` on a CtaBand adds `_edits.heading`; clearing the last property removes `_edits`; on the shell target writes `shell.header._edits`. `siteLayerRows` with a selection holding two elements returns the section row followed by two depth-1 rows, the selected one active. Session test: a `selected` message with an element sets `inspector.element`; `onStyleCommit("heading", { italic: true })` posts one `set_props` whose props carry `_edits.heading.italic === true` and calls save once; while `locked`, it posts nothing.
- [ ] **Step 2: Run** `cd apps/frontend && npx tsx --test src/features/site-editor/model/site-selection.test.ts src/features/site-editor/hooks/use-site-editing-session.test.ts` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same plus `src/features/site-editor/hooks/use-site-editing-session.scenario.test.ts` → PASS.
- [ ] **Step 5: Commit** `site editor app: element selection, element rows in Layers, and the style commit`.

### Task 6: Shared alignment and B / I / U controls

**Files:**
- Modify: `apps/frontend/src/features/chat-shell/components/inspector-primitives.tsx` (add exports), `image-inspector.tsx` (L177 private copy removed), `web-inspector.tsx` (L182 private copy removed), `chat-shell.module.css` only if a class is needed
- Test: the chat-shell / design-editor tests that pin these files (find them with `grep -rln "image-inspector\|web-inspector" apps/frontend/src --include='*.test.ts'`)

**Interfaces:**
- Produces: `TextAlignment({ disabled?, horizontal, onHorizontalChange, options: "three" | "four", vertical?, onVerticalChange? })` — no vertical group when `vertical` is undefined; the ad panel passes `"four"` + vertical (today's behaviour), the web panel `"three"` + vertical, hidden by its existing rule. `TextStyleToggles({ disabled?, bold, italic, underline, onBoldChange, onItalicChange, onUnderlineChange })` — three toggles in the alignment control's segmented style, labelled with the letters B / I / U (bold, italic, underlined glyphs), `aria-pressed` on each.

- [ ] **Step 1:** Run the pinning tests found above and record the green baseline.
- [ ] **Step 2: Write a failing test** for `TextStyleToggles`' pure part if any logic is extracted; otherwise this task is a pure move and Step 1's tests are its gate.
- [ ] **Step 3: Implement** the extraction; the ad and web panels render the same DOM as before.
- [ ] **Step 4: Run** the pinning tests and `npm test` (frontend `src`) → PASS, no change in behaviour.
- [ ] **Step 5: Commit** `inspector: one shared TextAlignment, plus B / I / U toggles`.

### Task 7: The site text panel

**Files:**
- Create: `apps/frontend/src/features/chat-shell/components/site-text-panel.tsx`, `site-text-panel.logic.ts`
- Modify: `apps/frontend/src/features/chat-shell/components/site-inspector.tsx`
- Test: `apps/frontend/src/features/chat-shell/components/site-text-panel.logic.test.ts`

**Interfaces:**
- Consumes: Task 5's binding fields; Task 6's controls; `ColorControl`, `InspectorSelect`, `InspectorInput`, `InspectorField`, `InspectorSection` from `inspector-primitives.tsx`.
- Produces (`site-text-panel.logic.ts`, pure):
  - `textPanelValues(override: StyleOverride | null, computed: ComputedTypography, palette): { color: string; colorToken: string | null; opacity: string; fontFamily: string; fontSize: string; fontWeight: string; bold: boolean; italic: boolean; underline: boolean; textAlign: … }` — the override wins, else the computed value; `bold` is `fontWeight >= 700`.
  - `textPanelPatch(override: StyleOverride | null, change: { kind: "colorToken"; token: string } | { kind: "colorHex"; hex: string } | { kind: "opacity"; value: string } | { kind: "fontFamily"; value: string } | { kind: "fontSize"; value: string } | { kind: "fontWeight"; value: string } | { kind: "bold" | "italic" | "underline"; on: boolean } | { kind: "textAlign"; value: … }, computed: ComputedTypography): StyleOverride | null` — returns the new override, or null when the input is invalid (a size that is not a number in 8–200 is refused, never clamped silently); `bold` on sets `fontWeight: 700`, off removes `fontWeight`; a hex keeps the current opacity (default 100); a weight list change to a family that lacks the current weight drops `fontWeight`.
  - `weightOptions(fonts, family): { label: string; value: string }[]` — that family's weights with the ad editor's labels ("400 Regular", "600 Semi Bold", …; reuse `FONT_WEIGHT_OPTIONS`' wording).
- Panel layout (spec §2, mockup 1): header = the element's label and a "text" chip; **Typography**: Color (`ColorControl`, Theme tab = palette, Custom tab = hex + opacity), Font (brand families), Size, Weight, Style (B / I / U), Alignment (four, no vertical); then **Layers**. When `binding.element` is null the panel is today's Content panel, unchanged.
- An invalid input shows the field's existing error state and sends nothing; while `binding.disabled` every control is disabled via the existing fieldset.

- [ ] **Step 1: Failing tests** for `textPanelValues`, `textPanelPatch` (each change kind, including size `"7"` → null and `"abc"` → null, bold on/off, hex keeping opacity) and `weightOptions`.
- [ ] **Step 2: Run** `npx tsx --test src/features/chat-shell/components/site-text-panel.logic.test.ts` → FAIL.
- [ ] **Step 3: Implement** the logic and the panel.
- [ ] **Step 4: Run** the test and `npm test` (frontend `src`) → PASS.
- [ ] **Step 5: Commit** `site inspector: the text panel — colour, font, size, weight, B / I / U, alignment`.

### Task 8: The design API and the agent's view

**Files:**
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/site/workspace.py` (`site_summary`, L408+)
- Create: `subsystems/clue-design/apps/api/tests/test_site_element_edits_scenarios.py`
- Test: `subsystems/clue-design/apps/agent_runtime/tests/test_site_workspace.py` (or the file that already tests `site_summary`; find with `grep -rln site_summary subsystems/clue-design/apps/agent_runtime/tests`)

**Interfaces:**
- Consumes: the site-kit bundles rebuilt from Tasks 1–3 (`npm run build -w @clue/site-kit`).
- Produces: `site_summary` prints, under each section (and under "Header and footer"), one line per `_edits` key: `   - styled by hand: heading — colour text.heading, Garner Serif, 48 px, Semi Bold, italic, centred` (hex colours as `#0F59B0 80%`). No other summary line changes.

- [ ] **Step 1: Failing tests.** Workspace test: a page.json with `_edits` on a CtaBand and on `shell.json`'s header yields those lines. Scenario test (through the real routes, the stored document and the published render, like `test_site_lane_b_scenarios.py`): `PUT /documents/{id}/site` with a CtaBand carrying `_edits.heading = {color:{token:<a garner token>}, fontSize:48}` → 200; reading the site back returns the same `_edits`; undo returns the previous version and redo restores it; a publish renders HTML containing `data-clue-section="<id>"` and `font-size:48px !important`; a `PUT` with `_edits.heading.fontSize = 1` is refused with an error naming `_edits.heading`; a `PUT` with an unknown token is refused with a fix hint.
- [ ] **Step 2: Run** each named file with the keyless runner → FAIL.
- [ ] **Step 3: Implement** the summary lines; fix whatever the scenario shows in the write path (expected: nothing beyond the rebuilt bundles; if Python strips or rejects `_edits`, fix it there and add the case to the scenario).
- [ ] **Step 4: Run** both files plus `subsystems/clue-design/apps/api/tests/test_site_render.py` and `test_site_lane_b_scenarios.py` → PASS.
- [ ] **Step 5: Commit** `site: _edits through the real write, undo and publish path; the agent sees manual styling in site.md`.

### Task 9: Browser proof in the real editor frame

**Files:**
- Create: `tests/site_editor/test_editor_element_styling.py`

- [ ] **Step 1: Write the tests** (harness: `garner_init`, `editor_frame`, `received`, `window.__send`):
  - clicking the CtaBand heading posts `selected` with `element.key == "heading"`, `elements` listing the band's text keys, and a `#RRGGBB` computed colour;
  - clicking the band's body next posts `selected` with `element.key == "body"`;
  - `select` with `elementKey: "heading"` from the app marks that heading `data-clue-el-selected`;
  - `set_props` with `_edits.heading = {fontSize: 48, italic: true}` makes the heading's computed `font-size` `48px` and `font-style` `italic`, and the frame's next `changed` (if any) still carries `_edits`;
  - on a cloned section: clicking a text element posts its structural key; a `set_props` adding `_edits` for that key leaves the clone's markup node the **same DOM node** (tag a node with a JS property before, read it after) and its editable slots still editable (Review Focus 1);
  - clicking "Prepared for" in the header posts a shell `selected` with `element.key == "preparedFor"`;
  - an agent section whose module writes `data-clue-el='"]{}body{'` on an element: clicking it selects the section with `element: null` (Review Focus 4).
- [ ] **Step 2: Build and run** — `cd apps/frontend && npm run build -w @clue/site-kit && npm run build -w @clue/site-editor`, then `CLUE_SITE_EDITOR_BROWSER=1 .superpowers/review/2026-10-13-wave2/pytest-keyless.sh tests/site_editor/test_editor_element_styling.py` → PASS; also re-run `test_editor_clone_editing.py`, `test_editor_selection_follows_section.py`, `test_editor_agent_sections.py` → PASS.
- [ ] **Step 3: Commit** `site editor: browser proof of element selection and styling`.

### Task 10: Skill text for the agent (founder gate)

**Files (draft only until approved):** `subsystems/clue-design/apps/agent_runtime/lumen_agent/site/skills-e5/writing-a-section/SKILL.md`, `skills/building-with-puck/SKILL.md`, `SKILLS-CHANGELOG.md`

- [ ] **Step 1: Draft** in plain, simple language: (a) in `writing-a-section` — name every heading, paragraph and label a marketer may want to restyle with `data-clue-el="<name>"` (letters, digits, `.`, `_`, `-`; unique within the section), and pass `el="<name>"` to `kit.Eyebrow` / `kit.Link`; (b) in `building-with-puck` — what `_edits` is, its exact properties, that the person may have styled things by hand (site.md says so), that the agent may keep, change or drop those values, and that brand tokens come first.
- [ ] **Step 2: Present both drafts to the founder in chat. Do not write them until the founder approves.** Record the decision in the ledger.
- [ ] **Step 3: After approval,** write them, add the changelog line, and run `subsystems/clue-design/apps/agent_runtime/tests/test_site_*` files that read the skills (find with `grep -rln "writing-a-section\|building-with-puck" subsystems/clue-design/apps/agent_runtime/tests`).
- [ ] **Step 4: Commit** `site agent skills: naming editable elements and the _edits layer`.

### Task 11: Gates, bundles and the live check

- [ ] **Step 1:** Rebuild bundles (`npm run build -w @clue/site-kit`, `-w @clue/site-editor`, and the design API's site bundles per `docs` / `DEV_STACK.md`); with the lane stack down, run the frontend gate `npm run design-system:build && npm run lint && npm run build` in `apps/frontend` → all pass.
- [ ] **Step 2:** Start the trenton lane (`nohup ./scripts/dev_stack_trenton.sh up …`), then in the in-app browser, on Garner (the Carmel Clay site), Conduit and Clue sites: click a heading in a brand section, in a cloned section, and "Prepared for" in the header; change colour (theme and custom), font, size, weight, B / I / U and alignment; confirm each shows on the canvas, survives a reload, undoes in one step, and appears on a published page. Screenshot each workspace.
- [ ] **Step 3:** Record the result, anything owed, and the costs in `_memory/` (a new session note) and the plan's ledger.
