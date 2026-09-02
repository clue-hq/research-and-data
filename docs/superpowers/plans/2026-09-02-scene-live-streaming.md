# Scene-ad editor live streaming — editor lock + checkpoint streaming (rung A), ported MVP live-reveal (rung B): design + implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this
> plan task-by-task (subagent dispatch revoked by standing founder rule 2026-08-27 — one
> accountable agent, inline execution). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** While the design deepagent generates a scene ad, the open editor tab shows the design
growing in real time instead of a grey canvas for 10–18 minutes — and the editor is view-only for
the whole run, enforced on both sides.

**Architecture:** Rung A forwards the ALREADY-EMITTED P0.4 `scene_checkpoint_committed` frames
from the design run's event stream into the thread SSE the shell already holds open, and extends
the one pure decision function that reloads the canvas; plus a two-sided edit lock (frontend
affordances + backend 409 on the document write routes while a design run is active). Rung B
ports the MVP editor's proven live-design-streaming consumption (op-batch frames + the S2.1
progressive-reveal pump) onto the platform editor, with P0.4 checkpoint versions as the
late-join/re-anchor mechanism the MVP never had. No engine (Rust) changes; no migrations; web
lane explicitly deferred.

**Tech Stack:** Python (platform `clue_api`, design `lumen_api`), TypeScript (apps/frontend),
existing thread SSE + `run_event` outbox, CanvasKit local repaint, vitest + pytest.

**Spec:** the 2026-09-01/02 founder discussion (this doc §"Founder rulings") — no separate spec
doc; the load-bearing ground truth is restated below so this plan stands alone.

## Global Constraints

- Scene (ad) lane only. The web lane ("website mode persists once at the end",
  `lumen_api/main.py:8932`) is DEFERRED — nothing here may block its later rung C.
- Platform editor only (`apps/frontend`); the design subsystem's MVP editor
  (`subsystems/clue-design/apps/editor`) is a READ-ONLY reference to port FROM, never modified.
- **No mid-run manual editing, ever** (founder ruling 2026-09-02, recorded in
  `part4-founder-rulings` memory): while a design turn is queued/running on a document the
  editor is view-only on every surface, even while streaming renders progress. Frontend lock AND
  backend refusal both required; the P0.4 CAS/checkpoint-skip machinery is a backstop, never the
  arbiter.
- Rung A must be SHIPPABLE ALONE (checkpoint-cadence streaming, ~per agent iteration). Rung B
  builds on it without reworking it.
- Streamed agent operations are display-state ONLY on the frontend — never enqueued into
  `editQueue` (they are not human writes; their durable form is the P0.4 checkpoint commits).
- All new stream frames ride the EXISTING thread SSE (one pipe; `text.delta` already proves the
  volume class). The design API's own per-run SSE (`run_stream.py`, token-minted) is recorded as
  the rejected alternative — a second authenticated pipe through the BFF for no added capability.
- Honesty invariant: only engine-verified state is ever rendered as the document. Rung A renders
  committed checkpoint versions (verified by construction). Rung B renders op batches that the
  engine compiled in the agent's working scene (`dsl_compiled`/`asset_placed` applied ops) and
  re-anchors to durable checkpoint versions — an op batch that fails LOCAL engine apply falls
  back to a document reload, never a hand-patched scene.
- Frontend gate per task: focused vitest; rung close = `npm run design-system:build && npm run
  lint && npm run build` + full suite (baseline 2246 pass / 0 fail; must not regress). Backend
  gate: the design API's focused pytest files per task.
- Local commits only; no push; no AI attribution trailers.

## Ground truth (verified in-session 2026-09-01/02, file+line)

**The producer side already exists and runs in every platform leg turn:**

- P0.4 `_LegSceneCommitter` (`lumen_api/main.py:9417`): every verified authoring round commits
  mid-run to `design_document` (engine-replay gate, ≥1-page gate, CAS on `current_version`,
  strictly additive: final version = base + N ops regardless of checkpoint count). Fires from
  `checkpoint_scene("render_preview")` — `agent_runtime/lumen_agent/tools/render.py:141`, i.e.
  once per agent render iteration (~1–3 min cadence).
