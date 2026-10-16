# S2a-2: agent-written sections edit in place (option B), plan of action

**Status:** APPROVED by the founder 2026-10-16: option B; D1 marker `.meta({ edit: "inline" })`; D3 silent fallback;
D4 skill wording in §6 approved as written. D2 is moot: the Puck site layer has never been deployed, so there are no
existing agent sections or stored sites to keep working (no backward-compatibility work anywhere in this plan).
**Finding:** S2a-2 in `docs/superpowers/verification/2026-10-14-wave2-area-review-findings.md`.
**Study:** `docs/superpowers/research/2026-10-16-s2a-2-agent-sections-in-edit-mode.md`.

## 1. What is broken today (read on 2026-10-16, branch `site/publish-durability`)

How an agent section gets its edit fields:

1. The agent writes a section file. `export const schema = z.object({...})` holds its props, and
   `export function render(props, kit)` draws it. Sections may import only `zod`, React types and
   `@/puck/agent-kit` (type-only, so erased at build). This is checked by
   `apps/frontend/packages/site-kit/src/check-section.ts` (`lint` + `typeCheck`), which never imports the file.
2. The design API reads the props schema inside the hardened render page:
   `site-kit/src/render-core.tsx::sectionPropsSchema` → `z.toJSONSchema(module.schema)`. It is stored with the section
   (`record_site_section_bytes` → `props_schema`) and sent to the editor in each section link (`link.propsSchema`).
3. The editor turns that JSON Schema into Puck fields:
   `apps/frontend/packages/site-editor/src/client/fields.ts::puckFieldsFromJsonSchema`, applied in
   `site-editor/src/client/config.tsx::buildPageConfig`. Today **every** `string` prop not named like a link or an image
   becomes `{type: "text"|"textarea", contentEditable: true}`. That includes `surface`, `look`, `cardLook`, `alt`, and
   any choice the agent invents.
4. In Edit mode, Puck's default field transform (`@puckeditor/core` 0.23.0, `getInlineTextTransform`) replaces each
   `contentEditable` value with an `<InlineTextField/>` React element before calling `render`. Puck's field walker also
   descends into list items and nested objects, so text inside `z.array(z.object({...}))` arrives as an element too.
5. site-kit mounts agent sections in `site-kit/src/config.tsx` (`Drawn` → `module.render(props, {...kit, editing})`)
   inside `SectionBoundary`, which shows an empty `data-agent-section-failed` marker when a section throws.

Two defects follow:
- **Choices made editable.** `surface` arrives as an element: `surfaceClass` gives `bg-surface-[object Object]` and
  the section loses its colours. `alt` shows "[object Object]". A `look` matches nothing. In the dock these appear as
  free-text boxes, and a name the brand doesn't have is refused by the save check (`site-kit/src/validate.ts`, the agent
  walk), so the save fails and the editor keeps re-sending it.
- **Text treated as a string.** A section that calls `.toUpperCase()`, `.split()` or similar on prose crashes in Edit
  mode only, and is replaced by the failed-section marker.

Preview, `render_page`, `compare_section` and the published page are unaffected: no transform runs there.

## 2. The design

### 2.1 The agent marks the props that edit in place

A prose prop carries an explicit marker in the schema: `z.string().meta({ edit: "inline" })`. Checked on 2026-10-16:
zod 4.4.3's `toJSONSchema` copies it into the stored props schema as `"edit": "inline"`, also on fields inside lists
and objects. Agent sections receive zod from the page through the section host, so the editor and the render page use
the same zod instance and registry.

**Unmarked text props are edited in the side panel and always arrive as plain strings.** This is the safe default:
a section that never uses the marker can never be broken by Edit mode.

### 2.2 Brand choices are pick-lists, whatever the agent does

In `puckFieldsFromJsonSchema`, by prop name, using the rules `validate.ts` already enforces:

| Prop name | Field | Options |
|---|---|---|
| `surface`, `…Surface` | `select` | `surfaceChoices(brand)` (labels as built-in sections show them) |
| `look`, `…Look` | `select` | "Standard" (`""`) + `buttonLooks(brand)` names |
| `cardLook`, `…CardLook` | `select` | "Standard" (`""`) + `cardLooks(brand)` names |

None of these is ever edited in place, even if marked. `puckFieldsFromJsonSchema` therefore needs the brand: change
its signature to `(schema, brand)` and pass `brand` from `buildPageConfig`. `z.enum` props stay selects, as today.
Links (`…href|link|url`) and images (`…image|logo|photo|picture|src`) stay side-panel-only, as today, and so does
`alt` (added to the never-inline names).

### 2.3 The editor makes exactly the marked props editable in place

`contentEditable: true` only when the property has `edit: "inline"`, is a `string`, and is not one of the names in
§2.2. `text` vs `textarea` keeps today's name rule (`LONG_TEXT`), which only decides whether line breaks are allowed.
This applies recursively, so marked fields inside lists and objects edit in place too. The dock (`describeField`) is
unchanged: it already turns `select` fields into select controls and text fields into text boxes.

### 2.4 Refuse misuse when the section is written

