# R5 spike: Puck richtext with an inline menu in the platform's skin (Lane C, C12)

Run on 2026-10-13, Puck 0.23.0, `trials/puck-spike/app/r5-richtext/`, probe `export/check_richtext_r5.py`
(dev server `npx next dev -p 3049`, Chromium via Playwright, viewport 1400×900; plus a hands-on pass in an
800-wide browser). Screenshot: `shots/r5-richtext.png`.

| # | Question | Answer | Evidence |
|---|---|---|---|
| 1 | Does `renderInlineMenu` render on the canvas with `Puck.Preview` only and Puck's iframe disabled? | **Yes, but only after two fixes on our side, and only in Puck's place for it.** As written in the brief, the menu never worked. (a) The custom menu root must carry `data-puck-rte-menu`. Without it, clicking any of its buttons in Chromium blurs the editor, Puck clears its rich-text state, the menu unmounts and the command never runs. (b) The editor needs a short wait to mount. The TipTap editor mounts about 0.5 s after `load`, and a click before then selects the component without placing a caret, so no menu appears. On first focus the menu first shows as Puck's Suspense fallback, with every button disabled, for about 300 ms. **Placement:** Puck draws the inline menu inside the selected component's own dark action bar, at the component's top-right corner, next to its label and the Duplicate and Delete buttons. It does not float at the selected text the way the platform toolbar does, and `renderInlineMenu` cannot move it. | probe `menu_visible: true`, screenshot; Details 1 |
| 2 | Can it take the platform toolbar's skin (row, 32px tools, divider, pressed state)? Does the hashed `ActionBarAction--active` class hold up as the only active marker? | **The row, the tools, the divider and the pressed state take the skin. Four details leak from Puck, and the dark action bar around the row stays Puck's.** These match the platform: border `rgb(214, 217, 224)`, 8px radius, white background, the popup shadow, 4px padding, 2px gap, 32×32 tools with a 6px radius and `#1C2028` icons, a 1×22 `#E6E9ED` divider, and an active tool with no hover at `rgba(0, 30, 75, 0.067)` (= `#001E4B11`). The four leaks: idle tools sit at opacity 0.75 (Puck's action-bar CSS); on hover the icon turns Puck's azure `rgb(100, 153, 207)`, because Puck's hover rule outranks ours; `RichTextMenu.Group` adds 6px padding on each side of the divider; and the icons are Puck's 16px lucide SVGs, not the platform's 12px/600 B/I/U/S letters. **The active marker:** the hashed class is the only one. There is no `aria-pressed` and no data attribute. `[class*="ActionBarAction--active"]` matched correctly in every state tested on 0.23.0, but it relies on Puck's private CSS-module class name. The robust route is our own controls: `renderInlineMenu` receives `editor` and `editorState` (`isBold`, `canBold`, …), so we can draw our own buttons with our own classes and `aria-pressed`. | `menu_border`, `buttons` (Bold has `_ActionBarAction--active_5vdfr_104`, the rest do not); Details 2 |
| 3 | What does the field store after Bold (HTML string? JSON?) and what does `render` receive? | **An HTML string,** updated on every keystroke: `<p><strong>Lower medical spend in year one. No plan changes.</strong></p>`. Marks nest in schema order, not the order applied (`strong > em > s > u`). Lists are stored as `<ul><li><p>…</p></li></ul>` and `<ol>…</ol>`. **`render` never receives the string.** In the editor it receives Puck's inline-editor element (the DOM is `section > div > div._RichTextEditor > div.rich-text > div.tiptap.ProseMirror > p`). In Puck's `<Render>`, every richtext prop is replaced by `<Suspense fallback={RichTextRenderFallback}>` around `RichTextRender`. That component parses the HTML through the TipTap schema, writes it out again and inserts it with `dangerouslySetInnerHTML`. The fallback inserts the raw stored string. The editor's own fallback does the same while TipTap loads, and makes it contentEditable. | `stored_body`; Details 3 |
| 4 | Does typing and formatting still work with ⌘Z swallowed by the frame (the editor's shortcut rule)? | **Typing and formatting work. Under the editor's rule, ⌘Z inside the text is passed through, not swallowed, but ⌘I is swallowed, so the italic shortcut stops working.** The spike page has no frame-level shortcut handler, so I tested twice: on the page as it is, and with a replica of the frame's rule injected (site-kit `shortcutFor` plus `editor-app.tsx`'s window capture listener). On the page as it is, all of these work: caret placement, typing at the start and end, replacing a selection, Enter (a new `<p>`), all six menu controls, ⌘B, ⌘I and ⌘U, and ⌘Z and ⇧⌘Z (one TipTap history step each). With the replica, ⌘Z and ⇧⌘Z in the text are exempt (the target is contentEditable), so TipTap's undo still works, and ⌘B and ⌘U work. ⌘I is swallowed whatever the target, so the stored value never gains `<em>`. The Italic button still works. **This can only be judged in the real frame:** how TipTap's local history meets the server's undo stack (a save per change; `flushChange` on every `focusout`, which a menu click triggers; a server `setData` that may remount the editor and reset its history). | manual; Details 4 |
| 5 | What would adopting it touch: site-kit `schemas.ts` (string → rich text), `validate.ts`, the catalog and the agent's skills, Lane A's sanitizer allow-list (`strong`, `em`, `u`, `s`, `ul`, `ol`, `li`, `p`), the published render? | **Eight places, listed in Details 5.** The schema stays a `z.string()`, with a refine that allows only the eight tags and no attributes. The validator's checks come from the schema. The catalog and the skill must say which fields take rich text. The sections' `<p>`/`<h2>` wrappers must become `<div>`s, and lists need their own CSS. The dock has no rich-text field kind. Puck's field options must also turn off `heading`, `link`, `code`, `textAlign` and `hardBreak`. With only the spike's options, typing `## ` makes an `<h2>`, `` `x` `` makes `<code>`, and pasted text keeps `<a target rel href>` and `style="text-align"`. **Lane A's sanitizer is not an allow-list.** It strips dangerous elements and attributes, so the eight tags already pass and nothing needs adding there. The real allow-list has to apply when content is written, because both Puck fallbacks insert the raw stored string. Plain strings keep working: Puck renders a string with no tags as one paragraph. | reading the code; Details 5 |

## Recommendation for Wave 3

**Adopt with changes.** The main reason: Puck's richtext does the hard part, live inline editing on our
real canvas (`Puck.Preview`, no iframe), stores clean HTML and already filters pasted markup through its
TipTap schema. What fails is Puck's default menu: its chrome and its focus handling. Each of those can be fixed
from our side without forking Puck:

- draw our own controls from `renderInlineMenu`'s `editor` and `editorState` (our glyphs, our classes, `aria-pressed`, no reliance on Puck's hashed class);
- mark the menu root `data-puck-rte-menu`;
- restyle or override Puck's `actionBar` so the dark chrome goes;
- narrow the field's options to the eight elements;
- enforce the allow-list when content is written (the schema refine).

