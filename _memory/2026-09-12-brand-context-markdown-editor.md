# Brand Context Markdown toggle — 2026-09-12

Founder requested an Edit/Preview toggle after verifying the existing renderer repairs.
The branch charter remains frontend-only. Asked asynchronously whether to extend the backend
for persistent saves (new versions and optimistic conflict detection); no answer has arrived
during this implementation. Proceeded with the independently authorized frontend toggle and
explicitly stated that drafts are temporary; no backend write endpoint or fake Save was added.

Implementation:
- Knowledge Preview/Edit controls in the existing document header.
- CodeMirror lazy-loaded on Edit; existing installed packages, no new dependencies.
  `basicSetup` + `@codemirror/lang-markdown` own editing, highlighting, history and shortcuts.
- Preview still uses react-markdown + remark-gfm directly; no custom Markdown renderer.
- Per-path drafts survive document/section switches in the mounted Brand Context page.
  Preview/Edit preserves the current CodeMirror instance and undo history.
- Discard changes restores server-provided Markdown. Visible temporary-edit notice and
  browser unload warning when drafts exist. No browser storage or database writes.
- Canonical Brand Context contract and polish backlog updated to supersede O5's removed toggle.

Verification so far:
- Frontend design-system build, lint and production build pass. Existing two unused design
  editor warnings remain. All 89 Brand Context tests pass.
- Standalone `tsc --noEmit` includes existing test-file errors unrelated to changed production
  files; the normal production build passes. No unrelated type-test cleanup was attempted.
- Authenticated verification on Semarang :3040 with its existing test account/workspace.
  Runtime, database, service configuration and sibling processes are unchanged.

Closing browser verification:
- CodeMirror exposes the labelled editable Markdown source, lazy-loaded as one editor.
- Draft preview renders GFM tables, links, bold, blockquotes, numbered lists and fenced code.
- Switched Company overview -> AI Fax Agent -> Company overview: separate original document
  and retained draft verified. Keyboard Select All / replacement rendered only the new body.
- Preview -> Edit -> Undo -> Preview restored the prior draft, proving history survives toggles.
- Discard restored Company overview and removed the dirty notice and Discard action.
- Desktop/mobile screenshots `.runtime/markdown-editor-{desktop,mobile}.png`; 390px viewport
  has no horizontal page overflow or framework overlay. No browser errors reported.
- Verification browser closed after discarding its temporary edits; Semarang remains running.
- Inspection caught an awkward selection/scroll position after Discard; controlled replacements
  now reset the caret to the start. No Markdown parsing or rendering logic was added locally.

Follow-up: if the founder chooses persistent writes, reconcile the document-write contract
before implementation. Current Knowledge reads expose per-version UUID IDs, body-only Markdown,
version/status, and immutable artifact custody. Design.md is a projection of the brand kit;
confirmed ICP documents participate in confirmation gates. Do not overwrite artifacts or
pretend a generated projection is independently writable. No persistence is shipped here.
