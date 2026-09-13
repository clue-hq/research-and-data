# Markdown editor toolbar Implementation Plan (Lane 2, plan 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One shared formatting toolbar above the CodeMirror markdown editor, used by the Brand Context Knowledge editor and the project document surface (Plan tab, ICP and persona documents), with keyboard shortcuts, tokens-only styling, and every command unit-tested without a DOM.

**Architecture:** Every command is a pure function `(state: EditorState) => TransactionSpec | null` in `components/markdown/commands.ts`, exercised with `EditorState.create` under `node --test` (no DOM needed). `MarkdownToolbar` is a React component that dispatches those specs on the `EditorView` the shared `useMarkdownSourceEditor` hook exposes; a `Compartment` adds the keymap. The toolbar renders only in edit mode; preview stays `react-markdown` + `remark-gfm`.

**Tech Stack:** Next.js App Router + TypeScript, CodeMirror 6 (`@codemirror/state`, `@codemirror/view`, `@codemirror/commands` — add it; `@codemirror/lang-markdown` present), `@clue/design-system` tokens, `node --test` via `tsx`.

**Spec:** `docs/superpowers/specs/2026-09-12-markdown-editor-toolbar-design.md` (the brief; rulings R10, R11). Depends on `2026-09-12-plan-tab-frontend.md` Task 5 (the shared `components/markdown/` pieces).

## Global Constraints