- Each checkpoint emits `SCENE_CHECKPOINT_EVENT = "scene_checkpoint_committed"`
  (`main.py:9414`) with payload `{document_id, version, operations, reason, preflight_clean}`
  onto the run's event stream (`store.emit_run_event`, fenced by lease generation) — landing on
  the platform `run_event` outbox as `design.run.event` frames (D7,
  `fleet_handler.py:536 sink`).
- The MVP live-streaming producer ALSO still runs: `tools/substrate.py:4462 record()` pushes an
  opt-in `sink_extra` channel; `dsl_compiled` (`substrate.py:684`) and `asset_placed` attach
  their applied `operations` — "authoring mutations that want the client to render the build as
  it happens" (S0). Per-mutation cadence, byte-identical to what accept replays.

**The consumer side exists only in the MVP editor (reference for rung B):**

- `apps/editor/src/engine/agentRunner.ts:268 operationsFromRunEvent` — strict-but-tolerant op
  extraction (absent/malformed → null, never throw; empty list = no batch).
- `apps/editor/src/hooks/useAgentTurn.ts` — the reveal pump: S2.1 inversion (apply each batch to
  the ENGINE immediately; HOLD the visible `setScene` until travel+draw animation completes),
  fast-forward apply, cumulative reconcile when a batch lands mid-draw, reload-resume via
  sessionStorage + gapless replay. Tests: `agentStreaming.test.ts`, `runEventStream.test.ts`.
- `apps/editor/src/engine/runEventStream.ts` — the D7 token-minted per-run SSE client (NOT
  ported; thread-SSE transport chosen instead — see Global Constraints).

**The platform/frontend seams this plan touches:**

- `platform/api/clue_api/design_fleet.py:144 drive()` — drives a leg run to terminal (claims,
  leases, polls `_run_is_terminal`, `_await_terminal_or_free`). The natural host for a mid-drive
  run-event forwarder (it is already the component watching the run).
