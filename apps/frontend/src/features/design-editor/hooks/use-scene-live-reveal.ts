"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { SceneStreamActionRecord } from "../adapter/scene-stream-cursor";
import type {
  NodeId,
  Operation,
  Page,
  PageId,
  Rect,
  Scene,
} from "../engine/scene/contracts";
import { pageIdForNode } from "../engine/scene/sceneQueries";
import type { EngineApplyOutcome } from "../engine/scene/wasmEngine";

/**
 * The live-reveal pump (scene live-streaming rung B, task 9) — the ported
 * `useAgentTurn.ts` §S2.1 / §D4.5 theater, on the platform's scene editor.
 *
 * Task 8 turned the streamed `design.op_batch` frames into an ARITHMETIC
 * answer: may this batch touch the canvas right now? This module is the other
 * half — given that a batch may, WHEN does the user see it? Applying every
 * batch the instant it lands would make a generating ad flicker through a dozen
 * half-states a second; the MVP's answer, ported here verbatim, is to run the
 * ENGINE ahead of the DISPLAY and hold each element back until a
 * travel-then-draw clock has elapsed, so the design appears to draw itself in
 * one element at a time.
 *
 * ── A LATE JOIN CANNOT DOUBLE-APPLY (task 10, fix round 2) ────────────────
 * A canvas that opens mid-run catches up on the operations the stream already
 * carried, which is the one place this pump could show the same operation
 * twice. It cannot, for three reasons that hold together. On a fresh mount the
 * pump has applied NOTHING before its first join. On a re-seed within one mount
 * the `seed` action re-seats the pump on the freshly loaded document first
 * (`join` → `rebase`: the queue, the held scene and the dirty latch all go and
 * the override drops), so nothing it had drawn survives into the catch-up. And
 * what is replayed is filtered by the cursor's contiguity rule against the
 * SEEDED position (`replaySceneStreamJoin`): every batch at or below the
 * position the loaded document holds is dropped rather than shown, which is
 * exactly the reload-at-a-checkpoint case.
 *
 * ── DISPLAY STATE ONLY. THIS MODULE WRITES NOTHING. ───────────────────────
 * Every scene it produces is a picture, never a document. It NEVER enqueues
 * into `editQueue`, never calls `applyOps` / `persistAppliedOps`, never touches
 * the undo or redo stacks, and never issues a request. Its single seam is the
 * canvas's `applyStreamedOperations` — the live engine apply, WITHOUT the
 * repaint-and-mirror `controls.applyOperations` does, because the whole point
 * is that the engine moves and the picture does not yet.
 *
 * Durability is somebody else's job and always was: the agent commits real
 * document versions as `design.checkpoint` frames, and rung A reloads the
 * canvas from them. That is why an engine refusal here costs a few seconds of
 * animation and nothing else — the pump stops applying, waits for the next
 * anchor, and the reload repairs whatever the display was showing. It never
 * hand-patches a scene it could not apply.
 *
 * ── WHAT THE CANVAS DOES WITH IT ──────────────────────────────────────────
 * `displayScene` is an OVERRIDE, in exactly the shape AD4.C's gesture preview
 * already uses: while it is non-null the canvas builds its artboard from it
 * instead of the loaded document, and when it is null the canvas renders the
 * document exactly as it does today. So every path out of streaming — the lock
 * releasing, a stale anchor, a document change — is the same one line: emit
 * null and the canvas is back on the document.
 *
 * ── DIVERGENCES FROM THE MVP, AND WHY ─────────────────────────────────────
 * 1. No reveal CHROME. The MVP publishes an `AgentStreamReveal` (label chip,
 *    bounds, fade duration) for an SVG overlay that draws the box and glides a
 *    cursor to it; the platform canvas has no such overlay, so the geometry is
 *    derived only as far as the TIMING needs it (a box's diagonal sets its draw
 *    duration). `MATERIALIZE_FADE_MS` is ported and exported all the same — it
 *    is part of the ratified cadence, and the surface that draws the outline
 *    will need the number it was tuned against.
 * 2. No terminal reconcile-to-base. The MVP owns a proposal it must reconcile
 *    the ephemeral stream against; here the durable document is the truth and
 *    rung A already reloads it at `leg.awaiting_user`, so the pump's terminal
 *    move is simply to stop overriding.
 * 3. The MVP's `stepsFromOps` seq bookkeeping is gone — task 8's cursor already
 *    guarantees each batch is contiguous and applied once, so the pump has no
 *    dedup left to do.
 */

/* ---------------------------------------------------------------------------
 * S2.1 draw-the-box choreography — the MVP's constants, verbatim.
 * `subsystems/clue-design/apps/editor/src/hooks/useAgentTurn.ts`.
 * ------------------------------------------------------------------------ */