One gap this spike did not close is placement. The menu docks at the selected section's corner, not at the
selected text. If floating at the text is a hard requirement, the next spike is a portal from
`renderInlineMenu` positioned with `editor.view.coordsAtPos` (untested here). The string → HTML cost in
Details 5 is real. Start with the long-text `body` fields (FeatureSplit, CtaBand, ProofCard).

## Probe output (verbatim, the committed probe)

```json
{
  "menu_visible": true,
  "menu_border": "rgb(214, 217, 224)",
  "buttons": [
    "<button type=\"button\" class=\"_ActionBarAction_5vdfr_30 _ActionBarAction--active_5vdfr_104\" title=\"Bold\" tabindex=\"0\"><svg xmlns=\"http://www.w3.org/2000/svg\" wid",
    "<button type=\"button\" class=\"_ActionBarAction_5vdfr_30\" title=\"Italic\" tabindex=\"0\"><svg xmlns=\"http://www.w3.org/2000/svg\" width=\"24\" height=\"24\" viewBox=\"0 0 ",
    "<button type=\"button\" class=\"_ActionBarAction_5vdfr_30\" title=\"Underline\" tabindex=\"0\"><svg xmlns=\"http://www.w3.org/2000/svg\" width=\"24\" height=\"24\" viewBox=\"0",
    "<button type=\"button\" class=\"_ActionBarAction_5vdfr_30\" title=\"Strikethrough\" tabindex=\"0\"><svg xmlns=\"http://www.w3.org/2000/svg\" width=\"24\" height=\"24\" viewBo",
    "<button type=\"button\" class=\"_ActionBarAction_5vdfr_30\" title=\"Bullet list\" tabindex=\"0\"><svg xmlns=\"http://www.w3.org/2000/svg\" width=\"24\" height=\"24\" viewBox=",
    "<button type=\"button\" class=\"_ActionBarAction_5vdfr_30\" title=\"Ordered list\" tabindex=\"0\"><svg xmlns=\"http://www.w3.org/2000/svg\" width=\"24\" height=\"24\" viewBox"
  ],
  "stored_body": "<p><strong>Lower medical spend in year one. No plan changes.</strong></p>"
}
```

