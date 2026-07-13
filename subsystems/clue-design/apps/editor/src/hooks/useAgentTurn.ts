import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import type { AgentChatMessage, QueuedAgentMessage } from "@/components/AgentChatPanel";
import type { EditorHistoryFrame } from "@/hooks/useEditHistory";
import {
  operationsFromRunEvent,
  type AgentRunEvent,
  type EditorAgentResult,
  type EditorAgentRunner
} from "@/engine/agentRunner";
import type {
  BrandCompatibilityReport,
  Diagnostic,
  ExportProfile,
  NodeId,
  Operation,
  PageId,
  Rect,
  Scene
} from "@/engine/contracts";
import { defaultEditorExportProfile, type EditorExportResult } from "@/engine/exportRunner";
import type { EditorPreflightResult } from "@/engine/preflightRunner";
import { firstPageId, pageIdForNode } from "@/engine/sceneQueries";
import { loadCanvasKit } from "@/engine/canvaskit/loadCanvasKit";
import { skiaMeasurements } from "@/engine/canvaskit/skiaMeasurements";
import {
  resolveAndFreezeScene,
  type AcceptBakeResult
} from "@/engine/documentStore";
import { editorApiBaseUrl } from "@/engine/editorConfig";
import { freezeLayoutEdit } from "@/engine/structuredEdits";
import type { OptimisticEnginePort } from "@/engine/wasmEngine";

/** Default K1.6(b) bake: the real /preflight-preview call with
 * freeze_layout, against the configured API. */
const defaultAcceptBakeRunner = (scene: Scene): Promise<AcceptBakeResult | null> =>
  resolveAndFreezeScene({ apiBaseUrl: editorApiBaseUrl() }, scene);

/**
 * The agent-turn state machine: run → propose → preview → Accept/Reject,
 * plus the message queue that drains one prompt per idle transition.
 *
 * This hook owns the workflow policy; EditorApp owns the scene, history,
 * and persistence primitives and passes them in as deps. The deps object
 * is rebuilt every render (like the closures it replaced), so hook
 * callbacks always see the current scene/selection — never memoize it.
 *
 * The canvas lock is enforced from BOTH sides: mutation paths in
 * EditorApp guard on `agentPreview` / `isAgentRunning` (surfacing the
 * diagnostics exported below), and the hook refuses new turns while one
 * is running or awaiting review.
 */

export const pendingAgentReviewDiagnostic = (): Diagnostic => ({
  severity: "warning",
  phase: "operation",
  code: "EDITOR_AGENT_REVIEW_PENDING",
  message: "An agent proposal is awaiting review.",
  subject: { kind: "document" },
  hint: "Accept or Reject the agent's changes before editing the design."
});

// Phase 2a exclusive turns (Moda's lock): while the agent designs, the
// canvas is read-only — mutations would race the turn's seed scene.
export const agentTurnRunningDiagnostic = (): Diagnostic => ({
  severity: "warning",
  phase: "operation",
  code: "EDITOR_AGENT_TURN_RUNNING",
  message: "The agent is designing — the canvas is locked until the turn finishes.",
  subject: { kind: "document" },
  hint: "Wait for the agent to finish (you can queue a chat message meanwhile), then edit or review its changes."
});

/** Phase 0c ephemeral preview: the proposed turn applied to the live scene,
 * with the base kept for Reject and the Before/After toggle. */
/** RC: one user-attached reference for the next turn — the uploaded library
 * asset id, a human label, and a thumbnail URL (GET /assets/{id}/thumbnail).
 * Per-turn context: cleared after each successful send. */
export interface PendingReference {
  assetId: string;
  label: string;
  thumbnailUrl: string;
}

/** RC: the maximum references a single turn carries — mirrors the runtime's
 * PLACED_PREVIEWS_MAX and the API cap (D1); more dilutes vision context. */
export const MAX_TURN_REFERENCES = 4;

export interface AgentPreviewState {
  operations: Operation[];
  /** Engine-computed inverse of the previewed batch, captured at apply time
   * so an Accept's undo frame can persist its undo later. */
  inverseOperations: Operation[] | null;
  baseScene: Scene;
  previewScene: Scene;
  baseActivePageId: PageId | null;
  baseSelectedNodeId: NodeId | null;
  view: "before" | "after";
}

/** Live-design-streaming (D3/D5): one streamed ops batch — the operations that
 * rode a single clean compile, with the run-event seq they arrived on. */
export interface AgentStreamBatch {
  seq: number;
  operations: Operation[];
}

/** S2 reveal metadata: the one element (or artboard) most recently materialized
 * by the pump, in the terms the SVG chrome + viewport auto-follow need. `bounds`
 * is the node's `computed.layout_bounds` in SCENE units (the wiring layer scales
 * by the page's unitScale and offsets by the artboard rect to reach workspace
 * space); it is null for an `add_page` placeholder (the whole artboard flashes).*/
export interface AgentStreamReveal {
  /** The run-event seq the revealed op rode in on. */
  seq: number;
  /** The revealed op's kind (`insert_node`, `add_page`, …) — drives chrome copy.*/
  kind: string;
  /** The materialized node, or null for a page placeholder / silent step. */
  nodeId: NodeId | null;
  /** The page the reveal belongs to (drives viewport auto-follow). */
  pageId: PageId | null;
  /** Scene-unit layout bounds of the revealed node; null for a page/silent step.*/
  bounds: Rect | null;
}

/** Live-design-streaming: the minimal streaming status the hook exposes so the
 * S2 theater can sequence reveals and draw chrome without re-plumbing. Small
 * and derived; the canonical proposal (not this) is what Accept ever persists. */
export interface AgentStreamStatus {
  /** A run is in flight and progressively applying streamed batches. */
  active: boolean;
  /** The highest run-event seq whose reveal-step was applied (seq-dedup guard).*/
  lastAppliedSeq: number;
  /** How many reveal-steps were successfully applied this run (one visual op per
   * paced step; a fast-forwarded backlog counts each drained step). */
  stepsApplied: number;
  /** An applyOperations failure stopped further streamed application; the
   * canvas holds the last good streamed scene and waits for the terminal
   * reconcile. Never breaks the turn or the final proposal. */
  brokenStream: boolean;
  /** The most recently applied step (ops + seq), or null before the first. */
  latestBatch: AgentStreamBatch | null;
  /** S2: the element/artboard just revealed, for the SVG chrome + auto-follow.*/
  currentReveal: AgentStreamReveal | null;
  /** S2: reveal-steps still queued behind the pump (0 = caught up / idle). */
  revealQueueLength: number;
}

