import type { Operation } from "../engine/scene/contracts";

/**
 * The stream cursor (scene live-streaming rung B, task 8).
 *
 * Rung A gave an open canvas a way to catch up: `design.checkpoint` announces a
 * version the document ALREADY holds durably, and the surface reloads. Rung B
 * adds the faster, weaker signal — `design.op_batch` carries the actual
 * operations of one mutation, streamed as the agent makes it, BEFORE any of it
 * is durable. Rendering those optimistically is what turns a five-minute blank
 * wait into a canvas the user can watch.
 *
 * The whole risk of doing that lives in one question, and this module is that
 * question: **may this batch be applied to the canvas right now?** Get it wrong
 * and the user watches a corrupted document — a batch applied twice, or applied
 * on top of a reloaded checkpoint version that already contains it, or a batch
 * applied over a hole where operations the stream never carried should be. So
 * the answer is arithmetic over one integer, exhaustible in a test, and no part
 * of it is a component's timing.
 *
 * ── THE LEDGER POSITION, NOT A BATCH COUNT ────────────────────────────────
 * Both frames report a position in the SAME per-run operation ledger, which is
 * the only reason they can be compared at all. But not every ledger entry is
 * streamed: asset and library registrations are recorded and never pushed to a
 * sink. So `operations_total` is where the batch ENDS in the ledger, and a
 * frame is contiguous with the cursor only when
 *
 *     operations_total − operations.length === cursor
 *
 * i.e. the batch begins exactly where the cursor stands. Anything else — a
 * gap left by un-streamed entries, a position-only frame (the forwarder drops
 * an oversize `operations` and keeps the position), an unreadable payload — is
 * NOT applicable, and the cursor goes DIRTY rather than guessing.
 *
 * ── DIRTY IS A WAITING ROOM, NOT AN ERROR ─────────────────────────────────
 * A dirty cursor drops every op frame it sees. It is not stuck: the next
 * checkpoint re-anchors it against a version the document durably holds, which
 * is the same mechanism rung A already ships. Dirty therefore costs the user
 * live motion for a few seconds, never correctness — which is the direction of
 * error this whole feature has to fail in.
 *
 * ── WHAT THIS MODULE DOES NOT DO ──────────────────────────────────────────
 * It applies nothing and reloads nothing. Task 9 owns the reveal pump that
 * consumes `apply` actions, and it will use an anchor's `inSync` to suppress
 * the visible reload when the canvas is provably already at the checkpoint's
 * version. **Task 3's throttled canvas reload stays exactly as it is** — this
 * task only COMPUTES `inSync`, and deliberately does not suppress anything;
 * changing the reload here would mean the cursor's first bug shows up as a
 * canvas that stops updating.
 *
 * Shape note: the task names this `SceneStreamCursor.advance(frame)`. It is
 * built as a pure fold instead (a state value plus `advanceSceneStreamCursor`),
 * matching `chat-shell/model/agent-run-lock`'s reducer — the controller holds
 * the state in React and a mutable object in a hook is the one shape that
 * cannot be held there safely.
 */

/** One `design.op_batch` payload, as the stream repository reads it. */
export interface SceneOpBatch {
  /** The design document these operations edit. */
  documentId: string | null;
  /**
   * The streamed operations — deliberately `unknown`.
   *
   * The repository boundary already reads this leniently, but this module is
   * the one that decides whether the bytes may touch a document, so it does
   * its own checking and accepts whatever it is handed rather than trusting a
   * type that came off the wire.
   */
  operations: unknown;
  /** Where the batch ENDS in the run's operation ledger. */
  operationsTotal: number | null;
  /** The authoring iteration that produced it. Carried, never decided on. */
  iteration: number | null;
}

/** The part of a `design.checkpoint` mark the cursor reads. */
export interface SceneCheckpointMark {
  documentId: string | null;
  /** The durable document version the checkpoint committed. */
  version: number | null;
  /** The ledger POSITION committed at that version — a count, not a list. */
  operations: number | null;
}

/**
 * The two frames the cursor understands. Every other frame stays away.
 *
 * `turnId` rides on the FRAME rather than inside the payloads because it is the
 * envelope's fact, not the design event's: every parsed stream frame carries
 * `turn_id`, and the payload shapes above are what the repository reads off the
 * design event itself. It is `string | null` for the same reason every other
 * field here is nullable — the wire is read leniently, and this module does its
 * own checking rather than trusting a type that came off it.
 */
