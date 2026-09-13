# MDXEditor toolbar integration (Lane 2, plan 2)

**Decision, 2026-09-13:** the founder selected MDXEditor. This supersedes the custom CodeMirror
command/keymap plan. Library choice approved; the implementation tasks below are not executed.

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

- [ ] Review the completed Task 5 prototype and chosen published release. Verify React 19/Next
  build compatibility, client-only plugin initialization, Lexical coexistence and actual exported
  controls. Do not repeat a successful foundation install or force unrelated version upgrades.
- [ ] Load headings H1–H6, inline formatting, nested/task lists, links, tables and fenced code.
  Enable parsing plugins needed by existing files even when their insertion controls are hidden.
- [ ] Check initial normalization stays clean, Preview/Edit preserves the session, Discard resets
  to saved content, and explicit external resets do not echo back as user changes.
- [ ] Verify malformed/unsupported content remains recoverable through library source mode.
  Import failure cannot result in an empty saved replacement. Record actual release/API gaps.

## Task 2: Compose and theme the toolbar

**Files:** create `components/markdown/markdown-toolbar.tsx`; update the shared editor and
`markdown.module.css`; add missing glyphs to `features/projects/config/project-icon-sources.ts`.

`MarkdownToolbar` composes MDXEditor controls in the library context. It takes no `EditorView`
and dispatches no homemade Markdown transactions.

- [ ] Configure `toolbarPlugin` with `UndoRedo`, `BlockTypeSelect`, `BoldItalicUnderlineToggles`
  (Bold/Italic), `StrikeThroughSupSubToggles` (Strikethrough), `CodeToggle`, `ListsToggle`,
  `CreateLink`, `InsertTable`, `InsertCodeBlock`, and `InsertThematicBreak`.
- [ ] Use headings/quote, lists, link/link-dialog, table, code-block/CodeMirror, thematic-break
  and Markdown-shortcut plugins. Offer Paragraph/H1–H3/Blockquote using public configuration.
  Keep H4–H6 import support; if menu filtering is unsupported, retain the native selector and
  record the small UI difference rather than fork it.
- [ ] Configure library source recovery without a new diff-review feature or a second editor.
  Hide non-v1 insertion controls while preserving existing content. Native table editing is
  included; no custom insertion dialog or fixed-size source template is required.
- [ ] Theme editor prose/code, toolbar, popups/dialogs and source mode through public CSS classes,
  variables and icon overrides. Use Clue tokens, 28×28 controls, wrapping groups and library
  pressed/focus behavior. No generated-class selectors or dependency CSS forks.
- [ ] Verify keyboard navigation, selection retention on toolbar clicks, dialog Escape/focus
  return and read-only state in both modes. Audit Mod+B/I/Shift+X/E/K/Z/Shift+Z and list shortcuts;
  reuse exported actions for any small binding adapter, or record a gap for review.
- [ ] Check long URLs, backtick spans, fenced code and narrow panes cannot widen the outer
  chat/document panel. Constrain flex/grid ancestors and local overflow; source text wraps
  without line numbers or developer-style gutters.
- [ ] Commit the coherent toolbar/theme change locally after relevant checks pass.

## Task 3: Mount and verify all document contexts

**Files:** Knowledge panel, project document surface, existing draft/save hooks, frontend
architecture docs and focused integration tests.

- [ ] Both surfaces use the shared editor; gallery ICP/persona cards open that project surface.
  Remove obsolete Knowledge-only editor/hook/styles when imports are gone. Preserve the active
  editor across Preview/Edit; scope drafts by document identity/path.
- [ ] Check distinct drafts, explicit resets, busy state, returned-version handling and external
  refresh. Keep a dirty draft on the original base revision so a 409 retains user changes.
- [ ] Test our adapter/draft decisions; verify selection/history/formatting through real component
  or browser interactions. Do not replace command tests with source-text assertions or duplicate
  library internals. Add test tooling only if the existing setup cannot exercise the integration.
- [ ] Run `npm run design-system:build`, `npm run lint`, `npm test`, `npm run build` in
  `apps/frontend` and `git diff --check`. Attribute inherited failures without unrelated cleanup.
- [ ] Browser checks on Semarang: Knowledge → Edit → format → Preview → Save → hard refresh;
  repeat on Plan and gallery-opened ICP/persona. Verify Discard, untouched open/close, edit then
  undo to initial content, switching documents, read-only, failed saves and version conflicts.
  Use a disposable verification document for destructive test content.
- [ ] Check nested/task lists, tables, fenced code, long inline text, unsupported input and narrow
  chat/gallery panes. Saved Markdown may normalize formatting, but meaningful content must remain.
- [ ] Update frontend architecture docs and `_memory/` with the version, evidence, remaining gaps
  and live-proof status. Commit locally; no remote publication without a current instruction.

## Completion

One shared library editor serves all four contexts, controls reuse library behavior, saves persist
through existing versioned routes, untouched content stays clean, parse errors preserve source,
and long-content checks introduce no outer horizontal scroll. Nothing is implemented by this plan.
