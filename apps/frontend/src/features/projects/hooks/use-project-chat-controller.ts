"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  NO_AGENT_RUN,
  applyAgentRunLockEvent,
  designLegFactFor,
  type AgentRunLockState,
  type DesignLegFact,
} from "@/features/chat-shell/model/agent-run-lock";
import {
  ClueChatApiError,
  isAccessError,
  newIdempotencyKey,
} from "../data/chat-api";
import type { ChatStreamHandle } from "../data/chat-stream.repository";
import type { ChatGateRead } from "../data/chat-gates.repository";
import {
  startConversationReads,
  takeChatPrefetch,
  type ChatPrefetch,
  type ConversationReads,
} from "../data/chat-prefetch";
import {
  useChatRepositories,
  useChatViewerIdentity,
} from "../data/projects-transport";
import type { ChatMessage } from "../model/chat-message";
import type { ChatGatePart } from "../model/chat-parts";
import {
  agentGateIdFromPart,
  gateAnswerDisplay,
  gateAnswerResponse,
  gateAuthorityFailure,
  gateCardModel,
  type ChatGate,
  type GateAnswerDisplay,
  type GateAuthorityFailure,
  type GateCardModel,
  type GateDecisionInput,
} from "../model/chat-gate";
import {
  applyChatStreamEvent,
  composeTranscript,
  emptyTranscriptState,
  mergeThreadMessages,
  seedDesignLeg,
  type OptimisticTurn,
  type TranscriptMessage,
  type TranscriptState,
} from "../model/chat-transcript";
import {
  DESIGN_CHECKPOINT_CANVAS_RELOAD_MIN_INTERVAL_MS,
  throttleTrailing,
} from "../model/design-checkpoint-throttle";
import { anchorReloadDecision } from "../model/design-anchor-reload";

/**
 * Task 9 (fix 1): "is the live reveal healthy for this document right now?"
 *
 * Structurally identical to the design editor's own `SceneRevealHealthProbe`,
 * and declared here rather than imported so nothing about the reveal pump —
 * not even a type — reaches this controller. One boolean is the whole seam.
 */
type SceneRevealHealthProbe = (documentId: string) => boolean;
import {
  DESIGN_CHECKPOINT_EVENT_TYPE,
  designRefreshForEvent,
} from "../model/design-leg";
import {
  NO_SCENE_STREAM,
  applySceneStreamFrame,
  seedSceneStreamState,
  type SceneStreamFrame,
  type SceneStreamState,
} from "@/features/design-editor/adapter/scene-stream-cursor";
import { ProjectPlanWriteTracker } from "../model/plan-write-signal";
import {
  deriveThreadStatus,
  threadLabel,
  threadRouteHref,
  resolveProjectThreadRoute,
  type ChatThread,
  type ThreadStatus,
} from "../model/chat-thread";
import { useProjectCatalogInvalidation } from "../model/project-catalog-invalidation";
import { useNamingCatchUp } from "./use-naming-catch-up";
import { usePageVisible } from "./use-page-visible";
import {
  CRM_WRITE_GATE_KIND,
  crmWriteRefusal,
} from "@/features/integrations/model/crm-write";
import { TERMINAL_TURN_EVENTS } from "../model/chat-events";
import type { ChatAttachmentRef } from "../model/chat-attachments";
import {
  applyTurnStateOverrides,
  EMPTY_QUEUE_CONTROL,
  isTerminalTurnState,
  isTurnLive,
  MessageSubmissionGuard,
  reconcileTurnStateOverrides,
  selectTurnQueueState,
  turnStateForStreamEvent,
  type ChatTurn,
  type TurnContextReference,
  type TurnState,
  type QueueControl,
} from "../model/chat-turn";

/**
 * The projects chat controller: repositories in, a renderable conversation out.
 *
 * It owns three things and deliberately nothing else — the repository calls,
 * the live stream attachments, and the React state that binds them. Every
 * semantic decision (how an event changes a transcript, what a gate card may
 * do, how a run aggregates) lives in `model/` as a pure function, which is why
 * those can be tested against synthetic streams and this can stay a thin
 * orchestrator.
 */

/** The newest frame cursor among the turns of the last thread read, or `null` if none has one. */
function newestTurnCursor(turns: readonly ChatTurn[]): number | null {
  let newest: number | null = null;
  for (const turn of turns) {
    if (turn.lastEventId !== null && (newest === null || turn.lastEventId > newest)) {
      newest = turn.lastEventId;
    }
  }
  return newest;
}

/** How many recent turns are re-projected on cold load. */
const REHYDRATED_TURNS = 3;

/** The derivation of the wake-up turn Clue queues when a CRM write card's changes finish. */
const CRM_WRITES_FINISHED = "crm_writes_finished";

/**
 * How often a thread held by a discovery re-reads its thread list. The thread
 * stream announces the wake turn that normally ends a hold; this only catches
 * a run released without one.
 */
const DISCOVERY_HOLD_SAFETY_REREAD_MS = 30_000;

export interface ChatAccessState {
  code: string;
  message: string;
}

export interface ChatRouteState {
  code: "THREAD_NOT_FOUND" | "NO_THREADS";
  message: string;
}