export type SceneStreamFrame =
  | { type: "design.op_batch"; turnId: string | null; batch: SceneOpBatch }
  | {
      type: "design.checkpoint";
      turnId: string | null;
      checkpoint: SceneCheckpointMark;
    };

/**
 * What one frame means for the open canvas.
 *
 * - `apply` — the batch begins exactly at the cursor; render it.
 * - `drop` — nothing to do: already reflected, another document's, or the
 *   cursor is dirty and waiting for an anchor.
 * - `dirty` — this frame cannot be applied, and neither can the ones behind it
 *   until a checkpoint re-anchors.
 * - `anchor` — a durable version landed. `inSync` says the canvas's streamed
 *   state provably equals it, which is what task 9 uses to decide whether the
 *   visible reload is worth showing the user.
 * - `seed` — task 10: a canvas JOINED this run, having loaded the document at
 *   a durable version. It is not a frame; it is the surface reporting a load,
 *   folded into the same ordered log so the pump learns of it exactly where it
 *   happened relative to the frames around it.
 * - `rebase` — task 10 fix 1: a frame from ANOTHER TURN arrived, so a new run's
 *   ledger has begun and this document's cursor was reset to its start. What
 *   the canvas is showing was drawn from the previous run's frames, and the new
 *   run's operations are measured from the DOCUMENT, so the display goes back
 *   to it before the first batch of the new run lands on top.
 */
export type SceneStreamAction =
  | { action: "apply"; operations: readonly Operation[] }
  | { action: "drop" }
  | { action: "dirty" }
  | { action: "anchor"; version: number | null; inSync: boolean }
  | { action: "seed"; position: number; dirty: boolean }
  | { action: "rebase"; turnId: string | null };

const DROP: SceneStreamAction = { action: "drop" };
const DIRTY: SceneStreamAction = { action: "dirty" };

/** One document's place in its run's operation ledger. */
export interface SceneStreamCursor {
  /** The document this cursor is for; a frame naming any other is dropped. */
  documentId: string;
  /**
   * The TURN whose ledger `position` counts — the run, not the document.
   *
   * `operations_total` is a position in ONE RUN's operation ledger, and a
   * document outlives many runs: the next run starts its ledger at zero over
   * whatever the document then is. A cursor that carried a turn's position into
   * the next turn would measure the new run's frames against an origin that has
   * nothing to do with them, which is exactly the defect a live walk caught (a
   * tab open at v122 seeded from the previous turn's checkpoint at position 2,
   * then dropped the new run's first batch, `operations_total` 1, as already
   * reflected — the reveal could never start). `null` until a frame has said
   * which turn this is.
   */
  turnId: string | null;
  /** The ledger position the canvas has been shown up to. */
  position: number;
  /** True once a frame could not be applied, until an anchor clears it. */
  dirty: boolean;
}

/** A cursor for a document nothing has been streamed for yet. */
export function newSceneStreamCursor(documentId: string): SceneStreamCursor {
  return { documentId, turnId: null, position: 0, dirty: false };
}

/** A `design.checkpoint` mark, kept with the turn whose run committed it. */
export interface SceneCheckpointRecord extends SceneCheckpointMark {
  /** The run that committed it. Marks from other runs are another ledger. */
  turnId: string | null;
}

/** What a canvas reports when it finishes loading a document. */
export interface SceneStreamSeed {
  documentId: string;
  /** The durable version the canvas actually loaded. */
  documentVersion: number;
  /**
   * The turn whose run is in flight over this document — the ledger the canvas
   * is joining, and the ONLY one whose marks mean anything to it.
   *
   * `null` (no run is known to be in flight, or the surface cannot name it) is
   * not a guess: no mark matches it, so the seed starts the ledger at 0 on the
   * loaded document, which is where any run's first frame would put it anyway.
   */
  turnId: string | null;
  /** The `design.checkpoint` marks seen so far — the fold keeps them. */
  backlogCheckpoints: readonly SceneCheckpointRecord[];
}