const idleAgentStreamStatus = (): AgentStreamStatus => ({
  active: false,
  lastAppliedSeq: 0,
  stepsApplied: 0,
  brokenStream: false,
  latestBatch: null,
  currentReveal: null,
  revealQueueLength: 0
});

/** S2 pump cadence: one reveal-step every ~100 ms (moda-parity element-by-
 * element materialization), but never let a single streamed batch's reveal
 * take longer than the cap — a large batch compresses its per-step pace to fit
 * (per-batch duration cap, not a fixed cadence). */
const REVEAL_CADENCE_MS = 100;
const MAX_BATCH_REVEAL_MS = 5000;

/** A single paced reveal-step: the ops applied together this beat (a run of
 * silent non-visual ops folded onto the one visual op so there are no dead
 * beats) and the visual op that drives the chrome (null = a silent step). */
interface RevealStep {
  seq: number;
  ops: Operation[];
  visualOp: Operation | null;
}

/** Structure-first reveal granularity: an `add_page` lands as an artboard
 * placeholder and an `insert_node` materializes one element — both are visual
 * beats. Everything else (asset upserts, slot writes, …) applies silently WITH
 * the next visual step. */
const isVisualRevealOp = (op: Operation): boolean =>
  op.kind === "add_page" || op.kind === "insert_node";

/** Split a streamed batch's ops into paced reveal-steps: each visual op closes a
 * step, carrying any preceding non-visual ops as its silent prefix; trailing
 * non-visual ops fold onto the last step (or form one silent step if the batch
 * has no visual op at all) so the pump never ticks on an empty beat. */
function stepsFromOps(seq: number, ops: Operation[]): RevealStep[] {
  const steps: RevealStep[] = [];
  let pending: Operation[] = [];
  for (const op of ops) {
    pending.push(op);
    if (isVisualRevealOp(op)) {
      steps.push({ seq, ops: pending, visualOp: op });
      pending = [];
    }
  }
  if (pending.length > 0) {
    if (steps.length > 0) {
      steps[steps.length - 1].ops.push(...pending);
    } else {
      steps.push({ seq, ops: pending, visualOp: null });
    }
  }
  return steps;
}

/** Derive the chrome/auto-follow metadata for a revealed step from the scene it
 * produced. `add_page` → the new page (whole-artboard flash, no node bounds);
 * `insert_node` → the materialized node + its computed bounds + owning page. */
function revealFromStep(step: RevealStep, scene: Scene): AgentStreamReveal {
  const op = step.visualOp;
  if (op?.kind === "add_page") {
    return { seq: step.seq, kind: op.kind, nodeId: null, pageId: op.page.id, bounds: null };
  }
  if (op?.kind === "insert_node") {
    // A later op folded onto this step can remove the just-inserted node (an
    // insert+delete that lands in one paced step). Only reveal a node that
    // actually survives into the applied scene — otherwise the chrome would
    // point at a node that no longer exists (a dangling reveal).
    const insertedId = op.node?.id ?? null;
    const nodeId = insertedId && scene.nodes[insertedId] ? insertedId : null;
    const pageId =
      op.parent.kind === "page"
        ? op.parent.id
        : nodeId
          ? pageIdForNode(scene, nodeId)
          : null;
    const bounds = nodeId ? scene.nodes[nodeId]?.computed?.layout_bounds ?? null : null;
    return { seq: step.seq, kind: op.kind, nodeId, pageId, bounds };
  }
  return { seq: step.seq, kind: op?.kind ?? "silent", nodeId: null, pageId: null, bounds: null };
}

export interface UseAgentTurnDeps {
  agentRunner: EditorAgentRunner;
  engineRef: { current: OptimisticEnginePort | null };
  scene: Scene;
  activeDocumentId: string | null;
  activePageId: PageId | null;
  selectedNodeId: NodeId | null;
  /** 2c: the chipped edit targets sent with each turn. */
  targetNodeIds: NodeId[];
  /** RC: uploads one attached file to the asset library and resolves its
   * reference descriptor (id + label + thumbnail url). Injected so the hook
   * stays testable (tests mock it); EditorApp wires the real uploadAsset +
   * thumbnail URL. Absent → the attach affordance is inert. */
  referenceUploader?: (file: File) => Promise<PendingReference>;
  /** 2e: the document's standing instructions sent with each turn. */
  agentInstructions: string | null;
  /** Model override sent with each turn (null = runtime default). */
  agentModel?: string | null;
  /** Advanced per-document opt-out from handoff-absolute: when true the
   * accept-time freeze is skipped, so the turn's Stack containers stay live. */
  layoutManagedEditing: boolean;
  /** K1.6(b): the server accept bake (resolve tokens + relayout + freeze on
   * the server, returning the raw scene + ops). Defaults to the real API
   * call; tests inject fakes. Null return / throw → client-side fallback. */
  acceptBakeRunner?: (scene: Scene) => Promise<AcceptBakeResult | null>;
  diagnostics: Diagnostic[];
  setDiagnostics: Dispatch<SetStateAction<Diagnostic[]>>;
  setScene: Dispatch<SetStateAction<Scene>>;
  replaceScene: (nextScene: Scene) => void;
  setActivePageId: Dispatch<SetStateAction<PageId | null>>;
  setSelectedNodeId: Dispatch<SetStateAction<NodeId | null>>;
  setUndoStack: Dispatch<SetStateAction<EditorHistoryFrame[]>>;
  setRedoStack: Dispatch<SetStateAction<EditorHistoryFrame[]>>;
  setBrandCompatibilityReport: Dispatch<SetStateAction<BrandCompatibilityReport | null>>;
  setPreflightResult: Dispatch<SetStateAction<EditorPreflightResult | null>>;
  setExportResult: Dispatch<SetStateAction<EditorExportResult | null>>;
  setWorkspaceMode: Dispatch<SetStateAction<"canvas" | "export" | "compare">>;
  commitAppliedOperations: (
    previousScene: Scene,
    operations: Operation[],
    nextScene: Scene,
    persistOptions?: { checkpoint?: string },
    inverseOperations?: Operation[] | null
  ) => "persisted" | "creation-seed" | "local-only";
  runExportForScene: (
    sceneForExport: Scene,
    profile: ExportProfile,
    pageIds: PageId[]
  ) => Promise<void>;
  applyOperations: (operations: Operation[], onAccepted?: (scene: Scene) => void) => void;
  /** 2b: rejoin an in-flight run's SSE stream after a tab reload (resume). The
   * run keeps executing server-side; this replays its events and resolves with
   * the final result. Omitted in tests (no resume). */
  resumeRun?: (
    runId: string,
    onEvent: (event: AgentRunEvent) => void
  ) => Promise<EditorAgentResult>;
}