- **External libraries only (R10):** CodeMirror is the engine; no markdown parsing beyond the commands' own line/selection arithmetic.
- **Buttons (v1):** Undo, Redo · H1, H2, H3 · Bold, Italic, Strikethrough, Inline code · Bullet list, Numbered list, Task list · Blockquote, Code block, Horizontal rule · Link, Table. No image, video, callout.
- **Shortcuts:** ⌘/Ctrl+B bold, ⌘I italic, ⌘⇧X strikethrough, ⌘E inline code, ⌘K link, ⌘Z / ⌘⇧Z undo/redo (CodeMirror's `history` keymap), ⌘⇧7 numbered list, ⌘⇧8 bullet list.
- **Styling:** `--clue-ds-*` tokens only; icon buttons 28×28; groups separated by 1px `--clue-ds-color-border-subtle` rules; pressed state on the active heading level and active inline marks (from the selection's surrounding text); the token test stays green. Icons come from `projectIconSources` (`ProjectIcon`); add missing glyphs there as SVG sources, never inline hex.
- **Accessibility:** `role="toolbar"`, `aria-label="Formatting"`, roving tabindex with Arrow keys, `aria-pressed` on toggles, `aria-keyshortcuts` on each button, `title` with the shortcut.
- **Gate:** `npm run design-system:build && npm run lint && npm run build` and `npm test` in `apps/frontend`.
- **Commits:** local only, no push, no AI attribution.

---

### Task 1: Pure commands

**Files:**
- Create: `apps/frontend/src/components/markdown/commands.ts`, `commands.test.ts`
- Modify: `apps/frontend/package.json` (`"@codemirror/commands": "^6.8.0"` — `npm install`)

**Interfaces:**

```ts
import type { EditorState, TransactionSpec } from "@codemirror/state";

export type MarkdownCommand = (state: EditorState) => TransactionSpec | null;

export const toggleHeading: (level: 1 | 2 | 3) => MarkdownCommand;   // per selected line: set "#"*level+" ", remove when already that level, replace another level
export const toggleInline: (marker: "**" | "*" | "~~" | "`") => MarkdownCommand; // wrap/unwrap the selection; empty selection → insert pair, cursor inside
export const toggleLinePrefix: (kind: "bullet" | "numbered" | "task" | "quote") => MarkdownCommand; // "- ", "1. " renumbered, "- [ ] ", "> "; toggle off when every selected line has it
export const wrapCodeBlock: MarkdownCommand;      // ```\n<sel>\n```; a selection already fenced is unfenced
export const insertHorizontalRule: MarkdownCommand; // "\n---\n" at the cursor, on its own line
export const insertLink: MarkdownCommand;         // "[<sel or text>](url)" with "url" selected
export const insertTable: MarkdownCommand;        // 3×2 GFM table template on its own lines
export function inlineMarkActive(state: EditorState, marker: string): boolean;   // selection or cursor inside a pair
export function headingLevelAt(state: EditorState): 0 | 1 | 2 | 3;
```

- [ ] **Step 1: Failing tests** (one `describe` per command; `EditorState.create({ doc, selection })` → apply spec with `state.update(spec).state.doc.toString()`): heading toggles on/off/replace across two selected lines; bold wraps `word` → `**word**`, unwraps, empty selection inserts `****` with cursor at 2; numbered list renumbers `1. 2. 3.` after toggling on three lines and strips when all three have it; task list on a bulleted line replaces `- ` with `- [ ] `; code block fences and unfences; rule inserts with surrounding newlines when the cursor is mid-line; link selects `url`; table inserts the template; `inlineMarkActive` true inside `**x|**`; `headingLevelAt` reads `## `.
- [ ] **Step 2: Run — FAIL. Step 3: Implement. Step 4: `npm test` PASS. Step 5: Commit** — `feat(markdown): pure CodeMirror markdown commands with tests`.

---

### Task 2: The toolbar component and the keymap

**Files:**
- Create: `apps/frontend/src/components/markdown/markdown-toolbar.tsx`, `markdown-toolbar.module.css`, `markdown-keymap.ts`
- Modify: `components/markdown/use-markdown-source-editor.ts` (expose `viewRef` and accept `extensions?: Extension[]`; add `history()` from `@codemirror/commands` if `minimalSetup` does not already include it — it does; keep `minimalSetup`), `components/markdown/markdown-source-editor.tsx` (render `<MarkdownToolbar view={…} />` above the editor when `toolbar !== false`), `features/projects/config/project-icon-sources.ts` (glyphs: `undo`, `redo`, `heading-1`, `heading-2`, `heading-3`, `bold`, `italic`, `strikethrough`, `code`, `list`, `list-ordered`, `list-checks`, `quote`, `code-block`, `minus`, `link`, `table`)
- Test: `markdown-keymap.test.ts` (the keymap binds each shortcut to the matching command name — assert on the exported binding table, not on CodeMirror internals)

**Interfaces:**

```tsx
export function MarkdownToolbar({ view }: { view: EditorView | null }): JSX.Element
export const markdownKeymap: readonly KeyBinding[];   // built from the same command table
```

Behaviour: each button `onMouseDown={e => e.preventDefault()}` (keeps editor focus) and `onClick` dispatches `command(view.state)` when non-null; `aria-pressed` computed from `inlineMarkActive`/`headingLevelAt` on `view.state` (subscribe through an `updateListener` set in the hook, re-rendering on selection change with a `useSyncExternalStore`). Layout per the brief: `.toolbar` flex, gap 2px, padding `4px 8px`, `border-bottom: var(--clue-ds-product-border-grid-width) solid var(--clue-ds-color-border-subtle)`, background `var(--clue-ds-color-bg-neutral)`; `.group` flex with a 1px right rule; `.button` 28×28, radius `var(--clue-ds-product-radius-sm)`, `color: var(--clue-ds-color-content-subtle)`, hover `background: var(--clue-ds-color-bg-neutral-hover)`, pressed `background: var(--clue-ds-color-bg-neutral-active); color: var(--clue-ds-color-content-neutral)`. Verify each token name exists in `packages/design-system/generated/tokens.css`.

- [ ] **Step 1: Failing keymap test. Step 2–3: implement; `npm test`, `npm run lint`, `npm run build`.**
- [ ] **Step 4: Browser check** (:3020, `/browse`): Knowledge page → Edit → the toolbar renders; Bold on a selection; ⌘K inserts a link; Arrow keys move focus across buttons; Preview hides the toolbar.
- [ ] **Step 5: Commit** — `feat(markdown): the shared formatting toolbar and keymap over the CodeMirror source editor`.

---

### Task 3: Mount on both surfaces; close-out

**Files:**
- Modify: `features/brand-context/components/knowledge-panel.tsx` (already uses the shared editor after plan-tab Task 5; pass `toolbar`), `features/projects/components/project-document-surface.tsx` (same), `apps/frontend/docs/architecture/frontend.md` (a paragraph on `components/markdown/`), `_memory/` note

- [ ] **Steps:** wire, gate, browser-check the Plan tab editing `plan.md` with the toolbar and saving a new version (the PUT path), commit — `feat(frontend): the markdown toolbar on the Knowledge editor and the project document surface`.

---

## Self-review

- **Brief coverage:** buttons and groups (T1–T2), shortcuts (T2), pure tested commands (T1), tokens-only styling and a11y (T2), both surfaces (T3), image/video/callout left out. ✔
- **Placeholders:** none; icon glyphs are named and added to the one icon source map. ✔
- **Type consistency:** `MarkdownCommand`, `inlineMarkActive`, `headingLevelAt`, `markdownKeymap`, `MarkdownToolbar({ view })` consistent across tasks. ✔
