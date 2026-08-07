# Phase 2a.5 — Frontend hygiene: editorConfig + useAgentTurn extraction

**Why this exists:** the Phase 1 sweeper audit (triaged in
`docs/frontend-practices.md`) flagged EditorApp as a god component. Rather
than a big-bang cleanup, 2a.5 extracts exactly the code Phase 2b is about to
rewrite (the agent-turn machinery, sync → async + SSE) plus the zero-risk
config duplication. Everything else on the debt table stays scheduled
(tokens + InspectorPanel split ride with the Moda restyle; Konva stays as
the jsdom test fallback).

## Commits

- `a134d98` — **editorConfig centralization.** The
  `NEXT_PUBLIC_LUMEN_API_BASE_URL ?? "http://localhost:8000"` fallback was
  copy-pasted at 12 sites (10 in EditorApp, plus page.tsx, CanvasKitStage,
  wasmEngine). All now call `editorApiBaseUrl()` from
  `apps/editor/src/engine/editorConfig.ts`. A function, not a const, so
  every caller keeps read-at-call-time semantics (Next inlines
  `NEXT_PUBLIC_*` per expression; jsdom reads real env — behavior identical
  in both).
- `e0f9660` — **useAgentTurn extraction.** The full turn lifecycle — run →
  propose → preview → Accept/Reject — plus the 2a message queue and its
  one-per-idle drain effect moved to `apps/editor/src/hooks/useAgentTurn.ts`.
  EditorApp: 2,433 → 2,011 lines; agent state now 0 of its useStates.

## Design decisions (the parts that weren't mechanical)

1. **Deps object rebuilt every render, no memoization.** EditorApp never
   used useCallback; every handler was a per-render closure. The hook
   mirrors that exactly: `useAgentTurn({...})` receives fresh deps each
   render, so its callbacks close over the current scene/selection with the
   same staleness characteristics (i.e., none) as the inline originals.
   Memoizing the deps object would CHANGE semantics — don't.
2. **The canvas lock spans both sides of the boundary.** The hook owns
   `isAgentRunning`/`agentPreview`; EditorApp's mutation paths
   (applyOperations, structured edits, undo/redo) guard on those values and
   surface `pendingAgentReviewDiagnostic` / `agentTurnRunningDiagnostic`,
   which are now module-level exports of the hook file.
3. **The applyOperations cycle is broken with a lazy wrapper.**
   applyOperations guards on hook state (defined after the hook call);
   the hook's applyAgentProposal fallback calls applyOperations. The deps
   entry `applyOperations: (ops, cb) => applyOperations(ops, cb)` defers
   the binding to event-handler time. runExport/runExportForScene moved
   above the hook call unchanged so they could be passed directly.
4. **Verbatim-move proof, not vibes.** A throwaway script diffed every
   moved block against `git show HEAD:...EditorApp.tsx`: sendAgentPrompt →
   setAgentPreviewView (336 lines), applyAgentProposal (41), the
   runExport pair (96), and the three module helpers — all byte-identical.
   Only deltas in the whole refactor: the two diagnostic factories gained
   `export` + lost 2-space indent, and the preview state's inline type
   annotation became the named `AgentPreviewState` interface.

## Known dead code, kept deliberately

`applyAgentProposal`'s server-only fallback passes an `onAccepted` callback
into `applyOperations`, but with no engine applyOperations returns at the
server-only diagnostic before ever invoking callbacks — the entire callback
body (system message, panel switch, export preview) is unreachable. Kept
byte-identical because 2a.5 is strictly behavior-preserving; fold its
removal into 2b's rewrite of this file.

## Gates

- tsc: baseline (the known pre-existing `ExportPanel.test.tsx` TS2493 only).
- vitest (`NEXT_PUBLIC_LUMEN_CANVASKIT=0`): **377 passed / 1 failed**, the
  failure being the same known pre-existing `EditorCanvas` env-split case —
  identical before and after both commits.
- Browser e2e: see below (run via Playwright MCP on the live :8002/:3002
  stack rebuilt at `e0f9660`, driven by a claude-opus-4.8 agent).

## Browser e2e evidence (PASS, all 8 steps)

Real stack (API :8002, editor :3002, both at `e0f9660`, handshake OK),
driven via Playwright MCP by a claude-opus-4.8 agent. Zero console errors
at every checkpoint. Screenshots in `browser-e2e/`.

1. Fresh load: engine active, no disabled banner (`2a5-e2e-0-loaded.png`).
2. Turn sent → "Agent is designing" banner + composer in queue mode, Send
   relabeled "Queue" (`2a5-e2e-1-running-locked.png`).
3. Mid-run queue: chip with remove affordance (`2a5-e2e-1b-queued-chip.png`).
4. Lock enforced during run: Delete and Cmd+Z were no-ops, Undo/Redo
   disabled, scene unchanged.
5. Turn 1 ended failed-with-draft (known agent-quality flakiness, not a
   refactor issue) → **queue auto-drained at idle**, turn 2 auto-started
   (`2a5-e2e-2-firstturn-failed-drain.png`) — the extracted drain effect
   works.
6. Turn 2 proposed → review bar; Before/After toggle flips active state
   (`2a5-e2e-2-review.png`) → Accept.
7. Accept → auto-create: URL gained
   `?document=doc_2b11816580df47a9a97b731554b34068`; API shows
   `current_version: 1` with the `apply_operations` envelope
   (`2a5-e2e-3-accepted-doc-url.png`).
8. Cold reload of the `?document=` URL: full scene rehydrated (layers tree,
   history v1), headline node selectable with inspector binding
   (`2a5-e2e-4-reloaded-persisted.png`).

Both lifecycle paths (failed→drain and proposed→Accept→persist) ran through
the extracted hook identically to the Phase 2a spec. Non-regression notes
from the gate: Enter inserts a newline in the composer (multi-line design,
pre-existing); turn-1 repair-budget flakiness is the tracked agent-quality
item, and the state machine handled it correctly.