// Moda's exclusive turn is server-durable in 2b: stash the in-flight run id so
// a tab reload can rejoin its live stream. sessionStorage (not local) so it is
// tab-scoped and cleared when the tab closes.
const ACTIVE_RUN_STORAGE_KEY = "lumen.activeAgentRun";

function writeActiveRun(runId: string): void {
  try {
    window.sessionStorage?.setItem(ACTIVE_RUN_STORAGE_KEY, runId);
  } catch {
    // Private-mode / disabled storage: resume is best-effort.
  }
}

function readActiveRun(): string | null {
  try {
    return window.sessionStorage?.getItem(ACTIVE_RUN_STORAGE_KEY) ?? null;
  } catch {
    return null;
  }
}

function clearActiveRun(): void {
  try {
    window.sessionStorage?.removeItem(ACTIVE_RUN_STORAGE_KEY);
  } catch {
    // ignore
  }
}

export function useAgentTurn(deps: UseAgentTurnDeps) {
  const {
    agentRunner,
    engineRef,
    scene,
    activeDocumentId,
    activePageId,
    selectedNodeId,
    targetNodeIds,
    referenceUploader,
    agentInstructions,
    agentModel,
    layoutManagedEditing,
    acceptBakeRunner = defaultAcceptBakeRunner,
    diagnostics,
    setDiagnostics,
    setScene,
    replaceScene,
    setActivePageId,
    setSelectedNodeId,
    setUndoStack,
    setRedoStack,
    setBrandCompatibilityReport,
    setPreflightResult,
    setExportResult,
    setWorkspaceMode,
    commitAppliedOperations,
    runExportForScene,
    applyOperations,
    resumeRun
  } = deps;

  const [isAgentRunning, setIsAgentRunning] = useState(false);
  const [agentDraft, setAgentDraft] = useState("");
  // 2b show-work: the live run-event stream feeding the Moda plan checklist.
  const [runEvents, setRunEvents] = useState<AgentRunEvent[]>([]);
  // Live-design-streaming (D3): the exposed streaming status the S2 theater
  // reads. Mirrors the synchronous working state in streamRef (below).
  const [agentStream, setAgentStream] = useState<AgentStreamStatus>(idleAgentStreamStatus);
  // The synchronous working copy of the stream, mutated in-place inside the SSE
  // event callback + the pump tick: cumulative application needs a monotonic
  // seq guard and a single captured base scene read/written without waiting for
  // a React re-render. `baseScene` is captured ONCE (before the first streamed
  // apply) and is what the terminal reconcile / failure-restore return the
  // engine to. `queue` holds the paced reveal-steps; `timer` is the single
  // setTimeout chain (D4.5: no rAF — the canvas repaints itself per setScene).
  const streamRef = useRef<{
    active: boolean;
    baseScene: Scene | null;
    lastEnqueuedSeq: number;
    lastAppliedSeq: number;
    stepsApplied: number;
    broken: boolean;
    queue: RevealStep[];
    cadenceMs: number;
    timer: ReturnType<typeof setTimeout> | null;
  } | null>(null);

  // The pre-turn seed scene, captured EXPLICITLY at arm time — before any
  // streamed apply mutates the live scene. Every settle path (live send AND
  // reload resume) reads THIS, never closure/ref `scene` (which streaming has
  // since mutated). Kills the staleness class the resume path fell into: an
  // undo frame that captured the half-built streamed scene, and an
  // unchanged-seed check that compared the draft against the streamed scene.
  // Held until the next armStream overwrites it (never nulled on settle, since
  // handleTurnResult reads it AFTER reconcileStreamToBase runs).
  const turnSeedRef = useRef<Scene | null>(null);

  const cancelPump = () => {
    const stream = streamRef.current;
    if (stream?.timer != null) {
      clearTimeout(stream.timer);
      stream.timer = null;
    }
  };

  // Arm the stream at run start: a fresh run paces batches from a base scene
  // captured lazily on the first reveal-step. Called by the live send and the
  // reload resume path alike.
  const armStream = () => {
    cancelPump();
    // Capture the pre-turn seed NOW — nothing streamed yet, so the engine's
    // scene (or the React scene) is the honest base for both the live send and
    // the reload-resume path (this mount's `scene` is the pre-turn base).
    turnSeedRef.current = engineRef.current?.scene ?? scene;
    streamRef.current = {
      active: true,
      baseScene: null,
      lastEnqueuedSeq: 0,
      lastAppliedSeq: 0,
      stepsApplied: 0,
      broken: false,
      queue: [],
      cadenceMs: REVEAL_CADENCE_MS,
      timer: null
    };
    setAgentStream({ ...idleAgentStreamStatus(), active: true });
  };

  const markStreamBroken = () => {
    cancelPump();
    const stream = streamRef.current;
    if (stream) {
      stream.broken = true;
      stream.queue = [];
    }
    setAgentStream((status) => ({ ...status, brokenStream: true, revealQueueLength: 0 }));
  };

  // Apply one reveal-step's ops cumulatively to the engine and mirror the result
  // onto the React scene (exactly the preview seam). A failed apply is SWALLOWED
  // loudly: the stream is marked broken, later steps are dropped, and the canvas
  // holds the last good streamed scene until the terminal reconcile replaces it.
  // Streaming can never break the turn or the final proposal. Returns false if
  // the apply broke (caller stops), true otherwise.
  const applyRevealStep = (step: RevealStep): boolean => {
    const stream = streamRef.current;
    const engine = engineRef.current;
    if (!stream || !engine) {
      return false;
    }
    if (stream.baseScene === null) {
      stream.baseScene = engine.scene;
    }
    try {
      const applied = engine.applyOperations(step.ops);
      if (!applied.accepted) {
        // eslint-disable-next-line no-console
        console.error(
          "[agent-stream] streamed step rejected by the engine; stream marked broken",
          applied.message ?? applied.code
        );
        markStreamBroken();
        return false;
      }
      stream.lastAppliedSeq = step.seq;
      stream.stepsApplied += 1;
      const reveal = revealFromStep(step, applied.scene);
      setScene(applied.scene);
      setAgentStream((status) => ({
        ...status,
        lastAppliedSeq: step.seq,
        stepsApplied: status.stepsApplied + 1,
        latestBatch: { seq: step.seq, operations: step.ops },
        currentReveal: reveal,
        revealQueueLength: stream.queue.length
      }));
      return true;
    } catch (error) {
      // eslint-disable-next-line no-console
      console.error("[agent-stream] applyOperations threw on a streamed step; stream marked broken", error);
      markStreamBroken();
      return false;
    }
  };

  // The pump (D4.1): apply the head reveal-step, then schedule the next on the
  // current cadence. One timer chain, cancellable; it halts on an empty queue,
  // a broken apply, or a torn-down stream.
  const scheduleNextRevealStep = () => {
    const stream = streamRef.current;
    if (!stream || !stream.active || stream.broken || stream.timer != null) {
      return;
    }
    if (stream.queue.length === 0) {
      return;
    }
    stream.timer = setTimeout(() => {
      const current = streamRef.current;
      if (!current || !current.active || current.broken) {
        return;
      }
      current.timer = null;
      const step = current.queue.shift();
      if (step && !applyRevealStep(step)) {
        return;
      }
      scheduleNextRevealStep();
    }, stream.cadenceMs);
  };

  // Enqueue a streamed batch (D4.1): its ops become paced reveal-steps. When a
  // NEW batch arrives while a backlog is still pending, fast-forward — drain the
  // whole backlog in ONE cumulative apply (no visible catch-up crawl), then pace
  // the new batch. Replayed-on-reconnect events therefore fast-forward for free.
  // The per-batch duration cap compresses the pace so a large batch still
  // finishes within MAX_BATCH_REVEAL_MS.
  const enqueueStreamedBatch = (event: AgentRunEvent) => {
    const stream = streamRef.current;
    if (!stream || !stream.active || stream.broken) {
      return;
    }
    const operations = operationsFromRunEvent(event);
    if (!operations) {
      return;
    }
    if (event.seq <= stream.lastEnqueuedSeq) {
      return;
    }
    stream.lastEnqueuedSeq = event.seq;
    const engine = engineRef.current;
    if (!engine) {
      // Server-only mode has no local engine to render onto; the terminal
      // proposal still arrives on `done` and applies through the normal path.
      return;
    }
    // Fast-forward any pending backlog from earlier batches as a single apply.
    if (stream.queue.length > 0) {
      cancelPump();
      const backlog = stream.queue;
      stream.queue = [];
      const drained: Operation[] = [];
      let lastStep: RevealStep | null = null;
      for (const pending of backlog) {
        drained.push(...pending.ops);
        if (pending.visualOp) {
          lastStep = pending;
        }
      }
      const flushSeq = backlog[backlog.length - 1]?.seq ?? stream.lastAppliedSeq;
      if (
        !applyRevealStep({
          seq: flushSeq,
          ops: drained,
          visualOp: lastStep?.visualOp ?? null
        })
      ) {
        return;
      }
    }
    const steps = stepsFromOps(event.seq, operations);
    if (steps.length === 0) {
      return;
    }
    stream.queue = steps;
    stream.cadenceMs = Math.min(REVEAL_CADENCE_MS, MAX_BATCH_REVEAL_MS / steps.length);
    setAgentStream((status) => ({ ...status, revealQueueLength: steps.length }));
    scheduleNextRevealStep();
  };

  // Terminal reconcile (D3, the invariant): cancel the pump, drop any pending
  // reveal-steps, and discard the ephemeral stream by resetting the engine to
  // the pre-turn base. previewAgentProposal reads `engine.scene` as its base and
  // applies the canonical ops from there, so the streamed engine state can
  // NEVER leak into the preview — a streamed run reconciles byte-identically to
  // a non-streamed one. `setScene(base)` covers the rare path where nothing
  // repaints after (an unchanged-seed failure); the proposed/draft paths
  // setScene their own result immediately after and win the batched update.
  const reconcileStreamToBase = () => {
    cancelPump();
    const stream = streamRef.current;
    if (stream?.baseScene) {
      engineRef.current?.reset(stream.baseScene);
      setScene(stream.baseScene);
    }
    streamRef.current = null;
    setAgentStream(idleAgentStreamStatus());
  };

  // Failure path: cancel the pump, drop pending steps, and restore the pre-turn
  // base exactly like Reject (replaceScene resets the engine AND the scene), so
  // a run that streamed some progress then failed never leaves a half-built
  // design masquerading as the result.
  const restoreStreamBaseOnFailure = () => {
    cancelPump();
    const stream = streamRef.current;
    if (stream?.baseScene) {
      replaceScene(stream.baseScene);
    }
    streamRef.current = null;
    setAgentStream(idleAgentStreamStatus());
  };

  // A mid-run unmount must not leak the pump's timer.
  useEffect(() => () => cancelPump(), []);
  const [agentMessages, setAgentMessages] = useState<AgentChatMessage[]>([]);
  const [agentProposal, setAgentProposal] = useState<EditorAgentResult | null>(null);
  // Phase 0c (Moda pattern): a proposed agent turn is applied to the live scene
  // as an ephemeral PREVIEW first. Nothing persists until the human Accepts;
  // Reject restores the pre-preview scene byte-for-byte. While a review is
  // pending, mutating actions (ops, undo/redo, new agent turns) are blocked.
  const [agentPreview, setAgentPreview] = useState<AgentPreviewState | null>(null);
  // Phase 2a (Moda's queue): messages typed while a turn runs or a review is
  // pending wait here and drain one per idle transition — each drained turn
  // seeds from the scene as it is at drain time, not at enqueue time.
  const [queuedAgentMessages, setQueuedAgentMessages] = useState<QueuedAgentMessage[]>([]);
  // RC: references the user attached for the NEXT turn. Per-turn context —
  // threaded into the runner call and cleared after each successful send.
  const [pendingReferences, setPendingReferences] = useState<PendingReference[]>([]);
  const [isUploadingReferences, setIsUploadingReferences] = useState(false);

  // Merge one streamed run event into the checklist state. Replay (EventSource
  // reconnect, or resume-on-mount) re-sends events, so dedupe by seq; the
  // run_started frame carries the run id we persist for reload resume.
  const handleRunEvent = (event: AgentRunEvent) => {
    if (typeof event.data.run_id === "string") {
      writeActiveRun(event.data.run_id);
    }
    // Live-design-streaming (D3/S2): pace the design's element-by-element
    // reveal. Events that carry no operations (checklist ticks) fall through
    // untouched.
    enqueueStreamedBatch(event);
    setRunEvents((events) => {
      if (events.some((existing) => existing.seq === event.seq && existing.type === event.type)) {
        return events;
      }
      return [...events, event].sort((left, right) => left.seq - right.seq);
    });
  };

  // Turn-settled bookkeeping, shared by the live send path and the reload
  // resume path: surface the proposal/draft, post the chat messages, and (for
  // a proposed turn) drop into the reviewable preview. The seed is the scene
  // the turn was ARMED from (turnSeedRef, captured before any streamed apply) —
  // NOT closure/ref `scene`, which progressive streaming has since mutated.
  // Both the unchanged-seed check and the draft's undo frame read this seed, so
  // the resume path can no longer compare against — or persist — the streamed
  // scene.
  const handleTurnResult = (result: EditorAgentResult) => {
    const seedScene = turnSeedRef.current ?? scene;
    // Live-design-streaming (D3): the streamed build is ephemeral. Reset the
    // engine to the pre-turn base BEFORE the canonical preview so the streamed
    // state can never leak into what Accept applies (the reconcile invariant).
    reconcileStreamToBase();
    // A failed run can hand back a "draft" that is just the untouched seed
    // (every authored block was rejected — nothing ever applied). Claiming
    // "draft visible" for an unchanged design reads as a broken canvas;
    // be honest instead and keep the proposal card in its blocked state.
    const draftIsUnchangedSeed =
      result.status === "failed" &&
      result.draft_scene !== null &&
      JSON.stringify(result.draft_scene) === JSON.stringify(seedScene);
    setAgentProposal(
      draftIsUnchangedSeed ? { ...result, draft_scene: null } : result
    );
    if (result.status === "failed" && result.draft_scene && !draftIsUnchangedSeed) {
      showAgentDraftScene(result, seedScene);
    }
    setAgentMessages((messages) => [
      ...messages,
      {
        id: uniqueChatMessageId("agent"),
        role: "agent",
        content: result.summary
      }
    ]);
    if (draftIsUnchangedSeed) {
      setAgentMessages((messages) => [
        ...messages,
        {
          id: uniqueChatMessageId("system"),
          role: "system",
          content:
            "The agent could not produce any applicable changes — the design is unchanged. " +
            "Try rephrasing the request, or ask for the change as an edit to the existing elements."
        }
      ]);
    }
    if (result.diagnostics.length > 0) {
      setDiagnostics(result.diagnostics);
    }
    // Phase 0c (Moda pattern): a proposed turn goes straight onto the canvas
    // as a reviewable preview — the human answers with Accept or Reject.
    if (result.status === "proposed" && result.operations.length > 0) {
      previewAgentProposal(result);
    }
  };

  const handleTurnError = (error: unknown) => {
    // Live-design-streaming (D3/D7): a failed run restores the pre-turn base
    // exactly like Reject — the stream never masks a failure as progress.
    restoreStreamBaseOnFailure();
    const message = error instanceof Error ? error.message : "Agent request failed.";
    const diagnostic: Diagnostic = {
      severity: "error",
      phase: "validation",
      code: "EDITOR_AGENT_REQUEST_FAILED",
      message,
      subject: { kind: "document" },
      hint: "Check the editor API/agent runtime connection and retry."
    };
    setAgentProposal({
      status: "failed",
      summary: message,
      dsl_blocks: [],
      operations: [],
      draft_scene: null,
      stop_reason: null,
      acceptance_scope: null,
      diagnostics: [diagnostic],
      trace: {
        run_id: null,
        trace_dir: null,
        preview_paths: []
      },
      artifacts: []
    });
    setDiagnostics([diagnostic]);
    setAgentMessages((messages) => [
      ...messages,
      {
        id: uniqueChatMessageId("system"),
        role: "system",
        content: message
      }
    ]);
  };

  const sendAgentPrompt = async (
    prompt: string,
    referencesOverride?: PendingReference[]
  ) => {
    const trimmedPrompt = prompt.trim();
    if (!trimmedPrompt || isAgentRunning) {
      return;
    }
    if (agentPreview) {
      setDiagnostics([pendingAgentReviewDiagnostic()]);
      return;
    }

    // RC: snapshot the references riding THIS turn before any async work, so a
    // reference added mid-flight never leaks into an in-flight send. A QUEUED
    // message passes its enqueue-time snapshot as the override (ship-blocker 2:
    // reading the live pending set at drain time dropped or mixed attachments);
    // a composer send reads the live pending set.
    const fromQueue = referencesOverride !== undefined;
    const turnReferences = fromQueue ? referencesOverride : pendingReferences;
    const referenceAssetIds = turnReferences.map((reference) => reference.assetId);
    setAgentDraft("");
    setAgentProposal(null);
    setRunEvents([]);
    armStream();
    setIsAgentRunning(true);
    setAgentMessages((messages) => [
      ...messages,
      {
        id: uniqueChatMessageId("user"),
        role: "user",
        content: trimmedPrompt,
        // RC: record what rode the turn so the transcript shows the attachments
        // (optional-metadata pattern, like `turn` on accepted messages).
        attachments:
          turnReferences.length > 0
            ? turnReferences.map((reference) => ({
                assetId: reference.assetId,
                label: reference.label
              }))
            : undefined
      }
    ]);

    try {
      const result = await agentRunner({
        prompt: trimmedPrompt,
        scene,
        documentId: activeDocumentId ?? undefined,
        activePageId,
        targetNodeIds,
        referenceAssetIds,
        agentInstructions,
        model: agentModel ?? null,
        diagnostics,
        onEvent: handleRunEvent
      });
      handleTurnResult(result);
      // RC per-turn semantics (D8): references are consumed by a successful
      // send. On error they stay so the user can retry without re-attaching.
      // Clear ONLY the ids that rode this turn (ship-blocker 2: a blanket []
      // wiped attachments the user added mid-flight for their NEXT message);
      // a queued send owns its snapshot and never touches the live pending set.
      if (!fromQueue) {
        const sentIds = new Set(turnReferences.map((reference) => reference.assetId));
        setPendingReferences((current) =>
          current.filter((reference) => !sentIds.has(reference.assetId))
        );
      }
    } catch (error) {
      handleTurnError(error);
    } finally {
      setIsAgentRunning(false);
      clearActiveRun();
    }
  };

  /** Post a system line into the chat from an external flow (e.g. a
   * checkpoint revert) — same id/shape as internally posted messages. */
  const postSystemMessage = (content: string) => {
    setAgentMessages((messages) => [
      ...messages,
      { id: uniqueChatMessageId("system"), role: "system", content }
    ]);
  };

  const queueAgentMessage = (content: string) => {
    const trimmed = content.trim();
    if (!trimmed) {
      return;
    }
    // RC (ship-blocker 2): the queued message OWNS the attachments pending at
    // enqueue time — snapshot them onto the message and consume them from the
    // composer, so the running turn's success-clear can never drop them and a
    // later message's attachments can never mix in.
    const references = pendingReferences;
    if (references.length > 0) {
      setPendingReferences([]);
    }
    setQueuedAgentMessages((queue) => [
      ...queue,
      {
        id: uniqueChatMessageId("user"),
        content: trimmed,
        references: references.length > 0 ? references : undefined
      }
    ]);
  };

  const removeQueuedAgentMessage = (id: string) => {
    setQueuedAgentMessages((queue) => queue.filter((message) => message.id !== id));
  };

  /** RC: upload each attached file (via the injected uploader) and add it to
   * the pending references, honoring the ≤4 cap and de-duping by asset id.
   * Files past the cap are dropped with a system note; an upload failure is
   * surfaced but never blocks the others. */
  const attachReferences = async (files: File[]) => {
    if (!referenceUploader || files.length === 0) {
      return;
    }
    const room = MAX_TURN_REFERENCES - pendingReferences.length;
    if (room <= 0) {
      postSystemMessage(
        `You can attach at most ${MAX_TURN_REFERENCES} references per turn — remove one to add another.`
      );
      return;
    }
    const accepted = files.slice(0, room);
    if (accepted.length < files.length) {
      postSystemMessage(
        `Only ${accepted.length} of ${files.length} files were attached — a turn carries at most ${MAX_TURN_REFERENCES} references.`
      );
    }
    setIsUploadingReferences(true);
    try {
      for (const file of accepted) {
        try {
          const reference = await referenceUploader(file);
          setPendingReferences((current) =>
            current.length >= MAX_TURN_REFERENCES ||
            current.some((existing) => existing.assetId === reference.assetId)
              ? current
              : [...current, reference]
          );
        } catch (error) {
          postSystemMessage(
            `Could not attach ${file.name}: ${
              error instanceof Error ? error.message : "upload failed"
            }`
          );
        }
      }
    } finally {
      setIsUploadingReferences(false);
    }
  };

  const removeReference = (assetId: string) => {
    setPendingReferences((current) =>
      current.filter((reference) => reference.assetId !== assetId)
    );
  };

  const clearReferences = () => setPendingReferences([]);

  // Drain the queue one message per idle transition: a turn must have
  // settled AND its review been resolved (Accept or Reject both count — the
  // user answered the preview; their queued intent still stands). Seeding
  // happens inside sendAgentPrompt from the live scene at drain time.
  useEffect(() => {
    if (isAgentRunning || agentPreview || queuedAgentMessages.length === 0) {
      return;
    }
    const [next, ...rest] = queuedAgentMessages;
    setQueuedAgentMessages(rest);
    void sendAgentPrompt(next.content, next.references ?? []);
    // sendAgentPrompt is re-created per render; keying the effect on it would
    // drain the whole queue in one burst instead of one per idle transition.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAgentRunning, agentPreview, queuedAgentMessages]);

  // Resume-on-mount: an async turn keeps running server-side across a tab
  // reload. If one was in flight, rejoin its SSE stream — replaying the
  // checklist and then either streaming live ticks or settling immediately if
  // it finished while we were away. Refs keep the mount-only effect calling
  // the latest handlers without re-firing; the pre-turn seed those handlers
  // settle against comes from turnSeedRef (armed on mount), not closure state.
  const handleRunEventRef = useRef(handleRunEvent);
  handleRunEventRef.current = handleRunEvent;
  const handleTurnResultRef = useRef(handleTurnResult);
  handleTurnResultRef.current = handleTurnResult;
  const handleTurnErrorRef = useRef(handleTurnError);
  handleTurnErrorRef.current = handleTurnError;

  useEffect(() => {
    if (!resumeRun) {
      return;
    }
    const runId = readActiveRun();
    if (!runId) {
      return;
    }
    setRunEvents([]);
    setAgentProposal(null);
    // Mid-run reload: SSE replay delivers every missed batch in order, so the
    // same cumulative apply path fast-forwards the build (S2 animates it).
    armStream();
    setIsAgentRunning(true);
    void resumeRun(runId, (event) => handleRunEventRef.current(event))
      .then((result) => handleTurnResultRef.current(result))
      .catch((error) => handleTurnErrorRef.current(error))
      .finally(() => {
        setIsAgentRunning(false);
        clearActiveRun();
      });
    // Mount-only: a reload rejoins exactly one in-flight run.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const showAgentDraftScene = (result: EditorAgentResult, seedScene: Scene) => {
    if (!result.draft_scene) {
      return;
    }
    const draftScene = result.draft_scene;
    // Compare the draft's pages against the pre-turn SEED, not closure `scene`
    // (which streaming mutated on the resume path) — otherwise a "new" draft
    // page could be misclassified against a half-built streamed scene.
    const draftPageId = agentDraftPageId(seedScene, draftScene, activePageId);
    const draftDiagnostic: Diagnostic = {
      severity: "warning",
      phase: "validation",
      code: "EDITOR_AGENT_UNAPPROVED_DRAFT_VISIBLE",
      message: "Showing the agent's latest unapproved draft on the canvas.",
      subject: { kind: "document" },
      hint:
        result.stop_reason ??
        "The draft did not pass the agent quality loop, but it is available for inspection and manual repair."
    };

    setUndoStack((stack) => [
      ...stack.slice(-49),
      {
        // The undo frame must capture the true PRE-TURN base (the seed), never
        // the streamed scene: undo history is durable, and "nothing streamed is
        // ever persisted" (D3). On the resume path closure `scene` is the
        // half-built streamed scene — the seed is the honest base.
        scene: seedScene,
        operations: [],
        inverseOperations: null,
        persisted: false
      }
    ]);
    setRedoStack([]);
    replaceScene(draftScene);
    setActivePageId(draftPageId);
    setSelectedNodeId(null);
    setBrandCompatibilityReport(null);
    setPreflightResult(null);
    setExportResult(null);
    setWorkspaceMode("canvas");
    setDiagnostics([draftDiagnostic, ...result.diagnostics]);
  };

  /**
   * Phase 0c: apply the proposed operations to the live scene as an ephemeral
   * PREVIEW. The engine holds the previewed state; nothing is persisted and no
   * undo frame is pushed until Accept. The base scene is kept for Reject and
   * for the Before/After toggle.
   */
  const previewAgentProposal = (result: EditorAgentResult) => {
    if (result.operations.length === 0 || agentPreview) {
      return;
    }
    const engine = engineRef.current;
    if (!engine) {
      // Server-only mode cannot apply locally; the proposal card's manual
      // apply button surfaces the same server-only diagnostic as any edit.
      return;
    }
    const baseScene = engine.scene;
    const applied = engine.applyOperations(result.operations);
    if (!applied.accepted) {
      setDiagnostics([
        {
          severity: "error",
          phase: "operation",
          code: "EDITOR_AGENT_PREVIEW_REJECTED",
          message:
            applied.message ??
            "The agent's operations were rejected by the editor engine; the scene is unchanged.",
          subject: { kind: "document" },
          hint: "The proposal may target content that changed since the agent turn started. Ask the agent again from the current design."
        }
      ]);
      return;
    }
    const proposedPageId = agentPreviewPageId(result.operations, activePageId, baseScene);
    const previewPageId =
      proposedPageId && applied.scene.pages[proposedPageId]
        ? proposedPageId
        : firstPageId(applied.scene);
    setAgentPreview({
      operations: result.operations,
      inverseOperations: applied.inverseOperations ?? null,
      baseScene,
      previewScene: applied.scene,
      baseActivePageId: activePageId,
      baseSelectedNodeId: selectedNodeId,
      view: "after"
    });
    setScene(applied.scene);
    setActivePageId(previewPageId);
    setSelectedNodeId((current) =>
      current && applied.scene.nodes[current] ? current : null
    );
    setBrandCompatibilityReport(null);
    setPreflightResult(null);
    setExportResult(null);
    setWorkspaceMode("canvas");
  };

  /** Accept the pending preview: commit the already-applied ops (undo frame,
   * history, persistence via the document operations path — edit_envelopes
   * inverses server-side), then run the export preview. The token-baked
   * preflight scene is never swapped into the live scene (see
   * runExportForScene). */
  const acceptAgentPreview = async () => {
    if (!agentPreview) {
      return;
    }
    const { operations, inverseOperations, baseScene, previewScene, view } = agentPreview;
    const advisoryDiagnostics = agentProposal?.diagnostics ?? [];
    // Anchor this turn to a server-side checkpoint: the persisted batch's
    // envelope gets checkpoint_label "agent-turn-<run id>", which Revert
    // points at later. The trace run id is unique per run; a turn without
    // one (defensive) falls back to the unique message id generator.
    const checkpoint = `agent-turn-${agentProposal?.trace.run_id ?? uniqueChatMessageId("system")}`;
    setAgentPreview(null);
    setAgentProposal(null);
    // The user may be looking at "Before" — the engine must hold the accepted
    // (preview) state before the commit bookkeeping runs.
    const engine = engineRef.current;
    let acceptedScene = previewScene;
    if (engine) {
      if (view === "before") {
        engine.reset(previewScene);
      }
      acceptedScene = engine.scene;
    }
    // Handoff-absolute: bake every Stack container to Free in the SAME
    // envelope as the turn's own ops — merged into one undo frame and one
    // server checkpoint (not a second commit), so a single Undo fully
    // unwinds both the freeze and the turn's content back to the true
    // pre-turn scene, and Revert has exactly one batch to point at. An empty
    // freeze outcome (already frozen / nothing to freeze) merges nothing.
    // The layout-managed-editing opt-out skips the bake entirely: the turn's
    // ops commit exactly as proposed and its Stack containers stay live.
    let mergedOperations = operations;
    let mergedInverseOperations = inverseOperations;
    if (!layoutManagedEditing) {
      // K1.6(b): resolve THEN freeze, both server-side. Agent proposal ops
      // carry token-form text with skeleton literals (Inter 16); the real
      // style exists only after token resolution, which is server preflight's
      // job. Any freeze built from a client solve can therefore bake
      // skeleton-derived geometry (17pt text heights, a 58pt hero, collapsed
      // child offsets — three live-proof failures of this family). The
      // server bake preflights the accepted scene (resolution + real
      // SkParagraph relayout) and builds the freeze from THAT, so frozen
      // numbers can never derive from unresolved literals. Resolution ops
      // ride the same envelope: the accepted design persists its derived
      // values in its own history.
      let baked: AcceptBakeResult | null = null;
      try {
        baked = await acceptBakeRunner(acceptedScene);
      } catch {
        // API unreachable mid-accept: fall through to the client-side path
        // below rather than blocking the accept.
      }
      if (baked) {
        acceptedScene = baked.scene;
        engine?.reset(baked.scene);
        mergedOperations = [
          ...operations,
          ...baked.resolutionOperations,
          ...baked.freezeOperations
        ];
        // Inverses undo in reverse order of the forward batch: the freeze's
        // inverse goes first so undoing peels the freeze off before the
        // turn's content. Resolution ops are not individually inverted —
        // turn inverses restore touched nodes' full prior state (same
        // semantics as the post-accept system preflight today).
        mergedInverseOperations =
          inverseOperations && baked.freezeInverseOperations.length > 0
            ? [...baked.freezeInverseOperations, ...inverseOperations]
            : mergedInverseOperations;
      } else if (engine?.applyStructuredEdit) {
        // Fallback (server declined/unreachable): the pre-(b) client-side
        // freeze — re-measure with kit-resolved fields, relayout, bake.
        // Weaker (client measurement can miss wrapped-text keys) but never
        // blocks an accept.
        if (engine.setMeasurements) {
          const bundle = await loadCanvasKit();
          if (bundle?.fontProvider) {
            engine.setMeasurements(
              skiaMeasurements(bundle.ck, bundle.fontProvider, engine.scene)
            );
            acceptedScene = engine.scene;
          }
        }
        const freezeOutcome = engine.applyStructuredEdit(freezeLayoutEdit());
        if (freezeOutcome.accepted && freezeOutcome.operations.length > 0) {
          acceptedScene = freezeOutcome.scene;
          mergedOperations = [...operations, ...freezeOutcome.operations];
          mergedInverseOperations =
            inverseOperations && freezeOutcome.inverseOperations
              ? [...freezeOutcome.inverseOperations, ...inverseOperations]
              : null;
        }
      }
    }
    const disposition = commitAppliedOperations(
      baseScene,
      mergedOperations,
      acceptedScene,
      { checkpoint },
      mergedInverseOperations
    );
    const messageId = uniqueChatMessageId("system");
    setAgentMessages((messages) => [
      ...messages,
      {
        id: messageId,
        role: "system",
        content:
          `Accepted ${operations.length} agent change${operations.length === 1 ? "" : "s"}.` +
          (advisoryDiagnostics.length > 0
            ? ` ${advisoryDiagnostics.length} advisory review note${advisoryDiagnostics.length === 1 ? "" : "s"} kept in Diagnostics.`
            : ""),
        turn: {
          key: messageId,
          // Only a batch that gets its own server envelope is revertible.
          // The empty-canvas accept folds into the creation seed (no
          // envelope), so its turn is honestly non-revertible from birth.
          checkpoint: disposition === "persisted" ? checkpoint : null,
          beforeScene: baseScene,
          afterScene: acceptedScene,
          operationCount: operations.length
        }
      }
    ]);
    const previewPageId =
      activePageId && acceptedScene.pages[activePageId]
        ? activePageId
        : firstPageId(acceptedScene);
    if (previewPageId) {
      await runExportForScene(acceptedScene, defaultEditorExportProfile(), [previewPageId]);
    }
    // Re-surface the agent's advisory review notes AFTER the export preview
    // (which resets diagnostics as it runs) so accepting never silently
    // discards them.
    if (advisoryDiagnostics.length > 0) {
      setDiagnostics((current) => [...advisoryDiagnostics, ...current]);
    }
  };

  /** Reject the pending preview: restore the pre-preview scene byte-for-byte.
   * Nothing was persisted, so there is nothing to roll back server-side. */
  const rejectAgentPreview = () => {
    if (!agentPreview) {
      return;
    }
    const { baseScene, baseActivePageId, baseSelectedNodeId } = agentPreview;
    setAgentPreview(null);
    setAgentProposal(null);
    replaceScene(baseScene);
    setActivePageId(
      baseActivePageId && baseScene.pages[baseActivePageId]
        ? baseActivePageId
        : firstPageId(baseScene)
    );
    setSelectedNodeId(
      baseSelectedNodeId && baseScene.nodes[baseSelectedNodeId] ? baseSelectedNodeId : null
    );
    setDiagnostics([]);
    setAgentMessages((messages) => [
      ...messages,
      {
        id: uniqueChatMessageId("system"),
        role: "system",
        content: "Rejected the agent changes and restored the previous design."
      }
    ]);
  };

  /** Before/After toggle (Moda's compare). The CanvasKit surface paints from
   * the ENGINE, not the React scene prop, so the toggle resets the engine to
   * the chosen snapshot — authoritative for every renderer. Accept re-arms the
   * preview state first; Reject resets to base anyway. */
  const setAgentPreviewView = (view: "before" | "after") => {
    setAgentPreview((current) => {
      if (!current || current.view === view) {
        return current;
      }
      const nextScene = view === "before" ? current.baseScene : current.previewScene;
      const engine = engineRef.current;
      if (engine) {
        engine.reset(nextScene);
        setScene(engine.scene);
      } else {
        setScene(nextScene);
      }
      return { ...current, view };
    });
  };

  const applyAgentProposal = () => {
    if (!agentProposal || agentProposal.operations.length === 0 || agentPreview) {
      return;
    }
    // The panel button re-enters the reviewable preview (the normal path
    // previews automatically when the proposal arrives). In server-only mode
    // (no engine) previewing is impossible; applyOperations then surfaces the
    // server-only diagnostic and applies nothing — its onAccepted callback
    // can never run without an engine, so none is passed.
    if (engineRef.current) {
      previewAgentProposal(agentProposal);
      return;
    }
    applyOperations(agentProposal.operations);
  };

  return {
    isAgentRunning,
    agentDraft,
    setAgentDraft,
    agentMessages,
    agentProposal,
    agentPreview,
    queuedAgentMessages,
    runEvents,
    agentStream,
    /** The scene the in-flight turn was armed from (its pre-turn seed), or null
     * once no stream is active. EditorApp threads this into
     * previewBaseSceneRef so a pre-run edit-queue batch draining MID-STREAM
     * reconciles against the honest base, not the streamed scene. */
    turnSeedRef,
    pendingReferences,
    isUploadingReferences,
    sendAgentPrompt,
    postSystemMessage,
    queueAgentMessage,
    removeQueuedAgentMessage,
    attachReferences,
    removeReference,
    clearReferences,
    applyAgentProposal,
    acceptAgentPreview,
    rejectAgentPreview,
    setAgentPreviewView
  };
}

function agentDraftPageId(
  currentScene: Scene,
  draftScene: Scene,
  activePageId: PageId | null
): PageId | null {
  const newDraftPage = Object.values(draftScene.pages).find(
    (page) => !currentScene.pages[page.id]
  );
  if (newDraftPage) {
    return newDraftPage.id;
  }
  if (activePageId && draftScene.pages[activePageId]) {
    return activePageId;
  }
  return firstPageId(draftScene);
}

function agentPreviewPageId(
  operations: Operation[],
  activePageId: PageId | null,
  scene: Scene
): PageId | null {
  for (let index = operations.length - 1; index >= 0; index -= 1) {
    const operation = operations[index];
    if (operation.kind === "add_page") {
      return operation.page.id;
    }
    if (operation.kind === "update_page") {
      return operation.page_id;
    }
    if (operation.kind === "insert_node" && operation.parent.kind === "page") {
      return operation.parent.id;
    }
    if (operation.kind === "move_node" && operation.new_parent.kind === "page") {
      return operation.new_parent.id;
    }
  }
  return activePageId && scene.pages[activePageId] ? activePageId : firstPageId(scene);
}

function uniqueChatMessageId(role: AgentChatMessage["role"]): string {
  return `${role}_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}
