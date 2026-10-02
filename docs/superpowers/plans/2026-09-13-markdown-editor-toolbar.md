# MDXEditor toolbar integration (Lane 2, plan 2)

**Decision, 2026-09-13:** the founder selected MDXEditor. This supersedes the custom CodeMirror
command/keymap plan. Implemented and verified 2026-09-14; see acceptance notes below.

**Goal:** one Clue-themed visual Markdown editor/toolbar for Knowledge, Plan, ICP and persona
documents, using the library's controls and formatting behavior.

**Architecture:** Lane 2 plan 1 Task 5 introduces shared `MarkdownArticle` (`react-markdown` +
`remark-gfm`) and client-only `MarkdownEditor` (MDXEditor). This slice configures the full toolbar
and verifies the complete flow. Existing hooks/repositories retain Save/Discard, permissions and
version-conflict ownership. No `commands.ts`, custom `markdown-keymap.ts` or marker arithmetic.

**Spec:** `docs/superpowers/specs/2026-09-12-markdown-editor-toolbar-design.md`, revised 2026-09-13.
**Dependency:** Lane 2 plan 1 Task 5; the remaining plan-1 surfaces precede final acceptance.

## Constraints

- Preserve Preview/Edit, explicit Save/Discard and the Markdown body + expected-revision API.
  No backend, front-matter, confirmation-gate, database or environment changes.
- Compose MDXEditor exports; no custom parser, serializer, formatting engine or parallel editor.
- Our styles use Clue tokens/icons. Import vendor structural CSS and theme public APIs.
- Replace the Knowledge-specific CodeMirror wrapper after verification; keep dependencies still
  used elsewhere or by the library's source/code plugins.
- Use the active Semarang frontend origin, verified from its local configuration/processes.
  Historical :3020 examples belong to another lane; never stop a sibling stack to run this one.

## Task 1: Verify the shared foundation

**Files:** plan 1 Task 5's `apps/frontend/src/components/markdown/`; package/lockfile only if needed.

- [x] Review the completed Task 5 prototype and chosen published release. Verify React 19/Next
  build compatibility, client-only plugin initialization, Lexical coexistence and actual exported
  controls. Do not repeat a successful foundation install or force unrelated version upgrades.
- [x] Load headings H1–H6, inline formatting, nested/task lists, links, tables and fenced code.
  Enable parsing plugins needed by existing files even when their insertion controls are hidden.
- [x] Check initial normalization stays clean, Preview/Edit preserves the session, Discard resets
  to saved content, and explicit external resets do not echo back as user changes.
- [x] Verify malformed/unsupported content remains recoverable through library source mode.
  Import failure cannot result in an empty saved replacement. Record actual release/API gaps.

## Task 2: Compose and theme the toolbar

**Files:** create `components/markdown/markdown-toolbar.tsx`; update the shared editor and
`markdown.module.css`; add missing glyphs to `features/projects/config/project-icon-sources.ts`.

`MarkdownToolbar` composes MDXEditor controls in the library context. It takes no `EditorView`
and dispatches no homemade Markdown transactions.

- [x] Configure `toolbarPlugin` with `UndoRedo`, `BlockTypeSelect`, `BoldItalicUnderlineToggles`
  (Bold/Italic), `StrikeThroughSupSubToggles` (Strikethrough), `CodeToggle`, `ListsToggle`,
  `CreateLink`, `InsertTable`, `InsertCodeBlock`, and `InsertThematicBreak`.
- [x] Use headings/quote, lists, link/link-dialog, table, code-block/CodeMirror, thematic-break
  and Markdown-shortcut plugins. Offer Paragraph/H1–H3/Blockquote using public configuration.
  Keep H4–H6 import support; if menu filtering is unsupported, retain the native selector and
  record the small UI difference rather than fork it.
- [x] Configure library source recovery without a new diff-review feature or a second editor.
  Hide non-v1 insertion controls while preserving existing content. Native table editing is
  included; no custom insertion dialog or fixed-size source template is required.
- [x] Theme editor prose/code, toolbar, popups/dialogs and source mode through public CSS classes,
  variables and icon overrides. Use Clue tokens, 28×28 controls, wrapping groups and library
  pressed/focus behavior. No generated-class selectors or dependency CSS forks.
- [x] Verify keyboard navigation, selection retention on toolbar clicks, dialog Escape/focus
  return and read-only state in both modes. Audit Mod+B/I/Shift+X/E/K/Z/Shift+Z and list shortcuts;
  reuse exported actions for any small binding adapter, or record a gap for review.
