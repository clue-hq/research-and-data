import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import type { AgentChatMessage, QueuedAgentMessage } from "@/components/AgentChatPanel";
import type { EditorHistoryFrame } from "@/hooks/useEditHistory";
import type {
  AgentRunEvent,
  EditorAgentResult,
  EditorAgentRunner
} from "@/engine/agentRunner";
import type {
  BrandCompatibilityReport,
  Diagnostic,
  ExportProfile,
  NodeId,
  Operation,
  PageId,
  Scene
} from "@/engine/contracts";
import { defaultEditorExportProfile, type EditorExportResult } from "@/engine/exportRunner";
import type { EditorPreflightResult } from "@/engine/preflightRunner";
import { firstPageId } from "@/engine/sceneQueries";
import { freezeLayoutEdit } from "@/engine/structuredEdits";
import type { OptimisticEnginePort } from "@/engine/wasmEngine";

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

export interface UseAgentTurnDeps {
  agentRunner: EditorAgentRunner;
  engineRef: { current: OptimisticEnginePort | null };
  scene: Scene;
  activeDocumentId: string | null;
  activePageId: PageId | null;
  selectedNodeId: NodeId | null;
  /** 2c: the chipped edit targets sent with each turn. */
  targetNodeIds: NodeId[];
  /** 2e: the document's standing instructions sent with each turn. */
  agentInstructions: string | null;
  /** Advanced per-document opt-out from handoff-absolute: when true the
   * accept-time freeze is skipped, so the turn's Stack containers stay live. */
  layoutManagedEditing: boolean;
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
    agentInstructions,
    layoutManagedEditing,
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

  // Merge one streamed run event into the checklist state. Replay (EventSource
  // reconnect, or resume-on-mount) re-sends events, so dedupe by seq; the
  // run_started frame carries the run id we persist for reload resume.
  const handleRunEvent = (event: AgentRunEvent) => {
    if (typeof event.data.run_id === "string") {
      writeActiveRun(event.data.run_id);
    }
    setRunEvents((events) => {
      if (events.some((existing) => existing.seq === event.seq && existing.type === event.type)) {
        return events;
      }
      return [...events, event].sort((left, right) => left.seq - right.seq);
    });
  };

  // Turn-settled bookkeeping, shared by the live send path and the reload
  // resume path: surface the proposal/draft, post the chat messages, and (for
  // a proposed turn) drop into the reviewable preview. `seedScene` is the scene
  // the turn was seeded from — used only to detect the unchanged-seed case.
  const handleTurnResult = (result: EditorAgentResult, seedScene: Scene) => {
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
      showAgentDraftScene(result);
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

  const sendAgentPrompt = async (prompt: string) => {
    const trimmedPrompt = prompt.trim();
    if (!trimmedPrompt || isAgentRunning) {
      return;
    }
    if (agentPreview) {
      setDiagnostics([pendingAgentReviewDiagnostic()]);
      return;
    }

    const seedScene = scene;
    setAgentDraft("");
    setAgentProposal(null);
    setRunEvents([]);
    setIsAgentRunning(true);
    setAgentMessages((messages) => [
      ...messages,
      {
        id: uniqueChatMessageId("user"),
        role: "user",
        content: trimmedPrompt
      }
    ]);

    try {
      const result = await agentRunner({
        prompt: trimmedPrompt,
        scene,
        documentId: activeDocumentId ?? undefined,
        activePageId,
        targetNodeIds,
        agentInstructions,
        diagnostics,
        onEvent: handleRunEvent
      });
      handleTurnResult(result, seedScene);
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
    setQueuedAgentMessages((queue) => [
      ...queue,
      { id: uniqueChatMessageId("user"), content: trimmed }
    ]);
  };

  const removeQueuedAgentMessage = (id: string) => {
    setQueuedAgentMessages((queue) => queue.filter((message) => message.id !== id));
  };

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
    void sendAgentPrompt(next.content);
    // sendAgentPrompt is re-created per render; keying the effect on it would
    // drain the whole queue in one burst instead of one per idle transition.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAgentRunning, agentPreview, queuedAgentMessages]);

  // Resume-on-mount: an async turn keeps running server-side across a tab
  // reload. If one was in flight, rejoin its SSE stream — replaying the
  // checklist and then either streaming live ticks or settling immediately if
  // it finished while we were away. Refs keep the mount-only effect calling
  // the latest handlers (which close over the current scene) without re-firing.
  const handleRunEventRef = useRef(handleRunEvent);
  handleRunEventRef.current = handleRunEvent;
  const handleTurnResultRef = useRef(handleTurnResult);
  handleTurnResultRef.current = handleTurnResult;
  const handleTurnErrorRef = useRef(handleTurnError);
  handleTurnErrorRef.current = handleTurnError;
  const sceneRef = useRef(scene);
  sceneRef.current = scene;

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
    setIsAgentRunning(true);
    void resumeRun(runId, (event) => handleRunEventRef.current(event))
      .then((result) => handleTurnResultRef.current(result, sceneRef.current))
      .catch((error) => handleTurnErrorRef.current(error))
      .finally(() => {
        setIsAgentRunning(false);
        clearActiveRun();
      });
    // Mount-only: a reload rejoins exactly one in-flight run.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const showAgentDraftScene = (result: EditorAgentResult) => {
    if (!result.draft_scene) {
      return;
    }
    const draftScene = result.draft_scene;
    const draftPageId = agentDraftPageId(scene, draftScene, activePageId);
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
        scene,
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
    if (!layoutManagedEditing && engine?.applyStructuredEdit) {
      const freezeOutcome = engine.applyStructuredEdit(freezeLayoutEdit());
      if (freezeOutcome.accepted && freezeOutcome.operations.length > 0) {
        acceptedScene = freezeOutcome.scene;
        mergedOperations = [...operations, ...freezeOutcome.operations];
        // Inverses undo in reverse order of the forward batch: the freeze's
        // inverse (each sub-batch already internally reverse-ordered) goes
        // first so undoing peels the freeze off before the turn's content.
        mergedInverseOperations =
          inverseOperations && freezeOutcome.inverseOperations
            ? [...freezeOutcome.inverseOperations, ...inverseOperations]
            : null;
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
    sendAgentPrompt,
    postSystemMessage,
    queueAgentMessage,
    removeQueuedAgentMessage,
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
