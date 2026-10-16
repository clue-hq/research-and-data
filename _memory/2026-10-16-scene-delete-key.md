# 2026-10-16 — Scene editor Delete key (branch `feat/scene-delete-key`, off `research-streaming` bb70d8003)

## Founder rulings (this session)
- Delete / Backspace (Mac "delete") removes ANY selected scene element.
- A container goes WITH its contents (lifting children out of an auto-layout box would re-flow and move them).
- Because containers read as empty transparent boxes, a delete that took nested elements says so in the
  inspector note line: `Deleted "Card" and 4 elements inside it. ⌘Z to undo.` (Ctrl+Z off-Mac). Leaf deletes say nothing.
- The page's artboard (root frame, `rootFrameId`) is never deleted by the key.
- Several selected (layer-panel shift/⌘ click) → one batch, one undo frame. Selection cleared after.
- Typing targets (inputs, textareas, selects, contenteditable, the canvas text overlay) keep their Backspace.
- Agent-run lock → the existing lock note; locked node or locked descendant → refused whole with a note.

## Implementation
- `apps/frontend/src/features/design-editor/adapter/scene-delete.ts` — pure `deleteShortcut` + `planSceneDelete`
  (remove_node ops via `applyOps`; nested selected ids collapsed; lock rule mirrors lumen-core `build_safe_delete`).
- `hooks/use-scene-delete.ts` — window keydown, wired in `use-scene-editing-session.ts` after the clipboard hook.
- Tests: `adapter/scene-delete.test.ts` (11, incl. a real-wasm-engine apply). Neighbouring session/arrange/clipboard suites green.
- `tsc --noEmit` shows only pre-existing errors in font/wasm-handshake test files (untouched).

## Owed
- Live browser walk on the dushanbe stack (:3022) — needs the founder to sign in (Clerk is a hosted IdP).

## Live check (2026-10-16, dushanbe stack :3022)
- Founder ruling: dushanbe's stack now runs on **nashville's DB `clue_nashville_pm`** (the only DB with the
  `aryan+clerk_test_arv2@example.com` account — 4 workspaces incl. Conduit AI — at this branch's head `1ecc7437e5bc`),
  with `CLUE_STORAGE_BACKEND=s3` (same R2 bucket `clue-dev-bench` nashville uses). Nashville's stack was stopped first
  (`scripts/dev_stack_nashville.sh down`) so the two stacks' workers never share the DB. `.env` backup:
  `.env.bak-2026-10-16-before-nashville-db`. Old lane DB `clue_dushanbe` untouched (1 workspace, 0 designs).
- Walked on "Atrium Hospitality 1:1 LinkedIn ad" (doc_e15da7b1…, Conduit AI): Layers-selected leaf deleted exactly
  the selected node (temporary debug log confirmed selection → plan → op log 1:1), no note for a leaf, ⌘Z restored it.
  Two early `account_name` removals were selections made in the shared browser pane, not a bug. Document left at its
  original 8 elements (version 64).
- Not yet walked live: the nested-container note and a Layers multi-select (this ad is flat).
