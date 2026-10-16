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