- `platform/api/clue_api/chat/turn_events.py:60 TurnEventType` + `emit_turn_event` — the thread
  stream's frame vocabulary (`turn.started`, `text.delta`, `leg.opened/awaiting_user/closed/
  reopened` at :93-96); `design_leg` rows carry `{document_id, thread_id}`
  (`design_leg_wiring.py:466-474`), and `design_leg_run_id(turn_id)` (:158) maps turn→run.
- Frontend stream: `features/projects/data/chat-stream.repository.ts` (SSE parse) →
  `use-project-chat-controller.ts` (`chat.designRefresh`, `runningTurn` at :97/:861) →
  `features/projects/model/design-leg.ts:147 designRefreshForEvent` — TODAY reloads canvas ONLY
  on `leg.awaiting_user`/`leg.closed`; every mid-run frame hits `default: NO_REFRESH`. This
  switch is why the user waits.
- Canvas reload: `chat-surface.tsx:573 canvasReloadToken={session.reloadNonce +
  sceneSession.reloadNonce}` → `artifact-stage.tsx:110 reloadToken` → document refetch + repaint
  (local CanvasKit; no server render). The rich-text session survives it (dual dirty-channel
  re-seed).
- Gallery feed refetches ONLY on `refetchFeed: true` frames — today terminal-only, so mid-run
  thumbnail churn does not exist and rung A must keep it that way (`refetchFeed: false` on
  checkpoint frames; the `?v=` immutable thumbnail cache then never mints mid-run).
- Manual write path to guard: frontend `editQueue.ts` posts to `POST
  /documents/{id}/operations` (`lumen_api/main.py:2631`); siblings `PUT /documents/{id}/scene`
  (:2563), `POST /documents/{id}/undo` (:2813), `/redo` (:2835). The AGENT's own writes use the
  internal tool path (`_turn_design_tools(...).invoke("design_apply_operations", …)`,
  `main.py:9502`) — guarding the HTTP routes cannot block the agent.
- Design-side run state: `design_store.py:1981 list_running_runs(conn, workspace_id)`; a leg
  run's envelope payload records its target document.
- Editing-disabled precedent: `adapter/scene-engine-banners.ts:101` ("Canvas editing is
  disabled" — the engine-down posture); `SceneManualEdits.canApply()` and the armed gates in
  `hooks/use-scene-manual-edits.ts` are where write-eligibility already concentrates.

## Founder rulings (binding)

1. Streaming is wanted at real cadence; no waiting for terminal (2026-09-01).
2. No mid-run manual editing anywhere, both-sides enforced (2026-09-02).
3. Rungs: A = lock + checkpoint-reload (shippable alone); B = ported MVP live-reveal; web lane
   deferred, not to be worried about now (2026-09-02).
4. `preflight_clean: false` checkpoints STREAM (my recommended default, presented 2026-09-01 and
   not objected: verified committed work is the honest progress signal; the terminal state
   carries the quality verdict). Reversible one-line filter if overruled.

## Founder-visible defaults chosen here (all reversible)

1. **Lock copy:** banner/pill "The design agent is working — editing unlocks when it finishes."
   Backend 409 detail: `document.agent_run_active`.
2. **Chat send with an open text session** (the ruled lean, unratified): the send commits/closes
   the session first (same transactional posture as blur); typed work is never silently lost.
   Implemented in rung A as: session force-commit precedes the lock engaging.
3. **Canvas reload throttle:** ≥2s between checkpoint-driven reloads; trailing edge always fires
   (the last checkpoint is never skipped).
4. **Reveal timings (rung B):** ported verbatim from the MVP pump (travel/draw/materialize) —
   retuning is a knob, not a redesign.
5. **Lock release:** on ANY terminal turn outcome (`turn.completed/failed/cancelled` + leg
   frames) — a failed run must never leave a locked editor. Backend guard self-heals the same
   way (only `running` non-stale runs lock).

## The ladder

- **Rung A** — the editor lock (frontend + backend) and checkpoint-cadence streaming: the open
  tab reloads the document at each committed mid-run version (~per agent iteration). Shippable
  alone.
- **Rung B** — MVP-grade live-reveal: per-mutation op frames stream into the locked editor and
  draw themselves in via the ported reveal pump; checkpoint frames become sync anchors; late
  join loads the last committed version then applies the op backlog fast-forward.

## Design

### Rung A

**A-1: backend write lock.** `design_store` gains
`active_design_run_for_document(document_id) -> str | None` (a `running`-status, lease-live
scene run whose envelope targets the document). The four HTTP write routes
(`/operations`, `/scene`, `/undo`, `/redo`) call it first and refuse with
`HTTPException(409, detail={"code": "document.agent_run_active", "run_id": …})`. The agent's
internal tool path is untouched by construction. `layout-managed-editing` and
`agent-instructions` PUTs stay unguarded (they are settings, not scene writes — recorded; flip
them in if the founder disagrees).

**A-2: checkpoint frames onto the thread stream.** New `TurnEventType.DESIGN_CHECKPOINT =
"design.checkpoint"`. The design leg driver (`design_fleet.py`), which already sits in a poll
loop watching the run it drives, tails the run's `run_event` rows from a cursor each poll tick
and forwards every `scene_checkpoint_committed` as one turn event:
`{document_id, version, operations, preflight_clean}` under the leg's turn/thread. Forwarding is
best-effort (a dropped frame costs one reload; the next checkpoint or terminal frame
self-heals) and fenced exactly as the leg frames are.

**A-3: frontend policy.** `designRefreshForEvent` gains:
`case "design.checkpoint": return { refetchFeed: false, reloadCanvas: true }` — still only for
the active thread. The controller throttles `reloadCanvas` bumps (≥2s, trailing edge). Feed
refetch stays terminal-only (no thumbnail churn, no auto-open re-trigger).

**A-4: frontend lock.** One derived boolean per open document, from state the controller already
holds: `agentRunActive = runningTurn?.threadId === activeThreadId && legBoundToDocument`
(engaged on `turn.accepted|started` for a design leg thread, released per default 5). It flows
into the editor surface as a prop and lands in the places write-eligibility already
concentrates: `SceneManualEdits.canApply()` → false (inspector writes + structured edits +
undo/redo refuse with the lock note), gesture arming refused (`canvasSelection`'s existing
refusal-message pattern), `canOpenTextEdit` → false, Edit button disabled with the pill copy.
A lock engaging while a text session is OPEN force-commits the session first (default 2).
View/zoom/pan/selection-for-inspection stay live.

### Rung B

**B-1: ledger positions on op frames.** `substrate.py`'s `dsl_compiled`/`asset_placed`
`sink_extra` grows `operations_total` (ledger length AFTER the batch — the committer's own
arithmetic, `committed_operations`-compatible). This is the exact dedup cursor the frontend
needs; without it late-join dedup would be heuristic.

**B-2: op frames onto the thread stream.** Same forwarder as A-2, second filter: run events
whose payload carries non-empty `operations` become `TurnEventType.DESIGN_OP_BATCH =
"design.op_batch"` frames `{document_id, operations, operations_total, iteration}`. Oversized
batches (> 256 KiB serialized) forward WITHOUT `operations` (position-only) — the consumer
treats that as "reload at next checkpoint" rather than truncating ops.

**B-3: frontend consumption.** Port `operationsFromRunEvent`'s strict-tolerance into the
platform stream schema. A per-document stream cursor `appliedOperationsTotal`:
- op frame with `operations_total ≤ cursor` → drop (already reflected);
- contiguous frame → hand to the reveal pump, advance cursor;
- gap detected (total jumps past cursor + batch size), payload-less frame, or a batch the LOCAL
  engine apply refuses → mark dirty; the next `design.checkpoint`/reload re-anchors (reload sets
  cursor to the checkpoint's `operations`).
- `design.checkpoint` with `operations == cursor` → in sync, suppress the rung-A reload (no
  flicker); mismatch → reload (the anchor wins).

**B-4: the reveal pump, ported.** The S2.1 inversion lands beside the platform canvas: each
batch applies to the engine/scene state immediately; the VISIBLE scene swap is held on the
animation clock (travel → draw-the-box → materialize fade, timings verbatim); fast-forward for
backlog (late join applies the whole tail with no animation); cumulative reconcile when a batch
lands mid-draw. Streamed scenes are display-state — `editQueue` untouched, undo stacks
untouched, and the lock (rung A) guarantees no human write interleaves.

**B-5: late join / reload mid-run.** A tab opening (or reloading) onto a document with
`agentRunActive`: load the document (already at the last checkpoint version — P0.4's gift),
set cursor from the loaded version's op count (the checkpoint frame's `operations` value,
re-served in the stream backlog), then apply replayed op frames > cursor fast-forward, then go
live. No sessionStorage needed (the MVP's resume trick) — durable versions + stream replay do
it better.

### Error handling (both rungs)

Every refusal is loud where a human can see it: the backend 409 surfaces through the editQueue's
existing rejected-batch path as the lock note (never the generic "This edit could not be
applied"); a forwarder failure logs per-event and drops (progress is best-effort; the document
and terminal frames are the truth); a local engine apply refusal during rung B silently falls
back to reload-at-anchor (the one silent path — it is invisible-by-design, the canvas just
updates slightly later; the dirty-mark is logged). The lock NEVER fails open on error: if
`agentRunActive` cannot be computed, the editor stays unlocked only when no design leg exists on
the thread (absence of evidence), and locked when the last frame seen was non-terminal.

### Testing

Pure decisions get exhaustive vitest: `designRefreshForEvent` (checkpoint/op frames, thread
scoping, feed stays false), the throttle (trailing edge), the lock derivation (engage/release
per frame vocabulary incl. `turn.failed`), the cursor algebra (drop/apply/gap/dirty/anchor
matrix), pump scheduling (engine-ahead vs held display, fast-forward, mid-draw reconcile — the
MVP's `agentStreaming.test.ts` cases re-expressed against the platform pump). Backend pytest:
the 409 guard (running run blocks operations/scene/undo/redo; terminal run unblocks; agent tool
path unaffected), the forwarder (checkpoint→frame mapping, op filter, oversize position-only
form, fencing). Live walks close each rung (below).

## Out of scope (recorded)

Web-lane streaming (rung C — needs the web `_LegSceneCommitter` equivalent first); retuning
reveal timings; per-run SSE through the BFF (rejected alternative); locking
`layout-managed-editing`/`agent-instructions` PUTs; streaming into the GALLERY grid (cards keep
terminal-only refresh); multi-viewer fan-out concerns (thread SSE already serves every open tab).

---

## Implementation plan (each task: TDD, focused tests, then the gate; local commit per task)

### Task 1: Backend — `active_design_run_for_document` + the 409 guard

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_api/design_store.py` (new query helper beside
  `list_running_runs`, :1981)
