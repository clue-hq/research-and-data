"use client";

import { useEffect, useMemo, useState, type CSSProperties, type PointerEvent as ReactPointerEvent } from "react";
import { Download, FileCheck2, History, PanelRightClose, RotateCcw, RotateCw, Send } from "lucide-react";
import { AgentChatPanel, type AgentChatMessage } from "./AgentChatPanel";
import { BrandKitPanel } from "./BrandKitPanel";
import { CanvasSurface } from "./canvas/CanvasSurface";
import { ExportPanel } from "./ExportPanel";
import { ExportPreviewSurface } from "./ExportPreviewSurface";
import { HistoryPanel } from "./HistoryPanel";
import { InspectorPanel } from "./InspectorPanel";
import { LayerPanel } from "./LayerPanel";
import { PageRail } from "./PageRail";
import { ValidationPanel } from "./ValidationPanel";
import { minimalScene } from "@/fixtures/minimalScene";
import type { BrandCompatibilityRunner } from "@/engine/brandCompatibility";
import type { BrandGovernanceRunner } from "@/engine/brandGovernance";
import {
  createApiAgentRunner,
  type EditorAgentResult,
  type EditorAgentRunner
} from "@/engine/agentRunner";
import type {
  BrandCompatibilityReport,
  BrandKitRef,
  BrandKitSummary,
  Diagnostic,
  DiagnosticSubject,
  Node,
  NodeId,
  Operation,
  Page,
  PageId,
  ParentRef,
  Scene
} from "@/engine/contracts";
import { localEditorEngine } from "@/engine/editorEngine";
import {
  createApiExportRunner,
  defaultEditorExportProfile,
  type EditorExportResult,
  type EditorExportRunner
} from "@/engine/exportRunner";
import {
  createApiPreflightRunner,
  type EditorPreflightResult,
  type EditorPreflightRunner
} from "@/engine/preflightRunner";
import {
  addPage,
  bindNodeToSlot,
  insertNode,
  removeExportProfile,
  removeNode,
  removePage,
  updateNodeTransform,
  upsertExportProfile
} from "@/engine/operations";
import { editorRenderDiagnostics } from "@/engine/renderDiagnostics";
import {
  clampNodeTransformToParentBounds,
  firstPageId,
  getNode,
  isNodeLayoutManaged,
  nodeIdForAsset,
  pageIdForNode
} from "@/engine/sceneQueries";

export interface EditorAppProps {
  documentId?: string;
  initialScene?: Scene;
  initialSelectedNodeId?: NodeId | null;
  initialAvailableBrandKits?: BrandKitSummary[];
  brandGovernanceRunner?: BrandGovernanceRunner;
  brandCompatibilityRunner?: BrandCompatibilityRunner;
  agentRunner?: EditorAgentRunner;
  exportRunner?: EditorExportRunner;
  preflightRunner?: EditorPreflightRunner;
}

interface EditorHistoryFrame {
  scene: Scene;
  operations: Operation[];
}

const defaultExportRunner = createApiExportRunner({
  apiBaseUrl: process.env.NEXT_PUBLIC_LUMEN_API_BASE_URL ?? "http://localhost:8000"
});

const defaultPreflightRunner = createApiPreflightRunner({
  apiBaseUrl: process.env.NEXT_PUBLIC_LUMEN_API_BASE_URL ?? "http://localhost:8000"
});

const defaultAgentRunner = createApiAgentRunner({
  apiBaseUrl: process.env.NEXT_PUBLIC_LUMEN_API_BASE_URL ?? "http://localhost:8000"
});

