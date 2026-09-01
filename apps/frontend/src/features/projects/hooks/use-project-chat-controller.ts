"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  NO_AGENT_RUN,
  applyAgentRunLockEvent,
  type AgentRunLockState,
} from "@/features/chat-shell/model/agent-run-lock";
import {
  ClueChatApiError,
  isAccessError,
  newIdempotencyKey,
} from "../data/chat-api";
import type { ChatStreamHandle } from "../data/chat-stream.repository";
import type { ChatGateRead } from "../data/chat-gates.repository";
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
  type OptimisticTurn,
  type TranscriptMessage,
  type TranscriptState,
} from "../model/chat-transcript";
import {
  DESIGN_CHECKPOINT_CANVAS_RELOAD_MIN_INTERVAL_MS,
  throttleTrailing,
} from "../model/design-checkpoint-throttle";
import {
  DESIGN_CHECKPOINT_EVENT_TYPE,
  designRefreshForEvent,
} from "../model/design-leg";
import {
  deriveThreadStatus,
  threadLabel,
  threadRouteHref,
  resolveProjectThreadRoute,
  type ChatThread,
  type ThreadStatus,
} from "../model/chat-thread";
import { useProjectCatalogInvalidation } from "../model/project-catalog-invalidation";
import {
  applyTurnStateOverrides,
  isTerminalTurnState,
  isTurnLive,
  MessageSubmissionGuard,
  reconcileTurnStateOverrides,
  selectTurnQueueState,
  turnStateForStreamEvent,
  type ChatTurn,
  type TurnContextReference,
  type TurnState,
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

/** How many recent turns are re-projected on cold load. */
const REHYDRATED_TURNS = 3;

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
   * Two monotone counters the design surfaces watch (genweb slice 3, B5).
   *
   * Each bumps when a **durable design-leg frame** for this thread says the
   * corresponding thing changed — never on a timer, and never optimistically.
   * The controller only counts; the decision is
   * `model/design-leg.designRefreshForEvent`, and the transport (a router
   * refresh, a canvas reload nonce) belongs to whoever renders them.
   */
  designRefresh: DesignRefreshCounters;
  /** True only when the current stream has observed an open design leg. */
  designLegOpen: boolean;
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
  submitting: boolean;
  gateFor(part: ChatGatePart): GateCardModel | null;
  gateAnswerForTurn(turnId: string): GateAnswerDisplay | null;
  submitMessage(
    text: string,
    options?: {
      contextRefs?: readonly TurnContextReference[];
      agentProfileId?: string | null;
    },
  ): Promise<ChatSubmissionResult>;
  answerGate(
    card: GateCardModel,
    input: GateDecisionInput,
  ): Promise<void>;
  recoverGate(card: GateCardModel): Promise<void>;
  stopActiveTurn(): Promise<void>;
  retryTurn(turnId: string): Promise<void>;
  selectThread(threadId: string): void;
  createThread(title?: string): Promise<ChatThread | null>;
  renameThread(threadId: string, title: string): Promise<void>;
  setThreadPinned(threadId: string, pinned: boolean): Promise<void>;
  archiveThread(threadId: string): Promise<void>;
  threadStatus(threadId: string): ThreadStatus;
  threadLabelFor(thread: ChatThread): string;
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
}: {
  projectId: string;
  initialThreadId?: string;
}): ProjectChatController {
  const router = useRouter();
  const routeQuery = useSearchParams().toString();
  const repositories = useChatRepositories();
  const viewer = useChatViewerIdentity();
  const { invalidate: invalidateProjectCatalog } =
    useProjectCatalogInvalidation();
  const [threads, setThreads] = useState<ChatThread[]>([]);
  // Seeded once from the route and never mutated: every thread change is a
  // navigation, and the workspace remount key reseeds a fresh controller
  // (single-mechanism rule, Phase R).
  const [activeThreadId] = useState<string | null>(initialThreadId ?? null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
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
  const [designRefresh, setDesignRefresh] = useState<DesignRefreshCounters>({
    feedRevision: 0,
    canvasRevision: 0,
  });
  // Task 4: the editor lock's observations. The reducer returns the SAME object
  // for every frame it does not act on (checkpoints, deltas, part frames), so a
  // busy stream costs no extra renders here.
  const [agentRunLock, setAgentRunLock] =
    useState<AgentRunLockState>(NO_AGENT_RUN);
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

  const loadThreads = useCallback(async () => {
    const page = await repositories.threads.list({ projectId });
    if (!mounted.current) return page.threads;
    setThreads(page.threads);
    return page.threads;
  }, [projectId, repositories]);

  const loadGates = useCallback(
    async (threadId: string) => {
      if (mounted.current) setGateReadLoading(true);
      try {
        const read = await repositories.gates.list({ projectId, threadId });
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
    async (threadId: string) => {
      const [messagePage, turnPage] = await Promise.all([
        repositories.messages.list({ projectId, threadId, includeBodies: true }),
        repositories.turns.list({ projectId, threadId }),
        loadGates(threadId),
      ]);
      if (!mounted.current) return;
      setMessages(messagePage.messages);
      turnsRef.current = turnPage.turns;
      setTurns(turnPage.turns);
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
    [loadGates, projectId, repositories],
  );

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const available = await loadThreads();
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
        await loadConversation(resolution.thread.id);
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
    report,
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
            if (refresh.reloadCanvas) bumpCanvasForCheckpoint();
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
                          running,
                        }),
                      },
                ),
              );
            }
            if (isTerminalTurnState(streamedState)) {
              invalidateProjectCatalog();
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
        agentProfileId?: string | null;
      } = {},
    ) => {
      const trimmed = text.trim();
      const contextRefs = options.contextRefs ?? [];
      const hasDesignReferences = contextRefs.some(
        (reference) => reference.objectType === "design_asset",
      );
      if ((!trimmed && !hasDesignReferences) || !activeThreadId) {
        return { status: "not_submitted" } as const;
      }
      const agentProfileId = options.agentProfileId ?? null;
      const attempt = messageSubmissions.current.begin(
        activeThreadId,
        { message: trimmed, contextRefs, agentProfileId },
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
    [activeThreadId, attach, loadConversation, projectId, repositories, report],
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
        if (!mounted.current) return;
        setGateFailures((current) => {
          const next = new Map(current);
          next.delete(card.gateId);
          return next;
        });
        // The answer is durable the moment the turn was accepted; the reload
        // below reads it back rather than the client asserting it locally.
        attach(activeThreadId, accepted.turnId);
        await loadConversation(activeThreadId);
      } catch (failure) {
        if (
          failure instanceof ClueChatApiError &&
          failure.code.startsWith("GATE_")
        ) {
          setGateFailures((current) => {
            const next = new Map(current);
            next.set(
              card.gateId,
              gateAuthorityFailure(failure.code, failure.message),
            );
            return next;
          });
        } else {
          report(failure);
        }
      } finally {
        if (mounted.current) setSubmitting(false);
      }
    },
    [activeThreadId, attach, loadConversation, projectId, repositories, report],
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

  const stopActiveTurn = useCallback(async () => {
    if (!activeThreadId || !queue.runningTurn) return;
    try {
      await repositories.turns.stop({
        projectId,
        threadId: activeThreadId,
        turnId: queue.runningTurn.turnId,
      });
      await loadConversation(activeThreadId);
    } catch (failure) {
      report(failure);
    }
  }, [
    activeThreadId,
    loadConversation,
    projectId,
    queue.runningTurn,
    repositories,
    report,
  ]);

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
        await repositories.threads.update({ projectId, threadId, title });
        await loadThreads();
      } catch (failure) {
        report(failure);
      }
    },
    [loadThreads, projectId, repositories, report],
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
    designRefresh,
    designLegOpen: stream.designLeg.open,
    agentRunLock,
    submitting,
    gateFor,
    gateAnswerForTurn,
    submitMessage,
    answerGate,
    recoverGate,
    stopActiveTurn,
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
  };
}