/** Cursor glide to the new element's corner. */
export const TRAVEL_MS = 200;
/** A small chip's outline drag. */
export const DRAW_MIN_MS = 250;
/** A full-width hero's (scaled by box diagonal, below). */
export const DRAW_MAX_MS = 500;
/** Whole-artboard placeholder outline (no corner-drag). */
export const ADD_PAGE_DRAW_MS = 300;
/** Outline fade after the content lands. */
export const MATERIALIZE_FADE_MS = 250;
/** Calm gap between elements. */
export const INTER_STEP_PAUSE_MS = 120;
/**
 * Per-batch duration cap: when steps × per-step exceeds it, the per-element
 * pace compresses proportionally — but never below MIN_STEP_TOTAL_MS per
 * element (and the draw is never dropped entirely). The new-batch fast-forward
 * still bypasses the theater wholesale.
 */
export const MAX_BATCH_REVEAL_MS = 15000;
export const MIN_STEP_TOTAL_MS = 250;
/** prefers-reduced-motion: collapse travel+draw to one fast beat. */
export const REDUCED_MOTION_STEP_MS = 80;

/**
 * Read the OS reduced-motion preference. Defensive around SSR / stubbed
 * environments — a missing `matchMedia` means full motion.
 */
export function prefersReducedMotion(): boolean {
  try {
    return (
      typeof window !== "undefined" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    );
  } catch {
    return false;
  }
}

/**
 * The reveal draw duration scales with the element's footprint: a small chip
 * (short diagonal relative to the page) draws in ~DRAW_MIN_MS, a full-bleed
 * hero in ~DRAW_MAX_MS. `add_page` placeholders (and any node whose bounds or
 * page are unknown) use a fixed whole-artboard beat. Bounds and `page.size`
 * share the pre-unitScale page-unit space, so the ratio is zoom-independent.
 */
function drawMsForReveal(
  kind: string,
  bounds: Rect | null,
  page: Page | undefined,
): number {
  if (kind === "add_page" || !bounds || !page) return ADD_PAGE_DRAW_MS;
  const pageDiagonal = Math.hypot(page.size.width, page.size.height);
  const boxDiagonal = Math.hypot(bounds.width, bounds.height);
  const fraction = pageDiagonal > 0 ? Math.min(1, boxDiagonal / pageDiagonal) : 0;
  return DRAW_MIN_MS + (DRAW_MAX_MS - DRAW_MIN_MS) * fraction;
}

/**
 * The per-step phase timing, after batch compression and the reduced-motion
 * collapse. `pauseMs` is the calm gap before the NEXT step.
 */
interface RevealTiming {
  travelMs: number;
  drawMs: number;
  pauseMs: number;
  materializeFadeMs: number;
}

function revealTiming(
  kind: string,
  bounds: Rect | null,
  page: Page | undefined,
  compression: number,
  reducedMotion: boolean,
): RevealTiming {
  if (reducedMotion) {
    // One fast beat; the draw still exists (never zero).
    return { travelMs: 0, drawMs: REDUCED_MOTION_STEP_MS, pauseMs: 0, materializeFadeMs: 0 };
  }
  let travelMs = TRAVEL_MS * compression;
  let drawMs = drawMsForReveal(kind, bounds, page) * compression;
  let pauseMs = INTER_STEP_PAUSE_MS * compression;
  let materializeFadeMs = MATERIALIZE_FADE_MS * compression;
  // Floor: never reveal an element faster than MIN_STEP_TOTAL_MS total (and so
  // never drop the draw) — if compression pushed the step under the floor,
  // scale the whole step back up proportionally.
  const total = travelMs + drawMs + pauseMs;
  if (total > 0 && total < MIN_STEP_TOTAL_MS) {
    const boost = MIN_STEP_TOTAL_MS / total;
    travelMs *= boost;
    drawMs *= boost;
    pauseMs *= boost;
    materializeFadeMs *= boost;
  }
  return { travelMs, drawMs, pauseMs, materializeFadeMs };
}

/**
 * The batch-wide compression factor: if pacing every step at its worst-case
 * nominal duration would overrun the cap, shrink every step by this factor so
 * the whole batch fits MAX_BATCH_REVEAL_MS (the per-step floor still applies).
 */
function batchCompression(stepCount: number): number {
  const nominalPerStep = TRAVEL_MS + DRAW_MAX_MS + INTER_STEP_PAUSE_MS;
  const totalNominal = stepCount * nominalPerStep;
  return totalNominal > MAX_BATCH_REVEAL_MS ? MAX_BATCH_REVEAL_MS / totalNominal : 1;
}

/**
 * A single paced reveal-step: the ops applied together this beat (a run of
 * silent non-visual ops folded onto the one visual op so there are no dead
 * beats) and the visual op that drives the pace (null = a silent step).
 */
interface RevealStep {
  ops: Operation[];
  visualOp: Operation | null;
}

/**
 * Structure-first reveal granularity: an `add_page` lands as an artboard
 * placeholder and an `insert_node` materializes one element — both are visual
 * beats. Everything else (asset upserts, slot writes, property patches) applies
 * silently WITH the next visual step.
 */
