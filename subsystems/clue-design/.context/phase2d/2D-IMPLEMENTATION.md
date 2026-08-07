# Phase 2d — Per-turn Compare | Revert (+ the scheduled hygiene)

The plan's "mostly UI" increment — the server checkpoint machinery
(envelope `checkpoint_label`, `GET /checkpoints`, `POST /revert` off stored
inverses) existed since Phase D and is UNTOUCHED. 2d opened with the debt
work scheduled for exactly this moment, then built the feature on clean
ground.

## Commits

- `d9d6ec0` — **the "transform flake" was cwd drift, not a toolchain bug.**
  Root-caused the recurring "Unexpected JSX expression across ~37 files"
  from 2b/2c: the repo root has no package.json, so a bare `npx vitest`
  whose cwd had drifted to the root silently used an npx-cached vitest with
  NO project config — no jsdom (`environment ~0ms` in failing summaries),
  no react JSX plugin — spuriously failing every .tsx file. Reproduced
  deterministically from the root; 3 consecutive cold-cache runs from
  apps/editor pass with zero warm-up. The `rm -rf .vite` "recipe" recorded
  in 2b/2c was a red herring (those commands also cd'd back). Fixed with a
  root `vitest.config.ts` guard that throws one clear error, clearing the
  poisoned npx cache, a frontend-practices trap entry, and debt-table
  updates (2a.5 rows DONE; `selected_node_id` drop added as a post-Phase-2
  chore). Diagnostic tell for the future: `setup 0ms / environment ~0ms`
  in a vitest summary = wrong-cwd run.
- `d7029ff` — **useEditHistory extraction** (debt row "undo/redo → 2d").
  Pure history mechanics (bounded frame stacks, operation log,
  lastOperation, undo()/redo() bodies — byte-identical moves, script-
  diffed). The agent-turn canvas-lock guards deliberately stay in
  EditorApp: the lock is orchestration policy enforced beside the other
  guarded mutation paths, so the hook has zero agent-state deps and the
  hook order stays linear (history → document → turn) with no new lazy
  wrappers. EditorHistoryFrame moved to the hook, killing the type-only
  cycle with EditorApp. Drive-by: deleted the dead applyAgentProposal
  server-only fallback (scheduled since 2a.5, missed in 2b — the
  onAccepted callback could never run without an engine) and the orphaned
  setEditorPanelMode dep.
- `3fbd8eb` — **useDocumentSync extraction** (the other half of the debt
  row). Document identity + the persistence leg: auto-create (in-flight
  batches riding behind creation in order), the three-site id adoption
  (engine + React scene + undo/redo frames — the false-divergence trap is
  now documented ON the hook), the ordered edit queue with
  reconcile-at-drain, create-failure retry. Bodies byte-identical
  (enqueueForPersistence's phase-history comments reworded per practices
  rule 9; code lines identical). EditQueueFactory moved to the hook,
  re-exported from EditorApp so tests keep their import.
- `c2cdb43` — **sticky persistence diagnostics** (the 2a-recorded
  last-writer-wins race, deferred out of 2b). engine/diagnosticsPolicy:
  persistence-class codes (create-failed, persist-failed, edit-rejected,
  reconcile-divergence, revert-failed) survive unrelated wholesale
  overwrites; a fresh write of the same code supersedes; clearing is an
  explicit `resolveDiagnosticCode` bypass called by the resolving flow
  (successful adoption clears create-failed). No diagnostics bus.
- `273a0b6` — **the feature.** Accept stamps `checkpoint:
  "agent-turn-<run id>"` onto its persisted batch (via new EnqueueOptions
  threaded enqueueForPersistence → editQueue → the ops POST, through all
  three persistence paths including auto-create). The accepted message
  carries the turn record (checkpoint + session-local before/after
  snapshots). hooks/useTurnCheckpoints owns:
  - **Compare** — read-only modal: engine.reset to the snapshot (CanvasKit
    paints from the ENGINE), live scene parked, every mutation path locked
    with EDITOR_COMPARE_ACTIVE; sends AND queueing blocked (a queued
    message would drain at idle under the read-only view); entry refused
    while running / reviewing / messages queued. Before|After toggle +
    "Back to current" restores the parked scene exactly.
  - **Revert** — POST /revert?checkpoint=…; on success adopt the
    authoritative scene, clear local history (frames reference pre-revert
    states), `resync` the edit queue's base_version (NEW EditQueuePort
    method — without it the next batch is rejected as a concurrent write
    and the queue halts), and invalidate every LATER turn client-side
    (mirroring the server's undo-stack rule). Refusals (409
    checkpoint_not_active / 404) are honest outcomes → "No longer
    revertible"; transport failures → sticky EDITOR_REVERT_FAILED.
    Two-step inline confirm, no browser dialogs.