Two contract checks, so a broken section never reaches a site:

1. **Marker placement** (in `render-core.tsx::sectionPropsSchema`, next to the existing id/surface rules): the marker
   is allowed only on a `string` prop whose name is not a choice, link, image or `alt`. Otherwise the section is
   refused with a plain message: `"surface" cannot be edited in place: it is a brand choice, picked from a list in
   the editor. Remove .meta({ edit: "inline" }) from it`.
2. **Text not handled as text** (in `check-section.ts`, during the type check): before `tsc` runs, the checker writes
   a shadow copy of the file in which every marked prop's schema entry is replaced by
   `z.custom<EditableText>()`. Here `EditableText` is a new type exported from `site-kit/src/agent-kit.tsx` as
   `string | ReactElement`. The rewrite stays on the same line, so line numbers survive. `tsc` then rejects, as type
   errors, every string operation on a marked prop, including through aliases, destructuring and `items.map(item =>
   item.title.toUpperCase())`. That covers `.toUpperCase()`, `.split()`, `.trim()`, `.length` and passing it where
   text is required (`alt`, `kit.Image`). Putting it into JSX (`{props.headline}`) passes. The checker maps these errors
   to one message: `"<prop>" is edited in place on the canvas, so while the page is being edited it is not text: put
   it in the page as it is ({props.<prop>}); for capitals use the uppercase class; for lines, use a list of items`. A
   small AST rule adds what types cannot see: a marked prop inside a template literal or `String(...)`.
   `kit.Button`'s `label` type widens from `string` to `ReactNode` (the brand button already accepts it), so a marked
   label can be passed to a button.

### 2.5 Safety net: a section that still fails in Edit mode falls back, not to the failed box

