/**
 * The editor lock (scene live-streaming rung A, task 4).
 *
 * Founder ruling: **no mid-run manual editing, ever.** While a design turn is
 * queued or running against the document the user has open, the scene editor is
 * VIEW-ONLY — every write path is inert and the surface says why, instead of
 * accepting a gesture the backend is going to refuse anyway.
 *
 * The backend already refuses: task 1 put a 409 (`document.agent_run_active`)
 * on the six manual write routes. That is the ENFORCEMENT. This is the honest
 * UX in front of it: a control the platform will refuse must not look live.
 *
 * ── WHAT BINDS A RUN TO A DOCUMENT ────────────────────────────────────────
 * The turn stream names a THREAD, never a document: `turn.*` frames carry
 * `{project, thread, turn}` and the `leg.*` frames add only `leg_id` (which is
 * why `artifact-auto-open` keys off the FEED rather than off `leg.opened`). So
 * the document side of the binding comes from the same place that module takes
 * it: the gallery card's `originThreadId`, the thread a design artifact was
 * born in. `documentThreadId` below is that value for the open document.
 *
 * Three postures, all deliberate:
 *
 *  • **no design leg on the thread → unlocked.** A strategy turn is not the
 *    design agent at work, and interleaved manual edits BETWEEN design turns are
 *    the ratified genweb feature this must not touch.
 *  • **a sibling thread's document → unlocked.** This thread's run cannot be
 *    writing a document another thread gave birth to.
 *  • **a document whose thread cannot be resolved → LOCKED.** Fail-safe: when
 *    the binding is unknown the honest answer is to refuse, not to allow a write
 *    the server would 409.
 *
 * ── WHY THE DURABLE `threadBusy` RIDES ALONG ──────────────────────────────
 * Frames are at-least-once but not at-least-one: a cold load into a run already
 * in flight has no `turn.accepted` to observe until the backlog replays. So the
 * controller's own durable queue fact (`selectTurnQueueState().threadBusy`)
 * is the floor — with one exception, which is the whole reason `released` is
 * tracked. A terminal LEG frame (`leg.awaiting_user`) lands while the delegating
 * head-of-ABM turn is still running, and the release matrix says the lock lifts
 * there; without the latch the lagging `threadBusy` would hold it shut.
 */

/** The lock's view of one turn-stream frame. */
export interface AgentRunLockFrame {
  threadId: string;
  turnId: string;
  type: string;
}

/**
 * What the surface has observed about the thread's design run.
 *
 * Folded frame by frame (`applyAgentRunLockEvent`) rather than held as a list:
 * the controller sees each frame exactly once, and a rolling three-field state
 * is the whole of what the decision below reads.
 */
export interface AgentRunLockState {
  /** The thread these observations belong to; `null` before any frame. */
  threadId: string | null;
  /** Turns seen accepted/started with no terminal frame for them since. */
  activeTurnIds: ReadonlySet<string>;
  /**
   * True once a TERMINAL frame settled the run and no engaging frame has
   * arrived since — the "the last frame I saw ended it" fact. It is what lets a
   * terminal leg frame release the lock while the durable queue still reads
   * busy, and it is cleared by the next `turn.accepted`.
   */
  released: boolean;
}

const NO_TURNS: ReadonlySet<string> = new Set();

/** Nothing observed yet: the lock then rests entirely on the durable fact. */
export const NO_AGENT_RUN: AgentRunLockState = {
  threadId: null,
  activeTurnIds: NO_TURNS,
  released: false,
};

/**
 * Fold one frame into the run state.
 *
 * The matrix, verbatim from the task's binding release rules:
 *
 *  • `turn.accepted` / `turn.started` **engage** (and clear `released`);
 *  • `turn.completed` / `turn.failed` / `turn.cancelled` **release that turn** —
 *    a failed run must never leave a locked editor, which is why `turn.failed`
 *    is a release and not a hold;
 *  • `leg.awaiting_user` / `leg.closed` **release the whole run**: the design
 *    leg has handed back, so whatever turn is still finishing its own tail is
 *    no longer the design agent writing this document;
 *  • `stream.reset` forgets everything — the backlog that follows re-derives it,
 *    and carrying a pre-reset run forward would assert a turn we can no longer
 *    prove.
 *
 * Any other frame (`design.checkpoint`, `text.delta`, the part frames) returns
 * the SAME object, so a busy stream costs no re-renders.
 *
 * `turn.awaiting_input` is deliberately NOT a release: the turn is parked on a
 * human gate but is still live, and the lock's direction of error is to hold.
 */
