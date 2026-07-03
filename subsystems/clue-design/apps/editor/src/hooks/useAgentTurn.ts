import { useEffect, useState, type Dispatch, type SetStateAction } from "react";
import type { AgentChatMessage, QueuedAgentMessage } from "@/components/AgentChatPanel";
import type { EditorHistoryFrame } from "@/components/EditorApp";
import type { EditorAgentResult, EditorAgentRunner } from "@/engine/agentRunner";
import type {
  BrandCompatibilityReport,
  Diagnostic,
  ExportProfile,
  NodeId,
  Operation,
  PageId,
  Scene
} from "@/engine/contracts";
import type { EditorPanelMode } from "@/engine/editorModes";
import { defaultEditorExportProfile, type EditorExportResult } from "@/engine/exportRunner";
import type { EditorPreflightResult } from "@/engine/preflightRunner";
import { firstPageId } from "@/engine/sceneQueries";
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
  setEditorPanelMode: Dispatch<SetStateAction<EditorPanelMode>>;
  commitAppliedOperations: (
    previousScene: Scene,
    operations: Operation[],
    nextScene: Scene
  ) => void;
  runExportForScene: (
    sceneForExport: Scene,
    profile: ExportProfile,
    pageIds: PageId[]
  ) => Promise<void>;
  applyOperations: (operations: Operation[], onAccepted?: (scene: Scene) => void) => void;
}

export function useAgentTurn(deps: UseAgentTurnDeps) {
  const {
    agentRunner,
    engineRef,
    scene,
    activeDocumentId,
    activePageId,
    selectedNodeId,
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
    setEditorPanelMode,
    commitAppliedOperations,
    runExportForScene,
    applyOperations
  } = deps;

  const [isAgentRunning, setIsAgentRunning] = useState(false);
  const [agentDraft, setAgentDraft] = useState("");
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

  const sendAgentPrompt = async (prompt: string) => {
    const trimmedPrompt = prompt.trim();
    if (!trimmedPrompt || isAgentRunning) {
      return;
    }
    if (agentPreview) {
      setDiagnostics([pendingAgentReviewDiagnostic()]);
      return;
    }

    setAgentDraft("");
    setAgentProposal(null);
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
        selectedNodeId,
        diagnostics
      });
      // A failed run can hand back a "draft" that is just the untouched seed
      // (every authored block was rejected — nothing ever applied). Claiming
      // "draft visible" for an unchanged design reads as a broken canvas;
      // be honest instead and keep the proposal card in its blocked state.
      const draftIsUnchangedSeed =
        result.status === "failed" &&
        result.draft_scene !== null &&
        JSON.stringify(result.draft_scene) === JSON.stringify(scene);
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
    } catch (error) {
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
    } finally {
      setIsAgentRunning(false);
    }
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
        operations: []
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
    const { operations, baseScene, previewScene, view } = agentPreview;
    const advisoryDiagnostics = agentProposal?.diagnostics ?? [];
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
    commitAppliedOperations(baseScene, operations, acceptedScene);
    setAgentMessages((messages) => [
      ...messages,
      {
        id: uniqueChatMessageId("system"),
        role: "system",
        content:
          `Accepted ${operations.length} agent change${operations.length === 1 ? "" : "s"}.` +
          (advisoryDiagnostics.length > 0
            ? ` ${advisoryDiagnostics.length} advisory review note${advisoryDiagnostics.length === 1 ? "" : "s"} kept in Diagnostics.`
            : "")
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
    // Phase 0c: the panel button re-enters the reviewable preview (the normal
    // path previews automatically when the proposal arrives). In server-only
    // mode (no engine) previewing is impossible; fall through to the legacy
    // immediate apply, which surfaces the server-only diagnostic.
    if (engineRef.current) {
      previewAgentProposal(agentProposal);
      return;
    }

    const proposedOperations = agentProposal.operations;
    const proposedPageId = agentPreviewPageId(proposedOperations, activePageId, scene);
    applyOperations(proposedOperations, (nextScene) => {
      const previewPageId =
        proposedPageId && nextScene.pages[proposedPageId]
          ? proposedPageId
          : firstPageId(nextScene);
      setAgentProposal(null);
      setAgentMessages((messages) => [
        ...messages,
        {
          id: uniqueChatMessageId("system"),
          role: "system",
          content: `Applied ${proposedOperations.length} agent operation${proposedOperations.length === 1 ? "" : "s"} and started preflight/export preview.`
        }
      ]);
      setEditorPanelMode("inspector");
      setActivePageId(previewPageId);
      setSelectedNodeId((currentSelectedNodeId) =>
        currentSelectedNodeId && nextScene.nodes[currentSelectedNodeId]
          ? currentSelectedNodeId
          : null
      );
      if (previewPageId) {
        void runExportForScene(nextScene, defaultEditorExportProfile(), [previewPageId]);
      }
    });
  };

  return {
    isAgentRunning,
    agentDraft,
    setAgentDraft,
    agentMessages,
    agentProposal,
    agentPreview,
    queuedAgentMessages,
    sendAgentPrompt,
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