- [x] Check long URLs, backtick spans, fenced code and narrow panes cannot widen the outer
  chat/document panel. Constrain flex/grid ancestors and local overflow; source text wraps
  without line numbers or developer-style gutters.
- [x] Commit the coherent toolbar/theme change locally after relevant checks pass.

## Task 3: Mount and verify all document contexts

**Files:** Knowledge panel, project document surface, existing draft/save hooks, frontend
architecture docs and focused integration tests.

- [x] Both surfaces use the shared editor; gallery ICP/persona cards open that project surface.
  Remove obsolete Knowledge-only editor/hook/styles when imports are gone. Preserve the active
  editor across Preview/Edit; scope drafts by document identity/path.
- [x] Check distinct drafts, explicit resets, busy state, returned-version handling and external
  refresh. Keep a dirty draft on the original base revision so a 409 retains user changes.
- [x] Test our adapter/draft decisions; verify selection/history/formatting through real component
  or browser interactions. Do not replace command tests with source-text assertions or duplicate
  library internals. Add test tooling only if the existing setup cannot exercise the integration.
- [x] Run `npm run design-system:build`, `npm run lint`, `npm test`, `npm run build` in
  `apps/frontend` and `git diff --check`. Attribute inherited failures without unrelated cleanup.
- [x] Browser checks on Semarang: Knowledge → Edit → format → Preview → Save → hard refresh;
  repeat on Plan and gallery-opened ICP/persona. Verify Discard, untouched open/close, edit then
  undo to initial content, switching documents, read-only, failed saves and version conflicts.
  Use a disposable verification document for destructive test content.
- [x] Check nested/task lists, tables, fenced code, long inline text, unsupported input and narrow
  chat/gallery panes. Saved Markdown may normalize formatting, but meaningful content must remain.
- [x] Update frontend architecture docs and `_memory/` with the version, evidence, remaining gaps
  and live-proof status. Commit locally; no remote publication without a current instruction.

## Completion

One shared library editor serves all four contexts, controls reuse library behavior, saves persist
through existing versioned routes, untouched content stays clean, parse errors preserve source,
and long-content checks introduce no outer horizontal scroll. Implementation and acceptance are complete for the shared editor.


## Acceptance — 2026-09-14

The consolidated [flow acceptance record](2026-09-14-lane2-flow-acceptance.md) closes the
founder's final verification step and distinguishes browser evidence from automated gates.

- MDXEditor 4.2.5, React 19.2.4 and Next 16.2.12; no reinstall or dependency fork.
  The extracted MarkdownToolbar composes native controls. Knowledge and every project
  Markdown file use it through the same client-only editor boundary.
- Native BlockTypeSelect uses the parsing plugin's allowed levels; it offers H1–H6.
  Keeping H4–H6 import support means retaining those native menu options. No custom menu.
- Native keyboard audit: Mod+B/I/K/Z and Mod+Shift+Z work (browser checked on macOS).
  This release has no native Mod+Shift+X/E or modifier-based list bindings; use the toolbar
  or library Markdown shortcuts. These gaps are recorded rather than adding a second
  formatting/keymap engine. Escape closes the link dialog and restores editor focus.
- Disposable Semarang project: Plan, ICP and persona browser saves produced new durable
  IDs/versions; saved content survived reload. Knowledge formatted text/table edit also
  survived reload. H1–H6, nested/task lists, links, tables and fenced-code metadata survived.
- File switch/close/reopen preserved separate drafts and native undo/redo. A stale save
  returned a conflict without clearing edits; checking updates retained the draft;
  explicit Discard adopted the latest revision. Untouched edit remained clean.
- Unsupported JSX blocked saving and stayed recoverable in native Source mode. Long source
  is virtualized by CodeMirror, so DOM innerText is not a full-source assertion; a bounded
  unsupported fixture verified exact source retention. Read-only prototype checks blocked
  visual/source/code-block typing and Save, without changing live permissions.
- At 390 and 720 px, long URLs, inline code and fences in Preview/Edit did not increase
  documentElement.scrollWidth beyond clientWidth. Library table overflow stays local.
- Gate: tokens, lint (two inherited canvasOperations warnings), all 2,270 tests and
  production build passed. The npm test CLI hit sandbox IPC EPERM, so the same suite ran
  through `node --import tsx --test` with no IPC listener. No model/fleet work was dispatched.
- New review item: document-reference chat cards still use inherited Plan chrome. Founder
  flagged the empty body/toggle during verification; compact file-row preview is isolated at
  `/file-card` in the existing prototype, awaiting visual approval before main styling changes.
