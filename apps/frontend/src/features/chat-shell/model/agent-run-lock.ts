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
 *  • **the platform positively says there is no design leg → unlocked.** A
 *    strategy turn is not the design agent at work, and interleaved manual edits
 *    BETWEEN design turns are the ratified genweb feature this must not touch.
 *    An UNKNOWN leg is not this case — see {@link DesignLegFact}.
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

/**
 * What is known about the thread's design leg — three answers, not two.
 *
 * The third is the whole point (fix round 1, finding I1). The stream's leg
 * state is seeded CLOSED and moved only by `leg.*` frames, and rehydration
 * replays only the last few turns — so "no leg frame in the backlog" is
 * `unknown`, NOT `none`. Collapsing the two unlocked the editor mid-run on
 * every cold load into a leg opened further back than the replay reaches.
 *
 * `running` comes from the durable thread wire (`ThreadSpeakerWire.design_leg_state`)
 * and is an ENGAGED FLOOR: it is the platform saying, at load time, that a
 * design run is in flight right now.
 */
export type DesignLegFact =
  | { kind: "unknown" }
  | { kind: "none" }
  | { kind: "open"; running: boolean };

export const UNKNOWN_DESIGN_LEG: DesignLegFact = { kind: "unknown" };

const NO_DESIGN_LEG: DesignLegFact = { kind: "none" };

/** The durable thread wire's leg projection, as `chat-thread` parses it. */
export interface ThreadDesignLegWire {
  legId: string | null;
  /** `null` means the platform says this thread holds no leg. */
  state: "open_awaiting_user" | "running" | null;
}

/**
 * Compose the leg fact from the two sources that can answer it.
 *
 * Precedence: the STREAM wins whenever it has actually observed something —
 * it is live, and the wire is a snapshot taken when the thread list was read.
 * The wire answers only for what the stream has not seen, which is exactly the
 * cold-load window I1 is about. `running` is read from the wire either way: it
 * is a fact no frame carries, and the selector below is what makes it expire
 * (an observed terminal frame drops the floor).
 */
export function designLegFactFor({
  leg,
  wire,
}: {
  /** The stream's own leg state (`chat-transcript`'s `designLeg`). `known` is
   * false until either a leg frame or the durable seed has moved it. */
  leg: { known: boolean; open: boolean };
  /** The active thread's durable leg projection, or `null` when the read did
   * not derive one (the platform sends `speaker: null` on such reads). */
  wire: ThreadDesignLegWire | null;
}): DesignLegFact {
  const open = leg.known ? leg.open : wire ? wire.state !== null : null;
  if (open === null) return UNKNOWN_DESIGN_LEG;
  if (!open) return NO_DESIGN_LEG;
  return { kind: "open", running: wire?.state === "running" };
}

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
 * the controller sees each frame through its stream attachment. Handoff markers
 * live only while their turn is active, never as an accumulated turn history.
 */