const isVisualRevealOp = (op: Operation): boolean =>
  op.kind === "add_page" || op.kind === "insert_node";

/**
 * Split a streamed batch's ops into paced reveal-steps: each visual op closes a
 * step, carrying any preceding non-visual ops as its silent prefix; trailing
 * non-visual ops fold onto the last step (or form one silent step if the batch
 * has no visual op at all) so the pump never ticks on an empty beat.
 */
function stepsFromOps(ops: readonly Operation[]): RevealStep[] {
  const steps: RevealStep[] = [];
  let pending: Operation[] = [];
  for (const op of ops) {
    pending.push(op);
    if (isVisualRevealOp(op)) {
      steps.push({ ops: pending, visualOp: op });
      pending = [];
    }
  }
  if (pending.length > 0) {
    if (steps.length > 0) {
      steps[steps.length - 1].ops.push(...pending);
    } else {
      steps.push({ ops: pending, visualOp: null });
    }
  }
  return steps;
}

/** The geometry the pace needs: which page, and how big the new box is. */
interface RevealGeometry {
  kind: string;
  pageId: PageId | null;
  bounds: Rect | null;
}

/**
 * Derive the pacing geometry for a revealed step from the scene it produced.
 * Read off the APPLIED scene, never the displayed one — the display lags the
 * engine during the draw window, so it could not answer this lookup.
 */
function revealGeometry(step: RevealStep, scene: Scene): RevealGeometry {
  const op = step.visualOp;
  if (op?.kind === "add_page") {
    return { kind: op.kind, pageId: op.page.id, bounds: null };
  }
  if (op?.kind === "insert_node") {
    // A later op folded onto this step can remove the just-inserted node. Only
    // pace against a node that actually survives into the applied scene.
    const insertedId: NodeId | null = op.node?.id ?? null;
    const nodeId = insertedId && scene.nodes[insertedId] ? insertedId : null;
    const pageId =
      op.parent.kind === "page"
        ? op.parent.id
        : nodeId
          ? pageIdForNode(scene, nodeId)
          : null;
    const bounds = nodeId
      ? (scene.nodes[nodeId]?.computed?.layout_bounds ?? null)
      : null;
    return { kind: op.kind, pageId, bounds };
  }
  return { kind: op?.kind ?? "silent", pageId: null, bounds: null };
}

/* ---------------------------------------------------------------------------
 * The pump.
 * ------------------------------------------------------------------------ */

/**
 * The live engine apply, injected. Null means the engine is unavailable (the
 * D9 read-only state) — indistinguishable, here, from a refusal: nothing was
 * applied, so nothing may be shown.
 */
export type SceneRevealApply = (
  operations: Operation[],
) => EngineApplyOutcome | null;

export interface SceneRevealPumpOptions {
  apply: SceneRevealApply;
  /**
   * Could a batch land right now — i.e. is the live engine available? The
   * canvas's own `canApply()`, asked live rather than remembered, because the
   * engine arrives after the first paint and can be absent for the whole
   * session (D9 read-only).
   *
   * It is separate from `apply` returning null because the pump has to answer
   * "am I healthy?" BEFORE it has a batch to try — the reload decision at an
   * anchor asks exactly that. Defaults to available.
   */
  engineAvailable?: () => boolean;
  /** Identity of the current engine; a remount must replay into its new instance. */
  engineIdentity?: () => object | null;
  /** The display override. `null` hands the canvas back to the document. */
  onDisplayScene: (scene: Scene | null) => void;
  /** Defaults to the OS preference, read once when the pump is built. */
  reducedMotion?: boolean;
}

/**
 * The scheduler, deliberately a plain object rather than a hook: the reveal is
 * a clock, and a clock held in React state would re-render the whole surface on
 * every beat. The hook below owns exactly one piece of state — the scene now on
 * screen — and this owns everything that ticks.
 *
 * D4.5: one `setTimeout` chain, never rAF. Exactly one timer is live at any
 * moment, so every cancellation (a stale anchor, a fast-forward, a stop) is one
 * `clearTimeout` and there is no way to leave a beat running behind a state
 * change.
 */
export class SceneRevealPump {
  private readonly apply: SceneRevealApply;
  private readonly engineAvailable: () => boolean;
  private readonly engineIdentity?: () => object | null;
  private readonly emit: (scene: Scene | null) => void;
  private readonly reducedMotion: boolean;