The brief's probe and client, as written, never produced output. The first run failed with
`Locator.wait_for: Timeout 10000ms exceeded … waiting for locator("[data-r5-inline-menu]") to be visible`, at the
menu wait: the click landed before the editor mounted. With an added wait for `.ProseMirror`, the run timed out
again, this time reading the menu after Bold: the Bold click had unmounted it. The two changes that made the run
pass are each a finding (row 1). The probe waits for `.ProseMirror` before its click, and the client's menu root
carries `data-puck-rte-menu=""`. Both are commented at their sites.

## Details

**1. The menu on the canvas.** Timings come from the dev server. At `load` there is no `.ProseMirror`; it
appears by about 0.95 s. A click at 0.41 s left the component selected (Puck's action bar was present) but no
editor focused, and no menu appeared for the next 6 s. After the editor mounts, one click focuses it and the
menu appears, even with an empty selection (caret only). The menu's first render is the Suspense fallback
(`LoadedRichTextMenuInner` with `editorState: null`, all buttons `disabled`). The `full-*.mjs` chunk (TipTap's
`useEditorState`) loads on first focus, and the buttons were enabled about 300 ms later.

The marker: `EditorInner.handleBlur` (`chunk-WF6I3XOL.mjs`) keeps rich-text state only when the blur's
`relatedTarget` is inside `[data-puck-rte-menu]`. Puck's own `RichTextMenu` root has that attribute; the
brief's custom `<div>` did not. Chromium focuses a button on mousedown, so a click blurred the editor,
`currentRichText` went to `null`, the menu unmounted and the click never fired: the stored value was
unchanged and the active element was `BODY`. With the attribute, the same click bolds the text and keeps the
focus and selection in the editor. Safari and Firefox on macOS do not focus buttons on click, so the bug is
probably Chromium-only, but the marker is right for every browser.

Placement: the menu row (233×42) sat at x=1090, y=12. That is inside Puck's action bar
(`rgb(24, 24, 24)`, 413×50 at x=979, y=8, labelled "RichTextProbe" with Duplicate and Delete), over the top-right of a
section whose text ran from x=48. In the 800-wide pass the bar overlapped the top of the section. The real
editor sets `duplicate: false, delete: false`, so its bar would hold only the label and this menu.

**2. The skin, measured** (`getComputedStyle` with the mouse away from the menu unless noted): row border
`rgb(214, 217, 224)` (the 0.5px border computes to 1px at device scale 1, as the platform's does), radius 8px,
background white, shadow `rgba(0, 24, 62, 0.12) 0px 8px 24px`, padding 4px, gap 2px. Tool: 32×32, radius 6px,
margin 0, colour `rgb(28, 32, 40)`, opacity 0.75 (Puck's `--puck-actionbar-opacity-text`; the platform's tools
are 1). Active Bold: `rgba(0, 30, 75, 0.067)`, opacity 1. Hovered Italic: our background `rgba(0, 37, 110, 0.027)`,
but colour `rgb(100, 153, 207)`, because Puck's `._ActionBarAction:hover:not(--disabled)` (0,3,0) beats
`.row button` (0,1,1). Fixing it needs a stronger selector or the `--puck-actionbar-color-action-hover`
variable. While the mouse is over an active tool it shows the hover background, not the pressed one (in
`shots/r5-richtext.png` the Bold icon is azure because the mouse is still over it). The
platform's `.tool:hover` also outranks `.tool.selected`, so that matches. Divider: 1×22, `rgb(230, 233, 237)`, 3px
margin, but each `RichTextMenu.Group` adds its own 6px padding beside it. Each tool is wrapped in
`span._Control--inline`. The active class tracked the marks exactly: after Bold, Italic, Underline and
Strikethrough in turn, the active set grew one by one, and a list toggle swapped which list button was active.

**3. The stored value after each control** (whole text selected each time):

| after | stored `body` |
|---|---|
| Bold | `<p><strong>Lower medical spend in year one. No plan changes.</strong></p>` |
| Italic | `<p><strong><em>…</em></strong></p>` |
| Underline | `<p><strong><em><u>…</u></em></strong></p>` |
| Strikethrough | `<p><strong><em><s><u>…</u></s></em></strong></p>` |
| Bullet list | `<ul><li><p><strong><em><s><u>…</u></s></em></strong></p></li></ul>` |
| Ordered list | `<ol><li><p>…</p></li></ol>` |
| hands-on: double-click "medical", Italic, type "clinical" | `<p>Lower <em>clinical</em> spend in year one. No plan changes.</p>` |
| hands-on: Enter, "Second line", select it, ⌘B | `<p>Lower <em>clinical</em></p><p><strong><em>Second line</em></strong> spend …</p>` |

On the canvas, lists render with no markers: the spike's Tailwind preflight gives `ul` `list-style-type: none`
and `padding-left: 0`, and Puck's `.rich-text` styles do not restore them.

**4. Keys.** The spike page, as it is: ⌘B, ⌘I and ⌘U each added their mark. With A, B, C and D typed 0.9 s apart (past
TipTap's 500 ms grouping), one ⌘Z removed only "D" and a second removed only "C". The ⌘Z keydown reaches
document-level listeners with `defaultPrevented: true` (ProseMirror handled it). Puck's history hotkey also
listens there and checks neither the target nor `defaultPrevented`, so both stacks may act. They agreed in
this test. That is not proof they agree once formatting and server saves interleave, and it already applies
to today's plain `contentEditable` text. With the frame-rule replica: ⌘B and ⌘U added their marks, ⌘I recorded
the frame decision `swallow` and added nothing, and ⌘Z and ⇧⌘Z in the text were not intercepted (no frame
decision) and undid and redid as before. In the hands-on pass, one ⌘B press did not take effect. A second press,
with a page-level keydown listener armed, reached the page as `meta+b` and bolded the selection. I am counting
the first as a harness artefact.

**5. What adopting touches** (read from the code on this branch unless noted):

- `site-kit/src/schemas.ts`: the long-text props (`body`, `intro`) are `text`/`optionalText` (`z.string()`).
  A rich-text prop stays a string, with a refine that parses it (node-html-parser is already a site-kit
  dependency) and allows only `p strong em u s ul ol li`, with no attributes. Whether to also allow `br` is a
  choice: `hardBreak` stays on unless the field's options turn it off. The string type keeps old pages valid,
  because `RichTextRender` treats a string with no tags as one paragraph. A plain string that happens to
  contain `<…>` would be read as HTML.
- `site-kit/src/validate.ts`: no new code if the refine lives in the schema, since `pageSchemaWith` already runs
  every component schema. Error lines come out as `content.N(id).body: …` like every other.
- `site-kit/src/catalog.ts`: a field's kind comes from its JSON Schema type, so a rich-text string prints as
  `text`. It needs a marker on the schema (for example a `.meta()` entry the catalog reads) to print "rich text:
  p, strong, em, u, s, ul, ol, li".
- The agent's skill: `building-with-puck/SKILL.md:71` says "Text fields take plain text." Today that skill
  exists only under `trials/puck-spike/agent/skills/`. It must name the rich-text fields and the tag list.
- `site-kit/src/sections.tsx`: `area("Body")` becomes a `richtext` field with `contentEditable`, the narrowed
  `options` (also `heading: false, link: false, code: false, textAlign: false`, and `hardBreak` per the choice
  above) and our `renderInlineMenu`. The wrappers change too: `FeatureSplit` renders `<p …>{body}</p>`, but a
  richtext node is block markup (`div > div.rich-text > p`), which is invalid inside `<p>`/`<h2>`. Those
  wrappers become `<div>`s, the brand classes style the inner `p/ul/ol/li`, and list markers need CSS in both the
  editor's stylesheet and the published CSS.
- `site-editor/src/client/fields.ts`: `describeField` has no `richtext` case (`default: return []`), so the field
  would vanish from the app's dock. Contract 6's `FieldKind` has no rich-text kind. Either add one, or make
  these fields canvas-only.
- Lane A's sanitizer: `lumen_api/site_sanitize.py` is on `puck/w2-lane-a` (commit `e3127bbeb`), not on this
  branch. Its rule is "strip, never refuse": it removes `script iframe object embed form base meta link`, the
  `on*` attributes, bad link schemes and foreign byte references, so the eight tags already pass. The paste
  test shows what TipTap's schema does on its own. It dropped `<script>`, `<img onerror>`, `onclick`, `class`,
  colour styles, a `javascript:` link and a table (flattened to `<p>cell</p>`). It kept
  `<a target="_blank" rel="noopener noreferrer nofollow" href="https://…">`, `<p style="text-align: center;">`
  and `<code>`. But only text that passes through the editor is filtered. The agent writes `page.json`
  directly, and both Puck fallbacks put the stored string into `innerHTML` raw. In the editor frame, the CSP
  (`script-src 'self' 'nonce-…'`, no inline handlers) contains that. On a published page the sanitizer is the
  backstop. The allow-list belongs in the schema.
- The published render: Lane A's renderer (`site_render.py`, Task 17, not landed) loads site-kit's render
  bundle in headless Chromium. If that bundle renders through Puck's `<Render>`, each richtext prop is a lazy
  `RichTextRender` behind a raw-string fallback, so the shell's done signal must wait for that chunk, or the
  page captures the fallback.
