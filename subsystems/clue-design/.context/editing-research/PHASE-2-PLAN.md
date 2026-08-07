# Phase 2 — The Moda agent-experience layer (implementation plan)

Source of truth: `MODA-EDITOR-PLAN.md` §4 Phase 2 (the backlog) + §1.2/§1.5/§1.6
(the observed Moda behaviors this phase reproduces). Entry state: **Phase 0
(0a/0b/0c) and Phase 1 (1a–1e) complete** — M1 done: seeded round-trip,
edit-scoped acceptance, Accept/Reject preview, freehand editing, agent pin
visibility. Styling reference for new chrome: `MODA-UI-STYLE-TOKENS.md`.

## Anchors (re-verified 2026-07-04 on `agents/editing-roundtrip-v0` @ 470fe94)

What Phase 2 rides on — all confirmed in current code:

- **Review lock exists, running lock does not.** `agentPreview` blocks manual
  edits/undo/redo/new turns (`EditorApp.tsx:450,508,568,718`), and
  `pendingReview` locks the chat input (`AgentChatPanel.tsx:47,104`) — but while
  `isAgentRunning` only the chat submit is disabled; **the canvas is fully
  editable during a live turn** (the exact conflict Moda's turn lock exists to
  prevent).
- **No document identity in real use.** `page.tsx` mounts `<EditorApp />` bare —
  no `documentId`, no `?document=` loader; the persistence path bails
  (`EditorApp.tsx:385`), so accepted ops vanish on reload. This is the recorded
  Phase-0c gap and it gates checkpoints + agent instructions.
- **The turn is synchronous.** `POST /agent/turn-preview` (`main.py:1017`) runs
  the whole loop inside the request; the editor learns nothing until the end.
  But the loop already records per-iteration `AgentIteration` records with
  compile/preflight/export/critique summaries and stop reasons (`loop.py:447+`),
  and the run dir under `.lumen-runs/<run_id>/` is written **incrementally**
  (per-iteration artifacts, `tools.py:213`; root at `config.py:33`) — the raw
  material for step streaming exists.
- **Selection already threads.** `payload.selected_node_id` + `active_page_id`
  land in the prompt's Editor-context JSON with a "prefer targeted repairs"
  instruction (`main.py:3218`). Chips are UI + a plural field + a stronger
  contract, not new plumbing.
- **Checkpoints are already a server feature.** `POST
  /documents/{id}/operations` accepts `checkpoint` → stored as the envelope's
  `checkpoint_label` (`main.py:~513`); `GET /documents/{id}/checkpoints` lists
  them (`main.py:579`); `POST /documents/{id}/revert?checkpoint=…` reverts via
  the stored `edit_envelopes` inverses + `undo_stack` (`main.py:731`), refusing
  cleanly when the anchor has left the stack. Compare|Revert is mostly UI.
- Multi-page + PageRail exist → variants-as-pages is a prompt change.

## Increments (do → check → decide, same rhythm as Phases 0/1)

### 2a — Document identity + exclusive turns (groundwork; editor-mostly)

1. **`?document=` loader**: `page.tsx` reads the param, fetches
   `GET /documents/{id}`, mounts `EditorApp` with `documentId` + scene.
   **Auto-create**: the first persisting action with no `documentId` (agent
   Accept or first manual op) `POST /documents` and adopts the id (URL
   updated via `history.replaceState`). Closes the 0c gap — accepted ops
   finally survive reload.
2. **Turn lock**: while `isAgentRunning`, block canvas edits/undo/redo/
   inspector commits with the same guards `agentPreview` already uses, plus a
   banner: *"Agent is designing — please wait to edit"* (reuse the
   engine-banner pattern/styles). The **Reject path must never lock** — it is
   the escape hatch.
3. **Message queue**: during run/review the chat input stays typeable
   (*"Type to queue a message…"*); queued messages submit one-at-a-time when
   the editor returns to idle. The drained turn seeds from the scene **at
   drain time**, not enqueue time.

**Gate (browser e2e):** start turn → canvas locked + banner → queue a message
→ run lands → review → Accept → queued message auto-fires as the next turn →
reload the `?document=` URL and the accepted design is still there.
**Decision (LOCKED 2026-07-04):** auto-create on first persisting action —
Moda-like, every canvas is a doc. No Save button.

### 2b — Show-work streaming: plan checklist + step events (the backend increment)

1. **Async turn**: `POST /agent/turns` starts the run in-process (thread) and
   returns `{run_id}` immediately. The loop gets an `on_event` hook emitting
   what it already knows (iteration started / DSL compiled / preflight /
   critique verdict / stop_reason / mode coercions) appended to
   `.lumen-runs/<run_id>/events.jsonl`.
2. **`GET /agent/runs/{run_id}`** returns `{status, events[], result?}`; the
   editor polls (~1s) and renders the Moda checklist in chat — *"Drafting
   design…" → "Edits applied ✓" → "Design reviewed ✓"* with live ticks —
   collapsing behind a **"Show work"** disclosure when the final summary lands
   (§1.6 step 4).
