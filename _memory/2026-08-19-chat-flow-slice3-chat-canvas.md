# 2026-08-19 — Chat-flow editor integration, Slice 3: the canvas live in the chats-route rail

Branch: `integration/frontend-design-part-iv-v2` (istanbul). Plan:
`docs/superpowers/plans/2026-08-19-chat-flow-editor-integration.md` §4 Slice 3.
Follows slices 1–2 (`f7540b63`, `f6d63cdc`, implemented in a prior Cursor session).
Process: SDD (ledger `.superpowers/sdd/2026-08-19-chat-flow-editor-integration/progress.md`),
Opus implemented, controller reviewed the diff inline (no reviewer subagent, per the
plan's binding founder rule) and re-ran the gates itself.

## What shipped (commit `3957166a` — one file: `chat-surface.tsx`)

- `ChatSurface` calls `useWebEditingSession({activeArtifactId: shell.activeArtifactId,
  documentIds})` — ids only, never the shell controller (§3 discipline; the two routes
  stay independent mounts of one machine).
- `ArtifactStage` gains the full canvas prop set the artifact route passes (mirror of
  `editor-surface.tsx:138-181`): `activeDocumentId`, `canvasControlsRef`,
  `canvasReloadToken`, `onCanvasSelect`, `selectedCanvasNodeId`, `undoDisabled`,
  `redoDisabled`, plus the lane-C rich-text props (`onRichTextCommit`,
  `onRichTextSessionChange`, `richTextBusy`, `richTextTheme`, `richTextEnabled`).
- **Controller ruling (ledgered):** `richTextEnabled` gates on the chat route's OWN
  dock-mount condition — `webEditingActive = editorVisible && kind === "web" &&
  session.activeDocumentId !== null` (the W4.8a law is per-mount: "the SAME condition
  that mounts the editing dock"). Slice 4 inherits `webEditingActive` as its natural
  guard for the real inspector props.
- `<main>` gains `data-selected-node` / `data-selected-schema` (same expressions as the
  artifact route) for browser verifiability.
- Untouched, per the slice-4 boundary: the `.chatBody` dock branches (placeholder
  `WebInspector`/`ImageInspector` props), the composer `onSubmit`, URL write-back.

## Verification

- Gates (implementer, re-run independently by controller): **757/757**, lint clean,
  production build green; zero test edits (pure prop plumbing, no new pure logic).
- Browser (Playwright MCP, authenticated 3030 stack, chat screen
  `/projects/prj_79aa…/chats/thr_4ef1f65…`): gallery card click opens the tab AND the
  real page renders in the rail (16k-char srcdoc; was empty before); Edit → canvas click
  selects (`data-selected-node="sub"`, `schema="text"`, outline drawn); undo/redo menu
  states proven DISCRIMINATINGLY (artifact-route write cleared the redo stack → chat
  route's menu showed Redo disabled — impossible from the prop defaults); conversation +
  bottom-docked composer intact when not editing; artifact route smoked unchanged
  (select → write v90→91 → undo → restored). Document left as found (undo_stack=49,
  redo_stack=1, alignment center; version counter advanced to 92 because the engine
  records an undo as a forward version — content identical).
- Screenshots: `.playwright-mcp/slice3-chat-{canvas-render,selection,undo-redo-menu}.png`.

## Notes

- Pre-existing, untouched: `chat-surface.tsx` fails `prettier --check` even before the
  change (lint gate is eslint-only); the seeded document's `example.com/widget` embed
  404s in the console on both routes (known benign fixture noise).
- While editing on the chat route the docked inspector still shows the placeholder
  fixture content over a REAL canvas selection — that is exactly the slice-4 boundary,
  not a defect.

## Next

Slice 4 — R6 choreography: feed the `.chatBody` web dock the real `WebInspector` props
from the hook (keyed per selected node, same set as `editor-surface.tsx:113-134`, using
`webEditingActive`), and dismiss-on-send at `chat-surface.tsx`'s accepted-submit point.
Then slice 5 (URL write-back), slice 6 (close-out).