export interface ProjectChatController {
  threads: readonly ChatThread[];
  activeThread: ChatThread | null;
  activeThreadId: string | null;
  transcript: readonly TranscriptMessage[];
  /** Non-null when the workspace/session refuses this conversation. */
  access: ChatAccessState | null;
  /** A controlled route state; never a raw backend error in the transcript. */
  route: ChatRouteState | null;
  loading: boolean;
  /** A stream or repository failure that did not change any durable outcome. */
  error: string | null;
  /** True when at least one turn is queued or running. */
  threadBusy: boolean;
  /** The one durable running turn Stop may target. */
  runningTurn: ChatTurn | null;
  /** Durable queued turns, preserving submission order. */
  queuedTurns: readonly ChatTurn[];
  /**
   * The account discovery holding this thread busy, as the thread list names
   * it, or `null`. While it is set the backend holds every message sent here
   * until the run's wake turn ends.
   */
  discoveryRunId: string | null;
  /** Stop that discovery. A no-op when there is none or it can no longer stop. */
  stopDiscovery(): Promise<void>;
  /**
   * Two monotone counters the design surfaces watch (genweb slice 3, B5).
   *
   * Each bumps when a **durable design-leg frame** for this thread says the
   * corresponding thing changed — never on a timer, and never optimistically.
   * The controller only counts; the decision is
   * `model/design-leg.designRefreshForEvent`, and the transport (a router
   * refresh, a canvas reload nonce) belongs to whoever renders them.
   */
  designRefresh: DesignRefreshCounters;
  /** New project Plan writes observed after this thread visit's initial server cursors. */
  planWriteRevision: number;
  writtenProjectDocumentId?: string;
  /** True when the thread is known to hold an open design leg — observed on the
   * stream, or seeded from the durable thread read. */
  designLegOpen: boolean;
  /**
   * Task 4 fix round 1: the same leg, as a THREE-valued fact — open / none /
   * not-yet-known. The editor lock reads this one, because for it the third
   * value is not the same answer as the second (see `agent-run-lock`).
   */
  designLeg: DesignLegFact;
  /**
   * Task 4 (scene live-streaming rung A): what this stream has observed about
   * the thread's design run, folded frame by frame.
   *
   * Deliberately the raw observation and not a verdict: whether the EDITOR is
   * locked also depends on which document is open and which thread it was born
   * in, and the controller can see neither. The decision is
   * `chat-shell/model/agent-run-lock.agentRunLockForThread`, taken by the
   * surface that holds all three facts.
   */
  agentRunLock: AgentRunLockState;
  /**
   * Task 8 (scene live-streaming rung B): the streamed operation batches, per
   * design document, folded through the cursor algebra.
   *
   * The raw observation again, not a verdict — the controller cannot see which
   * document the editor has open (that is the chat surface's state, and this
   * whole controller is a prop of it), so it keys a cursor on the document each
   * frame names and lets the surface read the one it cares about. What to DO
   * with an `apply` is the reveal pump's business, not this hook's.
   */
  sceneStream: SceneStreamState;
  /**
   * Task 9 (fix 1): the surface that mounts the reveal pump publishes a health
   * probe here — "is the live reveal healthy for this document right now?" —
   * and the checkpoint reload composes it with the cursor's own verdict.
   *
   * An INPUT to the controller, unlike everything else on this interface, and
   * deliberately the narrowest one possible: a function returning a boolean,
   * carrying no pump type and no scene. Publish `null` on teardown; unknown
   * health always reloads, which is rung A's shipped behaviour.
   */
  publishSceneRevealHealth: (probe: SceneRevealHealthProbe | null) => void;
  /**
   * Task 10 (late join): a canvas finished loading `documentId` at
   * `documentVersion`.
   *
   * The second INPUT on this interface, and the narrowest one that can carry
   * the fact: two primitives, no document type and no pump type. The controller
   * cannot see the editor — the same shape everything else here takes — so the
   * surface that loaded the document reports the version, and the fold turns it
   * into the cursor position the run's ledger says that version holds.
   *
   * Called on every LOAD, including a reload that lands the same version: the
   * load is the event, because it replaces whatever the canvas was showing.
   *
   * `turnId` is the run in flight over that document — the ledger the canvas is
   * joining. Only that run's checkpoints can say where the loaded version
   * stands, because a ledger position belongs to a run, not to a document
   * (fix round 1).
   */
  seedSceneStream: (
    documentId: string,
    documentVersion: number,
    turnId: string | null,
  ) => void;
  submitting: boolean;
  /** True while older transcript pages remain below the loaded window (C5). */
  hasOlderMessages: boolean;
  /** Fetch and prepend the preceding page. No-op when exhausted or in flight. */
  loadOlderMessages(): Promise<void>;
  gateFor(part: ChatGatePart): GateCardModel | null;
  gateAnswerForTurn(turnId: string): GateAnswerDisplay | null;
  /**
   * How many "changes finished" wake-up turns (derivation `crm_writes_finished`) this thread has
   * (R-12.18). When it moves, a CRM write card still being written to re-reads at once.
   */
  crmWritesFinished: number;
  submitMessage(
    text: string,
    options?: {
      contextRefs?: readonly TurnContextReference[];
      attachmentRefs?: readonly ChatAttachmentRef[];
      agentProfileId?: string | null;
    },
  ): Promise<ChatSubmissionResult>;
  answerGate(
    card: GateCardModel,
    input: GateDecisionInput,
  ): Promise<void>;
  recoverGate(card: GateCardModel): Promise<void>;
  stopActiveTurn(): Promise<void>;
  stopPending: boolean;
  queueControl: QueueControl;
  resumingQueue: boolean;
  resumeQueuedTurns(): Promise<void>;
  retryTurn(turnId: string): Promise<void>;
  selectThread(threadId: string): void;
  createThread(title?: string): Promise<ChatThread | null>;
  renameThread(threadId: string, title: string): Promise<void>;
  setThreadPinned(threadId: string, pinned: boolean): Promise<void>;
  archiveThread(threadId: string): Promise<void>;
  threadStatus(threadId: string): ThreadStatus;
  threadLabelFor(thread: ChatThread): string;
  /** Bumps on every terminal turn event of the thread this controller shows. */
  terminalTurnRevision: number;
}

/**
 * The composer's run control: Stop shows while a turn runs OR a discovery holds
 * the thread, and targets the discovery only when no turn is running.
 */
export function composerRunControl(
  chat: Pick<
    ProjectChatController,
    "runningTurn" | "discoveryRunId" | "stopActiveTurn" | "stopDiscovery"
  >,
): { running: boolean; onStop: () => void } {
  return {
    running: chat.runningTurn !== null || chat.discoveryRunId !== null,
    onStop: () =>
      void (chat.runningTurn === null && chat.discoveryRunId
        ? chat.stopDiscovery()
        : chat.stopActiveTurn()),
  };
}

export type ChatSubmissionResult =
  | { status: "accepted"; turnId: string }
  | { status: "failed" | "not_submitted" };

export interface DesignRefreshCounters {
  /** Bumps when the project's design-artifact feed should be re-read. */
  feedRevision: number;
  /** Bumps when an open web canvas should re-render from the durable document. */
  canvasRevision: number;
}