/**
 * Where a JUST-LOADED document stands in its run's ledger (task 10).
 *
 * `newSceneStreamCursor` starts at 0 because nothing has been streamed for that
 * document yet — right for a canvas opened before the run, and wrong for one
 * opened (or reloaded) DURING it. A late joiner's document already contains
 * every operation the run has committed, and the cursor has to say so, or the
 * arithmetic above is measuring from the wrong origin.
 *
 * The translation is the checkpoint frames the stream replays on attach: each
 * one says "version V holds N operations", so the loaded version picks the
 * position. Three cases, and they are the whole function:
 *
 * Only the IN-FLIGHT TURN's marks are read (fix round 1). A ledger belongs to a
 * run: the previous turn's checkpoint says where THAT run stood, which is no
 * evidence at all about where this one does, and treating it as evidence is
 * what made a live tab drop the new run's very first batch as stale.
 *
 * 1. **this turn committed exactly this version** — its mark's position IS what
 *    the document holds. Clean: the next contiguous frame animates, and the
 *    backlog beyond it fast-forwards.
 * 2. **this turn has no marks at all** — the run has committed nothing yet (or
 *    it only ever streamed), so its ledger starts at 0 on the document exactly
 *    as loaded. Position 0, clean, which is also task 8's default.
 * 3. **this turn has marks, but none for this version** — the loaded version is
 *    either ahead of every one of them (the backlog horizon did not reach it)
 *    or sits between two. Its position is UNKNOWN, so the cursor seeds DIRTY at
 *    the highest position this turn is known to have reached and every frame
 *    drops until the next checkpoint re-anchors. The canvas honestly shows the
 *    document it loaded meanwhile; nothing is applied over a hole.
 *
 * **Why case 1 wants the EXACT version, not "the newest mark at or below it".**
 * A mark below the loaded version is a LOWER BOUND, never a position: the
 * document holds that mark's operations plus everything committed since, and
 * the stream has not said how many that is. Seeding there and then accepting
 * the frame that begins there would re-apply operations the loaded document
 * already contains — the exact corruption this module exists to refuse. The
 * straddle is not hypothetical either: checkpoints key on round acceptance, so
 * a version can be committed without a checkpoint frame of its own, and a
 * document fetch racing ahead of the frame that describes it is the ordinary
 * shape of a late join. It costs a few seconds of live motion (the next
 * checkpoint re-anchors, and rung A reloads the canvas under it) and it cannot
 * cost a corrupted picture, which is the direction this whole feature fails in.
 *
 * A mark whose version or position cannot be read is skipped, for the same
 * reason the fold declines to re-seat on one: it is not evidence of anything.
 */
export function seedSceneStreamCursor({
  documentId,
  documentVersion,
  turnId,
  backlogCheckpoints,
}: SceneStreamSeed): SceneStreamCursor {
  let exact: number | null = null;
  let highestKnown = 0;
  let sawMark = false;
  for (const mark of backlogCheckpoints) {
    if (mark.documentId !== documentId) continue;
    // Another run's ledger. Not weaker evidence — no evidence.
    if (mark.turnId !== turnId) continue;
    const version = readPosition(mark.version);
    const position = readPosition(mark.operations);
    if (version === null || position === null) continue;
    sawMark = true;
    highestKnown = Math.max(highestKnown, position);
    // The LAST-arriving mark for the version wins — two marks for one version
    // agree on the position in every honest case, and the later one is the one
    // the stream currently stands behind.
    if (version === documentVersion) exact = position;
  }
  if (exact !== null) return { documentId, turnId, position: exact, dirty: false };
  if (!sawMark) return { documentId, turnId, position: 0, dirty: false };
  return { documentId, turnId, position: highestKnown, dirty: true };
}

export interface SceneStreamAdvance {
  cursor: SceneStreamCursor;
  action: SceneStreamAction;
  /**
   * The frame belonged to a DIFFERENT RUN, so the cursor was reset to the start
   * of that run's ledger before the frame's own rule ran. The fold turns this
   * into a `rebase` action, which is how the reveal learns that what it has
   * drawn belongs to a run that is over.
   */
  turnChanged: boolean;
}

function isOperationRecord(value: unknown): boolean {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  return typeof (value as Record<string, unknown>).kind === "string";
}

