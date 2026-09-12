# Markdown editor toolbar — brief (deferred slice)

**Date:** 2026-09-12. **Status:** brief only; founder ruling R11 in
`2026-09-12-project-context-and-icp-authoring-design.md`. Built later as one shared component,
used by the Brand Context Knowledge editor, the project Plan tab, and any future markdown surface.

## What it is

A formatting toolbar above the CodeMirror markdown editor (screenshot 2026-09-12, "Cursor ABM
Landing Page Design Plan"). CodeMirror is the editing engine; the toolbar is React over the
platform's own icons and tokens, each button running one small CodeMirror command. No in-house
markdown engine (ruling R10).

## Buttons, grouped as in the screenshot (image and video left out for v1)

| Group | Button | Command |
|---|---|---|
| History | Undo, Redo | CodeMirror `undo` / `redo` |
| Headings | H1, H2, H3 | toggle `# `, `## `, `### ` on the selected lines (remove when already that level) |
| Inline | Bold, Italic, Strikethrough, Inline code | wrap the selection with `**`, `*`, `~~`, `` ` `` (unwrap when already wrapped; with no selection insert the pair and place the cursor inside) |
| Lists | Bullet, Numbered, Task | prefix the selected lines with `- `, `1. ` (renumbered), `- [ ] ` (toggle off when present) |
| Blocks | Blockquote, Code block, Horizontal rule | prefix lines with `> `; wrap the selection in a fenced block; insert `\n---\n` |
| Insert | Link, Table | `[text](url)` around the selection (or a placeholder); a 3×2 GFM table template |

The megaphone icon in the screenshot (a callout) is not native markdown and is left out; a
blockquote covers the need.

## Rules

- Keyboard shortcuts mirror the buttons (⌘B, ⌘I, ⌘⇧X, ⌘E, ⌘K, ⌘Z / ⌘⇧Z) through CodeMirror keymaps.
- Every command is a pure function `(state) -> transaction` in `components/markdown/commands.ts`,
  unit-tested under `node --test` without a DOM.
- Styling: `--clue-ds-*` tokens only; icon buttons 28×28, groups separated by
  `--clue-ds-color-border-subtle` rules; the active heading level shows the pressed state.
- The toolbar renders only in edit mode; preview stays `react-markdown` + `remark-gfm`.

## Out of scope for v1

Image and video insertion; tables with cell editing; slash commands.