  private active = false;
  /** An apply refused or threw: stop applying until the next anchor. */
  private dirtyUntilAnchor = false;
  /**
   * Task 10: a canvas has just joined a run in flight and has not caught up to
   * it yet. While it holds, the next batches to arrive are BACKLOG — frames the
   * run already streamed — and they land at once instead of being drawn in.
   */
  private joining = false;
  /**
   * How far into the CURRENT run's ledger this pump has actually applied
   * (task 10, fix round 3), or `null` when it has applied nothing of it.
   *
   * The pump's one memory, and it exists for exactly one hazard: a canvas can
   * be streaming a run LIVE before its document has finished loading (the lock
   * and the open document are both known first), and the join that follows the
   * load replays that same run's logged batches. Without this, the join would
   * hand the engine operations it already holds — an insert applied twice is
   * refused, the pump latches dirty, and every checkpoint from then on reloads
   * a canvas that was in sync. The position belongs to one RUN and one ENGINE;
   * a new run or a join onto a replacement engine forgets it.
   */
  private appliedThrough: number | null = null;
  private appliedEngineIdentity: object | null | undefined;
  private queue: RevealStep[] = [];
  private compression = 1;
  private timer: ReturnType<typeof setTimeout> | null = null;
  /**
   * The engine-applied scene the display has NOT caught up to yet — the whole
   * of "engine-ahead". Every path that shows something shows THIS and clears
   * it, so a held scene can never be lost and can never be shown twice.
   */
  private pendingDisplay: Scene | null = null;

  constructor(options: SceneRevealPumpOptions) {
    this.apply = options.apply;
    this.engineAvailable = options.engineAvailable ?? (() => true);
    this.engineIdentity = options.engineIdentity;
    this.emit = options.onDisplayScene;
    this.reducedMotion = options.reducedMotion ?? prefersReducedMotion();
  }

  isDirty(): boolean {
    return this.dirtyUntilAnchor;
  }

  /**
   * Is this pump streaming at all — i.e. has it been started and not stopped?
   *
   * Its consumer is the hook's session effect, which starts a pump when the
   * lock closes over an open document. That effect keys on the SESSION, so a
   * pump rebuilt underneath an unchanged session (React's StrictMode does
   * exactly this on mount) would never be started: it would apply nothing and
   * report unclean for the rest of the session, which reloads the canvas at
   * every checkpoint. Asking the pump itself is what makes the effect
   * idempotent (fix round 3).
   */
  isStreaming(): boolean {
    return this.active;
  }

  /**
   * Is this pump actually rendering the stream right now?
   *
   * The pump half of the composite anchor decision
   * (`projects/model/design-anchor-reload`), and the ONLY definition of it:
   * both consumers — this pump's own `anchor()` and the controller's reload
   * bump, through the surface's health probe — read this one method, so they
   * cannot answer the same question differently.
   *
   * Three ways to be unhealthy, and each is a reason the canvas needs rung A's
   * reload rather than a suppression: the pump is not streaming this document
   * at all; the engine is unavailable, so nothing can ever be applied (D9
   * read-only); or an apply was refused and the picture is missing a batch.
   */
  isClean(): boolean {
    return this.active && !this.dirtyUntilAnchor && this.engineAvailable();
  }

  /** Begin streaming onto the canvas (the lock engaged over an open document). */
  start(): void {
    this.cancelTimer();
    this.active = true;
    this.dirtyUntilAnchor = false;
    this.joining = false;
    this.appliedThrough = null;
    this.queue = [];
    this.compression = 1;
    this.pendingDisplay = null;
  }

  /**
   * A canvas JOINED this run: it has finished loading the document at a durable
   * version, and task 10's cursor seed has re-seated the ledger position to
   * match (`SceneStreamAction` `seed`).
   *
   * Two things follow, and they are the whole method.
   *
   * **The document load has settled.** Queued display work and refusal state
   * are dropped, and the canvas renders the loaded document. An unchanged
   * engine may already hold live operations applied before this join arrived;
   * its watermark still prevents duplicates. A replacement engine owns only
   * its loaded checkpoint, so the old instance's watermark must be forgotten.
   *
   * **What arrives next is backlog, not news.** A run that has been going for
   * five minutes has streamed five minutes of frames; a tab that opens into it
   * wants to see where the design IS, not to watch it re-drawn from the
   * beginning. So the batches that follow the join land in one apply
   * (`settleJoin`), and only once the canvas has caught up does the reveal
   * start drawing elements in again.
   */
  join(): void {
    if (!this.active) return;
    // The pump can outlive the canvas (Gallery -> artifact). Its old engine's
    // watermark cannot suppress replay into the newly loaded checkpoint.
    if (this.engineIdentity && this.engineIdentity() !== this.appliedEngineIdentity) {
      this.appliedThrough = null;
    }
    this.reseat();
    this.joining = true;
  }

  /**
   * A NEW RUN's ledger began over this document (task 10, fix round 1).
   *
   * `operations_total` counts one run's operations, and the next run counts its
   * own from zero over whatever the document then is — so the moment a frame
   * from another turn arrives, everything this pump is holding describes a run
   * that is over. The queue, the held scene and the refusal latch all go, and
   * the override drops so the canvas renders the DOCUMENT, which is exactly the
   * base the new run's first batch is measured against.
   *
   * Unlike a join, no catch-up latch: the first batch of a run that is starting
   * now is live, and live batches draw themselves in.
   */
  rebase(): void {
    if (!this.active) return;
    this.reseat();
    // A NEW run counts from zero. A join keeps this mark only when the engine
    // instance still holds the operations, not merely because the run matches.
    this.appliedThrough = null;
  }