If a section passes the checks but still throws while the editor's inline widgets are in its props, the canvas should
not show an empty failed marker for a section that draws fine with plain text. In `site-kit/src/config.tsx`, the agent
mount gets an editor-only fallback:
- **First failure in Edit mode:** draw the section again with its **raw** props (the strings Puck stores). These come
  from an injected editor part, `EditorParts.rawProps(id)`, backed by Puck's `useGetPuck().getItemById(id)`
  (available in 0.23.0; Puck's preview shares the React tree, so the hook works there).
- **Effect:** that one section is edited in the side panel only, and nothing else changes on the page.
- **Second failure** (it also fails with plain text): the existing failed marker, as today.
- **Visibility:** silent on the canvas, because the designed frontend has no slot for a notice. The editor logs a
  warning with the section name.

The published page and the server render never use this path: `EditorParts` is injected only by the editor.

### 2.6 What does not change

- Built-in sections, clones and their `CloneEditor`.
- The published page, Preview, `render_page` and `compare_section`.
- The save check: it already enforces brand surfaces and styles.

## 3. Files

| File | Change |
|---|---|
| `apps/frontend/packages/site-editor/src/client/fields.ts` | marker-driven `contentEditable`; choice pick-lists from the brand; `alt` never inline; signature `(schema, brand)` |
| `apps/frontend/packages/site-editor/src/client/config.tsx` | pass `brand`; inject `rawProps` editor part |
| `apps/frontend/packages/site-editor/src/client/editor-app.tsx` | provide `rawProps` via `useGetPuck` |
| `apps/frontend/packages/site-kit/src/config.tsx` | `EditorParts.rawProps`; agent mount with the one-step fallback (§2.5) |
| `apps/frontend/packages/site-kit/src/agent-kit.tsx` | export `EditableText`; `Kit.Button.label: ReactNode` |
| `apps/frontend/packages/site-kit/src/render-core.tsx` | marker-placement rule in `sectionPropsSchema` |
| `apps/frontend/packages/site-kit/src/check-section.ts` | shadow-copy type check for marked props; template/`String()` rule; message mapping |
| `subsystems/clue-design/apps/agent_runtime/lumen_agent/site/skills-e5/writing-a-section/SKILL.md` | §6 wording (founder review) |
| `…/skills-e5/rebuilding-a-section/SKILL.md` | one line: mark the prose (founder review) |
| `…/skills-live/making-a-section-interactive/SKILL.md` | the accordion example marks its prose (founder review) |
| `…/lumen_agent/site/SKILLS-CHANGELOG.md` | entry |
| site-editor bundle | rebuild (`dist/`) so the lane's editor (port 3129) serves the change |

## 4. Tasks (each starts from a failing test)

1. **Field mapping** (`fields.ts`, `config.tsx`). Tests in `site-editor/test/fields.test.ts`:
   - marked text is `contentEditable`; unmarked text is not;
   - `surface`/`heroSurface` → select with the brand's surfaces; `look`/`ctaLook` → select with "Standard" + the
     brand's button styles; `cardLook` → select with "Standard" + card styles;
   - a marked `surface`, `alt`, `…Href` or `…Image` is still not inline;
   - marked fields inside `z.array(z.object(...))` are inline;
   - the dock description shows those choices as `select` with the same options.
2. **Marker placement** (`render-core.tsx`). Tests: the marker on a choice, link, image, `alt` or non-string prop
   refuses the section with the §2.4 message; on prose it passes and the stored schema carries `edit: "inline"`.
3. **Write-time check** (`check-section.ts`, `agent-kit.tsx`). Tests over real section files:
   - refused: `props.headline.toUpperCase()`; `items.map(i => i.title.split(" "))`; `const { headline } = props;
     headline.trim()`; `<kit.Image alt={props.caption}>` with a marked caption; `` `${props.headline}!` `` and
     `String(props.headline)`;
   - accepted: `{props.headline}`, `<kit.Button label={props.cta} …/>`, and string operations on unmarked props;
   - the message names the prop and says what to write instead.
4. **Edit-mode fallback** (site-kit `config.tsx`, editor `rawProps`). Tests:
   - a section that throws only when a prop is an element draws with raw props in Edit mode, with no failed marker;
   - a section that throws always still shows the failed marker;
   - the published render path never calls `rawProps`.
5. **End to end in the browser** (business-logic test, founder rule 2026-10-13). Adopt the reviewer's probe
   (`.superpowers/review/2026-10-13-wave2/reports/S2a-site-editor-package-probes/test_s2a_agent_props.py`) as a
   permanent test. It runs a real agent section through the real section compiler and record path, opened through the
   editor's token route, with Edit mode on, and asserts:
   - the same surface class and background as in Preview;
   - `alt` is a string;
   - typing into a marked prose field on the canvas, then saving, stores the new text;
   - choosing a surface from the dock list saves with no 422;
   - an old section without markers edits its text in the dock and never breaks.
6. **Skills** (§6 wording, after founder approval) and the changelog entry.
7. **Gates.**
   - site-kit and site-editor tests, then the frontend gate (`npm run design-system:build && npm run lint && npm run
     build`, with the lane stack down per the hangzhou lesson).
   - Named design API test files only: the site-section record and render tests, `test_site_write_routes.py`, and the
     section-check tests. Never the whole `apps/api/tests` folder (7–8 h).
   - Rebuild the site-editor bundle.
   - Live check in the Claude in-app browser on the three workspaces (Conduit, garnerhealth.com, Clue; founder rule
     2026-10-04), on a lane site with an agent section: Edit on, type on the canvas, change the surface from the
     list, save, publish, view.
   - A new agent run that writes a section with markers needs the founder's go (it spends money).

Rough size: about a day, plus the founder's review of §6.

## 5. Risks and how the plan covers them

| Risk | Cover |
|---|---|
| The agent forgets the marker | Safe: that prop is edited in the side panel and never breaks. The skill example shows the marker. |
| The agent marks a choice or a link | Refused at write time (§2.4.1). |
| The agent string-processes marked text | Type error at write time, including through aliases (§2.4.2); anything left falls back (§2.5). |
| A section breaks in Edit mode in a way the checks can't see | §2.5 fallback: side-panel editing for that section, never an empty box. |
| zod meta lost between the module and the stored schema | Tested in Tasks 2 and 5 through the real record path. Same zod instance via the section host. |
| `contentEditable` inside an interactive element (a button in an accordion) | Same behaviour as built-in sections' button labels; covered by the live check. |
| Lists of plain strings (`z.array(z.string())`) | Not editable today and still not editable (Puck lists need object items). The skill keeps lists as objects, as its examples already do. |

## 6. Skill wording for founder review (plain, not condensed)

**writing-a-section, the example's schema:**

```tsx
export const schema = z.object({
  id: z.string(),
  surface: z.string(),
  quote: z.string().min(1).meta({ edit: "inline" }),
  attribution: z.string().meta({ edit: "inline" }),
}).strict();
```

**writing-a-section, new rule (in "Rules"):**

> - Mark every prop a marketer reads as words on the page (a heading, a paragraph, a quote, a button's words, a card's
>   title) with `.meta({ edit: "inline" })`. The marketer can then click those words and type. While they do, such a
>   prop is not text but an editable piece of the page: put it into the page exactly as it is (`{props.quote}`), and
>   never change it in code (no capitals, splitting, cutting or joining). For capitals, use the `uppercase` class. For
>   separate lines, use a list of items. Do not mark choices (surface, look, cardLook), links, images or `alt`: the
>   editor offers those from lists and fields. write_section refuses a section that breaks these rules and says why.

**rebuilding-a-section, step 2, one added line:**

> - Mark every heading, paragraph and button's words with `.meta({ edit: "inline" })`, as the writing-a-section skill
>   says, so the marketer can edit them on the page.

**making-a-section-interactive, the accordion example:** `heading`, `question` and `answer` gain
`.meta({ edit: "inline" })`. The rest of the example is unchanged: it already puts each into the page as it is.

## 7. Decisions for the founder

| # | Decision | Recommendation |
|---|---|---|
| D1 | The marker's form: `.meta({ edit: "inline" })` | **Approved.** |
| D2 | (moot: nothing deployed, no existing sections) | — |
| D3 | The §2.5 fallback is silent on the canvas (no notice; the designed frontend has no slot for one) | **Approved.** A warning goes to the editor log. |
| D4 | The skill wording in §6 | **Approved as written.** |