/**
 * The streamed batch as operations, or `null` when there is nothing to apply.
 *
 * Ported from the MVP editor's `operationsFromRunEvent`
 * (`subsystems/clue-design/apps/editor/src/engine/agentRunner.ts`): absent or
 * malformed returns null, an empty list returns null, and it never throws.
 *
 * One deliberate divergence from that source. It keeps whatever members are
 * plain objects and FILTERS the rest out; this refuses the whole list unless
 * every member is an object carrying a string `kind`. Half a batch applied to a
 * canvas is a corrupted document — the same reason the platform forwarder sends
 * a bare position rather than a truncated `operations` when a batch is oversize
 * — so a member this build cannot read costs the batch, not the document. The
 * caller then goes dirty and waits for the checkpoint behind it.
 */
export function operationsFromStreamFrame(batch: {
  operations: unknown;
}): Operation[] | null {
  const raw = batch.operations;
  if (!Array.isArray(raw) || raw.length === 0) return null;
  if (!raw.every(isOperationRecord)) return null;
  return raw as unknown as Operation[];
}

function readPosition(value: number | null): number | null {
  return value !== null && Number.isFinite(value) ? value : null;
}

/**
 * Fold one frame into the cursor — the whole §B-3 matrix, in one function.
 *
 * Order matters and is the order of the rules:
 *
 * 0. **the run** (fix round 1) — a frame naming a turn other than the cursor's
 *    is a NEW LEDGER: that run counts its operations from zero over whatever
 *    the document is now, so the cursor resets to `{turn, 0, clean}` and the
 *    rules below then run against THAT. Nothing else about them changes, which
 *    is why a same-turn stream behaves exactly as it did. A frame carrying no
 *    turn at all cannot be attributed to another run, so it does not reset —
 *    it is simply read against the cursor as it stands.
 * 1. **the document** — a frame for any other document, or a frame naming no
 *    document at all, drops untouched. One cursor is one document's truth, and
 *    an unattributable frame cannot be proven to be this one's.
 * 2. **a checkpoint** anchors: the cursor is re-seated to the position the
 *    version durably holds and dirty is cleared, ALWAYS. `inSync` is true only
 *    when the cursor already stood there and was clean. A checkpoint whose
 *    position cannot be read drops rather than re-seating blind — rung A's
 *    reload still handles the canvas, so nothing is lost by declining.
 * 3. **a dirty cursor** drops every op frame. Only an anchor gets out.
 * 4. **already reflected** — `operations_total <= position` drops. This is
 *    checked before the payload is read: a frame behind the cursor is stale
 *    whatever it carries, and going dirty over a stale malformed frame would
 *    cost live motion for no reason.
 * 5. **contiguous** — `operations_total - operations.length === position`
 *    applies and advances to `operations_total`.
 * 6. **everything else** is dirty, and carries the position forward to
 *    `max(position, operations_total)` when the total is readable, so the
 *    frames still in flight behind the gap drop as stale once an anchor lands.
 */
export function advanceSceneStreamCursor(
  cursor: SceneStreamCursor,
  frame: SceneStreamFrame,
): SceneStreamAdvance {
  if (frameDocumentId(frame) !== cursor.documentId) {
    return { cursor, action: DROP, turnChanged: false };
  }
  const turnChanged = frame.turnId !== null && frame.turnId !== cursor.turnId;
  const active: SceneStreamCursor = turnChanged
    ? {
        documentId: cursor.documentId,
        turnId: frame.turnId,
        position: 0,
        dirty: false,
      }
    : cursor;
  return { ...advanceWithinTurn(active, frame), turnChanged };
}