  /** The move `join` and `rebase` share: drop everything held, show the document. */
  private reseat(): void {
    this.cancelTimer();
    this.queue = [];
    this.pendingDisplay = null;
    this.dirtyUntilAnchor = false;
    this.emit(null);
  }

  /**
   * End of the consume pass a join happened in: show everything it brought at
   * once, and the join is over.
   *
   * Pass-scoped, and it can be (fix round 2) because the catch-up no longer
   * races the document load. The fold replays the run's logged backlog into the
   * seed's OWN pass (`seedSceneStreamState` → `replaySceneStreamJoin`), so
   * whatever a join has to catch up on is already queued behind it here.
   * Anything arriving after that is live by definition and draws itself in —
   * which matters most on the ordinary path, where a tab sits open, a run
   * starts, and its first batch must be a reveal rather than a snap.
   */
  settleJoin(): void {
    if (!this.joining || !this.active) return;
    this.fastForward();
    this.joining = false;
  }

  /**
   * Stop streaming: the lock released, the document changed, or the surface
   * unmounted. The override drops, so the canvas renders the document — which
   * rung A has already reloaded at `leg.awaiting_user`.
   */
  stop(): void {
    this.cancelTimer();
    this.active = false;
    this.dirtyUntilAnchor = false;
    this.joining = false;
    this.appliedThrough = null;
    this.queue = [];
    this.pendingDisplay = null;
    this.emit(null);
  }

  /**
   * The action log lost entries between one read of it and the next (task 10).
   *
   * The log is bounded at 64: a commit that appends more than the consumer has
   * yet read EVICTS the oldest, and what was evicted may have been an `apply`.
   * The cursor's own arithmetic cannot save the pump here — every batch it
   * cleared IS contiguous in the ledger, which is exactly why the ones that
   * survived the eviction would land on top of a canvas missing the ones that
   * did not. So contiguity is never assumed across an eviction: the pump
   * latches the same dirty it latches on a refused apply, drops op frames, and
   * waits for the anchor behind the gap — which reloads the canvas from the
   * document, because a dirty pump is not clean and an unclean pump reloads.
   */
  gap(): void {
    if (!this.active || this.dirtyUntilAnchor) return;
    console.error(
      "[scene-reveal] the streamed action log outran this canvas; the pump waits for the next checkpoint",
    );
    this.markDirty();
  }

  /**
   * A durable checkpoint landed. `cursorInSync` is task 8's arithmetic over the
   * frames — half of the decision, never all of it.
   *
   * The anchor is treated as IN SYNC only when the cursor says so AND this pump
   * is clean, which is the same composite the controller computes for the
   * reload (`anchorReloadDecision`) off the same `isClean()`. So the two moves
   * always agree: **an anchor that reloads is an anchor this pump treats as
   * stale**, and vice versa.
   *
   * In sync: nothing to repair. The working scene is kept and the canvas is not
   * flickered through a reload it does not need.
   *
   * Stale — a gap in the stream, a refused apply, an unavailable engine: the
   * reload fires, and its document is the new base. The override drops (the
   * document is always right; a streamed picture is only sometimes) and the
   * dirty latch clears, because that same reload re-seats the engine the latch
   * was protecting.
   */
  anchor(cursorInSync: boolean): void {
    if (!this.active) return;
    if (cursorInSync && this.isClean()) return;
    this.reseat();
    // The reload builds a NEW engine from the document, so nothing this pump
    // applied is in it any more.
    this.appliedThrough = null;
  }

