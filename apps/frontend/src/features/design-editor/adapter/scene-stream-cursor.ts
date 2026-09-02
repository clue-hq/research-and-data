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

/** The two frames the cursor understands. Every other frame stays away. */
export type SceneStreamFrame =
  | { type: "design.op_batch"; batch: SceneOpBatch }
  | { type: "design.checkpoint"; checkpoint: SceneCheckpointMark };

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
 */
export type SceneStreamAction =
  | { action: "apply"; operations: readonly Operation[] }
  | { action: "drop" }
  | { action: "dirty" }
  | { action: "anchor"; version: number | null; inSync: boolean };

const DROP: SceneStreamAction = { action: "drop" };
const DIRTY: SceneStreamAction = { action: "dirty" };

/** One document's place in its run's operation ledger. */
export interface SceneStreamCursor {
  /** The document this cursor is for; a frame naming any other is dropped. */
  documentId: string;
  /** The ledger position the canvas has been shown up to. */
  position: number;
  /** True once a frame could not be applied, until an anchor clears it. */
  dirty: boolean;
}

/** A cursor for a document nothing has been streamed for yet. */
export function newSceneStreamCursor(documentId: string): SceneStreamCursor {
  return { documentId, position: 0, dirty: false };
}

export interface SceneStreamAdvance {
  cursor: SceneStreamCursor;
  action: SceneStreamAction;
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
  if (frame.type === "design.checkpoint") {
    const mark = frame.checkpoint;
    if (mark.documentId !== cursor.documentId) return { cursor, action: DROP };
    const position = readPosition(mark.operations);
    if (position === null) return { cursor, action: DROP };
    return {
      cursor: { documentId: cursor.documentId, position, dirty: false },
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
      cursor: { documentId: cursor.documentId, position: total, dirty: false },
      action: { action: "apply", operations },
    };
  }
  return {
    cursor: {
      documentId: cursor.documentId,
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
}

const NO_CURSORS: ReadonlyMap<string, SceneStreamCursor> = new Map();
const NO_ACTIONS: readonly SceneStreamActionRecord[] = [];

/** Nothing streamed yet. */
export const NO_SCENE_STREAM: SceneStreamState = {
  cursors: NO_CURSORS,
  actions: NO_ACTIONS,
};

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
  const { cursor, action } = advanceSceneStreamCursor(current, frame);
  if (action.action === "drop") return state;
  const cursors = new Map(state.cursors);
  cursors.set(documentId, cursor);
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
  };
}