/** Rules 1–6, against a cursor already known to be on the frame's own run. */
function advanceWithinTurn(
  cursor: SceneStreamCursor,
  frame: SceneStreamFrame,
): { cursor: SceneStreamCursor; action: SceneStreamAction } {
  if (frame.type === "design.checkpoint") {
    const mark = frame.checkpoint;
    if (mark.documentId !== cursor.documentId) return { cursor, action: DROP };
    const position = readPosition(mark.operations);
    if (position === null) return { cursor, action: DROP };
    return {
      cursor: {
        documentId: cursor.documentId,
        turnId: cursor.turnId,
        position,
        dirty: false,
      },
      action: {
        action: "anchor",
        version: mark.version,
        inSync: position === cursor.position && !cursor.dirty,
      },
    };
  }

  const batch = frame.batch;
  if (batch.documentId !== cursor.documentId) return { cursor, action: DROP };
  if (cursor.dirty) return { cursor, action: DROP };
  const total = readPosition(batch.operationsTotal);
  if (total === null) {
    return {
      cursor: { ...cursor, dirty: true },
      action: DIRTY,
    };
  }
  if (total <= cursor.position) return { cursor, action: DROP };
  const operations = operationsFromStreamFrame(batch);
  if (operations !== null && total - operations.length === cursor.position) {
    return {
      cursor: {
        documentId: cursor.documentId,
        turnId: cursor.turnId,
        position: total,
        dirty: false,
      },
      action: { action: "apply", operations },
    };
  }
  return {
    cursor: {
      documentId: cursor.documentId,
      turnId: cursor.turnId,
      position: Math.max(cursor.position, total),
      dirty: true,
    },
    action: DIRTY,
  };
}

/**
 * How many actions the controller keeps.
 *
 * The log exists because several frames can arrive in ONE event-loop tick (SSE
 * hands the reader a chunk, not a frame) and React would then commit only the
 * last state — an `apply` coalesced away is a batch the canvas never renders.
 * A consumer therefore reads the log, not the latest action, and tracks the
 * last `sequence` it has seen. The bound only has to cover one commit's worth
 * of frames; it is generous, and it is what keeps a long run from growing an
 * array nothing ever drains.
 */
export const SCENE_STREAM_ACTION_LOG_LIMIT = 64;

/** One decided frame, in arrival order. */
export interface SceneStreamActionRecord {
  /** Monotone across the whole fold; the consumer's resume point. */
  sequence: number;
  documentId: string;
  action: SceneStreamAction;
}

/**
 * The controller's whole scene-stream state: a cursor per document named on the
 * active thread's stream, plus the recent actions.
 *
 * Keyed on the DOCUMENT THE FRAME NAMES rather than on the document the editor
 * has open, because the controller cannot see the latter: the open artifact is
 * the chat surface's state, and the surface receives this state as a prop (the
 * same split the editor lock uses — the controller observes, the surface, which
 * holds all the facts, decides). Routing by the frame's own `document_id` keeps
 * the cross-document guarantee without that plumbing, and a thread's design leg
 * pins one document, so the map is small by construction.
 */
export interface SceneStreamState {
  cursors: ReadonlyMap<string, SceneStreamCursor>;
  actions: readonly SceneStreamActionRecord[];
  /**
   * Task 10: the readable `design.checkpoint` marks seen so far, in arrival
   * order and bounded.
   *
   * A cursor remembers only WHERE it stands, which is all a frame needs. A
   * canvas joining mid-run needs the other half of the mapping — which VERSION
   * that position belongs to, and in WHICH RUN — and the only place it exists
   * is the checkpoint frames themselves. Keeping them here rather than in the
   * controller means the seed is folded and tested with everything else it has
   * to agree with.
   */
  checkpoints: readonly SceneCheckpointRecord[];
}

const NO_CURSORS: ReadonlyMap<string, SceneStreamCursor> = new Map();
const NO_ACTIONS: readonly SceneStreamActionRecord[] = [];
const NO_CHECKPOINTS: readonly SceneCheckpointRecord[] = [];

/** Nothing streamed yet. */
export const NO_SCENE_STREAM: SceneStreamState = {
  cursors: NO_CURSORS,
  actions: NO_ACTIONS,
  checkpoints: NO_CHECKPOINTS,
};

/**
 * How many checkpoint marks the fold keeps.
 *
 * Only the mark that committed the loaded version is ever read, so this only
 * has to cover the replay horizon of one attach — and a run commits a
 * checkpoint every few seconds, not every frame, so it is generous. Trimming
 * from the FRONT is what makes the bound safe: the mark a late joiner needs is
 * a recent one, and losing an old one only ever costs it a seed it would have
 * refused anyway.
 */
export const SCENE_STREAM_CHECKPOINT_LOG_LIMIT = 32;

