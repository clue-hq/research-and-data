# Shared Markdown editor and toolbar — MDXEditor

**Date:** 2026-09-12; revised 2026-09-13. **Status:** library choice approved; implementation pending.
The founder selected MDXEditor after the library comparison. This replaces the custom CodeMirror
toolbar/source-editor approach in the original brief and updates parent rulings R10/R11.

## Experience

One shared visual editor serves Brand Context Knowledge, Plan, and project ICP/persona documents.
Preview remains `react-markdown` + `remark-gfm`. Edit uses MDXEditor with formatted headings,
lists, links and tables. Prose uses Clue's document typography; code and source mode use monospace.
Save/Discard remain in the document header. The existing immutable-version and conflict contract
stays in the feature hooks/repositories; no autosave or new backend contract is introduced.

Our shared React toolbar composes the library controls. MDXEditor owns formatting, selection
state, history, parsing and serialization; no custom Markdown command engine is built.

## Controls

| Group | User action | Library control / plugin |
| --- | --- | --- |
| History | Undo, Redo | `UndoRedo` |
| Blocks | Paragraph, H1–H3, Blockquote | `BlockTypeSelect`, headings/quote plugins |
| Inline | Bold, Italic | `BoldItalicUnderlineToggles`, limited to Bold/Italic |
| Inline | Strikethrough, Inline code | `StrikeThroughSupSubToggles`, limited to Strikethrough; `CodeToggle` |
| Lists | Bullet, Numbered, Task | `ListsToggle`, lists plugin |
| Insert | Link | `CreateLink`, link/link-dialog plugins |
| Insert | Table | `InsertTable`, table plugin, including native cell editing |
| Insert | Code block, Horizontal rule | `InsertCodeBlock`, code-block/CodeMirror plugins; `InsertThematicBreak`, thematic-break plugin |

The library block selector replaces separate heading buttons. Preserve existing H4–H6 content
even if the menu offers only H1–H3; do not constrain parsing to restrict the menu. Use native table
creation/cell editing; the previous exact 3×2 source template and exclusion of cell editing are
superseded. Image/video insertion, callouts, slash commands, AI authoring and collaboration remain
outside v1. Hide insertion controls without silently dropping those constructs from existing files.

Use MDXEditor's source mode to recover content it cannot import. Keep source monospace, wrapped
and without line numbers. Do not maintain another handwritten CodeMirror hook. A diff-review
feature is out of scope. Server-owned front matter stays outside the editable body.
Founder prototype review (2026-09-13): keep code blocks as simple monospace text, without
a language picker or syntax-highlighting controls. Preserve existing fence metadata.

## Integration and preservation

- Load MDXEditor and its plugins only on the client. Verify the selected published release with
  this checkout's React/Next/Lexical versions; avoid unrelated dependency overrides/upgrades.
- Share `MarkdownArticle` and `MarkdownEditor` under `components/markdown/`. Feature hooks own
  permissions, requests and drafts. The editor itself remains transport-free.
- The library's `markdown` prop initializes content. Use its API for explicit external resets;
  do not feed each keystroke back as a content replacement. Preserve the editor session and
  undo history through Preview/Edit. Discard resets to saved content.
- Key drafts by scope and stable path. A refreshed version UUID must not overwrite a dirty draft.
  Failed/conflicting saves retain changes. Busy/read-only state covers toolbar and source mode.
- Opening/focusing/previewing must not mark a document dirty or mint a new version. Ignore the
  library's initial-normalization event as a user change and retain the original untouched body.
  Also verify edit-then-undo-to-initial-content. Do not implement a second Markdown parser to
  compare serialized values.
- Real visual edits may normalize whitespace/marker choices when the library serializes them.
  Preserve meaning and formatting; do not promise byte-identical output after a visual edit.
  Import failures must retain recoverable original source and must never save an empty replacement.

## Styling and interaction

- Map documented public classes, CSS variables and `iconComponentFor` to Clue tokens/icons.
  App-authored styles use `--clue-ds-*`; retain vendor structural CSS with scoped overrides.
  Avoid generated internal class names and dependency forks. Theme popups/dialogs too.
- Use compact 28×28 controls, subtle separators, visible focus and selected states. Wrap toolbar
  groups in narrow panes. Reuse library toolbar navigation, selection and focus behavior.
- Verify shortcuts against the previous requested set. Any small binding adapter must invoke
  an exported library action; record missing bindings instead of recreating formatting commands.
- Wrap long URLs, backtick spans and source text; contain wide tables/code locally. The surrounding
  document pane, chat and page must not gain unintended horizontal scrolling.

## Acceptance

Check Knowledge, Plan and gallery-opened ICP/persona documents: all controls, keyboard use,
Preview/Edit, Save/reload, Discard, untouched imports, undo/redo, separate drafts, refreshed
versions during a draft, 409 retention, read-only behavior and recoverable import errors.
Use representative Markdown, nested/task lists, tables, fenced code and long unbroken text.
Run the frontend gate and browser checks on the active Semarang stack; preserve its environment,
database and sibling processes. This brief records a choice, not a completed compatibility test.

## Official references

- [Toolbar controls](https://mdxeditor.dev/editor/docs/customizing-toolbar)
- [Theming](https://mdxeditor.dev/editor/docs/theming)
- [Next.js setup and value lifecycle](https://mdxeditor.dev/editor/docs/getting-started)
- [Editor props and initial normalization](https://mdxeditor.dev/editor/api/interfaces/MDXEditorProps)
- [Import errors and recovery](https://mdxeditor.dev/editor/docs/error-handling)
- [Source mode](https://mdxeditor.dev/editor/docs/diff-source)
