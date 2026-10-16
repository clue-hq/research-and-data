# S2a-2 — agent-written sections break when Edit mode is on: scope study

**Date:** 2026-10-16. **Status:** study only, no code changed. **Needs a founder decision** (§5) before
any implementation. **Source finding:** `docs/superpowers/verification/2026-10-14-wave2-area-review-findings.md`
§S2a-2 (Important, open); the reviewer's full analysis and its browser probe are in the git-ignored
`.superpowers/review/2026-10-13-wave2/reports/S2a-site-editor-package.md` (§S2a-2) and
`…/S2a-site-editor-package-probes/test_s2a_agent_props.py`.

## 1. What a person sees

A marketer opens a site that contains a section the agent wrote (any `write_section` section) and turns on
**Edit**. In that mode only:

- the section loses its brand background and text colour (it goes transparent);
- an image's description (`alt`) becomes the literal text "[object Object]";
- a button or card the section draws falls back to the standard style instead of the brand style it named;
- a section that does anything with its text (capitalises it, splits it into lines, compares it) crashes and is
  replaced by an empty failed-section marker;
- in the dock, `surface`, `look` and `cardLook` of an agent section are free-text boxes; typing a name the brand
  does not have (e.g. "Dark") is refused by the save check, and the editor keeps re-sending it.

**Preview and the published page are correct.** So the page changes look the moment the marketer starts
editing, and the agent's own sections are the ones that break. Every site with at least one agent section is
affected. Built-in sections and cloned sections are not.

## 2. Why it happens (the mechanism, with code)

1. **Every plain-text prop of an agent section is made "edit in place".** The editor builds an agent section's
   fields from its props schema in `apps/frontend/packages/site-editor/src/client/fields.ts`
   (`puckFieldsFromJsonSchema`): any `string` prop that is not named like a link (`…href/link/url`) or an
   image (`…image/logo/photo/picture/src`) becomes `{ type: "text" | "textarea", contentEditable: true }`. That
   includes props that are **choices**, not prose: `surface` (every agent section must have one — the skill's own
   example passes it to `kit.Shell`), `look`, `cardLook`, `alt`, and any `variant`/`align`-style prop the agent
   invents.
2. **Puck replaces an edit-in-place value with an editing widget before the section draws.** In Edit mode,
   Puck 0.23's default field transform (`@puckeditor/core` `chunk-55V3NZVF.mjs`, `getInlineTextTransform`,
   ~line 5239) swaps every `contentEditable` text/textarea value for a React element `<InlineTextField …/>`.
   The section's `render(props, kit)` therefore receives **an element where it expects a string**.
3. **Built-in sections are written for that; agent sections are not.** site-kit's own sections type their text
   props as `string | ReactNode` and put them straight into JSX, and their choices are `select` fields (never
   edit-in-place). An agent section, as the skill teaches it (`surface: z.string()`, `props.quote` used as text),
   does `surfaceClass(props.surface)` → `bg-surface-[object Object]` (`site-kit/src/sections.tsx` `surfaceClass`),
   passes an element as `alt`, matches no look, or calls a string method on an element and throws.
4. **The dock mirrors the same mistake.** `describeField` reports those choice props as `kind: "text"`, while the
   save check accepts only the brand's names for `surface`/`*Surface`, `look`/`*Look`, `cardLook`/`*CardLook`
   (`site-kit/src/validate.ts`, the agent-section walk) → a typed free-text value is refused (422).

Where agent sections are mounted: `site-kit/src/config.tsx` (`agentSections` → `module.render(props, { ...kit,
editing })` inside `SectionBoundary`); the agent already receives `kit.editing` (true while the marketer edits),
which today only means "show your first state and start nothing".

## 3. What is in scope