export default function EditorApp({
  documentId,
  initialScene = minimalScene,
  initialSelectedNodeId = "node_contact_name",
  initialAvailableBrandKits = [],
  brandGovernanceRunner,
  brandCompatibilityRunner,
  agentRunner = defaultAgentRunner,
  exportRunner = defaultExportRunner,
  preflightRunner = defaultPreflightRunner
}: EditorAppProps = {}) {
  const [scene, setScene] = useState<Scene>(initialScene);
  const [activePageId, setActivePageId] = useState<PageId | null>(() => firstPageId(initialScene));
  const [selectedNodeId, setSelectedNodeId] = useState<NodeId | null>(initialSelectedNodeId);
  const [diagnostics, setDiagnostics] = useState<Diagnostic[]>([]);
  const [lastOperation, setLastOperation] = useState<Operation | null>(null);
  const [undoStack, setUndoStack] = useState<EditorHistoryFrame[]>([]);
  const [redoStack, setRedoStack] = useState<EditorHistoryFrame[]>([]);
  const [operationHistory, setOperationHistory] = useState<Operation[]>([]);
  const [isBrandGovernanceRunning, setIsBrandGovernanceRunning] = useState(false);
  const [isBrandCompatibilityRunning, setIsBrandCompatibilityRunning] = useState(false);
  const [isAgentPanelOpen, setIsAgentPanelOpen] = useState(false);
  const [agentSidebarWidth, setAgentSidebarWidth] = useState(420);
  const [isAgentRunning, setIsAgentRunning] = useState(false);
  const [agentDraft, setAgentDraft] = useState("");
  const [agentMessages, setAgentMessages] = useState<AgentChatMessage[]>([]);
  const [agentProposal, setAgentProposal] = useState<EditorAgentResult | null>(null);
  const [isPreflighting, setIsPreflighting] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [exportResult, setExportResult] = useState<EditorExportResult | null>(null);
  const [preflightResult, setPreflightResult] = useState<EditorPreflightResult | null>(null);
  const [workspaceMode, setWorkspaceMode] = useState<"canvas" | "export" | "compare">("canvas");
  const [brandCompatibilityReport, setBrandCompatibilityReport] =
    useState<BrandCompatibilityReport | null>(null);
  const selectedNode = useMemo(() => getNode(scene, selectedNodeId), [scene, selectedNodeId]);
  const activePage = activePageId ? scene.pages[activePageId] ?? null : null;
  const effectiveBrandKit = useMemo(
    () =>
      scene.meta.brand_kit
        ? initialAvailableBrandKits.find(
            (brandKit) =>
              brandKit.id === scene.meta.brand_kit?.id &&
              brandKit.version === scene.meta.brand_kit?.version
          )
        : null,
    [initialAvailableBrandKits, scene.meta.brand_kit]
  );
  const compatibilityTarget = useMemo(
    () => latestBrandKitVersion(initialAvailableBrandKits, scene.meta.brand_kit),
    [initialAvailableBrandKits, scene.meta.brand_kit]
  );
  const brandDiagnostics = diagnostics.filter((diagnostic) => diagnostic.phase === "brand");
  const renderDiagnostics = useMemo(
    () => editorRenderDiagnostics(scene, activePageId),
    [activePageId, scene]
  );

  useEffect(() => {
    if (activePageId && !scene.pages[activePageId]) {
      setActivePageId(firstPageId(scene));
      setSelectedNodeId(null);
      return;
    }
    if (!activePageId) {
      setActivePageId(firstPageId(scene));
    }
    if (selectedNodeId && !scene.nodes[selectedNodeId]) {
      setSelectedNodeId(null);
    }
  }, [activePageId, scene, selectedNodeId]);

  const applyOperations = (operations: Operation[], onAccepted?: (scene: Scene) => void) => {
    if (operations.length === 0) {
      return;
    }
    setScene((currentScene) => {
      let nextScene = currentScene;
      for (const operation of operations) {
        const result = localEditorEngine.applyOperation(nextScene, operation);
        if (!result.accepted) {
          setDiagnostics([
            {
              severity: "error",
              phase: "operation",
              code: "EDITOR_LOCAL_APPLY",
              message: result.message ?? "Operation was rejected by the local editor engine",
              subject: selectedNodeId
                ? {
                    kind: "node",
                    id: selectedNodeId
                  }
                : null,
              hint: "The editor will use checked core/WASM operation application once that workstream is available."
            }
          ]);
          return currentScene;
        }
        nextScene = result.scene;
      }

      const lastAcceptedOperation = operations[operations.length - 1] ?? null;
      if (lastAcceptedOperation) {
        setLastOperation(lastAcceptedOperation);
        setBrandCompatibilityReport(null);
        setPreflightResult(null);
        setExportResult(null);
        setWorkspaceMode("canvas");
        setUndoStack((stack) => [
          ...stack.slice(-49),
          {
            scene: currentScene,
            operations
          }
        ]);
        setRedoStack([]);
        setOperationHistory((history) => [...history, ...operations].slice(-50));
        setDiagnostics([]);
        onAccepted?.(nextScene);
        return nextScene;
      }

      return currentScene;
    });
  };

  const applyOperation = (operation: Operation) => {
    applyOperations([operation]);
  };

  const sendAgentPrompt = async (prompt: string) => {
    const trimmedPrompt = prompt.trim();
    if (!trimmedPrompt || isAgentRunning) {
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
        documentId,
        activePageId,
        selectedNodeId,
        diagnostics
      });
      setAgentProposal(result);
      if (result.status === "failed" && result.draft_scene) {
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
      if (result.diagnostics.length > 0) {
        setDiagnostics(result.diagnostics);
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
    setScene(draftScene);
    setActivePageId(draftPageId);
    setSelectedNodeId(null);
    setBrandCompatibilityReport(null);
    setPreflightResult(null);
    setExportResult(null);
    setWorkspaceMode("canvas");
    setDiagnostics([draftDiagnostic, ...result.diagnostics]);
  };

  const undoLastOperation = () => {
    const undoFrame = undoStack[undoStack.length - 1];
    if (!undoFrame) {
      return;
    }

    const nextHistory =
      undoFrame.operations.length > 0
        ? operationHistory.slice(0, -undoFrame.operations.length)
        : operationHistory;

    setUndoStack((stack) => stack.slice(0, -1));
    setRedoStack((stack) => [
      ...stack.slice(-49),
      {
        scene,
        operations: undoFrame.operations
      }
    ]);
    setOperationHistory(nextHistory);
    setScene(undoFrame.scene);
    setLastOperation(nextHistory[nextHistory.length - 1] ?? null);
    setDiagnostics([]);
    setBrandCompatibilityReport(null);
    setPreflightResult(null);
    setExportResult(null);
    setWorkspaceMode("canvas");
  };

  const redoLastOperation = () => {
    const redoFrame = redoStack[redoStack.length - 1];
    if (!redoFrame) {
      return;
    }

    setRedoStack((stack) => stack.slice(0, -1));
    setUndoStack((stack) => [
      ...stack.slice(-49),
      {
        scene,
        operations: redoFrame.operations
      }
    ]);
    setOperationHistory((history) => [...history, ...redoFrame.operations].slice(-50));
    setScene(redoFrame.scene);
    setLastOperation(redoFrame.operations[redoFrame.operations.length - 1] ?? null);
    setDiagnostics([]);
    setBrandCompatibilityReport(null);
    setPreflightResult(null);
    setExportResult(null);
    setWorkspaceMode("canvas");
  };

  const startAgentSidebarResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = agentSidebarWidth;
    const resize = (moveEvent: PointerEvent) => {
      if (!Number.isFinite(moveEvent.clientX)) {
        return;
      }
      const nextWidth = clampNumber(startWidth + startX - moveEvent.clientX, 320, 720);
      setAgentSidebarWidth(nextWidth);
    };
    const stopResize = () => {
      window.removeEventListener("pointermove", resize);
    };
    window.addEventListener("pointermove", resize);
    window.addEventListener("pointerup", stopResize, { once: true });
  };

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (isEditableEventTarget(event.target)) {
        return;
      }

      const historyAction = keyboardHistoryAction(event);
      if (historyAction === "undo") {
        event.preventDefault();
        undoLastOperation();
        return;
      }
      if (historyAction === "redo") {
        event.preventDefault();
        redoLastOperation();
        return;
      }

      if (event.key === "Escape" && selectedNodeId) {
        event.preventDefault();
        setSelectedNodeId(null);
        return;
      }

      if (!selectedNode) {
        return;
      }
      if ((event.key === "Delete" || event.key === "Backspace") && !selectedNode.locked) {
        event.preventDefault();
        applyOperation(removeNode(selectedNode.id));
        setSelectedNodeId(null);
        return;
      }

      const nudge = arrowNudge(event.key);
      if (!nudge || selectedNode.locked || isNodeLayoutManaged(scene, selectedNode.id)) {
        return;
      }
      event.preventDefault();
      const step = event.shiftKey ? 10 : 1;
      const nextTransform = clampNodeTransformToParentBounds(scene, selectedNode, {
        ...selectedNode.transform,
        x: selectedNode.transform.x + nudge.x * step,
        y: selectedNode.transform.y + nudge.y * step
      });
      applyOperation(
        updateNodeTransform(selectedNode, nextTransform)
      );
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [redoLastOperation, scene, selectedNode, selectedNodeId, undoLastOperation]);

  const runPreflight = async () => {
    setIsPreflighting(true);
    setDiagnostics([
      {
        severity: "advice",
        phase: "validation",
        code: "EDITOR_PREFLIGHT_RUNNING",
        message: "Running canonical preflight validation.",
        subject: null,
        hint: "Preflight resolves BrandKit tokens, layout, text-fit diagnostics, and computed geometry before export."
      }
    ]);

    try {
      const result = await preflightRunner({ scene });
      setPreflightResult(result);
      setExportResult(null);
      setWorkspaceMode("canvas");
      if (result.status === "applied" && result.scene) {
        setScene(result.scene);
        setDiagnostics(
          result.diagnostics.length > 0
            ? result.diagnostics
            : [
                {
                  severity: "advice",
                  phase: "validation",
                  code: "EDITOR_PREFLIGHT_OK",
                  message: `Preflight applied ${preflightOperationCount(result)} canonical operation${preflightOperationCount(result) === 1 ? "" : "s"}.`,
                  subject: { kind: "document" },
                  hint: result.brand_kit.source
                    ? `Effective Brand Kit source: ${result.brand_kit.source}.`
                    : null
                }
              ]
        );
      } else {
        setDiagnostics(
          result.diagnostics.length > 0
            ? result.diagnostics
            : [
                {
                  severity: "error",
                  phase: "validation",
                  code: "EDITOR_PREFLIGHT_FAILED",
                  message: "Preflight failed without returning detailed diagnostics.",
                  subject: { kind: "document" },
                  hint: "Inspect the API/core logs and retry after correcting the scene."
                }
              ]
        );
      }
    } catch (error) {
      setPreflightResult(null);
      setDiagnostics([
        {
          severity: "error",
          phase: "validation",
          code: "EDITOR_PREFLIGHT_REQUEST_FAILED",
          message: error instanceof Error ? error.message : "Preflight request failed.",
          subject: { kind: "document" },
          hint: "Check the editor API connection and retry validation."
        }
      ]);
    } finally {
      setIsPreflighting(false);
    }
  };

  const runBrandGovernance = async () => {
    if (!scene.meta.brand_kit) {
      setDiagnostics([
        {
          severity: "warning",
          phase: "brand",
          code: "EDITOR_BRAND_KIT_REQUIRED",
          message: "No Brand Kit is attached to this document.",
          subject: { kind: "document" },
          hint: "Attach a stored Brand Kit before running strict brand governance."
        }
      ]);
      return;
    }

    if (!brandGovernanceRunner) {
      setDiagnostics([
        {
          severity: "advice",
          phase: "brand",
          code: "EDITOR_BRAND_GOVERNANCE_PORT",
          message: "Brand governance UI is wired; provide a BrandGovernanceRunner to call the API/core validator.",
          subject: { kind: "document" },
          hint: "Use createApiBrandGovernanceRunner against POST /documents/{id}/brand-governance."
        }
      ]);
      return;
    }

    setIsBrandGovernanceRunning(true);
    setDiagnostics([
      {
        severity: "advice",
        phase: "brand",
        code: "EDITOR_BRAND_GOVERNANCE_RUNNING",
        message: "Running Brand Kit governance checks.",
        subject: { kind: "document" },
        hint: null
      }
    ]);

    try {
      const result = await brandGovernanceRunner({
        scene,
        brandKit: effectiveBrandKit ?? null
      });
      setDiagnostics(
        result.diagnostics.length > 0
          ? result.diagnostics
          : [
              {
                severity: "advice",
                phase: "brand",
                code: "EDITOR_BRAND_GOVERNANCE_OK",
                message: "Brand Kit governance passed with no diagnostics.",
                subject: { kind: "document" },
                hint: null
              }
            ]
      );
    } catch (error) {
      setDiagnostics([
        {
          severity: "error",
          phase: "brand",
          code: "EDITOR_BRAND_GOVERNANCE_FAILED",
          message: error instanceof Error ? error.message : "Brand governance request failed.",
          subject: { kind: "document" },
          hint: "Check the editor API connection and retry the Brand Kit check."
        }
      ]);
    } finally {
      setIsBrandGovernanceRunning(false);
    }
  };

  const runBrandCompatibility = async () => {
    if (!scene.meta.brand_kit) {
      setDiagnostics([
        {
          severity: "warning",
          phase: "brand",
          code: "EDITOR_BRAND_KIT_REQUIRED",
          message: "No Brand Kit is attached to this document.",
          subject: { kind: "document" },
          hint: "Attach a stored Brand Kit before checking compatibility."
        }
      ]);
      return;
    }

    if (!compatibilityTarget) {
      setBrandCompatibilityReport(null);
      setDiagnostics([
        {
          severity: "advice",
          phase: "brand",
          code: "EDITOR_BRAND_COMPATIBILITY_CURRENT",
          message: "No newer stored Brand Kit version is available for this document.",
          subject: { kind: "document" },
          hint: "Compatibility warnings appear when a later version of the same Brand Kit is available."
        }
      ]);
      return;
    }

    if (!brandCompatibilityRunner) {
      setDiagnostics([
        {
          severity: "advice",
          phase: "brand",
          code: "EDITOR_BRAND_COMPATIBILITY_PORT",
          message: "Brand compatibility UI is wired; provide a BrandCompatibilityRunner to call the API/core report.",
          subject: { kind: "document" },
          hint: "Use createApiBrandCompatibilityRunner against POST /brand-kits/compatibility."
        }
      ]);
      return;
    }

    setIsBrandCompatibilityRunning(true);
    setDiagnostics([
      {
        severity: "advice",
        phase: "brand",
        code: "EDITOR_BRAND_COMPATIBILITY_RUNNING",
        message: "Checking Brand Kit version compatibility.",
        subject: { kind: "document" },
        hint: null
      }
    ]);

    try {
      const result = await brandCompatibilityRunner({
        scene,
        currentBrandKit: effectiveBrandKit ?? null,
        targetBrandKit: compatibilityTarget
      });
      setBrandCompatibilityReport(result.report);
      const reportDiagnostics = result.diagnostics.length > 0 ? result.diagnostics : result.report?.diagnostics ?? [];
      setDiagnostics(
        reportDiagnostics.length > 0
          ? reportDiagnostics
          : [
              {
                severity: "advice",
                phase: "brand",
                code: "EDITOR_BRAND_COMPATIBILITY_OK",
                message:
                  result.report && result.report.token_changes.length > 0
                    ? "Brand Kit compatibility report completed with token changes to review."
                    : "Brand Kit compatibility report passed with no token changes.",
                subject: { kind: "document" },
                hint: null
              }
            ]
      );
    } catch (error) {
      setBrandCompatibilityReport(null);
      setDiagnostics([
        {
          severity: "error",
          phase: "brand",
          code: "EDITOR_BRAND_COMPATIBILITY_FAILED",
          message: error instanceof Error ? error.message : "Brand compatibility request failed.",
          subject: { kind: "document" },
          hint: "Check the editor API connection and retry the compatibility check."
        }
      ]);
    } finally {
      setIsBrandCompatibilityRunning(false);
    }
  };

  const selectPage = (pageId: PageId) => {
    setActivePageId(pageId);
    setSelectedNodeId(null);
  };

  const createCustomPage = (input: { name: string; width: number; height: number; unit: Page["size"]["unit"] }) => {
    const page: Page = {
      id: uniquePageId(scene, input),
      name: input.name,
      size: {
        width: input.width,
        height: input.height,
        unit: input.unit,
        preset: "custom",
        orientation: input.width > input.height ? "landscape" : "portrait"
      },
      children: [],
      bleed: null,
      safe_area: null,
      background: []
    };
    applyOperation(addPage(page));
    setActivePageId(page.id);
    setSelectedNodeId(null);
  };

  const duplicatePageInEditor = (pageId: PageId) => {
    const page = scene.pages[pageId];
    if (!page) {
      return;
    }
    const operations = duplicatePageOperations(scene, page);
    const addPageOperation = operations.find((operation) => operation.kind === "add_page");
    const duplicatedPageId = addPageOperation?.kind === "add_page" ? addPageOperation.page.id : null;
    applyOperations(operations, () => {
      if (duplicatedPageId) {
        setActivePageId(duplicatedPageId);
        setSelectedNodeId(null);
      }
    });
  };

  const removePageFromEditor = (pageId: PageId) => {
    const selectedNodePageId = selectedNodeId ? pageIdForNode(scene, selectedNodeId) : null;
    const remainingPageId = Object.values(scene.pages).find((page) => page.id !== pageId)?.id ?? null;

    applyOperation(removePage(pageId));
    if (activePageId === pageId) {
      setActivePageId(remainingPageId);
      setSelectedNodeId(null);
    } else if (selectedNodePageId === pageId) {
      setSelectedNodeId(null);
    }
  };

  const selectDiagnosticSubject = (subject: DiagnosticSubject) => {
    switch (subject.kind) {
      case "page": {
        if (scene.pages[subject.id]) {
          setActivePageId(subject.id);
          setSelectedNodeId(null);
        }
        return;
      }
      case "node": {
        if (!scene.nodes[subject.id]) {
          return;
        }
        const pageId = pageIdForNode(scene, subject.id);
        if (pageId) {
          setActivePageId(pageId);
        }
        setSelectedNodeId(subject.id);
        return;
      }
      case "slot": {
        const slot = scene.slots[subject.id];
        const boundNodeId = slot?.bound_nodes.find((nodeId) => Boolean(scene.nodes[nodeId])) ?? null;
        if (!boundNodeId) {
          return;
        }
        const pageId = pageIdForNode(scene, boundNodeId);
        if (pageId) {
          setActivePageId(pageId);
        }
        setSelectedNodeId(boundNodeId);
        return;
      }
      case "asset": {
        const nodeId = nodeIdForAsset(scene, subject.id);
        if (!nodeId) {
          return;
        }
        const pageId = pageIdForNode(scene, nodeId);
        if (pageId) {
          setActivePageId(pageId);
        }
        setSelectedNodeId(nodeId);
        return;
      }
      case "document":
        return;
    }
  };

  const applyAgentProposal = () => {
    if (!agentProposal || agentProposal.operations.length === 0) {
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
      setIsAgentPanelOpen(false);
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

  const runExport = async (
    profile = defaultEditorExportProfile(),
    pageIds: PageId[] = activePageId ? [activePageId] : []
  ) => runExportForScene(scene, profile, pageIds);

  const runExportForScene = async (
    sceneForExport: Scene,
    profile = defaultEditorExportProfile(),
    pageIds: PageId[] = activePageId ? [activePageId] : []
  ) => {
    if (pageIds.length === 0) {
      setDiagnostics([
        {
          severity: "warning",
          phase: "export",
          code: "EDITOR_EXPORT_PAGE_REQUIRED",
          message: "Select a page before exporting.",
          subject: { kind: "document" },
          hint: "Choose a page in the page rail or export all pages from the Export panel."
        }
      ]);
      return;
    }

    setIsExporting(true);
    setDiagnostics([
      {
        severity: "advice",
        phase: "validation",
        code: "EDITOR_EXPORT_PREFLIGHT_RUNNING",
        message: `Preflighting ${pageIds.length} page${pageIds.length === 1 ? "" : "s"} before export.`,
        subject: { kind: "document" },
        hint: "Export always uses the preflighted scene so computed geometry and BrandKit resolution match approval output."
      }
    ]);

    try {
      const preflight = await preflightRunner({ scene: sceneForExport });
      setPreflightResult(preflight);
      const preflightDiagnostics = exportPreflightDiagnostics(preflight);
      const sceneToExport = preflight.scene ?? sceneForExport;
      if (preflight.scene) {
        setScene(preflight.scene);
      }
      setDiagnostics([
        {
          severity: preflightDiagnostics.length > 0 ? "warning" : "advice",
          phase: "export",
          code: "EDITOR_EXPORT_RUNNING",
          message: `Exporting ${preflightDiagnostics.length > 0 ? "with preflight diagnostics" : "preflighted scene"} using ${profile.name}.`,
          subject: { kind: "document" },
          hint:
            preflightDiagnostics.length > 0
              ? "Preview export continues for inspection, but approval remains blocked until preflight diagnostics are resolved."
              : `Preflight applied ${preflightOperationCount(preflight)} canonical operation${preflightOperationCount(preflight) === 1 ? "" : "s"}.`
        }
      ]);

      const result = await exportRunner({
        scene: sceneToExport,
        profile,
        pageIds,
        ...(documentId ? { documentId } : {})
      });
      const combinedDiagnostics = [...preflightDiagnostics, ...result.diagnostics];
      const resultWithPreflightDiagnostics: EditorExportResult = {
        ...result,
        diagnostics: combinedDiagnostics
      };
      setExportResult(resultWithPreflightDiagnostics);
      if (result.status === "ok" && result.artifacts.length > 0) {
        setWorkspaceMode("compare");
      }
      setDiagnostics(
        combinedDiagnostics.length > 0
          ? combinedDiagnostics
          : [
              {
                severity: result.status === "ok" ? "advice" : "error",
                phase: "export",
                code: result.status === "ok" ? "EDITOR_EXPORT_OK" : "EDITOR_EXPORT_FAILED",
                message:
                  result.status === "ok"
                    ? `Export produced ${result.artifacts.length} artifact${result.artifacts.length === 1 ? "" : "s"}.`
                    : "Export failed without returning detailed diagnostics.",
                subject: { kind: "document" },
                hint: null
              }
            ]
      );
    } catch (error) {
      setExportResult(null);
      setDiagnostics([
        {
          severity: "error",
          phase: "export",
          code: "EDITOR_EXPORT_REQUEST_FAILED",
          message: error instanceof Error ? error.message : "Export request failed.",
          subject: { kind: "document" },
          hint: "Check the editor API connection and retry export."
        }
      ]);
    } finally {
      setIsExporting(false);
    }
  };

  return (
    <main className="editor-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">ABM Design Engine</p>
          <h1>{scene.meta.title}</h1>
        </div>
        <div className="toolbar" aria-label="Editor actions">
          <button type="button" onClick={() => void runPreflight()} disabled={isPreflighting}>
            <FileCheck2 aria-hidden size={16} />
            {isPreflighting ? "Validating" : "Validate"}
          </button>
          <button
            type="button"
            className={isAgentPanelOpen ? "active" : ""}
            onClick={() => setIsAgentPanelOpen((isOpen) => !isOpen)}
            aria-pressed={isAgentPanelOpen}
          >
            <Send aria-hidden size={16} />
            Agent
          </button>
          <button type="button" onClick={() => void runExport()} disabled={!activePageId || isExporting}>
            <Download aria-hidden size={16} />
            {isExporting ? "Exporting" : "Export"}
          </button>
          <button type="button" onClick={undoLastOperation} disabled={undoStack.length === 0}>
            <RotateCcw aria-hidden size={16} />
            Undo
          </button>
          <button type="button" onClick={redoLastOperation} disabled={redoStack.length === 0}>
            <RotateCw aria-hidden size={16} />
            Redo
          </button>
        </div>
      </header>
      <div
        className={`workspace-grid${isAgentPanelOpen ? " agent-open" : ""}`}
        style={{ "--right-sidebar-width": `${agentSidebarWidth}px` } as CSSProperties}
      >
        <div className="left-sidebar">
          <PageRail
            scene={scene}
            activePageId={activePageId}
            onSelectPage={selectPage}
            onAddCustomPage={createCustomPage}
            onDuplicatePage={duplicatePageInEditor}
            onRemovePage={removePageFromEditor}
          />
          <LayerPanel
            scene={scene}
            activePageId={activePageId}
            selectedNodeId={selectedNodeId}
            onSelectNode={setSelectedNodeId}
            onOperation={applyOperation}
          />
        </div>
        <section className="center-workspace">
          <div className="view-toggle" aria-label="Preview mode">
            <button
              type="button"
              className={workspaceMode === "canvas" ? "active" : ""}
              onClick={() => setWorkspaceMode("canvas")}
            >
              Canvas
            </button>
            <button
              type="button"
              className={workspaceMode === "export" ? "active" : ""}
              disabled={!exportResult?.artifacts.length}
              onClick={() => setWorkspaceMode("export")}
            >
              Export Preview
            </button>
            <button
              type="button"
              className={workspaceMode === "compare" ? "active" : ""}
              disabled={!exportResult?.artifacts.length}
              onClick={() => setWorkspaceMode("compare")}
            >
              Compare
            </button>
          </div>
          {workspaceMode === "compare" ? (
            <div className="compare-workspace">
              <div className="compare-pane">
                <div className="compare-heading">Canvas</div>
                <CanvasSurface
                  scene={scene}
                  activePageId={activePageId}
                  selectedNodeId={selectedNodeId}
                  onSelectNode={setSelectedNodeId}
                  onOperation={applyOperation}
                />
              </div>
              <div className="compare-pane">
                <div className="compare-heading">Export Preview</div>
                <ExportPreviewSurface
                  scene={scene}
                  activePageId={activePageId}
                  exportResult={exportResult}
                  onSelectSubject={selectDiagnosticSubject}
                />
              </div>
            </div>
          ) : workspaceMode === "export" ? (
            <ExportPreviewSurface
              scene={scene}
              activePageId={activePageId}
              exportResult={exportResult}
              onSelectSubject={selectDiagnosticSubject}
            />
          ) : (
            <CanvasSurface
              scene={scene}
              activePageId={activePageId}
              selectedNodeId={selectedNodeId}
              onSelectNode={setSelectedNodeId}
              onOperation={applyOperation}
            />
          )}
        </section>
        {isAgentPanelOpen ? (
          <div
            className="right-sidebar-resizer"
            role="separator"
            aria-label="Resize agent chat sidebar"
            aria-orientation="vertical"
            onPointerDown={startAgentSidebarResize}
          />
        ) : null}
        <aside
          className="inspector-shell"
          aria-label={isAgentPanelOpen ? "Agent chat sidebar" : "Inspector sidebar"}
        >
          {isAgentPanelOpen ? (
            <AgentChatPanel
              messages={agentMessages}
              draft={agentDraft}
              isRunning={isAgentRunning}
              proposal={agentProposal}
              activePageId={activePageId}
              selectedNodeId={selectedNodeId}
              diagnostics={diagnostics}
              onDraftChange={setAgentDraft}
              onSend={(prompt) => void sendAgentPrompt(prompt)}
              onApplyProposal={applyAgentProposal}
            />
          ) : (
            <>
              <div className="panel-title">
                <PanelRightClose aria-hidden size={16} />
                Inspector
              </div>
              <InspectorPanel
                scene={scene}
                activePage={activePage}
                selectedNode={selectedNode}
                selectedNodeId={selectedNodeId}
                brandTokens={effectiveBrandKit?.tokens ?? null}
                diagnostics={diagnostics}
                renderDiagnostics={renderDiagnostics}
                onOperation={applyOperation}
                onOperations={applyOperations}
                onSelectSubject={selectDiagnosticSubject}
              />
              <BrandKitPanel
                scene={scene}
                availableBrandKits={initialAvailableBrandKits}
                diagnostics={brandDiagnostics}
                compatibilityReport={brandCompatibilityReport}
                compatibilityTarget={compatibilityTarget}
                onOperation={applyOperation}
                onRunBrandGovernance={runBrandGovernance}
                isRunningBrandGovernance={isBrandGovernanceRunning}
                onRunBrandCompatibility={runBrandCompatibility}
                isRunningBrandCompatibility={isBrandCompatibilityRunning}
                onSelectSubject={selectDiagnosticSubject}
              />
              <ExportPanel
                scene={scene}
                activePageId={activePageId}
                exportResult={exportResult}
                isExporting={isExporting}
                onExport={(profile, pageIds) => void runExport(profile, pageIds)}
                onSaveProfile={(profile) => applyOperation(upsertExportProfile(profile))}
                onRemoveProfile={(name) => applyOperation(removeExportProfile(name))}
                onSelectSubject={selectDiagnosticSubject}
              />
              <OperationHistoryPanel operations={operationHistory} redoCount={redoStack.length} />
              {documentId ? (
                <HistoryPanel
                  apiBaseUrl={
                    process.env.NEXT_PUBLIC_LUMEN_API_BASE_URL ?? "http://localhost:8000"
                  }
                  documentId={documentId}
                />
              ) : null}
              <ValidationPanel
                scene={scene}
                activePageId={activePageId}
                selectedNodeId={selectedNodeId}
                diagnostics={diagnostics}
                renderDiagnostics={renderDiagnostics}
                lastOperation={lastOperation}
                preflightResult={preflightResult}
                onSelectSubject={selectDiagnosticSubject}
              />
            </>
          )}
        </aside>
      </div>
    </main>
  );
}

function OperationHistoryPanel({
  operations,
  redoCount
}: {
  operations: Operation[];
  redoCount: number;
}) {
  const recentOperations = operations.slice(-6).reverse();

  return (
    <section className="inspector-section">
      <div className="section-heading">
        <History aria-hidden size={15} />
        Operation history
      </div>
      {operations.length === 0 ? (
        <p className="muted">No accepted editor operations yet.</p>
      ) : (
        <ol className="operation-history-list">
          {recentOperations.map((operation, index) => (
            <li key={`${operations.length - index}-${operation.kind}`}>
              <span>{operations.length - index}</span>
              <code>{operationLabel(operation)}</code>
            </li>
          ))}
        </ol>
      )}
      {redoCount > 0 ? <p className="muted">{redoCount} action{redoCount === 1 ? "" : "s"} available to redo.</p> : null}
    </section>
  );
}

function operationLabel(operation: Operation): string {
  switch (operation.kind) {
    case "add_page":
      return `add_page ${operation.page.id}`;
    case "remove_page":
      return `remove_page ${operation.page_id}`;
    case "insert_node":
      return `insert_node ${operation.node.id}`;
    case "update_node":
      return `update_node ${operation.node_id}`;
    case "remove_node":
      return `remove_node ${operation.node_id}`;
    case "update_page":
      return `update_page ${operation.page_id}`;
    case "move_node":
      return `move_node ${operation.node_id}`;
    case "upsert_slot":
      return `upsert_slot ${operation.slot.key}`;
    case "remove_slot":
      return `remove_slot ${operation.slot_id}`;
    case "bind_node_to_slot":
      return `bind_node_to_slot ${operation.node_id}`;
    case "unbind_node_from_slot":
      return `unbind_node_from_slot ${operation.node_id}`;
    case "upsert_asset":
      return `upsert_asset ${operation.asset.id}`;
    case "remove_asset":
      return `remove_asset ${operation.asset_id}`;
    case "place_asset_in_node":
      return `place_asset_in_node ${operation.node_id}`;
    case "place_asset_in_slot":
      return `place_asset_in_slot ${operation.slot_id}`;
    case "upsert_export_profile":
      return `upsert_export_profile ${operation.profile.name}`;
    case "remove_export_profile":
      return `remove_export_profile ${operation.name}`;
    case "update_document":
      return "update_document";
  }
}

function uniquePageId(scene: Scene, input: { name: string; width: number; height: number }): PageId {
  const readable = input.name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  const base = readable || `custom_${input.width}x${input.height}`;
  let candidate = `page_${base}`;
  let index = 2;
  while (scene.pages[candidate]) {
    candidate = `page_${base}_${index}`;
    index += 1;
  }
  return candidate;
}

function duplicatePageOperations(scene: Scene, page: Page): Operation[] {
  const pageName = `${page.name} Copy`;
  const pageId = uniquePageId(scene, {
    name: pageName,
    width: page.size.width,
    height: page.size.height
  });
  const usedNodeIds = new Set(Object.keys(scene.nodes));
  const nodeIdMap = new Map<NodeId, NodeId>();

  const assignNodeIds = (nodeId: NodeId) => {
    if (nodeIdMap.has(nodeId)) {
      return;
    }
    const clonedNodeId = uniqueClonedNodeId(usedNodeIds, nodeId, pageId);
    nodeIdMap.set(nodeId, clonedNodeId);
    const node = scene.nodes[nodeId];
    for (const childId of node?.children ?? []) {
      assignNodeIds(childId);
    }
  };

  for (const childId of page.children) {
    assignNodeIds(childId);
  }

  const duplicatedPage: Page = {
    ...cloneJson(page),
    id: pageId,
    name: pageName,
    children: []
  };
  const operations: Operation[] = [addPage(duplicatedPage)];

  const emitNodeTree = (sourceNodeId: NodeId, parent: ParentRef, index: number) => {
    const sourceNode = scene.nodes[sourceNodeId];
    const clonedNodeId = nodeIdMap.get(sourceNodeId);
    if (!sourceNode || !clonedNodeId) {
      return;
    }
    const clonedNode: Node = {
      ...cloneJson(sourceNode),
      id: clonedNodeId,
      children: [],
      computed: null
    };
    operations.push(insertNode(parent, index, clonedNode));

    for (const slot of Object.values(scene.slots)) {
      if (slot.bound_nodes.includes(sourceNodeId)) {
        operations.push(bindNodeToSlot(slot.id, clonedNodeId));
      }
    }

    sourceNode.children.forEach((childId, childIndex) =>
      emitNodeTree(childId, { kind: "node", id: clonedNodeId }, childIndex)
    );
  };

  page.children.forEach((childId, index) =>
    emitNodeTree(childId, { kind: "page", id: pageId }, index)
  );

  return operations;
}

function uniqueClonedNodeId(usedNodeIds: Set<NodeId>, sourceNodeId: NodeId, pageId: PageId): NodeId {
  const pageSuffix = pageId
    .replace(/^page_/, "")
    .replace(/[^a-zA-Z0-9_]+/g, "_")
    .replace(/^_+|_+$/g, "");
  const base = `${sourceNodeId}_${pageSuffix || "copy"}`;
  let candidate = base;
  let index = 2;
  while (usedNodeIds.has(candidate)) {
    candidate = `${base}_${index}`;
    index += 1;
  }
  usedNodeIds.add(candidate);
  return candidate;
}

function cloneJson<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function preflightOperationCount(result: EditorPreflightResult): number {
  return (
    result.preflight.brand_ref_operations +
    result.preflight.token_operations +
    result.preflight.layout_operations
  );
}

function hasErrorDiagnostics(diagnostics: Diagnostic[]): boolean {
  return diagnostics.some((diagnostic) => diagnostic.severity === "error");
}

function exportPreflightDiagnostics(preflight: EditorPreflightResult): Diagnostic[] {
  const diagnostics = [...preflight.diagnostics];
  const needsSyntheticError =
    preflight.status !== "applied" ||
    preflight.preflight.has_errors ||
    !preflight.scene;

  if (needsSyntheticError && !hasErrorDiagnostics(diagnostics)) {
    diagnostics.unshift({
      severity: "error",
      phase: "validation",
      code:
        preflight.status !== "applied" || !preflight.scene
          ? "EDITOR_EXPORT_PREFLIGHT_FAILED_NONBLOCKING"
          : "EDITOR_EXPORT_PREFLIGHT_HAS_ERRORS",
      message:
        preflight.status !== "applied" || !preflight.scene
          ? "Preflight failed; exporting the current scene anyway for preview inspection."
          : "Preflight reported unresolved errors; exporting anyway for preview inspection.",
      subject: { kind: "document" },
      hint:
        "This preview is useful for inspection, but the artifact is not ready for approval until preflight diagnostics are resolved."
    });
  }

  return diagnostics;
}

function clampNumber(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
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

function isEditableEventTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  const tagName = target.tagName.toLowerCase();
  return (
    tagName === "input" ||
    tagName === "textarea" ||
    tagName === "select" ||
    target.isContentEditable
  );
}

function keyboardHistoryAction(event: KeyboardEvent): "undo" | "redo" | null {
  const key = event.key.toLowerCase();
  const modifier = event.metaKey || event.ctrlKey;
  if (!modifier) {
    return null;
  }
  if (key === "z" && event.shiftKey) {
    return "redo";
  }
  if (key === "z") {
    return "undo";
  }
  if (key === "y") {
    return "redo";
  }
  return null;
}

function arrowNudge(key: string): { x: number; y: number } | null {
  switch (key) {
    case "ArrowLeft":
      return { x: -1, y: 0 };
    case "ArrowRight":
      return { x: 1, y: 0 };
    case "ArrowUp":
      return { x: 0, y: -1 };
    case "ArrowDown":
      return { x: 0, y: 1 };
    default:
      return null;
  }
}

function latestBrandKitVersion(
  brandKits: BrandKitSummary[],
  currentRef: BrandKitRef | null
): BrandKitSummary | null {
  if (!currentRef) {
    return null;
  }

  return (
    brandKits
      .filter((brandKit) => brandKit.id === currentRef.id && brandKit.version > currentRef.version)
      .sort((left, right) => right.version - left.version)[0] ?? null
  );
}