export function applyAgentRunLockEvent(
  state: AgentRunLockState,
  event: AgentRunLockFrame,
): AgentRunLockState {
  // A frame for another thread re-bases the state onto that thread: one
  // controller shows one conversation, so observations never mix.
  const base: AgentRunLockState =
    state.threadId === event.threadId
      ? state
      : { threadId: event.threadId, activeTurnIds: NO_TURNS, released: false };
  switch (event.type) {
    case "turn.accepted":
    case "turn.started": {
      if (base.activeTurnIds.has(event.turnId) && !base.released) return base;
      const active = new Set(base.activeTurnIds);
      active.add(event.turnId);
      return { threadId: event.threadId, activeTurnIds: active, released: false };
    }
    case "turn.completed":
    case "turn.failed":
    case "turn.cancelled": {
      const active = new Set(base.activeTurnIds);
      active.delete(event.turnId);
      return {
        threadId: event.threadId,
        activeTurnIds: active,
        // Only when nothing is left running: a sibling turn still in flight is
        // still the agent at work.
        released: active.size === 0,
      };
    }
    case "leg.awaiting_user":
    case "leg.closed":
      return {
        threadId: event.threadId,
        activeTurnIds: NO_TURNS,
        released: true,
      };
    case "stream.reset":
      return {
        threadId: event.threadId,
        activeTurnIds: NO_TURNS,
        released: false,
      };
    default:
      return base;
  }
}

/**
 * The one sentence the lock says, everywhere it says anything (ratified copy —
 * do not paraphrase it at a call site).
 */
export const AGENT_RUN_LOCK_NOTE =
  "The design agent is working — editing unlocks when it finishes.";

export interface AgentRunLock {
  /** True when every manual write path on the open document must be inert. */
  locked: boolean;
  /** The reason to show, or `null` when there is nothing to explain. */
  note: string | null;
}

const UNLOCKED: AgentRunLock = { locked: false, note: null };
const LOCKED: AgentRunLock = { locked: true, note: AGENT_RUN_LOCK_NOTE };

/**
 * Is the open document view-only right now?
 *
 * Read the header for the reasoning; the shape of the answer is: a design leg
 * open on the active thread, a document bound to that thread, and a design run
 * that has engaged and not yet released.
 *
 * View, zoom, pan and selection-for-inspection are NOT this function's
 * business — looking at a document is not changing it, and nothing here should
 * ever be wired to a read path.
 */
export function agentRunLockForThread({
  activeThreadId,
  designLegOpen,
  documentId,
  documentThreadId,
  state,
  threadBusy,
}: {
  activeThreadId: string | null;
  /** The transcript's own leg fact (`stream.designLeg.open`) — a leg is open
   * between `leg.opened`/`leg.reopened` and its `leg.closed`. Read rather than
   * re-derived here so the two surfaces cannot disagree about the leg. */
  designLegOpen: boolean;
  /** The design document open in the editor, or `null`. */
  documentId: string | null;
  /** The thread the open document was born in (its gallery card's
   * `originThreadId`), or `null` when it cannot be resolved. */
  documentThreadId: string | null;
  state: AgentRunLockState;
  /** The controller's durable queue fact: a turn queued or running. */
  threadBusy: boolean;
}): AgentRunLock {
  if (activeThreadId === null) return UNLOCKED;
  // The ratified unlocked-by-default state: no design leg, nothing designing.
  if (!designLegOpen) return UNLOCKED;
  // Nothing open is nothing to lock.
  if (documentId === null) return UNLOCKED;
  // A document another thread gave birth to; this thread's run is not it.
  // A NULL binding falls through on purpose — unresolved means locked.
  if (documentThreadId !== null && documentThreadId !== activeThreadId) {
    return UNLOCKED;
  }
  const observed = state.threadId === activeThreadId ? state : NO_AGENT_RUN;
  const runActive =
    observed.activeTurnIds.size > 0 || (!observed.released && threadBusy);
  return runActive ? LOCKED : UNLOCKED;
}