- Modify: `subsystems/clue-design/apps/api/lumen_api/main.py` (routes :2563, :2631, :2813, :2835)
- Test: `subsystems/clue-design/apps/api/tests/test_agent_run_write_lock.py` (create)

**Interfaces:**
- Produces: `design_store.active_design_run_for_document(document_id: str) -> Optional[str]`
  (run_id of a `running` scene-leg run targeting the document, else None);
  HTTP 409 `{"code": "document.agent_run_active", "run_id": "..."}` on the four write routes.

- [ ] **Step 1: failing tests** — seed a running leg run bound to doc D: POST
  `/documents/D/operations` → 409 with code `document.agent_run_active`; same for PUT `/scene`,
  POST `/undo`, `/redo`; mark the run terminal → all four succeed again; a running run bound to
  doc E does NOT block doc D; the internal `design_apply_operations` tool path (invoked as the
  committer does) succeeds WHILE the run is running.
- [ ] **Step 2: run — expect FAIL** (`.venv/bin/pytest subsystems/clue-design/apps/api/tests/test_agent_run_write_lock.py -x -q`)
- [ ] **Step 3: implement** (helper reads the runs table exactly as `list_running_runs` does,
  filtered to scene-leg payloads carrying this `document_id`; guard is 4 call sites, one shared
  `_refuse_if_agent_running(document_id, store)` function)