export function useProjectChatController({
  projectId,
  initialThreadId,
  projectTitle,
}: {
  projectId: string;
  initialThreadId?: string;
  /** The project's current title; still the placeholder until naming lands. */
  projectTitle: string;
}): ProjectChatController {
  const router = useRouter();
  const routeQuery = useSearchParams().toString();
  const repositories = useChatRepositories();
  const viewer = useChatViewerIdentity();
  const { invalidate: invalidateProjectCatalog } =
    useProjectCatalogInvalidation();
  const [threads, setThreads] = useState<ChatThread[]>([]);
  // Conversation naming (§4.7): bumps on every terminal turn event, so the
  // bounded catch-up poll knows a turn just ended.
  const [terminalTurnRevision, setTerminalTurnRevision] = useState(0);
  // Seeded once from the route and never mutated: every thread change is a
  // navigation, and the workspace remount key reseeds a fresh controller
  // (single-mechanism rule, Phase R).
  const [activeThreadId] = useState<string | null>(initialThreadId ?? null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  // C5 backward pagination: the durable read serves the *newest* page first and
  // `olderCursor` names the preceding page. Seeded once per mount (a thread
  // change is a remount), because later `loadConversation` reloads re-fetch the
  // newest window and must not reset a scrollback boundary the user has moved.
  const [olderCursor, setOlderCursor] = useState<string | null>(null);
  const olderCursorSeeded = useRef(false);
  const loadingOlder = useRef(false);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [queueControl, setQueueControl] = useState<QueueControl>(EMPTY_QUEUE_CONTROL);
  const [localStopTarget, setLocalStopTarget] = useState<string | null>(null);
  const stopRequestRef = useRef<{ turnId: string; settled: boolean } | null>(null);
  const [resumingQueue, setResumingQueue] = useState(false);
  const resumeRequestRef = useRef(false);
  const conversationReadVersion = useRef(0);
  const [turnStateOverrides, setTurnStateOverrides] = useState<
    ReadonlyMap<string, TurnState>
  >(new Map());
  const [gateRead, setGateRead] = useState<ChatGateRead>({
    available: false,
    gates: [],
    reason: null,
  });
  const [gateReadLoading, setGateReadLoading] = useState(true);
  const [gateFailures, setGateFailures] = useState<
    ReadonlyMap<string, GateAuthorityFailure>
  >(new Map());
  const [stream, setStream] = useState<TranscriptState>(emptyTranscriptState);
  const [planWriteRevision, setPlanWriteRevision] = useState(0);
  const [writtenProjectDocumentId, setWrittenProjectDocumentId] = useState<string>();
  const [planWrites] = useState(() => new ProjectPlanWriteTracker());
  const [designRefresh, setDesignRefresh] = useState<DesignRefreshCounters>({
    feedRevision: 0,
    canvasRevision: 0,
  });
  // Task 4: the editor lock's observations. The reducer returns the SAME object
  // for every frame it does not act on (checkpoints, deltas, part frames), so a
  // busy stream costs no extra renders here.
  const [agentRunLock, setAgentRunLock] =
    useState<AgentRunLockState>(NO_AGENT_RUN);
  // Task 8: the op-frame cursors. Deliberately NOT cleared on `stream.reset`,
  // unlike the lock above — the backlog that follows a reset replays frames the
  // cursor has already passed, and they drop as stale exactly because it kept
  // its position. Zeroing it would turn every one of them into a gap.
  const [sceneStream, setSceneStream] =
    useState<SceneStreamState>(NO_SCENE_STREAM);
  // Task 9: the cursor's own copy, kept synchronously.
  //
  // The fold has to be READ inside the frame handler, not only stored — a
  // checkpoint's `inSync` verdict decides whether that same frame reloads the
  // canvas, and a state updater's result is not available until the commit
  // after. So the ref is the source the fold reads and `setSceneStream`
  // publishes it; a side effect inside the updater would be the alternative,
  // and StrictMode double-invokes those.
  const sceneStreamRef = useRef<SceneStreamState>(NO_SCENE_STREAM);
  /**
   * Task 9 (fix 1): "is the live reveal healthy for this document?", published
   * by the surface that owns the pump.
   *
   * The controller cannot see the canvas — that is the whole shape of this
   * hook, and task 8 said so — but the checkpoint reload decision needs the
   * canvas's health as well as the cursor's verdict, so the surface reports it
   * as ONE boolean through the setter below. Nothing about the reveal machinery
   * crosses in. Null (nothing published, no pump mounted, another tab) is
   * UNKNOWN, and unknown always reloads: rung A's shipped behaviour is the
   * default this can only be an exception to.
   */
  const sceneRevealHealthRef = useRef<SceneRevealHealthProbe | null>(null);
  const publishSceneRevealHealth = useCallback(
    (probe: SceneRevealHealthProbe | null) => {
      sceneRevealHealthRef.current = probe;
    },
    [],
  );
  /**
   * Task 10: a canvas joined the run — it loaded this document at this durable
   * version, and the cursor has to be re-seated to where that version stands in
   * the ledger, or the arithmetic above measures from the wrong origin.
   *
   * Through the REF, exactly like the fold above and for the same reason: a
   * frame arriving in the same tick has to see the seeded cursor, and a state
   * updater's result is not readable until the commit after.
   */
  const seedSceneStream = useCallback(
    (documentId: string, documentVersion: number, turnId: string | null) => {
      const next = seedSceneStreamState(sceneStreamRef.current, {
        documentId,
        documentVersion,
        turnId,
      });
      sceneStreamRef.current = next;
      setSceneStream(next);
    },
    [],
  );
  const [optimistic, setOptimistic] = useState<OptimisticTurn[]>([]);
  const [access, setAccess] = useState<ChatAccessState | null>(null);
  const [route, setRoute] = useState<ChatRouteState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  const attachments = useRef(new Map<string, ChatStreamHandle>());
  const resetReattach = useRef(new Set<string>());
  //: Turns this thread has already been attached to, kept **after** the handle
  //: closes. A turn's backlog is replayed exactly once per thread visit: the
  //: durable read that follows a close changes `turns` by identity, so without
  //: this a closed attachment would be re-opened on every reload — an endless
  //: mint-token / replay-backlog loop against a real backend.
  const attached = useRef(new Set<string>());
  const messageSubmissions = useRef(new MessageSubmissionGuard());
  const turnsRef = useRef<ChatTurn[]>([]);
  // The active thread's discovery, readable inside the stream handler (which
  // is created once per attach and would otherwise see a stale list).
  const discoveryHeldRef = useRef(false);
  const discoveryStopRef = useRef<string | null>(null);
  const mounted = useRef(true);
  useEffect(() => {
    const open = attachments.current;
    mounted.current = true;
    return () => {
      mounted.current = false;
      for (const handle of open.values()) handle.close();
      open.clear();
    };
  }, []);

  const report = useCallback((failure: unknown) => {
    if (isAccessError(failure)) {
      // Lane B contract §6: an access refusal is a *state*, never an empty
      // transcript. Rendering "no messages" for "you may not see this" is the
      // one failure mode that looks like success.
      setAccess({ code: failure.code, message: failure.message });
      return;
    }
    if (failure instanceof ClueChatApiError) {
      if (failure.code === "THREAD_NOT_FOUND") {
        setRoute({
          code: "THREAD_NOT_FOUND",
          message: "This conversation is not available in this project.",
        });
        return;
      }
      setError(
        failure.requestId
          ? `${failure.message} (request ${failure.requestId})`
          : failure.message,
      );
      return;
    }
    setError(failure instanceof Error ? failure.message : String(failure));
  }, []);

  /**
   * The mid-run canvas reload, rate-limited (scene live-streaming rung A).
   *
   * A generating scene commits a checkpoint every few seconds and each one is a
   * real new document version, so the *decision* to reload is unconditional
   * (`designRefreshForEvent`). Only the rate is capped, and only here: the
   * terminal `leg.*` reloads keep going through the unthrottled path below,
   * because a hand-back is the one reload the user is actually waiting on.
   */
  const bumpCanvasRevision = useCallback(() => {
    if (!mounted.current) return;
    setDesignRefresh((current) => ({
      ...current,
      canvasRevision: current.canvasRevision + 1,
    }));
  }, []);

  const bumpCanvasForCheckpoint = useMemo(
    () =>
      throttleTrailing(
        bumpCanvasRevision,
        DESIGN_CHECKPOINT_CANVAS_RELOAD_MIN_INTERVAL_MS,
      ),
    [bumpCanvasRevision],
  );

  useEffect(
    () => () => bumpCanvasForCheckpoint.cancel(),
    [bumpCanvasForCheckpoint],
  );

  const replaceThreadInRoute = useCallback(
    (threadId: string) => {
      // Phase R (R10): canonicalization is a `replace`, never a `push` — a
      // `push` would trap the back button on the pre-canonical URL. The path
      // change flips the workspace remount key, which is the one and only
      // URL→thread mechanism (see workspaceRemountKey).
      router.replace(threadRouteHref(projectId, threadId, routeQuery));
    },
    [projectId, routeQuery, router],
  );

  // --- reads ------------------------------------------------------------

  const loadThreads = useCallback(async (early?: ChatPrefetch["threads"]) => {
    const page = await (early ?? repositories.threads.list({ projectId }));
    if (!mounted.current) return page.threads;
    setThreads(page.threads);
    // Task 4 fix round 1 (I1): seed the transcript's leg from the DURABLE read.
    //
    // The turn-stream backlog replays only the last few turns, so a leg opened
    // before that is invisible to the frames — and the editor lock read that
    // silence as "this thread has no design leg" and unlocked the scene editor
    // mid-run. `ThreadSpeakerWire` knows; this is where its answer lands. It is
    // a floor only: `seedDesignLeg` refuses to overwrite anything the stream has
    // already observed.
    const activeLeg = activeThreadId
      ? (page.threads.find((thread) => thread.id === activeThreadId)?.designLeg ??
        null)
      : null;
    if (activeLeg) {
      setStream((current) =>
        seedDesignLeg(current, {
          legId: activeLeg.legId,
          open: activeLeg.state !== null,
        }),
      );
    }
    return page.threads;
  }, [activeThreadId, projectId, repositories]);

  const loadGates = useCallback(
    async (threadId: string, early?: Promise<ChatGateRead>) => {
      if (mounted.current) setGateReadLoading(true);
      try {
        const read = await (early ?? repositories.gates.list({ projectId, threadId }));
        if (!mounted.current) return read;
        setGateRead(read);
        setGateFailures((current) => {
          const answered = new Set(
            read.gates
              .filter((gate) => gate.answer !== null)
              .map((gate) => gate.gateId),
          );
          if (answered.size === 0) return current;
          const next = new Map(current);
          for (const gateId of answered) next.delete(gateId);
          return next;
        });
        return read;
      } catch (failure) {
        if (
          isAccessError(failure) ||
          (failure instanceof ClueChatApiError &&
            failure.code === "THREAD_NOT_FOUND")
        ) {
          throw failure;
        }
        globalThis.console.error("Durable gate read failed", failure);
        const read: ChatGateRead = {
          available: false,
          gates: [],
          reason: "We couldn't load the approval details. Please try again.",
        };
        if (mounted.current) setGateRead(read);
        return read;
      } finally {
        if (mounted.current) setGateReadLoading(false);
      }
    },
    [projectId, repositories],
  );

  const loadConversation = useCallback(
    async (threadId: string, early?: ConversationReads) => {
      const readVersion = ++conversationReadVersion.current;
      const [messagePage, turnPage] = await Promise.all([
        early?.messages ?? repositories.messages.list({ projectId, threadId, includeBodies: true }),
        early?.turns ?? repositories.turns.list({ projectId, threadId }),
        loadGates(threadId, early?.gates),
      ]);
      if (!mounted.current || readVersion !== conversationReadVersion.current) return;
      planWrites.seedHistory(turnPage.turns);
      // Merge, never replace: the read serves the newest page, and replacing
      // would throw away older pages the user has already scrolled in.
      setMessages((current) => mergeThreadMessages(current, messagePage.messages));
      if (!olderCursorSeeded.current) {
        olderCursorSeeded.current = true;
        setOlderCursor(messagePage.nextCursor);
      }
      turnsRef.current = turnPage.turns;
      setTurns(turnPage.turns);
      setQueueControl(turnPage.queueControl);
      const pending = stopRequestRef.current;
      if (pending?.settled) {
        const target = turnPage.turns.find((turn) => turn.turnId === pending.turnId);
        if (target && (target.state === "cancelled" || !target.stopRequest?.pending)) {
          stopRequestRef.current = null;
          setLocalStopTarget(null);
        }
      }
      setTurnStateOverrides((current) =>
        reconcileTurnStateOverrides(current, turnPage.turns),
      );
      // A durable message for a turn means the optimistic stand-in has done its
      // job; keeping it would double the user's own sentence.
      const durableTurns = new Set([
        ...messagePage.messages.map((message) => message.turnId),
        ...turnPage.turns
          .filter((turn) => turn.submissionMessage !== null)
          .map((turn) => turn.turnId),
      ]);
      setOptimistic((current) =>
        current.filter((item) => !durableTurns.has(item.turnId)),
      );
      return turnPage.turns;
    },
    [loadGates, planWrites, projectId, repositories],
  );

  const loadOlderMessages = useCallback(async () => {
    if (!activeThreadId || olderCursor === null || loadingOlder.current) return;
    loadingOlder.current = true;
    try {
      const page = await repositories.messages.list({
        projectId,
        threadId: activeThreadId,
        cursor: olderCursor,
        includeBodies: true,
      });
      if (!mounted.current) return;
      setMessages((current) => mergeThreadMessages(current, page.messages));
      // The walk's own cursor moves; `null` means history is exhausted.
      setOlderCursor(page.nextCursor);
    } catch (failure) {
      report(failure);
    } finally {
      loadingOlder.current = false;
    }
  }, [activeThreadId, olderCursor, projectId, repositories, report]);

  useEffect(() => {
    let cancelled = false;
    // The chat in the address is read alongside the project's chat list rather than after it
    // (2026-10-15: the wait for the list was 0.5–1 s of every chat load). Its reads are applied
    // only if the list confirms this exact chat below; otherwise they are dropped unused.
    // When the project loader already started them (before this view existed), they are taken
    // from the shared prefetch store instead of being asked for again.
    const prefetched = activeThreadId ? takeChatPrefetch(projectId, activeThreadId) : null;
    const early: ConversationReads | null = activeThreadId
      ? (prefetched?.conversation ?? startConversationReads(repositories, projectId, activeThreadId))
      : null;
    void (async () => {
      try {
        const available = await loadThreads(prefetched?.threads);
        if (cancelled || !mounted.current) return;
        const resolution = resolveProjectThreadRoute(available, activeThreadId);
        if (resolution.kind === "not-found") {
          setRoute({
            code: "THREAD_NOT_FOUND",
            message: "This conversation is not available in this project.",
          });
          return;
        }
        if (resolution.kind === "empty") {
          setRoute({
            code: "NO_THREADS",
            message: "This project has no conversations yet. Start a new thread.",
          });
          return;
        }
        setRoute(null);
        if (resolution.canonicalize) {
          // Single-mechanism rule (Phase R): the path replace flips the
          // workspace remount key; the fresh mount reseeds this controller
          // and loads the conversation. Loading here too would do the work
          // twice on an instance that is about to be torn down.
          replaceThreadInRoute(resolution.thread.id);
          return;
        }
        await loadConversation(
          resolution.thread.id,
          early && resolution.thread.id === activeThreadId ? early : undefined,
        );
      } catch (failure) {
        if (!cancelled) report(failure);
      } finally {
        if (!cancelled && mounted.current) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // `activeThreadId` intentionally drives a reload; the guard above keeps the
    // first pass from looping when the id is resolved rather than chosen.
  }, [
    activeThreadId,
    loadConversation,
    loadThreads,
    replaceThreadInRoute,
    projectId,
    report,
    repositories,
  ]);

  const effectiveTurns = useMemo(
    () => applyTurnStateOverrides(turns, turnStateOverrides),
    [turnStateOverrides, turns],
  );

  // --- live attachment ---------------------------------------------------

  const attach = useCallback(
    (threadId: string, turnId: string) => {
      if (attachments.current.has(turnId) || attached.current.has(turnId)) return;
      attached.current.add(turnId);
      // A newly submitted turn may attach before its first listing. Its entire stream
      // belongs to this visit; existing turns already have their cold-load cursor.
      planWrites.seedHistory([{ turnId, lastEventId: null }]);
      const handle = repositories.stream.attach({
        projectId,
        threadId,
        turnId,
        // From the turn's first frame, not from its latest cursor: the part
        // backlog (tool cards, activity, task, gate) has no other read, so an
        // attach that skipped it would leave a reloaded transcript with prose
        // and no cards. The backlog is one turn's worth and bounded.
        lastEventId: null,
        onEvent(event) {
          if (!mounted.current) return;
          setStream((current) => applyChatStreamEvent(current, event));
          // Task 4 (founder ruling: no mid-run manual editing, ever): the
          // editor lock's own fold over the same frames. Kept beside the
          // transcript rather than derived from it because the release matrix
          // is not the transcript's — a terminal LEG frame releases the lock
          // while the delegating turn is still running.
          setAgentRunLock((current) =>
            applyAgentRunLockEvent(current, {
              threadId: event.threadId,
              turnId: event.turnId,
              type: event.type,
            }),
          );
          // Task 8 (scene live-streaming rung B): the same frames, through the
          // cursor algebra, so a streamed batch can never be applied twice or
          // applied over a hole. Scoped to the active thread exactly as the
          // refresh decision below is; the cursor itself then drops anything
          // naming a document other than its own.
          //
          // Task 9 reads the verdict back out: did the cursor prove, for THIS
          // frame, that the canvas already stands at the checkpoint's version?
          // Then the reload below is a remount that would change nothing a
          // user can see, and would interrupt a reveal to do it.
          let anchorReload: boolean | null = null;
          if (event.threadId === threadId) {
            // The TURN rides along (task 10 fix 1): `operations_total` counts
            // ONE RUN's ledger, so a cursor that did not know which run a frame
            // belonged to measured the next run's frames against the last
            // one's origin — and dropped a fresh run's first batch as stale.
            const sceneFrame: SceneStreamFrame | null =
              event.opBatch !== null
                ? {
                    type: "design.op_batch",
                    turnId: event.turnId,
                    batch: event.opBatch,
                  }
                : event.checkpoint !== null
                  ? {
                      type: "design.checkpoint",
                      turnId: event.turnId,
                      checkpoint: event.checkpoint,
                    }
                  : null;
            if (sceneFrame !== null) {
              const next = applySceneStreamFrame(
                sceneStreamRef.current,
                sceneFrame,
              );
              if (next !== sceneStreamRef.current) {
                sceneStreamRef.current = next;
                setSceneStream(next);
                const decided = next.actions[next.actions.length - 1]?.action;
                if (
                  decided?.action === "anchor" &&
                  sceneFrame.type === "design.checkpoint"
                ) {
                  // BOTH facts, composed where both exist. The cursor's
                  // `inSync` is computed from the frames and says nothing about
                  // whether the canvas managed to render them; a pump whose
                  // engine refused a batch — or a canvas with no engine at all
                  // — reports unhealthy here, and rung A's reload goes ahead.
                  const documentId = sceneFrame.checkpoint.documentId;
                  anchorReload = anchorReloadDecision({
                    cursorInSync: decided.inSync,
                    pumpClean:
                      documentId === null
                        ? null
                        : (sceneRevealHealthRef.current?.(documentId) ?? null),
                  }).reloadCanvas;
                }
              }
            }
          }
          if (planWrites.observe(event)) {
            if (event.part?.kind === "plan") setWrittenProjectDocumentId(event.part.planRef.objectId ?? undefined);
            setPlanWriteRevision((revision) => revision + 1);
          }
          // Genweb slice 3 (founder requirements 1 + 6): the gallery and any
          // open canvas refresh exactly when a durable design-leg transition
          // says the document moved — the frame IS the signal, so there is no
          // timer and nothing polls. `attach` is only ever called for the
          // thread this controller is showing, so that thread is the active one.
          const refresh = designRefreshForEvent(event, {
            activeThreadId: threadId,
          });
          if (event.type === DESIGN_CHECKPOINT_EVENT_TYPE) {
            // A mid-run checkpoint: canvas only (the decision says so), and
            // rate-limited, because a busy run commits several a minute and
            // remounting the editor on each would make it unreadable. The
            // trailing edge always fires, so the version the canvas settles on
            // is the last one that was committed, never a skipped one.
            //
            // Task 9 (rung B) adds the one exception the reveal earned: when
            // the cursor is in sync AND the pump is healthy, the streamed
            // canvas provably holds exactly the version this checkpoint
            // committed, so reloading it would replace the picture with an
            // identical one — and interrupt the reveal to do it. Anything else
            // — a gap, a dirty cursor, a refused apply, no engine, no pump —
            // reloads exactly as rung A shipped it, because the document is
            // always right and a streamed picture is only sometimes.
            // `anchorReload === null` means this frame produced no anchor at
            // all, which is rung A untouched.
            if (refresh.reloadCanvas && anchorReload !== false) {
              bumpCanvasForCheckpoint();
            }
          } else if (refresh.refetchFeed || refresh.reloadCanvas) {
            setDesignRefresh((current) => ({
              feedRevision: current.feedRevision + (refresh.refetchFeed ? 1 : 0),
              canvasRevision:
                current.canvasRevision + (refresh.reloadCanvas ? 1 : 0),
            }));
          }
          const streamedState = turnStateForStreamEvent(event.type);
          if (streamedState !== null) {
            // Turn events are already durable authority. Reflect running and
            // terminal transitions on this render cycle so Stop appears for
            // the real attempt and cannot linger after it finishes.
            const nextTurns = turnsRef.current.map((turn) =>
              turn.turnId === event.turnId
                ? { ...turn, state: streamedState }
                : turn,
            );
            turnsRef.current = nextTurns;
            setTurns(nextTurns);
            setTurnStateOverrides((current) => {
              const next = new Map(current);
              next.set(event.turnId, streamedState);
              return next;
            });
            if (
              streamedState === "running" ||
              (isTerminalTurnState(streamedState) &&
                streamedState !== "awaiting_input")
            ) {
              const running = selectTurnQueueState(nextTurns).threadBusy;
              setThreads((current) =>
                current.map((thread) =>
                  thread.id !== threadId ||
                  thread.status === "archived" ||
                  thread.status === "approval" ||
                  thread.status === "needs-input"
                    ? thread
                    : {
                        ...thread,
                        status: deriveThreadStatus({
                          archived: false,
                          // A held discovery keeps the thread running after
                          // its turns end, exactly as the server derives it.
                          running: running || thread.discovery !== null,
                        }),
                      },
                ),
              );
            }
            if (
              !isTerminalTurnState(streamedState) &&
              discoveryHeldRef.current
            ) {
              // A turn moving on a held thread is the wake turn, or a message
              // the hold just let go: either way the run may be gone, and only
              // the thread list says so. (Terminal frames re-read it below.)
              void loadThreads().catch(() => undefined);
            }
            if (isTerminalTurnState(streamedState)) {
              invalidateProjectCatalog();
              // Conversation naming (§4.7): the header reads the thread's title from THIS
              // controller's list, so reload it alongside the catalog, and let the bounded
              // catch-up poll know a turn just ended. `attach` is only ever called for the
              // thread this controller is showing, so every frame here is the active thread's.
              void loadThreads().catch(() => undefined);
              setTerminalTurnRevision((current) => current + 1);
            }
          }
        },
        onWarning(reason) {
          // Parser diagnostics belong in telemetry, never in the transcript.
          globalThis.console.warn("Dropped unreadable chat-stream frame", {
            projectId,
            threadId,
            turnId,
            reason,
          });
        },
        onError(failure) {
          attachments.current.delete(turnId);
          if (!mounted.current) return;
          if (isAccessError(failure)) {
            report(failure);
            return;
          }
          globalThis.console.error("Chat stream stopped; rehydrating", failure);
          setError("Connection interrupted; refreshing the conversation.");
          void loadConversation(threadId).catch(report);
        },
        onClosed(reason) {
          attachments.current.delete(turnId);
          if (!mounted.current) return;
          if (reason === "reset") {
            // The repository stopped before accepting any post-reset backlog.
            // Re-read durable state first, then the turns effect below resumes
            // only if this turn is still queued/running.
            attached.current.delete(turnId);
            resetReattach.current.add(turnId);
            void Promise.all([
              loadConversation(threadId),
              loadThreads(),
            ]).catch(report);
            return;
          }
          // The turn is finished as far as the stream is concerned; the durable
          // read is what proves it, so go and get it.
          void Promise.all([loadConversation(threadId), loadThreads()]).catch(
            report,
          );
        },
      });
      attachments.current.set(turnId, handle);
    },
    [
      bumpCanvasForCheckpoint,
      invalidateProjectCatalog,
      loadConversation,
      loadThreads,
      planWrites,
      projectId,
      repositories,
      report,
    ],
  );

  useEffect(() => {
    if (!activeThreadId) return;
    const candidates = new Map<string, ChatTurn>();
    for (const turn of effectiveTurns.slice(-REHYDRATED_TURNS)) {
      candidates.set(turn.turnId, turn);
    }
    for (const turn of effectiveTurns.filter(isTurnLive)) {
      candidates.set(turn.turnId, turn);
    }
    for (const turn of candidates.values()) {
      if (resetReattach.current.delete(turn.turnId)) {
        if (isTurnLive(turn)) attach(activeThreadId, turn.turnId);
        continue;
      }
      attach(activeThreadId, turn.turnId);
    }
  }, [activeThreadId, attach, effectiveTurns]);

  // --- writes ------------------------------------------------------------

  const submitMessage = useCallback(
    async (
      text: string,
      options: {
        contextRefs?: readonly TurnContextReference[];
        attachmentRefs?: readonly ChatAttachmentRef[];
        agentProfileId?: string | null;
      } = {},
    ) => {
      const trimmed = text.replace(/[\u200B\uFEFF]/g, "").trim();
      const contextRefs = options.contextRefs ?? [];
      const attachmentRefs = options.attachmentRefs ?? [];
      if (stopRequestRef.current || turnsRef.current.some((turn) => turn.stopRequest?.pending && turn.state !== "cancelled")) {
        return { status: "not_submitted" } as const;
      }
      if (
        (!trimmed && !contextRefs.length && !attachmentRefs.length) ||
        !activeThreadId
      ) {
        return { status: "not_submitted" } as const;
      }
      const agentProfileId = options.agentProfileId ?? null;
      const attempt = messageSubmissions.current.begin(
        activeThreadId,
        { message: trimmed, contextRefs, attachmentRefs, agentProfileId },
        () => newIdempotencyKey("turn"),
      );
      if (!attempt) return { status: "not_submitted" } as const;
      let accepted: Awaited<ReturnType<typeof repositories.turns.submit>>;
      try {
        accepted = await repositories.turns.submit({
          projectId,
          threadId: activeThreadId,
          submission: {
            kind: "message",
            message: trimmed,
            contextRefs,
            attachmentRefs,
            agentProfileId,
          },
          idempotencyKey: attempt.idempotencyKey,
        });
      } catch (failure) {
        report(failure);
        return { status: "failed" } as const;
      } finally {
        messageSubmissions.current.finish(attempt);
      }
      // The sidebar orders a project's chats by their last message, and this
      // one just changed: re-read it now rather than when the reply finishes.
      invalidateProjectCatalog();
      if (mounted.current) {
        setOptimistic((current) => [
          ...current.filter((item) => item.turnId !== accepted.turnId),
          {
            turnId: accepted.turnId,
            text: trimmed,
            requestedAt: accepted.requestedAt,
          },
        ]);
        attach(activeThreadId, accepted.turnId);
        try {
          await loadConversation(activeThreadId);
        } catch (failure) {
          // The durable accept already succeeded. Rehydration failure must not
          // make the composer retain and resubmit the accepted message.
          report(failure);
        }
      }
      return { status: "accepted", turnId: accepted.turnId } as const;
    },
    [
      activeThreadId, attach, invalidateProjectCatalog, loadConversation, projectId,
      repositories, report,
    ],
  );

  const answerGate = useCallback(
    async (card: GateCardModel, input: GateDecisionInput) => {
      if (!activeThreadId) return;
      let response;
      try {
        response = gateAnswerResponse(card, input);
      } catch (failure) {
        setError(failure instanceof Error ? failure.message : String(failure));
        return;
      }
      setError(null);
      setSubmitting(true);
      try {
        const accepted = await repositories.turns.submit({
          projectId,
          threadId: activeThreadId,
          submission: {
            kind: "gate_response",
            response,
          },
          idempotencyKey: newIdempotencyKey(
            `gate:${card.gateId}:${input.decision}`,
          ),
        });
        // An answer is a message too: it moves this chat up the sidebar.
        invalidateProjectCatalog();
        if (!mounted.current) return;
        setGateFailures((current) => {
          const next = new Map(current);
          next.delete(card.gateId);
          return next;
        });
        // The answer is durable the moment the turn was accepted; the reload
        // below reads it back rather than the client asserting it locally.
        // An answer the agent does not reply to (a CRM write card, R-11.6) runs
        // no turn: there is no stream to follow and nothing in flight — the
        // card follows its proposal instead.
        if (accepted.agentReply !== "none") attach(activeThreadId, accepted.turnId);
        await loadConversation(activeThreadId);
      } catch (failure) {
        const crmWrite = card.kind === CRM_WRITE_GATE_KIND;
        if (
          failure instanceof ClueChatApiError &&
          (failure.code.startsWith("GATE_") ||
            (crmWrite && failure.code.startsWith("CRM_")))
        ) {
          setGateFailures((current) => {
            const next = new Map(current);
            next.set(
              card.gateId,
              crmWrite
                ? { reason: crmWriteRefusal(failure.code), recovery: null }
                : gateAuthorityFailure(failure.code, failure.message),
            );
            return next;
          });
          // A write card stays put and says why; its gate is read again so a card another
          // member answered, or a newer card replaced, shows what really happened.
          if (crmWrite) void loadGates(activeThreadId).catch(report);
        } else {
          report(failure);
        }
      } finally {
        if (mounted.current) setSubmitting(false);
      }
    },
    [
      activeThreadId, attach, invalidateProjectCatalog, loadConversation, loadGates,
      projectId, repositories, report,
    ],
  );

  const recoverGate = useCallback(
    async (card: GateCardModel) => {
      if (!activeThreadId || card.recovery === null) return;
      setError(null);
      if (card.recovery.kind === "retry_gate_read") {
        setGateFailures((current) => {
          const next = new Map(current);
          next.delete(card.gateId);
          return next;
        });
        try {
          await loadGates(activeThreadId);
        } catch (failure) {
          report(failure);
        }
        return;
      }

      setSubmitting(true);
      try {
        const prompt =
          card.kind === "icp_confirmation"
            ? "Please create a fresh ideal customer profile proposal for me to review. The current proposal is no longer available."
            : "Please create a fresh proposal for me to review. The current one is no longer available.";
        await submitMessage(prompt);
      } finally {
        if (mounted.current) setSubmitting(false);
      }
    },
    [activeThreadId, loadGates, report, submitMessage],
  );

  const queue = useMemo(() => selectTurnQueueState(effectiveTurns), [effectiveTurns]);
  const stopPending = localStopTarget !== null || effectiveTurns.some(
    (turn) => turn.stopRequest?.pending && turn.state !== "cancelled",
  );

  useEffect(() => {
    if (!activeThreadId || (!stopPending && !queueControl.paused)) return;
    const timer = window.setInterval(() => {
      void loadConversation(activeThreadId).catch(report);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [activeThreadId, loadConversation, queueControl.paused, report, stopPending]);

  const stopActiveTurn = useCallback(async () => {
    if (!activeThreadId || !queue.runningTurn || stopRequestRef.current || stopPending) return;
    const turnId = queue.runningTurn.turnId;
    stopRequestRef.current = { turnId, settled: false };
    setLocalStopTarget(turnId);
    try {
      await repositories.turns.stop({ projectId, threadId: activeThreadId, turnId });
    } catch (failure) {
      report(failure);
    } finally {
      if (stopRequestRef.current?.turnId === turnId) stopRequestRef.current.settled = true;
      // A transport failure is not acknowledgement. A fresh canonical read resolves it.
      await loadConversation(activeThreadId).catch(report);
    }
  }, [activeThreadId, loadConversation, projectId, queue.runningTurn, repositories, report, stopPending]);

  const resumeQueuedTurns = useCallback(async () => {
    const holdControlId = queueControl.holdControlId;
    if (!activeThreadId || !holdControlId || stopPending || resumeRequestRef.current) return;
    resumeRequestRef.current = true;
    setResumingQueue(true);
    try {
      const receipt = await repositories.turns.resume({ projectId, threadId: activeThreadId, holdControlId });
      if (receipt.dispatchedTurnId) attach(activeThreadId, receipt.dispatchedTurnId);
      await loadConversation(activeThreadId);
    } catch (failure) {
      report(failure);
    } finally {
      resumeRequestRef.current = false;
      if (mounted.current) setResumingQueue(false);
    }
  }, [activeThreadId, attach, loadConversation, projectId, queueControl.holdControlId, repositories, report, stopPending]);

  const retryTurn = useCallback(
    async (turnId: string) => {
      if (!activeThreadId) return;
      try {
        const accepted = await repositories.turns.retry({
          projectId,
          threadId: activeThreadId,
          turnId,
        });
        attach(activeThreadId, accepted.turnId);
        await loadConversation(activeThreadId);
      } catch (failure) {
        report(failure);
      }
    },
    [activeThreadId, attach, loadConversation, projectId, repositories, report],
  );

  const createThread = useCallback(
    async (title?: string) => {
      try {
        const thread = await repositories.threads.create({ projectId, title });
        // Single-mechanism rule (Phase R): navigating to the new thread's
        // path flips the remount key; the fresh mount reloads the thread
        // list and the (empty) conversation.
        router.push(threadRouteHref(projectId, thread.id, routeQuery));
        return thread;
      } catch (failure) {
        report(failure);
        return null;
      }
    },
    [projectId, repositories, report, routeQuery, router],
  );

  const renameThread = useCallback(
    async (threadId: string, title: string) => {
      try {
        const saved = await repositories.threads.update({
          projectId, threadId, title,
        });
        if (mounted.current) {
          setThreads((current) => current.map((thread) =>
            // Only the list read derives the discovery; a rename's echo sends
            // none, and must not release a thread the run still holds.
            thread.id === saved.id ? { ...saved, discovery: thread.discovery } : thread,
          ));
        }
        invalidateProjectCatalog();
      } catch (failure) {
        report(failure);
      }
    },
    [invalidateProjectCatalog, projectId, repositories, report],
  );

  const setThreadPinned = useCallback(
    async (threadId: string, pinned: boolean) => {
      try {
        await repositories.threads.update({ projectId, threadId, pinned });
        await loadThreads();
      } catch (failure) {
        report(failure);
      }
    },
    [loadThreads, projectId, repositories, report],
  );

  const archiveThread = useCallback(
    async (threadId: string) => {
      try {
        await repositories.threads.archive({ projectId, threadId });
        await loadThreads();
      } catch (failure) {
        report(failure);
      }
    },
    [loadThreads, projectId, repositories, report],
  );

  // --- derived -----------------------------------------------------------

  const transcript = useMemo(
    () => composeTranscript({ messages, turns: effectiveTurns, stream, optimistic }),
    [effectiveTurns, messages, optimistic, stream],
  );

  const gatesById = useMemo(() => {
    const map = new Map<string, ChatGate>();
    for (const gate of gateRead.gates) map.set(gate.gateId, gate);
    return map;
  }, [gateRead]);

  const crmWritesFinished = useMemo(
    () => turns.filter((turn) => turn.derivation === CRM_WRITES_FINISHED).length,
    [turns],
  );

  const gateFor = useCallback(
    (part: ChatGatePart) => {
      const gateId = agentGateIdFromPart(part);
      return gateCardModel({
        gate: gateId ? (gatesById.get(gateId) ?? null) : null,
        part,
        currentUserId: viewer.userId,
        currentWorkspaceId: viewer.workspaceId,
        expectedProjectId: projectId,
        expectedThreadId: activeThreadId ?? "",
        gateReadAvailable: gateRead.available,
        gateReadLoading,
        authorityFailure:
          gateId === null ? null : (gateFailures.get(gateId) ?? null),
      });
    },
    [
      activeThreadId,
      gateFailures,
      gateRead.available,
      gateReadLoading,
      gatesById,
      projectId,
      viewer.userId,
      viewer.workspaceId,
    ],
  );

  const gateAnswersByTurn = useMemo(() => {
    const map = new Map<string, GateAnswerDisplay>();
    for (const gate of gateRead.gates) {
      if (gate.answer === null) continue;
      const display = gateAnswerDisplay(gate);
      if (display !== null) map.set(gate.answer.turnId, display);
    }
    return map;
  }, [gateRead.gates]);

  const gateAnswerForTurn = useCallback(
    (turnId: string) => gateAnswersByTurn.get(turnId) ?? null,
    [gateAnswersByTurn],
  );

  const activeThread = useMemo(
    () => threads.find((thread) => thread.id === activeThreadId) ?? null,
    [activeThreadId, threads],
  );

  // --- account discovery -------------------------------------------------

  const activeDiscovery = activeThread?.discovery ?? null;
  const discoveryRunId = activeDiscovery?.runId ?? null;
  useEffect(() => {
    discoveryHeldRef.current = discoveryRunId !== null;
  }, [discoveryRunId]);

  // A run released with nobody to wake (or whose wake could not be queued)
  // writes no turn frame, so the thread stream cannot announce the end of the
  // hold. While a discovery holds the thread, re-read the thread list slowly as
  // the safety net (final review of F2, finding #2).
  useEffect(() => {
    if (!activeThreadId || discoveryRunId === null) return;
    const timer = globalThis.setInterval(() => {
      void loadThreads().catch(() => undefined);
    }, DISCOVERY_HOLD_SAFETY_REREAD_MS);
    return () => globalThis.clearInterval(timer);
  }, [activeThreadId, discoveryRunId, loadThreads]);

  // --- the thread stream (CRM trial 1, F2) -------------------------------
  //
  // Each turn has its own stream, but only a turn this chat knows about gets
  // attached. The thread stream tells it about the others — a wake turn the
  // server queued (a discovery that finished, a CRM that connected), a message
  // sent from another tab, a teammate — by sending every turn's lifecycle
  // frames. A frame for a turn the chat has not seen re-reads the thread once,
  // and the turns effect above attaches it. Held only while the tab is
  // visible; a hidden tab closes it and reopens it from its cursor.

  const pageVisible = usePageVisible();
  const threadCursor = useRef(new Map<string, number>());
  const rereadForTurn = useRef(new Set<string>());
  const threadReaders = useRef({ loadThreads, loadConversation, report });
  useEffect(() => {
    threadReaders.current = { loadThreads, loadConversation, report };
  }, [loadConversation, loadThreads, report]);

  useEffect(() => {
    if (!activeThreadId || !pageVisible) return;
    const threadId = activeThreadId;
    let open = true;
    const reread = () => {
      const readers = threadReaders.current;
      void Promise.all([readers.loadThreads(), readers.loadConversation(threadId)]).catch(
        readers.report,
      );
    };
    const handle = repositories.threadStream.open({
      projectId,
      threadId,
      // A first open starts from the page's last read of the thread, not from the thread's
      // tail: a tab loaded hidden (or in the background) opens only when shown, and a turn that
      // began in between would otherwise be skipped.
      lastEventId: threadCursor.current.get(threadId) ?? newestTurnCursor(turnsRef.current),
      onCursor(eventId) {
        if (open) threadCursor.current.set(threadId, eventId);
      },
      onTurnEvent(event) {
        if (!open || !mounted.current) return;
        const known =
          attachments.current.has(event.turnId) ||
          attached.current.has(event.turnId) ||
          rereadForTurn.current.has(event.turnId);
        if (!known) {
          rereadForTurn.current.add(event.turnId);
          reread();
          return;
        }
        if (TERMINAL_TURN_EVENTS.has(event.type) && discoveryHeldRef.current) {
          // The hold may have ended with this turn; only the thread list says so.
          void threadReaders.current.loadThreads().catch(() => undefined);
        }
      },
      onReset() {
        if (!open || !mounted.current) return;
        reread();
      },
      onError(failure) {
        if (!open || !mounted.current) return;
        if (isAccessError(failure)) {
          threadReaders.current.report(failure);
          return;
        }
        globalThis.console.warn("The thread stream stopped", { projectId, threadId, failure });
      },
    });
    return () => {
      open = false;
      handle.close();
    };
  }, [activeThreadId, pageVisible, projectId, repositories]);

  const stopDiscovery = useCallback(async () => {
    if (
      !activeDiscovery ||
      !activeDiscovery.stoppable ||
      discoveryStopRef.current === activeDiscovery.runId
    ) {
      return;
    }
    const runId = activeDiscovery.runId;
    discoveryStopRef.current = runId;
    try {
      await repositories.discoveries.stop({ projectId, runId });
    } catch (failure) {
      // Not acknowledged, so a second press may try again.
      discoveryStopRef.current = null;
      report(failure);
    } finally {
      await loadThreads().catch(report);
    }
  }, [activeDiscovery, loadThreads, projectId, repositories, report]);

  // Conversation naming (§4.7): a name that lands after the terminal event needs a
  // second look. Bounded, and only while a placeholder is still on screen.
  const namingPending =
    (activeThread !== null && activeThread.title === null) ||
    projectTitle === "Untitled project";
  useNamingCatchUp({
    namingPending,
    terminalRevision: terminalTurnRevision,
    tick: () => {
      invalidateProjectCatalog();
      void loadThreads().catch(() => undefined);
    },
  });

  // Task 4 fix round 1: the leg fact the editor lock consults. The stream wins
  // once it has observed anything; the durable read answers the cold-load
  // window it cannot reach, and is the only source of "a design run is in
  // flight right now".
  const designLeg = useMemo(
    () =>
      designLegFactFor({
        leg: {
          known: stream.designLeg.known,
          open: stream.designLeg.open,
        },
        wire: activeThread?.designLeg ?? null,
      }),
    [activeThread, stream.designLeg.known, stream.designLeg.open],
  );

  return {
    threads,
    activeThread,
    activeThreadId,
    transcript,
    access,
    route,
    loading,
    error,
    threadBusy: queue.threadBusy,
    runningTurn: queue.runningTurn,
    queuedTurns: queue.queuedTurns,
    discoveryRunId,
    stopDiscovery,
    designRefresh,
    planWriteRevision,
    writtenProjectDocumentId,
    designLegOpen: stream.designLeg.open,
    designLeg,
    agentRunLock,
    sceneStream,
    publishSceneRevealHealth,
    seedSceneStream,
    submitting,
    hasOlderMessages: olderCursor !== null,
    loadOlderMessages,
    gateFor,
    gateAnswerForTurn,
    crmWritesFinished,
    submitMessage,
    answerGate,
    recoverGate,
    stopActiveTurn,
    stopPending,
    queueControl,
    resumingQueue,
    resumeQueuedTurns,
    retryTurn,
    selectThread(threadId) {
      if (threadId === activeThreadId) return;
      if (!threads.some((thread) => thread.id === threadId)) {
        setRoute({
          code: "THREAD_NOT_FOUND",
          message: "This conversation is not available in this project.",
        });
        return;
      }
      // Single-mechanism rule (Phase R): a user-initiated switch is a
      // navigation with history. The path push flips the workspace remount
      // key, which tears this controller down (the unmount cleanup closes
      // every stream attachment) and reseeds it from the new route. No
      // internal teardown here — doing both would reload the thread twice.
      router.push(threadRouteHref(projectId, threadId, routeQuery));
    },
    createThread,
    renameThread,
    setThreadPinned,
    archiveThread,
    threadStatus(threadId) {
      return threads.find((thread) => thread.id === threadId)?.status ?? "idle";
    },
    threadLabelFor: threadLabel,
    terminalTurnRevision,
  };
}