## Known edges (recorded, deliberate)

- Compare snapshots are session-local: a reload loses Compare for earlier
  turns; Revert still works off the persisted checkpoint.
- The empty-canvas Accept (creation IS the persistence, batch skipped) has
  no server envelope → its Revert refuses honestly (EDITOR_REVERT_UNAVAILABLE).
- Local undo/redo still doesn't persist inverse batches server-side — a
  pre-existing gap (recorded since W3), untouched by 2d; the reconcile
  divergence path covers it. Candidate for the pre-restyle increment.

## Gates

- tsc at baseline; editor suite **402/403** cold-cache with zero warm-up
  (+11 across the increment: 5 diagnostics policy, 2 editQueue
  checkpoint/resync, 2 documentStore revert, 2 turn-row states; the 1 is
  the known EditorCanvas env-split case). API suite untouched (no server
  changes).
- Browser e2e (the plan's gate: two turns + a manual edit between them;
  Compare each; Revert turn 1; invalidated case renders disabled): below.

## Browser e2e evidence — run 1 FAILED (by design), fixes, run 2 PASSED

Both runs driven via Playwright MCP by a claude-opus-4.8 agent on the live
stack. Screenshots in `browser-e2e/` (`2d-e2e-*` = run 1, `2d-r2-*` = run 2).

### Run 1 (at `273a0b6`) — FAIL, and that's the gate doing its job

Compare passed fully (read-only enforced: no persisted mutations, sends
blocked, exact restore). But Revert exposed a two-defect chain on
`doc_0d7f8ce5…`:

- **Turn 1 (empty-canvas accept) had no checkpoint** — its batch folded
  into the creation seed (the recorded 2a edge), V1=0, no envelope. The UI
  offered Revert anyway → 404 `checkpoint_not_found`, the refusal was
  invisible in agent mode (diagnostics panel hidden), and the clicked row
  got mislabeled.
- **The post-Accept export preview was PERSISTING**: `persist_preflight`
  defaults true server-side, so each preview wrote the token-BAKED
  preflight scene + ops into the document (observed: V2=1 → V3=21 for a
  1-op turn) behind the edit queue's back → the next edit 409'd and
  persistence halted until reload. Also the server-side twin of the 0c
  scene-swap bug: the stored doc was losing live token bindings on every
  Accept.

### The fixes (`9107022`)

Editor document-export payload sends `persist_preflight: false` (the
editor's export is a preview, never a writer). The Accept path learns its
persistence disposition (`persisted | creation-seed | local-only`); a
creation turn carries `checkpoint: null` and renders "Not revertible
(created the document)" from birth (Compare stays); turn identity in
Compare moved to a stable per-turn key; revert refusals/failures also post
a visible chat message.

### Run 2 (at `9107022`) — PASS on all core gates

`doc_2d9cc0a5…`, versions 4 → 5 (turn 1, exactly +1 — no export
inflation) → 7 (manual edit, **no 409 right after an Accept**) → 8
(turn 2) → 11 (revert appended 3 inverse envelopes) → 12 (post-revert
in-session edit, no reload). **Every request in the session returned 200 —
zero 409, zero 404. Zero console errors.**

- Compare turn 1: correct Before/After, read-only held, Back to current
  exact (`2d-r2-4*.png`).
- **Revert turn 1 (primary gate):** two-step confirm → "Reverted the
  design to just after this turn (3 later change batches undone)" → canvas
  back to post-turn-1 (headline "Checkpoint Two", subtitle without later
  edits) → **turn 2's row → "No longer revertible"** → server scene +
  version corroborate (`2d-r2-5.png`).
- Post-revert edit persisted in-session (resync gate) (`2d-r2-6.png`).

### Honest gaps from run 2

- **Fix 2's "Not revertible" row wasn't reachable in r2's flow**: two
  failed draft attempts left a visible draft on canvas, so the eventual
  creation accept seeded from a non-empty scene and legitimately earned a
  checkpoint. The creation-seed branch only fires on a truly-empty-canvas
  accept — exactly what run 1 hit (V=0, no checkpoint, 404). Run 1 proved
  the branch's necessity; the row rendering is unit-tested; the
  disposition return is 6 lines of straight-line code.
- **Agent-quality note (not 2d):** a plain "create a poster" prompt on a
  fresh canvas repeatedly returned no_proposal/Draft-visible — the loop
  judges the visible draft as already satisfying the request. Belongs on
  the agent-improvement backlog (seeded-vs-fresh heuristics).