function withAction(
  state: SceneStreamState,
  checkpoints: readonly SceneCheckpointRecord[],
  cursors: ReadonlyMap<string, SceneStreamCursor>,
  documentId: string,
  action: SceneStreamAction,
): SceneStreamState {
  const last = state.actions[state.actions.length - 1];
  const actions = [
    ...state.actions,
    { sequence: (last?.sequence ?? 0) + 1, documentId, action },
  ];
  return {
    cursors,
    actions:
      actions.length > SCENE_STREAM_ACTION_LOG_LIMIT
        ? actions.slice(actions.length - SCENE_STREAM_ACTION_LOG_LIMIT)
        : actions,
    checkpoints,
  };
}

/**
 * A canvas finished loading `documentId` at `documentVersion` (task 10).
 *
 * Re-seats that document's cursor with `seedSceneStreamCursor` and records the
 * join in the SAME ordered action log the frames go through. The record is what
 * the reveal pump reads: it says "the canvas under you is a freshly loaded
 * document", which is both the point it may start applying from and the point
 * everything it was holding stops being true. It is appended on every load —
 * including a reload that lands the same version — because the LOAD is the
 * event, not the number.
 */
export function seedSceneStreamState(
  state: SceneStreamState,
  seed: { documentId: string; documentVersion: number; turnId: string | null },
): SceneStreamState {
  const cursor = seedSceneStreamCursor({
    ...seed,
    backlogCheckpoints: state.checkpoints,
  });
  const cursors = new Map(state.cursors);
  cursors.set(seed.documentId, cursor);
  return withAction(state, state.checkpoints, cursors, seed.documentId, {
    action: "seed",
    position: cursor.position,
    dirty: cursor.dirty,
  });
}

function frameDocumentId(frame: SceneStreamFrame): string | null {
  return frame.type === "design.op_batch"
    ? frame.batch.documentId
    : frame.checkpoint.documentId;
}

/**
 * Route one frame to its document's cursor and record what it decided.
 *
 * Two frames return the SAME state, so a busy stream costs no re-renders (the
 * discipline `chat-shell/model/agent-run-lock` already follows):
 *
 * - a frame naming no document — there is no cursor it could belong to, so
 *   there is nothing to decide;
 * - a DROPPED frame — `advanceSceneStreamCursor` returns the cursor it was
 *   given on every drop path (an invariant, and the reason this shortcut is
 *   safe), and a drop is by definition nothing for a consumer to do. Only
 *   `apply`, `dirty` and `anchor` reach the log.
 */
export function applySceneStreamFrame(
  state: SceneStreamState,
  frame: SceneStreamFrame,
): SceneStreamState {
  const documentId = frameDocumentId(frame);
  if (documentId === null) return state;
  const current =
    state.cursors.get(documentId) ?? newSceneStreamCursor(documentId);
  const { cursor, action, turnChanged } = advanceSceneStreamCursor(
    current,
    frame,
  );
  // A dropped frame is nothing for a consumer to do — unless it also crossed a
  // run boundary, in which case the reset it caused is real and must be kept.
  if (action.action === "drop" && !turnChanged) return state;
  const cursors = new Map(state.cursors);
  cursors.set(documentId, cursor);
  // Task 10: keep the mark behind an anchor, WITH the run that committed it, so
  // a canvas that loads later can translate its version into a position in the
  // right ledger. Only anchors get here — an unreadable checkpoint dropped
  // above, and it would tell the seed nothing.
  let checkpoints = state.checkpoints;
  if (action.action === "anchor" && frame.type === "design.checkpoint") {
    const kept = [...checkpoints, { ...frame.checkpoint, turnId: frame.turnId }];
    checkpoints =
      kept.length > SCENE_STREAM_CHECKPOINT_LOG_LIMIT
        ? kept.slice(kept.length - SCENE_STREAM_CHECKPOINT_LOG_LIMIT)
        : kept;
  }
  // The rebase is logged BEFORE the frame's own action, because that is the
  // order they happened in: the previous run's picture stops being the base,
  // and only then does this frame land on the document underneath it.
  let next = state;
  if (turnChanged) {
    next = withAction(next, checkpoints, cursors, documentId, {
      action: "rebase",
      turnId: cursor.turnId,
    });
  }
  if (action.action !== "drop") {
    next = withAction(next, checkpoints, cursors, documentId, action);
  }
  return next;
}
