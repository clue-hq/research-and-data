"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ClueChatApiError,
  isAccessError,
  newIdempotencyKey,
} from "../data/chat-api";
import type { ChatStreamHandle } from "../data/chat-stream.repository";
import {
  answerFixtureGate,
  type ChatGateRead,
} from "../data/chat-gates.repository";
import { useChatRepositories } from "../data/projects-transport";
import type { ChatMessage } from "../model/chat-message";
import type { ChatGatePart, GateDecision } from "../model/chat-parts";
import { gateCardModel, type ChatGate, type GateCardModel } from "../model/chat-gate";
import {
  applyChatStreamEvent,
  composeTranscript,
  emptyTranscriptState,
  turnsAwaitingRehydration,
  type OptimisticTurn,
  type TranscriptMessage,
  type TranscriptState,
} from "../model/chat-transcript";
import {
  threadLabel,
  type ChatThread,
  type ThreadStatus,
} from "../model/chat-thread";
import { isTurnLive, type ChatTurn } from "../model/chat-turn";

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

export interface ProjectChatController {
  threads: readonly ChatThread[];
  activeThread: ChatThread | null;
  activeThreadId: string | null;
  transcript: readonly TranscriptMessage[];
  /** Non-null when the workspace/session refuses this conversation. */
  access: ChatAccessState | null;
  loading: boolean;
  /** A stream or repository failure that did not change any durable outcome. */
  error: string | null;
  warnings: readonly string[];
  /** True while a same-thread turn is queued or executing. */
  busy: boolean;
  /** The turn a Stop control acts on, if any. */
  activeTurnId: string | null;
  submitting: boolean;
  gateFor(part: ChatGatePart): GateCardModel | null;
  submitMessage(text: string): Promise<void>;
  answerGate(card: GateCardModel, decision: GateDecision): Promise<void>;
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

export function useProjectChatController({
  projectId,
  initialThreadId,
}: {
  projectId: string;
  initialThreadId?: string;
}): ProjectChatController {
  const repositories = useChatRepositories();
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(
    initialThreadId ?? null,
  );
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [gateRead, setGateRead] = useState<ChatGateRead>({
    available: false,
    gates: [],
    reason: null,
  });
  const [stream, setStream] = useState<TranscriptState>(emptyTranscriptState);
  const [optimistic, setOptimistic] = useState<OptimisticTurn[]>([]);
  const [access, setAccess] = useState<ChatAccessState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  const attachments = useRef(new Map<string, ChatStreamHandle>());
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
      setError(
        failure.requestId
          ? `${failure.message} (request ${failure.requestId})`
          : failure.message,
      );
      return;
    }
    setError(failure instanceof Error ? failure.message : String(failure));
  }, []);

  // --- reads ------------------------------------------------------------

  const loadThreads = useCallback(async () => {
    const page = await repositories.threads.list({ projectId });
    if (!mounted.current) return page.threads;
    setThreads(page.threads);
    return page.threads;
  }, [projectId, repositories]);

  const loadConversation = useCallback(
    async (threadId: string) => {
      const [messagePage, turnPage, gates] = await Promise.all([
        repositories.messages.list({ projectId, threadId, includeBodies: true }),
        repositories.turns.list({ projectId, threadId }),
        repositories.gates.list({ projectId, threadId }),
      ]);
      if (!mounted.current) return;
      setMessages(messagePage.messages);
      setTurns(turnPage.turns);
      setGateRead(gates);
      // A durable message for a turn means the optimistic stand-in has done its
      // job; keeping it would double the user's own sentence.
      const durableTurns = new Set(messagePage.messages.map((m) => m.turnId));
      setOptimistic((current) =>
        current.filter((item) => !durableTurns.has(item.turnId)),
      );
      return turnPage.turns;
    },
    [projectId, repositories],
  );

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const available = await loadThreads();
        if (cancelled || !mounted.current) return;
        const chosen =
          available.find((thread) => thread.id === activeThreadId) ??
          available.find((thread) => thread.status !== "archived") ??
          available[0] ??
          null;
        if (chosen && chosen.id !== activeThreadId) setActiveThreadId(chosen.id);
        if (chosen) await loadConversation(chosen.id);
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
  }, [activeThreadId, loadConversation, loadThreads, report]);

  // --- live attachment ---------------------------------------------------

  const attach = useCallback(
    (threadId: string, turnId: string) => {
      if (attachments.current.has(turnId)) return;
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
        },
        onWarning(reason) {
          if (!mounted.current) return;
          setStream((current) =>
            current.warnings.includes(reason)
              ? current
              : { ...current, warnings: [...current.warnings, reason] },
          );
        },
        onError(failure) {
          attachments.current.delete(turnId);
          if (mounted.current) report(failure);
        },
        onClosed() {
          attachments.current.delete(turnId);
          if (!mounted.current) return;
          // The turn is finished as far as the stream is concerned; the durable
          // read is what proves it, so go and get it.
          void loadConversation(threadId).catch(report);
        },
      });
      attachments.current.set(turnId, handle);
    },
    [loadConversation, projectId, repositories, report],
  );

  useEffect(() => {
    if (!activeThreadId) return;
    const live = turns.filter(isTurnLive).map((turn) => turn.turnId);
    const recent = turns.slice(-REHYDRATED_TURNS).map((turn) => turn.turnId);
    for (const turnId of new Set([...recent, ...live])) {
      attach(activeThreadId, turnId);
    }
  }, [activeThreadId, attach, turns]);

  // A projection that disowned itself (`stream.reset`, or a replayed turn that
  // streamed nothing) is repaired from the durable message — never rewritten.
  const rehydrating = useRef<string>("");
  useEffect(() => {
    if (!activeThreadId) return;
    const pending = turnsAwaitingRehydration(stream).join(",");
    if (!pending || pending === rehydrating.current) return;
    rehydrating.current = pending;
    void loadConversation(activeThreadId).catch(report);
  }, [activeThreadId, loadConversation, report, stream]);

  // --- writes ------------------------------------------------------------

  const submitMessage = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || !activeThreadId) return;
      setSubmitting(true);
      const idempotencyKey = newIdempotencyKey("turn");
      try {
        const accepted = await repositories.turns.submit({
          projectId,
          threadId: activeThreadId,
          submission: { kind: "message", message: trimmed },
          idempotencyKey,
        });
        if (!mounted.current) return;
        setOptimistic((current) => [
          ...current.filter((item) => item.turnId !== accepted.turnId),
          {
            turnId: accepted.turnId,
            text: trimmed,
            requestedAt: accepted.requestedAt,
          },
        ]);
        attach(activeThreadId, accepted.turnId);
        await loadConversation(activeThreadId);
      } catch (failure) {
        report(failure);
      } finally {
        if (mounted.current) setSubmitting(false);
      }
    },
    [activeThreadId, attach, loadConversation, projectId, repositories, report],
  );

  const answerGate = useCallback(
    async (card: GateCardModel, decision: GateDecision) => {
      if (!activeThreadId) return;
      if (card.expectedSubjectSha256 === null || card.amountCents === null) {
        // Structurally unanswerable: the two `expected*` fields are what make
        // "approve" mean the card that was on the screen, and the server
        // refuses anything else. Say so rather than sending a guess.
        setError(
          card.unavailableReason ??
            "this gate cannot be answered without its subject digest and maximum spend",
        );
        return;
      }
      setSubmitting(true);
      try {
        const accepted = await repositories.turns.submit({
          projectId,
          threadId: activeThreadId,
          submission: {
            kind: "gate_response",
            response: {
              gateId: card.gateId,
              decision,
              expectedSubjectSha256: card.expectedSubjectSha256,
              expectedEstimatedCostCents: card.amountCents,
            },
          },
          idempotencyKey: newIdempotencyKey(`gate:${card.gateId}:${decision}`),
        });
        if (!mounted.current) return;
        setGateRead((current) =>
          answerFixtureGate(current, {
            gateId: card.gateId,
            decision,
            turnId: accepted.turnId,
          }),
        );
        attach(activeThreadId, accepted.turnId);
        await loadConversation(activeThreadId);
      } catch (failure) {
        report(failure);
      } finally {
        if (mounted.current) setSubmitting(false);
      }
    },
    [activeThreadId, attach, loadConversation, projectId, repositories, report],
  );

  const activeTurn = useMemo(
    () => turns.filter(isTurnLive).at(-1) ?? null,
    [turns],
  );

  const stopActiveTurn = useCallback(async () => {
    if (!activeThreadId || !activeTurn) return;
    try {
      await repositories.turns.stop({
        projectId,
        threadId: activeThreadId,
        turnId: activeTurn.turnId,
      });
      await loadConversation(activeThreadId);
    } catch (failure) {
      report(failure);
    }
  }, [
    activeThreadId,
    activeTurn,
    loadConversation,
    projectId,
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
        await loadThreads();
        setActiveThreadId(thread.id);
        return thread;
      } catch (failure) {
        report(failure);
        return null;
      }
    },
    [loadThreads, projectId, repositories, report],
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
    () => composeTranscript({ messages, turns, stream, optimistic }),
    [messages, optimistic, stream, turns],
  );

  const gatesById = useMemo(() => {
    const map = new Map<string, ChatGate>();
    for (const gate of gateRead.gates) map.set(gate.gateId, gate);
    return map;
  }, [gateRead]);

  const gateFor = useCallback(
    (part: ChatGatePart) => {
      const gateId = part.gateRef.objectId;
      return gateCardModel({
        gate: gateId ? (gatesById.get(gateId) ?? null) : null,
        part,
        unavailableReason: gateRead.reason,
      });
    },
    [gateRead.reason, gatesById],
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
    loading,
    error,
    warnings: stream.warnings,
    busy: activeTurn !== null,
    activeTurnId: activeTurn?.turnId ?? null,
    submitting,
    gateFor,
    submitMessage,
    answerGate,
    stopActiveTurn,
    retryTurn,
    selectThread(threadId) {
      if (threadId === activeThreadId) return;
      for (const handle of attachments.current.values()) handle.close();
      attachments.current.clear();
      // Switching threads is a real switch: the previous conversation's
      // projections do not belong to the next one.
      setStream(emptyTranscriptState());
      setMessages([]);
      setTurns([]);
      setOptimistic([]);
      setError(null);
      setLoading(true);
      setActiveThreadId(threadId);
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