  /**
   * Take one streamed batch (task 8 has already proven it contiguous).
   *
   * D4.1: when a NEW batch arrives while a backlog is still pending,
   * fast-forward — drain the whole backlog in ONE cumulative apply, shown at
   * once, then pace the new batch. That is the MVP's only queue bound, and it
   * is a good one: the pump can never fall further behind than one batch,
   * because the batch behind it always collapses the one in front. Replayed
   * frames after a reconnect therefore fast-forward for free.
   */
  enqueue(operations: readonly Operation[], operationsTotal?: number): void {
    if (!this.active || this.dirtyUntilAnchor) return;
    // Fix round 3: never hand the engine a ledger range it already holds. The
    // batch ends at `operationsTotal` and, being contiguous, begins at
    // `operationsTotal - operations.length`; anything at or below what this
    // pump has already applied is dropped, and a batch that straddles the mark
    // applies only its tail.
    if (operationsTotal !== undefined) {
      if (this.appliedThrough !== null) {
        if (operationsTotal <= this.appliedThrough) return;
        const begins = operationsTotal - operations.length;
        if (begins < this.appliedThrough) {
          operations = operations.slice(this.appliedThrough - begins);
        }
      }
      this.appliedThrough = operationsTotal;
      this.appliedEngineIdentity = this.engineIdentity?.();
    }
    if (operations.length === 0) return;
    if (this.queue.length > 0) {
      // A step already applied to the engine but still mid-draw is covered too:
      // its ops are in the engine, so the cumulative scene this shows includes
      // them — no held content is lost.
      this.cancelTimer();
      const backlog = this.queue;
      this.queue = [];
      const drained: Operation[] = [];
      let lastVisual: Operation | null = null;
      for (const step of backlog) {
        drained.push(...step.ops);
        if (step.visualOp) lastVisual = step.visualOp;
      }
      if (!this.applyImmediate({ ops: drained, visualOp: lastVisual })) return;
    }
    const steps = stepsFromOps(operations);
    if (steps.length === 0) return;
    this.queue = steps;
    this.compression = batchCompression(steps.length);
    // The first element begins after one inter-step pause (0 under reduced
    // motion); each subsequent step then self-schedules.
    this.scheduleNextStep(
      this.reducedMotion ? 0 : INTER_STEP_PAUSE_MS * this.compression,
    );
  }

  /**
   * Apply everything pending immediately, with no animation.
   *
   * Task 10 uses it for a late-join backlog: someone who opens the canvas
   * mid-run wants to SEE where the design is, not to watch it be re-drawn from
   * the beginning. It is also what the mid-draw reconcile above does
   * internally, by the same reasoning.
   */
  fastForward(): void {
    if (!this.active || this.dirtyUntilAnchor) return;
    this.cancelTimer();
    if (this.queue.length > 0) {
      const backlog = this.queue;
      this.queue = [];
      const drained: Operation[] = [];
      let lastVisual: Operation | null = null;
      for (const step of backlog) {
        drained.push(...step.ops);
        if (step.visualOp) lastVisual = step.visualOp;
      }
      this.applyImmediate({ ops: drained, visualOp: lastVisual });
      return;
    }
    // Nothing queued, but a beat may still be holding its content back.
    this.showPending();
  }

  /* ----------------------------------------------------------------------- */

  private cancelTimer(): void {
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
  }

  /**
   * S2.1 inversion: hand the step's ops to the ENGINE and read the resulting
   * scene, WITHOUT showing it. A refusal is swallowed loudly — the pump latches
   * dirty, drops the rest of the batch and shows nothing new; the canvas holds
   * the last good streamed scene until the next anchor's reload repairs it.
   * Streaming can never corrupt the document, because it never writes to it.
   */
  private applyStep(step: RevealStep): RevealTiming | null {
    let outcome: EngineApplyOutcome | null;
    try {
      outcome = this.apply(step.ops);
    } catch (error) {
      console.error(
        "[scene-reveal] the engine threw on a streamed batch; the pump waits for the next checkpoint",
        error,
      );
      this.markDirty();
      return null;
    }
    if (!outcome || !outcome.accepted) {
      console.error(
        "[scene-reveal] a streamed batch was refused by the engine; the pump waits for the next checkpoint",
        outcome?.message ?? outcome?.code ?? "no engine",
      );
      this.markDirty();
      return null;
    }
    const presentation = outcome.presentationScene ?? outcome.scene;
    // Readiness belongs to this outcome, not the engine's newest revision.
    // Keep applying the stream so a later operation can repair the context,
    // but never queue degraded literal geometry for a later ready engine to
    // unmask while its own reveal is still held. Legacy outcomes omit status.
    this.pendingDisplay = outcome.derivation && outcome.derivation.status !== "ready"
      ? null
      : presentation;
    const geometry = revealGeometry(step, presentation);
    const page = geometry.pageId ? outcome.scene.pages[geometry.pageId] : undefined;
    return revealTiming(
      geometry.kind,
      geometry.bounds,
      page,
      this.compression,
      this.reducedMotion,
    );
  }

  private markDirty(): void {
    this.cancelTimer();
    this.dirtyUntilAnchor = true;
    this.queue = [];
    this.pendingDisplay = null;
  }

  /** Show the engine-applied scene the display is behind, if there is one. */
  private showPending(): void {
    if (this.pendingDisplay === null) return;
    const scene = this.pendingDisplay;
    this.pendingDisplay = null;
    this.emit(scene);
  }

  /** Engine-apply AND show at once — no theater. */
  private applyImmediate(step: RevealStep): boolean {
    if (this.applyStep(step) === null) return false;
    this.showPending();
    return true;
  }