- [ ] **Step 4: run — expect PASS** - [ ] **Step 5: commit**
  `feat(design-api): document writes refuse while a design run is active (409 agent_run_active)`

### Task 2: Platform — forward checkpoint frames into the thread stream

**Files:**
- Modify: `platform/api/clue_api/chat/turn_events.py` (`DESIGN_CHECKPOINT = "design.checkpoint"`)
- Modify: `platform/api/clue_api/design_fleet.py` (run-event tailer inside the drive/await loop)
- Test: `tests/design/test_design_checkpoint_forwarding.py` (create, beside the existing design
  fleet tests)

**Interfaces:**
- Consumes: `run_event` rows for the driven run (same reader the D8 pruner lane uses);
  `emit_turn_event` (existing signature).
- Produces: `design.checkpoint` turn frames
  `{document_id, version, operations, preflight_clean}` on the leg's thread, in event order,
  each forwarded at most once (cursor kept per drive attempt; replays tolerated downstream by
  the frontend's version monotonicity).

- [ ] **Step 1: failing tests** — a driven run emitting two `scene_checkpoint_committed` rows
  yields exactly two `design.checkpoint` turn events with mapped payloads, in order; non-checkpoint
  run events yield none (this task); a forwarder DB error is swallowed (drive completes, terminal
  frames intact); a fenced/foreign-generation row is not forwarded.
- [ ] **Step 2: FAIL** → **Step 3: implement** (poll-tick piggyback: each `_await` iteration
  reads rows after the cursor, forwards matching ones) → **Step 4: PASS**
- [ ] **Step 5: commit** `feat(platform): design.checkpoint frames stream mid-run into the thread SSE`

### Task 3: Frontend — stream schema + refresh policy + throttle

**Files:**
- Modify: `apps/frontend/src/features/projects/data/chat-stream.repository.ts` (parse the new
  frame type into the stream event union)
- Modify: `apps/frontend/src/features/projects/model/design-leg.ts` (`designRefreshForEvent`)
- Modify: `apps/frontend/src/features/projects/hooks/use-project-chat-controller.ts` (throttled
  canvas-revision bump)
- Test: `design-leg.test.ts` + a new `design-checkpoint-throttle.test.ts` (pure)

**Interfaces:**
- Produces: `designRefreshForEvent` returns `{refetchFeed: false, reloadCanvas: true}` for
  `design.checkpoint` on the active thread; `throttleTrailing(fn, 2000)` helper (pure,
  fake-timer tested) wrapping the canvasRevision bump.

- [ ] **Step 1: failing tests** — checkpoint frame on active thread → canvas-only refresh;
  inactive thread → NO_REFRESH; `leg.awaiting_user`/`leg.closed` behavior byte-identical to
  today (pin it); throttle: 5 frames in 3s → bumps at t=0 and t=2s and a trailing bump for the
  last frame; a single frame bumps immediately.
- [ ] **Steps 2–4: FAIL → implement → PASS** — **Step 5: commit**
  `feat(frontend): canvas reloads on design.checkpoint frames, throttled, feed untouched`

### Task 4: Frontend — the editor lock

**Files:**
- Create: `apps/frontend/src/features/chat-shell/model/agent-run-lock.ts` (pure derivation +
  copy)
- Modify: `use-project-chat-controller.ts` (expose `agentRunActive` per document),
  `chat-surface.tsx`/`editor-surface.tsx` (prop threading),
  `hooks/use-scene-manual-edits.ts` (`canApply` honors the lock; refusal note = lock copy),
  `components/scene-artifact-canvas.tsx` (gesture arming + `canOpenTextEdit` honor the lock;
  open text session force-commits when the lock engages),
  Edit button site (disabled + pill copy)
- Test: `agent-run-lock.test.ts` (pure) + extensions of the manual-edits/session tests

**Interfaces:**
- Produces: `agentRunLockForThread(frames..., activeThreadId, documentId): {locked: boolean}`
  — engaged on `turn.accepted|turn.started` for a thread with a design leg bound to the
  document, released on `turn.completed|turn.failed|turn.cancelled` and terminal leg frames;
  `AGENT_RUN_LOCK_NOTE = "The design agent is working — editing unlocks when it finishes."`

- [ ] **Step 1: failing tests** — lock engages/releases per the frame matrix (incl. `turn.failed`
  releasing — a failed run never leaves a locked editor); `canApply()` false + note while locked;
  gesture/text-session refusals carry the note; lock engaging with an open dirty text session
  commits it (spy on the session commit) before edits go inert; undo/redo disabled while locked;
  view/zoom/selection still permitted.
- [ ] **Steps 2–4** — **Step 5: commit**
  `feat(frontend): scene editor is view-only while the design agent runs`

### Task 5: Rung A close — gates + live walk

- [ ] **Step 1:** backend pytest files (Tasks 1–2) green; frontend gate
  (`design-system:build && lint && build` + full vitest, ≥2246, 0 fail).
- [ ] **Step 2: live walk** (colombo stack, Apollo workspace): start a generation from chat with
  the ad tab open → canvas updates at each agent render (~1–3 min), gallery card quiet until
  terminal; during the run: inspector writes refused with the lock note, Edit pill disabled,
  text session cannot open, a second tab's raw POST gets the 409; kill the worker mid-run →
  turn fails → editor unlocks; after terminal: editing works, undo history clean (no streamed-op
  frames in it).
- [ ] **Step 3: commit walk memory note** (`_memory/2026-09-XX-scene-streaming-rung-a.md`).

### Task 6: Runtime — ledger position on op frames (rung B begins)

**Files:**
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/tools/substrate.py`
  (`dsl_compiled` + `asset_placed` `sink_extra` gains `operations_total`)
- Test: extend the runtime's substrate event tests

- [ ] **Step 1: failing test** — a compile emitting a 3-op batch onto an 8-op ledger pushes
  `sink_extra` with `operations: [...3]` and `operations_total: 11`; a refused compile pushes
  neither.
- [ ] **Steps 2–4** — **Step 5: commit**
  `feat(agent-runtime): op-bearing sink events carry their ledger position`

### Task 7: Platform — `design.op_batch` frames

**Files:**
- Modify: `chat/turn_events.py` (`DESIGN_OP_BATCH = "design.op_batch"`), `design_fleet.py`
  (second forwarder filter)
- Test: extend `test_design_checkpoint_forwarding.py`

**Interfaces:**
- Produces: `design.op_batch` frames `{document_id, operations, operations_total, iteration}`;
  batches serializing over 256 KiB forward as `{document_id, operations_total, iteration}` only.

- [ ] **Step 1: failing tests** — an op-bearing run event forwards with ops + total; a
  non-op event does not; an oversize batch forwards position-only; ordering interleaves
  correctly with checkpoint frames.
- [ ] **Steps 2–4** — **Step 5: commit** `feat(platform): design.op_batch frames stream per-mutation ops`

### Task 8: Frontend — op-frame consumption + cursor algebra

**Files:**
- Create: `apps/frontend/src/features/design-editor/adapter/scene-stream-cursor.ts`
- Modify: `chat-stream.repository.ts` (frame parse), controller (route frames to the open
  document's stream state)
- Test: `scene-stream-cursor.test.ts` (pure, exhaustive)

**Interfaces:**
- Produces: `SceneStreamCursor` — `advance(frame) → {action: "apply", operations} | {action:
  "drop"} | {action: "dirty"} | {action: "anchor", version, inSync: boolean}` implementing the
  §B-3 matrix; `operationsFromStreamFrame(frame): Operation[] | null` (the ported
  strict-tolerance).

- [ ] **Step 1: failing tests** — the full §B-3 matrix: stale frame drops; contiguous applies
  and advances; gap → dirty; payload-less → dirty; checkpoint matching cursor → anchor
  inSync (reload suppressed); checkpoint mismatch → anchor stale (reload); malformed ops →
  null → dirty (never throw); dirty state drops applies until an anchor.
- [ ] **Steps 2–4** — **Step 5: commit** `feat(design-editor): stream cursor algebra for op frames`

### Task 9: Frontend — the ported reveal pump

**Files:**
- Create: `apps/frontend/src/features/design-editor/hooks/use-scene-live-reveal.ts` (the ported
  pump; MVP `useAgentTurn.ts` §S2.1/D4.5 as the verbatim reference)
- Modify: `artifact-stage.tsx`/`scene-artifact-canvas.tsx` (display-scene override channel while
  streaming — the same substitution pattern AD4.C's gesture preview uses)
- Test: `use-scene-live-reveal.test.ts` (fake timers; the MVP `agentStreaming.test.ts` cases
  re-expressed)

**Interfaces:**
- Consumes: `SceneStreamCursor` actions; the local engine apply (same call the MVP used —
  apply operations to the working scene, display-state only).
- Produces: `useSceneLiveReveal({documentId, locked, frames}) → {displayScene | null,
  fastForward()}` — engine-ahead apply, held display swap on the animation clock (timings
  verbatim), cumulative reconcile mid-draw, fast-forward for backlog, `null` when not streaming
  (canvas falls back to the document).

- [ ] **Step 1: failing tests** — batch applies to engine immediately but display swaps at
  travel+draw; a second batch mid-draw reconciles cumulatively; fast-forward snaps; an engine
  refusal surfaces as dirty (pump emits nothing; cursor anchors later); unlock/terminal clears
  the override so the canvas returns to the document.
- [ ] **Steps 2–4** — **Step 5: commit** `feat(design-editor): live-reveal pump — the design draws itself in`

### Task 10: Frontend — late join / reload mid-run

**Files:**
- Modify: `use-scene-live-reveal.ts` + the controller wiring
- Test: extend `use-scene-live-reveal.test.ts` + `scene-stream-cursor.test.ts`

- [ ] **Step 1: failing tests** — joining with an active run: document loads (at last checkpoint
  version), cursor seeds from the replayed checkpoint frame's `operations`, backlog op frames
  beyond it apply fast-forward, then live frames animate; a mid-run tab reload reproduces the
  same; joining with NO backlog checkpoint (run younger than first checkpoint) seeds cursor 0
  from the version-0 document.
- [ ] **Steps 2–4** — **Step 5: commit** `feat(design-editor): late join streams from the last committed version`

### Task 11: Rung B close — gates + live walk

- [ ] **Step 1:** full gates both sides (as Task 5), plus the runtime's substrate tests.
- [ ] **Step 2: live walk**: full generation with the tab open — elements draw in per mutation
  (seconds cadence, not minutes); checkpoint anchors cause no visible flicker when in sync;
  open the tab at minute ~8 → instant last-committed design + fast-forward catch-up + live
  tail; reload the tab mid-run → same; oversize/dirty path forced once (dev hook) → canvas
  self-heals at the next anchor; run terminal → pump clears, editing unlocks, final design
  byte-identical to a run watched with the tab closed (P0.4 additivity).
- [ ] **Step 3: close-out memory note** + update the CLAUDE.md backlog if any residual ships.

## Self-review (run at plan close)

Rulings 1–4 → Tasks 2–3 (streaming), 1+4 (both-sides lock), 5/11 (shippable rungs), ruling 4 →
no preflight filter anywhere. Defaults 1–5 → Tasks 4 (copy, session-commit, release matrix),
3 (throttle), 9 (timings). §B-3 matrix ↔ Task 8 tests 1:1. Type consistency: cursor actions
(Task 8) consumed verbatim by pump (Task 9); frame names (Tasks 2/7) consumed by repository
parse (Tasks 3/8). Placeholder scan clean 2026-09-02.


## Amendments (rung A execution, 2026-09-02)

- **Task 4b added (runtime):** the P0.4 checkpoint trigger keys on round ACCEPTANCE (critic PNG
  clean; a canonical-SVG failure is excused only when every error is the font-embedding refusal).
  Ground-truth correction: on this branch `checkpoint_scene` fires only from the orchestrator's
  `checkpoint=True` render (§5.2), and the WOFF2 font-embedding refusal made `reviewer.status`
  `error` every round, so NO checkpoint ever committed for ~71% of stored brand fonts. Commit
  4aa344bf6. Separate follow-up: WOFF2 embedding in `lumen-skia/embed.rs`.
- **Migration was required** (`35cda1939728`, closed CHECK on `agent_turn_event_stream_type`) —
  the "no migrations" line above is superseded.
- **Task 2 placement:** background tailer for the whole drive + final drain (the "poll-tick
  piggyback" hint would have delivered frames only after terminal when this lane drives).
- **Task 4 fix round:** durable leg seed from `ThreadWire.speaker.design_leg_state`; per-turn leg
  release; `writeGate()`; proactive note. Ruled defaults: `turn.awaiting_input` holds the lock; the
  direct `/artifacts/[id]` route stays lockless in rung A.
- **Runner correction:** `features/projects` / `chat-shell` tests are node:test (`npx tsx --test`).
- Close-out: `_memory/2026-09-02-scene-streaming-rung-a.md`.

## Amendments (rung B execution, 2026-09-02)

- **Task 7:** a second migration (`f506a1210f0c`) widens the turn-event CHECK for
  `design.op_batch`; the forwarder was extracted to `clue_api/design_event_forwarder.py`; a leg
  with no pinned `document_id` streams checkpoints but no op batches.
- **Task 8 (§B-3 corrected):** contiguity is `operations_total − operations.length === cursor`
  (non-streamed ledger ops exist); cursors are keyed by the FRAME's document id.
- **Task 9 (+ fix round):** the anchor reload decision is `!(cursorInSync && pumpClean)` with
  unknown health → reload; an in-sync anchor does not clear the pump's dirty latch; no drawn-box
  chrome (paced materialization with the MVP timings).
- **Task 10 (+ 3 fix rounds, two correcting the plan's rulings):** cursor and seed are scoped per
  (document, TURN) — ledger positions are per run; the seed uses an EXACT version match (a lower
  mark would double-apply) else dirty; a join REPLAYS the in-flight turn's logged applies through
  the seeded cursor (`replaySceneStreamJoin`), never seeks past them; a turn-less seed defers to the
  lock fold's active turn; `appliedThrough` prevents any double-apply.
- **Task 11 walk residuals:** worker-down leaves the run orphaned and the editor locked until a
  worker returns and RETRIES the turn (no `turn.failed`); walk #7's single anchor reload was not
  reproduced from clean loads (Fast Refresh artifact during instrumentation).
- Close-out: `_memory/2026-09-02-scene-streaming-rung-b.md`.