3. Keep `POST /agent/turn-preview` as a thin start-and-wait wrapper so tests,
   CLI, and existing fixtures stay valid.
4. **Remote-cursor-lite**: at preview application, highlight the nodes named in
   the op batch ("these changed"). A per-op animated cursor is optional polish
   later — our ops land as one previewed batch, not one-by-one writes.

**Gate (browser e2e):** live ticks during a real turn; close and reopen the tab
mid-run → the SSE reconnect (Last-Event-ID) replays missed events from the
store and live ticks resume.
**Decision (LOCKED 2026-07-04):** SSE with a PERSISTENT event store — Redis
or Postgres, NOT filesystem JSON. Design implication for 2b: the loop's
`on_event` hook writes run events to the store (run_id-keyed, monotonic seq);
`GET /agent/runs/{run_id}/events` is an SSE endpoint that replays from the
store on (re)connect — supporting `Last-Event-ID` — then streams live. The
API currently uses SQLite for documents; adding the run-event table to
Postgres (or standing up Redis) is part of 2b's scope and should be decided
against deployment reality when 2b starts (Postgres favored if the document
store migrates too; Redis if we want pub/sub fan-out cheaply).

### 2c — Selection-as-chat-context chips + compensating-edit contract (cheap, high value)

1. **Chips UI**: selecting a node attaches a removable chip to the chat input —
   display layer name + node id (Moda's two-layer "text-2"/"n14" mapping,
   §1.5/§1.6); persists across turns; multi-select → multiple chips.
2. **Payload**: `selected_node_id` → `target_node_ids[]` (keep the singular
   field one release for back-compat).
3. **Prompt contract**: strengthen `editor_instruction` (`main.py:3230`) into
   the compensating-edit behavior (§1.6): apply the change → re-fit → verify
   fit/no-overlap (managed mode re-fits free via the solver; the critic is the
   verify step) → the summary states what changed **and what was preserved**.

**Gate (fixtures):** on the type fixture from
`apps/agent_runtime/evaluation/sprint_fixtures/`, a chip-targeted §1.6-style
edit lands as targeted ops on exactly that node id; untouched nodes
byte-identical (reuse the 0b fixture assertion); summary names the preserved
layout.

### 2d — Per-turn checkpoints: Compare | Revert under each agent message

1. On Accept, pass `checkpoint: "agent-turn-<run_id>"` to
   `POST /documents/{id}/operations` — the field already exists server-side.
2. Under each accepted agent message render **Compare | Revert…**: Compare
   reuses the 0c before/after engine-reset machinery pointed at the checkpoint
   boundary; Revert calls `POST /documents/{id}/revert?checkpoint=…` and adopts
   the returned scene.
3. **Manual-edit interplay**: the endpoint already refuses when the anchor left
   the `undo_stack`; surface that honestly (disabled link + tooltip), don't
   pretend every turn is forever revertible.

**Gate (browser e2e):** two agent turns + one manual edit between them;
Compare each; Revert turn 1 → scene byte-equal to that checkpoint; the
invalidated case renders disabled. **Depends on 2a** (documentId).

### 2e — The experience extras (small, parallelizable after 2b)

- **Design-Plan pre-brief**: 4-question skippable form (variations / brand
  adherence / focus / CTA) folded into the prompt (§1.3).
- **Agent instructions**: per-document standing instructions stored on the
  document, injected into every turn's context (File → Agent instructions).
- **Variants as pages**: prompt change — N concepts as named pages.
- **Post-turn suggestion chips** (static heuristics v1: "Match other pages",
  "Bolder headline").
- **Notify-when-done toast** (rides 2b's run status).

## Milestone M2 — "Moda-experience"

On a real persisted document: the human watches the agent's plan tick while the
canvas is locked, queues a message mid-run, chips a node for a targeted
revision, Accepts the preview, then Compares/Reverts any past turn. Every beat
rides existing machinery — 0b's acceptance contract, 0c's preview, the envelope
inverses, Phase-1 freehand untouched.

## Risks / notes

- **Async run lifecycle (2b) is the only structural backend change**; all else
  is additive. In-process thread + `events.jsonl` keeps it dependency-free (no
  broker); the API is already the process that runs turns today.
- Queue semantics: drain one message per idle transition; a Reject drains the
  queue too (the user answered the preview; their queued intent still stands).
- Turn lock scope: block *mutations*, not navigation — zoom/pan/panel browsing
  stay live during a run (Moda locks editing, not looking).
- PNG↔SVG fit disparity + the agent-doc improvement backlog
  (`.context/agent-improvement/`) stay on the quality track, orthogonal to
  Phase 2.

## Sequence

**2a → 2b → 2c → 2d → 2e.** 2c has no backend dependency and can move ahead of
2b if quick wins are wanted; 2d strictly follows 2a; 2e items are cherry-pickable.