  /**
   * One paced beat: apply the head step to the engine AHEAD of the display and
   * HOLD the content; at travel+draw the held scene is shown — the content
   * lands exactly when the box would have finished drawing — and the next step
   * starts after the inter-step pause.
   */
  private runStep(): void {
    if (!this.active || this.dirtyUntilAnchor) return;
    const step = this.queue.shift();
    if (!step) return;
    const timing = this.applyStep(step);
    if (timing === null) return;
    // The corner-drag hold-back applies only to NODES. An `add_page` (or a
    // silent step) materializes IMMEDIATELY — the empty artboard IS the
    // placeholder, and holding it back would leave the next node's beat
    // pointing at a page the canvas has not drawn yet.
    const holdContent = step.visualOp?.kind === "insert_node";
    if (!holdContent) this.showPending();
    const drawDone = timing.travelMs + timing.drawMs;
    this.timer = setTimeout(() => {
      this.timer = null;
      if (!this.active || this.dirtyUntilAnchor) return;
      if (holdContent) this.showPending();
      this.scheduleNextStep(timing.pauseMs);
    }, drawDone);
  }

  /**
   * Schedule the next beat to BEGIN after `leadMs`. One chain, cancellable; it
   * halts on an empty queue, a dirty latch, or a stopped pump.
   */
  private scheduleNextStep(leadMs: number): void {
    if (!this.active || this.dirtyUntilAnchor || this.timer !== null) return;
    if (this.queue.length === 0) return;
    this.timer = setTimeout(() => {
      this.timer = null;
      this.runStep();
    }, leadMs);
  }
}

/* ---------------------------------------------------------------------------
 * Consuming task 8's action log.
 * ------------------------------------------------------------------------ */

/**
 * Drive the pump with every action NEWER than `lastSequence`, in order, and
 * return the sequence to resume from.
 *
 * Resume by SEQUENCE, never by "the latest action". Several SSE frames commit
 * in one React tick — the reader is handed a chunk, not a frame — so a consumer
 * that looked only at the tail of the log would silently coalesce applies away
 * and the canvas would skip whole batches. Task 8's log exists precisely so
 * this cannot happen; this is the half that honours it.
 *
 * A `dirty` action is deliberately nothing to do. It says the CURSOR cannot
 * place the frames it is seeing, not that the engine refused anything: what the
 * pump has already drawn is still exactly what it applied, so it keeps showing
 * it and waits for the anchor behind the gap, which is the cursor's own
 * recovery mechanism.
 */
export function consumeSceneStreamActions(
  pump: SceneRevealPump,
  actions: readonly SceneStreamActionRecord[],
  documentId: string | null,
  lastSequence: number,
): number {
  let sequence = lastSequence;
  // An eviction gap: the log's oldest surviving entry is already PAST the
  // resume point, so entries this consumer never saw were trimmed away. Checked
  // before anything is consumed, because what follows a gap must not be applied
  // (see `SceneRevealPump.gap`). Note that a jump in sequence WITHIN the log is
  // not a gap — the log is shared by every document the thread streams, and
  // another document's records legitimately sit between this one's.
  const oldest = actions[0];
  if (oldest !== undefined && oldest.sequence > lastSequence + 1) pump.gap();
  for (const record of actions) {
    if (record.sequence <= sequence) continue;
    sequence = record.sequence;
    // The cursor already refuses cross-document frames; this is the second
    // gate, because the log is shared by every document the thread streams.
    if (documentId === null || record.documentId !== documentId) continue;
    switch (record.action.action) {
      case "apply":
        pump.enqueue(record.action.operations, record.action.operationsTotal);
        break;
      case "anchor":
        pump.anchor(record.action.inSync);
        break;
      case "rebase":
        // A frame from another turn: a new run's ledger, whose base is the
        // document rather than anything this pump has drawn.
        pump.rebase();
        break;
      case "seed":
        // Task 10: a canvas loaded this document at a durable version and the
        // cursor was re-seated to match. Whatever the pump was holding belongs
        // to the document that load replaced, and whatever arrives next is the
        // run's backlog rather than its news.
        pump.join();
        break;
      case "dirty":
      case "drop":
        break;
    }
  }
  // The join's other half, and the reason it is here rather than in the loop:
  // the batches that catch a late joiner up can arrive in the SAME pass as the
  // seed or a tick or two behind it (the document fetch and the replayed frames
  // race), and both must land at once. A no-op on a pump that is not joining.
  pump.settleJoin();
  return sequence;
}

/* ---------------------------------------------------------------------------
 * The hook — a thin adapter over the pump above.
 * ------------------------------------------------------------------------ */

/**
 * "Is the live reveal healthy for this document right now?" — the boolean the
 * chat surface publishes to the chat controller so the checkpoint reload can
 * compose it with the cursor's own verdict (`anchorReloadDecision`).
 *
 * A probe rather than a snapshot on purpose: both facts behind it — whether an
 * apply was refused, and whether the engine is available — are imperative and
 * change without a render, so a value published on the last commit could be
 * stale by the time a frame arrives. The controller calls this at frame time
 * and gets the truth then.
 */
export type SceneRevealHealthProbe = (documentId: string) => boolean;

