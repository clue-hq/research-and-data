# Increment 2a — Document identity + exclusive turns + message queue

Implements `PHASE-2-PLAN.md` §2a on `agents/editing-roundtrip-v0`. Decisions
locked with the user 2026-07-04: **auto-create on first persisting action**
(no Save button), and for 2b **persistent SSE backed by Redis/Postgres** (no
filesystem-JSON event store) — recorded in the plan.

## What shipped

### Document identity (`documentStore.ts`, `page.tsx`, `EditorApp.tsx`)
- `?document=<id>` loader: `page.tsx` fetches `GET /documents/{id}` and
  mounts `EditorApp` with `documentId` + the authoritative scene. Loading and
  error states are explicit; a failed load offers "Start a new design"
  (clears the param) instead of silently opening an empty canvas.
- Auto-create: `documentId` became state. With none set, the first persisting
  action (`commitAppliedOperations → enqueueForPersistence`) POSTs
  `/documents` and adopts the server-minted id. The local placeholder id
  (`doc_untitled`) is stripped from the POSTed scene so the server mints
  (`POST /documents` adopts `scene.meta.id` verbatim when present — a shared
  placeholder would collide on the second create).
- **Adoption must patch every local scene copy** — engine scene, React scene,
  and all undo/redo frames get `meta.id` rewritten to the new id, else the
  first reconcile flags a false `meta.id` divergence and stomps local state.
  The URL gains `?document=<id>` via `history.replaceState`.
- Seed choice: creation seeds from the PRE-op scene and then enqueues the
  triggering batch (so even the first action gets a server-side envelope —
  the 2d checkpoint machinery needs it). Exception: an empty canvas is not a
  creatable document (LUMV0100 requires ≥1 page), so the first action on an
  empty canvas seeds from the POST-op scene and skips enqueueing that batch
  (the creation IS its persistence — the first agent turn has no envelope in
  this one case; its "before" was an empty canvas anyway). Ops that leave the
  canvas still empty stay local; the scene carries them into the eventual
  creation seed.
- Concurrency: single-flight creation promise; batches that land while
  creation is in flight ride behind it in order. Failure surfaces
  `EDITOR_DOCUMENT_CREATE_FAILED` and the next persisting action retries.

### Exclusive turns (Moda's lock)
- While `isAgentRunning`: `applyOperations`, `applyStructuredEditInstruction`,
  `undoLastOperation`, `redoLastOperation` are gated (same pattern as the 0c
  `agentPreview` review gate) with a new `EDITOR_AGENT_TURN_RUNNING`
  diagnostic; topbar Undo/Redo disable during run AND review.
- Floating status pill top-center of the canvas: *"Agent is designing —
  please wait to edit"* (with pulse dots). Only mutations lock — zoom/pan,
  panel switching, selection, Validate/Export stay live. The Reject path is
  never gated.

### Message queue (Moda's "Type to queue a message…")
- The composer stays typeable during run AND review; submitting while busy
  queues (`QueuedAgentMessage[]`), with the queued list rendered above the
  composer and per-message remove buttons. Placeholder + button label are
  state-aware (Queue vs Send).
- Drain: one message per idle transition (`!isAgentRunning && !agentPreview`),
  via effect. Accept and Reject both count as resolution (the user answered
  the preview; queued intent stands). A failed turn also drains — including
  the failed-with-visible-draft case, where the queued turn seeds from the
  draft on canvas (observed live, behaved correctly). Seeding is at DRAIN
  time (sendAgentPrompt reads live state), not enqueue time.

## Found-and-fixed: the editQueue could never persist in a real browser

The e2e caught a latent pre-existing bug: `ApiEditQueue` stored the global
`fetch` bare in a class field (`this.fetchImpl = options.fetchImpl ?? fetch`),
so `this.fetchImpl(...)` rebound `this` to the queue instance → Chrome throws
**"TypeError: Illegal invocation"** on the first persist. Every unit test
injects `fetchImpl`, and no real browser had ever run the queue (the editor
never had a documentId in real use until this increment) — so W3's
persistence leg was dead code in production from day one. Fix: wrap instead
of storing bare (`(input, init) => fetch(input, init)`).

Cost observed live: the first Accept created the document but silently lost
its op batch (version stayed 0; the "Queue Works" edit vanished on reload).
After the fix, an accepted turn bumped the document 0 → 11 with
editor-sourced envelopes and survived reload.

**Observability flag for 2b:** the queue's failure diagnostic
(`request_failed` reconcile) was swallowed by the Accept path's concurrent
export-preview flow (`setDiagnostics` races — last writer wins). Persistence
failures must not lose to cosmetic flows; 2b's run/status surface is the
natural place to fix diagnostic merging.

## Browser e2e (real stack: API :8002 @ 7fde677, editor :3002, real Opus)

Full gate on a fresh empty editor (screenshots in `browser-e2e/`):
1. Generation turn started → **banner up**, composer in queue mode
   (`2a-e2e-1-running-locked-queued.png`).
2. Mid-run mutation blocked: typed a Document Title rename during the run —
   engine scene + topbar heading unchanged.
3. Queued *"Change the headline text to 'Queue Works'"* while running; chip
   rendered with remove affordance.
4. Turn 1 ended failed-with-draft (known agent-quality flakiness, tracked in
   the agent-improvement backlog — irrelevant to 2a) → queue correctly
   drained at idle → queued turn ran seeded from the visible draft →
   edit-scoped proposal → review pill (`2a-e2e-2-queued-turn-review.png`).
5. **Accept → auto-create**: URL became `?document=doc_8f86…`; local engine
   scene adopted the server id; server had the pre-edit seed at v0.
6. (Post-fix) seeded turn *"Persisted Edit"* → Accept → **version 0 → 11**,
   editor envelope present.
7. **Reload the `?document=` URL** → loader fetched the document, canvas
   rendered "Persisted Edit", engine active and editable
   (`2a-e2e-3-reloaded-persisted.png`).

## Gates

- Editor suite **377 passed / 1 failed** — the 1 is the pre-existing
  `EditorCanvas` CanvasKit-default env-split case (run with
  `NEXT_PUBLIC_LUMEN_CANVASKIT=0`). +10 new tests: 6 in
  `EditorAppDocumentFlow.test.tsx` (auto-create/adoption/undo-frame patch,
  empty-canvas seed, create-failure retry, turn lock, queue drain + removal,
  queue-through-review + Reject drain) and 4 in `documentStore.test.ts`.
- tsc: clean except the pre-existing `ExportPanel.test.tsx` TS2493.
- One EditorApp test updated: the review-lock assertion now expects the
  ENABLED queue-mode composer instead of a disabled input.

## Notes / deferred

- Text-edit entry on canvas during a run isn't pre-blocked; the commit is
  gated (typing then being blocked loses that in-progress text). Fine for
  v1; revisit with 2b's lock UX polish.
- Reloading mid-run abandons the in-flight turn (sync POST dies with the
  page) — 2b's async run + SSE makes turns survive reloads.
- `adoptCreatedDocument` resets the engine mid-session (identical scene, new
  meta.id); a concurrent drag gesture could theoretically observe the reset.
  Not observed live; racy only in the first-persist instant.
- Next: **2b** (async turns + persistent SSE via Redis/Postgres per the
  locked decision, show-work checklist, "Show work" disclosure) or **2c**
  (selection chips — no backend dependency) if a quick win is preferred.