export interface AgentRunLockState {
  /** The thread these observations belong to; `null` before any frame. */
  threadId: string | null;
  /** Turns seen accepted/started with no terminal frame for them since. */
  activeTurnIds: ReadonlySet<string>;
  /** Active turns whose own `leg.opened` identifies a non-writing handoff. */
  handoffTurnIds: ReadonlySet<string>;
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
  handoffTurnIds: NO_TURNS,
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
 *  • `leg.awaiting_user` / `leg.closed` **release their own turn**: the design
 *    leg has handed back, while a separately active writer must stay locked;
 *  • `leg.opened` marks its active submitting turn as a handoff opener; only
 *    that turn's `turn.awaiting_input` releases it;
 *  • `stream.reset` forgets everything — the backlog that follows re-derives it,
 *    and carrying a pre-reset run forward would assert a turn we can no longer
 *    prove.
 *
 * Any other frame (`design.checkpoint`, `text.delta`, the part frames) returns
 * the SAME object, so a busy stream costs no re-renders.
 *
 * Other `turn.awaiting_input` frames are deliberately NOT releases: a Design
 * turn parked on a human gate is still live. `leg.reopened` is not evidence of
 * a new-document handoff and does not change that conservative rule.
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
      : { ...NO_AGENT_RUN, threadId: event.threadId };
  switch (event.type) {
    case "turn.accepted":
    case "turn.started": {
      if (base.activeTurnIds.has(event.turnId) && !base.released) return base;
      const active = new Set(base.activeTurnIds);
      active.add(event.turnId);
      return { ...base, activeTurnIds: active, released: false };
    }
    case "leg.opened": {
      // The open-design-leg tool emits this under the Head-of-ABM turn that
      // creates the handoff, before a later Design turn does any authoring.
      // Ignore a late/missing-start marker: it has no active lock to retire,
      // and retaining it could misclassify a later attempt of the same turn.
      if (!base.activeTurnIds.has(event.turnId) || base.handoffTurnIds.has(event.turnId)) {
        return base;
      }
      return { ...base, handoffTurnIds: new Set([...base.handoffTurnIds, event.turnId]) };
    }
    case "turn.awaiting_input":
    case "turn.completed":
    case "turn.failed":
    case "turn.cancelled":
    case "leg.awaiting_user":
    case "leg.closed": {
      if (event.type === "turn.awaiting_input" && !base.handoffTurnIds.has(event.turnId)) {
        return base;
      }
      // Fix round 1, finding I2: release ONLY the turn this frame names.
      //
      // Clearing every active turn here was the second dangerous-direction
      // defect: per-turn backlog attaches have no cross-turn ordering and every
      // design turn ends with `leg.awaiting_user`, so a previous turn's
      // late-replayed hand-back unlocked the editor under the run in flight.
      // The leg frames are emitted under the SUBMITTING turn's id
      // (`design_leg_wiring.py`), so a turn still releases itself.
      const active = new Set(base.activeTurnIds);
      active.delete(event.turnId);
      const handoffs = new Set(base.handoffTurnIds);
      handoffs.delete(event.turnId);
      return {
        threadId: event.threadId,
        activeTurnIds: active,
        handoffTurnIds: handoffs,
        // Nothing left running: this is also what lifts the durable
        // `threadBusy` floor at a cold-loaded hand-back, where the turn was
        // never seen to start.
        released: active.size === 0,
      };
    }
    case "stream.reset":
      return { ...NO_AGENT_RUN, threadId: event.threadId };
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

/**
 * The share menu's line while Publish waits for the run (founder copy,
 * 2026-10-13 — do not paraphrase it at a call site).
 */
export const AGENT_RUN_PUBLISH_NOTE =
  "The design agent is working — publishing unlocks when it finishes.";

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
  designLeg,
  documentId,
  documentThreadId,
  state,
  threadBusy,
}: {
  activeThreadId: string | null;
  /**
   * What is known about the thread's leg — `designLegFactFor`'s answer.
   *
   * Only a POSITIVE `none` (the platform's durable wire saying this thread
   * holds no leg, or the stream having watched one close) unlocks by itself.
   * `unknown` does not: absence of evidence is not evidence of absence, and
   * erring the other way is what unlocked a live run (fix round 1, I1).
   */
  designLeg: DesignLegFact;
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
  // The ratified unlocked-by-default state, and the ONLY one: the platform
  // positively says this thread has no design leg, so nothing is designing.
  if (designLeg.kind === "none") return UNLOCKED;
  // Nothing open is nothing to lock.
  if (documentId === null) return UNLOCKED;
  // A document another thread gave birth to; this thread's run is not it.
  // A NULL binding falls through on purpose — unresolved means locked.
  if (documentThreadId !== null && documentThreadId !== activeThreadId) {
    return UNLOCKED;
  }
  const observed = state.threadId === activeThreadId ? state : NO_AGENT_RUN;
  // Three engaging facts, one expiry. The two FLOORS — the wire's "a design run
  // is in flight" and the durable turn queue's "a turn is queued or running" —
  // hold only until the stream has actually observed the run settle; after that
  // the frames are the newer truth and a stale snapshot must not hold the
  // editor shut. An observed active turn needs no floor: it IS the observation.
  const floor =
    (designLeg.kind === "open" && designLeg.running) || threadBusy;
  const runActive =
    observed.activeTurnIds.size > 0 || (!observed.released && floor);
  return runActive ? LOCKED : UNLOCKED;
}