export interface UseSceneLiveRevealOptions {
  /** The design document the editor has open, or null. */
  documentId: string | null;
  /** The agent-run lock (task 4). Streaming happens only while it holds. */
  locked: boolean;
  /** Task 8's decided-frame log, straight off the controller. */
  actions: readonly SceneStreamActionRecord[];
  /**
   * The canvas's live engine apply — display-state only. Stable identity, or
   * the pump would be rebuilt mid-run; the hook reads it through a ref so a
   * changing callback cannot strand a beat.
   */
  apply: SceneRevealApply;
  /**
   * Could the canvas apply a batch right now (its `canApply()`)? Absent means
   * "assume yes", which is only right for a caller with no engine to lose.
   */
  engineAvailable?: () => boolean;
  /** The mounted canvas's engine identity, independent of its controls object. */
  engineIdentity?: () => object | null;
  /** Test seam; production reads the OS preference. */
  reducedMotion?: boolean;
}

export interface SceneLiveReveal {
  /**
   * The scene the canvas should draw INSTEAD of the loaded document, or null
   * to draw the document. Null whenever the pump is not streaming.
   */
  displayScene: Scene | null;
  /** Show everything pending at once, with no animation. */
  fastForward: () => void;
  /**
   * The health probe to publish to the chat controller. Stable identity, and
   * false for any document this pump is not currently streaming — including
   * when it is not streaming at all.
   */
  isClean: SceneRevealHealthProbe;
}

export function useSceneLiveReveal({
  documentId,
  locked,
  actions,
  apply,
  engineAvailable,
  engineIdentity,
  reducedMotion,
}: UseSceneLiveRevealOptions): SceneLiveReveal {
  const [displayScene, setDisplayScene] = useState<Scene | null>(null);

  // The engine seam, latched (the canvas's own `onSceneChangeRef` pattern): a
  // beat fires from a timer, long after the render that handed the callback
  // over, so it must read the current one rather than the one it closed on.
  const applyRef = useRef(apply);
  const engineAvailableRef = useRef(engineAvailable);
  const engineIdentityRef = useRef(engineIdentity);
  useEffect(() => {
    applyRef.current = apply;
    engineAvailableRef.current = engineAvailable;
    engineIdentityRef.current = engineIdentity;
  });

  // ONE pump for the life of the surface, built in an effect. It holds a
  // running clock, so it is not render state and it is not derived from
  // anything — a document or lock change moves it through `start`/`stop`
  // below, and rebuilding it there would drop a beat mid-draw. (An effect
  // rather than a lazy initializer because the pump reads the latched seam
  // above, and a ref may only be touched outside render.)
  const pumpRef = useRef<SceneRevealPump | null>(null);
  useEffect(() => {
    const pump = new SceneRevealPump({
      apply: (operations) => applyRef.current(operations),
      engineAvailable: () => engineAvailableRef.current?.() ?? true,
      engineIdentity: () => engineIdentityRef.current?.() ?? null,
      onDisplayScene: setDisplayScene,
      reducedMotion,
    });
    pumpRef.current = pump;
    return () => {
      // The override drops with the surface: whatever was mid-reveal is not a
      // document, and the canvas that comes back has one.
      pump.stop();
      pumpRef.current = null;
    };
  }, [reducedMotion]);

  /**
   * Which streaming session the pump is in — one document, one lock. A change
   * is a hard reset, and the log is fast-forwarded past: everything already in
   * it happened BEFORE this canvas was open, and the document it was handed was
   * loaded at a version that already contains those operations. Re-applying
   * them would double-apply the run's own work.
   *
   * (Catching a late-join up to where the run actually is, rather than leaving
   * it still until the next batch, is task 10's — it has `fastForward` and the
   * durable read to do it honestly.)
   */
  const sessionRef = useRef<string | null>(null);
  const lastSequenceRef = useRef(0);

  useEffect(() => {
    const pump = pumpRef.current;
    if (!pump) return;
    const session = locked && documentId !== null ? documentId : null;
    // A session change — or a pump that is not streaming the session it should
    // be (a rebuilt pump under an unchanged session; fix round 3).
    if (sessionRef.current !== session || (session !== null && !pump.isStreaming())) {
      sessionRef.current = session;
      lastSequenceRef.current = actions[actions.length - 1]?.sequence ?? 0;

      if (session === null) pump.stop();
      else pump.start();
      return;
    }
    if (session === null) return;
    lastSequenceRef.current = consumeSceneStreamActions(
      pump,
      actions,
      documentId,
      lastSequenceRef.current,
    );
  }, [actions, documentId, locked]);

  const fastForward = useCallback(() => {
    pumpRef.current?.fastForward();
  }, []);

  // Stable, so the surface's publish effect runs once rather than on every
  // render; every fact it reports is read live inside it.
  const isClean = useCallback<SceneRevealHealthProbe>(
    (documentId) =>
      sessionRef.current === documentId &&
      (pumpRef.current?.isClean() ?? false),
    [],
  );

  return { displayScene, fastForward, isClean };
}
