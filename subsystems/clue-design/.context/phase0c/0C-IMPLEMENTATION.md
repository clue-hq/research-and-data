# Increment 0c — Accept/Reject gate + ops-diff application

Date: 2026-07-03. Branch: `agents/editing-roundtrip-v0`. Editor/API increment of
the Phase 0 round-trip plan; browser-validated live against the real API + real
LLM on the CanvasKit/Skia renderer (the product renderer — Konva appears below
only as a pre-existing unit-test harness mock).

## What shipped

**Preview + Accept/Reject (Moda's pattern), `EditorApp.tsx`:**
- A `proposed` agent turn no longer applies immediately: `previewAgentProposal`
  applies the ops to the ENGINE as an ephemeral preview (no undo frame, no
  persistence), and the canvas shows the result with a floating bottom-center
  review pill — `Before | After` segmented compare · "N agent changes" ·
  ghost `✕ Reject` · magenta `✓ Accept` — styled after moda.app
  (screenshots in this dir; reference screenshots in `.context/attachments/`).
- `acceptAgentPreview` commits the already-applied ops through the SAME
  bookkeeping as manual edits (`commitAppliedOperations`, extracted from
  `applyOperations`): undo frame, operation history, persistence via
  `/documents/{id}/operations` (edit_envelopes inverses server-side — the
  Compare/Revert machinery 0d+ can reuse), then runs the export preview and
  re-surfaces the agent's advisory diagnostics after it.
- `rejectAgentPreview` restores the pre-preview scene byte-for-byte
  (`engine.reset(baseScene)`); nothing was persisted, nothing to roll back.
- While a review is pending, mutating actions are blocked with a
  `EDITOR_AGENT_REVIEW_PENDING` diagnostic: `applyOperations`, undo/redo, and
  new agent turns (chat input disabled with a Moda-style "Accept or reject to
  continue" placeholder).
- `AgentChatPanel`: proposal card gets a "Reviewing changes" state with its own
  Reject/Accept row, an "Edit-scoped" chip when `acceptance_scope === "edit"`,
  and "Advisory" chips on `agent_runtime.visual_critique_advisory` diagnostics.
  `agentRunner` parses the 0b `acceptance_scope` field.

**The token-baking fix (the 0c-named bug):**
- `runExportForScene` no longer calls `replaceScene(preflight.scene)`
  (EditorApp.tsx:1099 pre-change). The preflight scene is token-BAKED (brand
  refs resolved to literals); swapping it into the live scene silently stripped
  live token bindings on every export/agent apply. It is now transient export
  INPUT only. Pinned by a unit test using a marker-titled baked scene: the
  export runner receives the baked scene, the live document never adopts it.
- Note: `runPreflight` (the explicit Validate button) still applies the
  preflight scene — that is the button's documented purpose ("Preflight
  applied N canonical operations"). Deliberately out of 0c scope; flagged for
  a later look because it bakes tokens too.

**"Ops diffed against the seed":** already guaranteed server-side by 0b's
`ops_valid_through_iteration` window; the editor previews exactly those ops on
the live scene. If the live scene drifted mid-turn and an op no longer applies,
the engine rejects atomically and the editor surfaces
`EDITOR_AGENT_PREVIEW_REJECTED` with a retry hint — no partial state.

## Browser e2e (Playwright MCP, CanvasKit + Skia + real WASM engine + real LLM)

Setup: uvicorn API (`.env` sourced, helper at `target/debug`) + `next dev`;
wasm + helper REBUILT at the same HEAD so the W5 version handshake passes
(engine_commit `ca396752cdce` on both — they had drifted, which silently
downgrades the editor to server-only mode and disables previews).

Flow validated (screenshots in this dir):
1. Turn 1 "Change the contact name text to 'Dr. Anaya Rao'" → proposed →
   auto-preview: canvas shows the new text; review pill up; chat locked;
   proposal card in review mode with DSL `#node_contact_name text("Dr. Anaya
   Rao")` + 1 update_node op (`0c-review-after.png`).
2. Before/After compare — **found a real bug live**: the toggle was
   display-only (`setScene`), but the CanvasKit surface paints from the ENGINE,
   so "Before" showed stale pixels (`0c-review-before.png`, kept as the bug
   record). Fixed: the toggle resets the engine to the chosen snapshot
   (authoritative for every renderer), and Accept re-arms the preview state
   first (`0c-review-before-fixed.png` shows Before correctly rendering
   "Dr. Priya Sharma" in Skia).
3. Accept → review pill gone, ops committed (operation history shows the
   update_node, Undo enabled), export preview rendered, slot binding on the
   node fully intact, document title untouched (no baked-scene adoption).
4. Turn 2 "Change the contact name text to 'Mr. Reject Me'" → preview showed it
   (`0c-reject-pending.png`) → Reject → content restored byte-exact to the
   accepted state "Dr. Anaya Rao" (`0c-after-reject-restored.png`), chat
   unlocked, nothing committed.

Also observed live: the 0b director prompt language is doing its job — both
turn summaries explicitly reasoned "per seeded-continuation rules, pre-existing
quality issues outside the requested edit are advisory and should not block."

## Tests

- `EditorApp.test.tsx`: main agent test rewritten for the preview flow
  (auto-preview, review bar, Before/After via the real WasmEngine, Accept
  commits + undo enabled + advisory chips + edit-scoped chip + the token-baked
  marker-scene assertion) + a new Reject test (byte-restore, no undo frame, no
  export, selection preserved). `AgentChatPanel.test.tsx` updated for new props.
- Suites: editor 47/47 in the agent/panel files; full editor suite green in its
  standard config. (Pre-existing, unrelated: `ExportPanel.test.tsx` has a tsc
  error at HEAD, and the suite has an inherent env split — `EditorApp.test`
  mocks the Konva surface so it runs with `NEXT_PUBLIC_LUMEN_CANVASKIT=0`,
  while `EditorCanvas.test` asserts the CanvasKit default. Flagged, not
  touched.)

## Deferred / follow-ups

- `runPreflight`'s scene swap (explicit Validate) also bakes tokens — same
  class of issue as the fixed export path, but user-initiated; decide in 0d.
- Editor cannot yet OPEN a saved document (page.tsx always starts from
  minimalScene, documentId undefined → accept-persistence is skipped in the
  browser; covered by unit tests). A `?document=` loader is small and makes
  accepted ops actually persist in real use — natural 0d item alongside
  Compare/Revert.
- Multi-page proposals: the review bar previews all ops at once; per-page
  stepping (Moda's page chips) later.