| Part | Where | Notes |
|---|---|---|
| Field mapping for agent props | `site-editor/src/client/fields.ts` | the heuristic that marks props editable |
| Choice pick-lists in the dock | `fields.ts` + `site-kit` (`surfaceChoices`, `buttonLookOptions`, `cardLooks`) | the same lists built-in sections already get |
| What agent sections receive in Edit | `site-kit/src/config.tsx` agent mount, or a Puck `fieldTransforms` override on `<Puck>` (`site-editor/src/client/editor-app.tsx`) | depends on the decision in §5 |
| The agent's contract | `lumen_agent/site/skills-e5/writing-a-section/SKILL.md` (+ `rebuilding-a-section`), and possibly `site-kit/src/check-section.ts` (write-time lint) | only if text props may arrive as editable widgets; skill wording needs founder review (standing rule) |
| Save check | `site-kit/src/validate.ts` | already right; it is what exposes the dock bug |

Out of scope: clones (edited by `CloneEditor`, unaffected), built-in sections (already correct), the published
page and Preview (correct), K3-1 (agent code posting into the frame — a separate security item).

## 4. Facts that constrain the design

- In-place text editing on the canvas is a deliberate product choice for built-in sections ("Text fields are
  `contentEditable`, so they edit in place on the canvas", `site-kit/src/sections.tsx`).
- Puck's in-place editing works only by handing the section an element for that prop. There is no Puck mode
  that keeps the value a string **and** makes it editable in place; the alternatives are editing in the dock, or
  making the drawn DOM editable ourselves (what `CloneEditor` does for clones).
- Puck accepts a `fieldTransforms` prop on `<Puck>`, so the editor can decide per field type what a section
  receives — a clean seam for any of the options below.
- Agent sections are free-form code; we cannot make them all handle elements safely without telling the agent
  (skill) and checking it (lint).

## 5. Options (founder decision)

| Option | What the marketer gets | What changes | Risk | Size |
|---|---|---|---|---|
| **A. Agent sections edit in the dock only** | Agent-section text is edited in the dock fields; clicking text on the canvas selects the section but does not type into it. Choices become pick-lists. | Agent props never `contentEditable`; choice props → `select` with the brand's lists. No skill change. | None to the drawing; less direct editing for agent sections only | small (half a day with tests) |
| **B. Prose edits in place, choices are pick-lists** (closest to built-in sections) | Agent-section prose is editable on the canvas like built-in text; choices are pick-lists. | Only prose props are editable in place (decided by an explicit marker in the agent's schema, not by guessing from names); the skill tells the agent such props may arrive as editable text and must be put straight into JSX, never string-processed; a write-time lint refuses string methods on those props. | Depends on the agent following the rule; the lint catches the common cases | medium (a day; skill change needs your review) |
| **C. Keep the name guess, exclude choices** | Like B for most prose; choices are pick-lists. | Add `surface`, `*Look`, `cardLook`, `alt`, … to the exclusions; choice props → `select`. | A section that string-processes its prose still breaks in Edit; any new choice-like name the agent invents breaks too | small |
| D. Make the drawn text editable ourselves (as clones do) | Agent prose editable in place while sections always get plain strings | A `CloneEditor`-style DOM editor for agent sections | Fragile mapping from drawn text back to props | large |

**Recommendation:** B if in-place editing of agent text matters to you (it is how the rest of the page behaves);
otherwise A, which is the most robust and smallest. Either way the dock gets real pick-lists for surfaces and
styles. C fixes today's visible breakage but leaves the crash class open.

## 6. How it would be verified

- Adopt the reviewer's browser probe as a permanent test (`test_s2a_agent_props.py`): a real agent section,
  compiled with the section compiler, served through the editor's token route; assert in **Edit** the same
  surface class, background, `alt` type and string handling as in **Preview**.
- Field-mapping tests (`site-editor/test/fields.test.ts`): `surface`/`look`/`cardLook` → pick-lists with the
  brand's values; prose behaviour per the chosen option.
- Dock round trip: choose a surface from the list → save accepted (no 422).
- For B: a lint test that refuses `props.<prose>.toUpperCase()` / `.split(` etc., and the skill text reviewed by
  you before it ships.
