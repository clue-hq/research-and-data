"use client";

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent
} from "react";
import { AlertTriangle, Check, Download, FileCheck2, History, PanelRightClose, RotateCcw, RotateCw, X } from "lucide-react";
import { AgentChatPanel, type AgentChatMessage } from "./AgentChatPanel";
import { BrandKitPanel } from "./BrandKitPanel";
import { EditorCanvas } from "./canvas/EditorCanvas";
import { ExportPanel, type ExportPanelState } from "./ExportPanel";
import { ExportPreviewSurface } from "./ExportPreviewSurface";
import {
  openBlankArtifactPreviewWindow,
  showArtifactInPreviewWindow
} from "./exportArtifactActions";
import { AssetBrowserPanel } from "./AssetBrowserPanel";
import { HistoryPanel } from "./HistoryPanel";
import { WorstCasePreviewPanel } from "./WorstCasePreviewPanel";
import { InspectorPanel } from "./InspectorPanel";
import { LayerPanel } from "./LayerPanel";
import { PageRail } from "./PageRail";
import { ValidationPanel } from "./ValidationPanel";
import { emptyScene } from "@/fixtures/emptyScene";
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
import {
  createEditQueue,
  type EditQueuePort,
  type ReconcileEvent
} from "@/engine/editQueue";
import {
  EDITOR_PANEL_MODES,
  rightSidebarLabelForMode,
  type EditorPanelMode
} from "@/engine/editorModes";
import {
  activateWasmCore,
  wasmCoreFlagEnabled,
  WasmEngine,
  type OptimisticEnginePort
} from "@/engine/wasmEngine";
import {
  createApiExportRunner,
  defaultEditorExportProfile,
  type EditorExportArtifact,
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
import { normalizePageSize } from "@/engine/pageGeometry";
import type { StructuredEdit } from "@/engine/structuredEdits";
import { editorRenderDiagnostics } from "@/engine/renderDiagnostics";
import { pageDescriptor } from "@/engine/renderAdapter";
import {
  defaultWorkspaceViewport,
  type WorkspaceFitTarget,
  type WorkspaceTool
} from "@/engine/workspaceViewport";
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
  /**
   * Optimistic editing engine override. When omitted, the editor loads
   * the WASM core behind NEXT_PUBLIC_LUMEN_WASM_CORE; until it is active
   * (flag off, module loading/failed, or version mismatch) the editor is
   * in server-only mode — local optimistic editing is unavailable. The
   * legacy TS mirror was retired at Track E W4.
   */
  optimisticEngine?: OptimisticEnginePort;
  /**
   * Edit-persistence queue factory override (tests). The default posts
   * operation batches to /documents/{id}/operations with base_version and
   * reconciles the server scene at drain.
   */
  editQueueFactory?: EditQueueFactory;
}

export type EditQueueFactory = (options: {
  documentId: string;
  localScene: () => Scene;
  onReconcile: (event: ReconcileEvent) => void;
}) => EditQueuePort;

const defaultEditQueueFactory: EditQueueFactory = (options) =>
  createEditQueue({
    apiBaseUrl: process.env.NEXT_PUBLIC_LUMEN_API_BASE_URL ?? "http://localhost:8000",
    ...options
  });

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
  initialScene = emptyScene,
  initialSelectedNodeId = "node_contact_name",
  initialAvailableBrandKits = [],
  brandGovernanceRunner,
  brandCompatibilityRunner,
  agentRunner = defaultAgentRunner,
  exportRunner = defaultExportRunner,
  preflightRunner = defaultPreflightRunner,
  optimisticEngine,
  editQueueFactory = defaultEditQueueFactory
}: EditorAppProps = {}) {
  const [scene, setScene] = useState<Scene>(initialScene);
  // The optimistic engine owns local edit application (Track E): the WASM
  // core, loaded behind the flag (or injected by tests). Until it is
  // active the editor is in server-only mode. `replaceScene` keeps the
  // engine in sync with every non-operation scene replacement (agent
  // drafts, preflight, undo frames).
  const engineRef = useRef<OptimisticEnginePort | null>(optimisticEngine ?? null);
  const sceneRef = useRef<Scene>(scene);
  sceneRef.current = scene;
  const [activePageId, setActivePageId] = useState<PageId | null>(() => firstPageId(initialScene));
  const [selectedNodeId, setSelectedNodeId] = useState<NodeId | null>(initialSelectedNodeId);
  const [diagnostics, setDiagnostics] = useState<Diagnostic[]>([]);
  // When the WASM core is expected (flag on, no injected engine) but fails to
  // activate, the editor is in server-only mode: nothing on the canvas can be
  // selected or edited. That failure was previously only a buried warning
  // diagnostic; this state drives a loud, persistent canvas banner instead —
  // a rendered-but-uneditable design is the worst failure for this product.
  const [engineDisabled, setEngineDisabled] = useState<{
    reason: "load_failed" | "handshake_failed" | "version_mismatch";
    detail: string;
  } | null>(null);
  const [lastOperation, setLastOperation] = useState<Operation | null>(null);
  const [undoStack, setUndoStack] = useState<EditorHistoryFrame[]>([]);
  const [redoStack, setRedoStack] = useState<EditorHistoryFrame[]>([]);
  const [operationHistory, setOperationHistory] = useState<Operation[]>([]);
  const [isBrandGovernanceRunning, setIsBrandGovernanceRunning] = useState(false);
  const [isBrandCompatibilityRunning, setIsBrandCompatibilityRunning] = useState(false);
  const [editorPanelMode, setEditorPanelMode] = useState<EditorPanelMode>("inspector");
  const [agentSidebarWidth, setAgentSidebarWidth] = useState(420);
  const [isAgentRunning, setIsAgentRunning] = useState(false);
  const [agentDraft, setAgentDraft] = useState("");
  const [agentMessages, setAgentMessages] = useState<AgentChatMessage[]>([]);
  const [agentProposal, setAgentProposal] = useState<EditorAgentResult | null>(null);
  // Phase 0c (Moda pattern): a proposed agent turn is applied to the live scene
  // as an ephemeral PREVIEW first. Nothing persists until the human Accepts;
  // Reject restores the pre-preview scene byte-for-byte. While a review is
  // pending, mutating actions (ops, undo/redo, new agent turns) are blocked.
  const [agentPreview, setAgentPreview] = useState<{
    operations: Operation[];
    baseScene: Scene;
    previewScene: Scene;
    baseActivePageId: PageId | null;
    baseSelectedNodeId: NodeId | null;
    view: "before" | "after";
  } | null>(null);
  const [isPreflighting, setIsPreflighting] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [exportResult, setExportResult] = useState<EditorExportResult | null>(null);
  const [exportPanelState, setExportPanelState] = useState<ExportPanelState>(() => {
    const profile = defaultEditorExportProfile();
    return {
      profileName: profile.name,
      scope: "active",
      draftProfile: profile
    };
  });
  const [preflightResult, setPreflightResult] = useState<EditorPreflightResult | null>(null);
  const [workspaceMode, setWorkspaceMode] = useState<"canvas" | "export" | "compare">("canvas");
  const [workspaceViewport, setWorkspaceViewport] = useState(defaultWorkspaceViewport);
  const [workspaceTool, setWorkspaceTool] = useState<WorkspaceTool>("select");
  const [workspaceFitTarget, setWorkspaceFitTarget] = useState<WorkspaceFitTarget>("all");
  const [brandCompatibilityReport, setBrandCompatibilityReport] =
    useState<BrandCompatibilityReport | null>(null);
  const isAgentPanelOpen = editorPanelMode === "agent";
  const hasExportArtifacts = Boolean(exportResult?.artifacts.length);
  const exportWorkspaceMode = workspaceMode === "compare" && hasExportArtifacts ? "compare" : "export";
  const renderedWorkspaceMode = editorPanelMode === "export" ? exportWorkspaceMode : "canvas";
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

  // Activate the WASM core behind the flag, gated on the W5 version
  // handshake: the module's { schema_version, engine_commit } must match
  // the API's /build-info exactly — never mixed-version optimistic
  // editing. Any failure (module missing, API unreachable, mismatch)
  // leaves the editor in server-only mode, which stays functional: agent,
  // preflight, export, and document history all run server-side.
  useEffect(() => {
    if (optimisticEngine || !wasmCoreFlagEnabled()) {
      return;
    }
    let cancelled = false;
    void (async () => {
      const activation = await activateWasmCore();
      if (cancelled) {
        return;
      }
      if (activation.status !== "active") {
        // Loud, always-on signal (any reason: module missing, handshake, or
        // mismatch) — the canvas banner reads this and tells the user how to
        // recover. The diagnostic stays for the two verifiable-mismatch cases.
        setEngineDisabled({ reason: activation.reason, detail: activation.detail });
        if (activation.reason === "version_mismatch" || activation.reason === "handshake_failed") {
          setDiagnostics([
            {
              severity: "warning",
              phase: "operation",
              code: "EDITOR_WASM_VERSION_MISMATCH",
              message: `In-browser engine disabled: ${activation.detail}`,
              subject: { kind: "document" },
              hint: "The editor is in server-only mode until the editor and API run the same engine build."
            }
          ]);
        }
        return;
      }
      try {
        engineRef.current = new WasmEngine(activation.module, sceneRef.current);
        setEngineDisabled(null);
        // Adopt the engine's relaid (whole-tree computed) scene so render
        // geometry is single-source from the moment the engine is live —
        // otherwise the first edit's heuristic delta would merge into a
        // scene carrying server (Skia) or no computed, re-creating the
        // parent/child desync.
        setScene(engineRef.current.scene);
      } catch (error) {
        // Server-only mode; the editor stays functional — but the inert
        // canvas must still announce itself (same banner as load failures).
        setEngineDisabled({
          reason: "load_failed",
          detail: `the engine failed to start: ${error instanceof Error ? error.message : String(error)}`
        });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [optimisticEngine]);

  // An injected engine (tests, and any pre-constructed port) is live at
  // mount; adopt its relaid scene once so the initial render and every
  // later edit share one coherent geometry source.
  useEffect(() => {
    if (optimisticEngine) {
      setScene(optimisticEngine.scene);
    }
    // Only when the injected engine identity changes; setScene is stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [optimisticEngine]);

  /**
   * Replace the scene outside the operation path (agent drafts, preflight
   * results, undo/redo frames). Keeps the optimistic engine's wasm-side
   * state in sync — these are exactly the snapshot-in moments the boundary
   * contract allows.
   */
  const replaceScene = (nextScene: Scene) => {
    const engine = engineRef.current;
    if (engine) {
      // The engine relays out on reset; render its coherent, single-source
      // (local heuristic) geometry rather than the raw input — so reconcile,
      // agent drafts, and undo/redo frames never render server Skia computed
      // directly, which would jump text. With no engine (server-only mode)
      // the raw scene is the only geometry available.
      engine.reset(nextScene);
      setScene(engine.scene);
    } else {
      setScene(nextScene);
    }
  };

  // Wave 3 C4: the CanvasKit canvas installs SkParagraph text metrics straight
  // on the engine (setMeasurements relays out without emitting a delta), so
  // the React scene is re-synced from the engine to render the Skia-faithful
  // geometry. No-op in server-only mode.
  const refreshSceneFromEngine = () => {
    const engine = engineRef.current;
    if (engine) {
      setScene(engine.scene);
    }
  };

  // W3 optimistic pipeline: locally-applied batches persist to the
  // document API in order; the server reconciles at drain. Divergence is a
  // bug signal — the server scene replaces the local one and a diagnostic
  // surfaces.
  const editQueueRef = useRef<EditQueuePort | null>(null);
  const enqueueForPersistence = (operations: Operation[]) => {
    if (!documentId) {
      return;
    }
    const engine = engineRef.current;
    if (!engine || engine.kind !== "wasm") {
      return;
    }
    editQueueRef.current ??= editQueueFactory({
      documentId,
      localScene: () => engineRef.current?.scene ?? sceneRef.current,
      onReconcile: (event) => {
        if (event.serverScene) {
          replaceScene(event.serverScene);
        }
        setDiagnostics([event.diagnostic]);
      }
    });
    editQueueRef.current.enqueueOperations(operations);
  };

  /**
   * Shared post-apply bookkeeping for operations that are already applied to
   * the engine: undo frame, history, persistence. Used by the direct edit path
   * (applyOperations) and by accepting an agent preview (Phase 0c), so both
   * commit identically.
   */
  const commitAppliedOperations = (
    previousScene: Scene,
    operations: Operation[],
    nextScene: Scene
  ) => {
    setLastOperation(operations[operations.length - 1] ?? null);
    setBrandCompatibilityReport(null);
    setPreflightResult(null);
    setExportResult(null);
    setWorkspaceMode("canvas");
    setUndoStack((stack) => [
      ...stack.slice(-49),
      {
        scene: previousScene,
        operations
      }
    ]);
    setRedoStack([]);
    setOperationHistory((history) => [...history, ...operations].slice(-50));
    setDiagnostics([]);
    setScene(nextScene);
    enqueueForPersistence(operations);
  };

  const pendingAgentReviewDiagnostic = (): Diagnostic => ({
    severity: "warning",
    phase: "operation",
    code: "EDITOR_AGENT_REVIEW_PENDING",
    message: "An agent proposal is awaiting review.",
    subject: { kind: "document" },
    hint: "Accept or Reject the agent's changes before editing the design."
  });

  const applyOperations = (operations: Operation[], onAccepted?: (scene: Scene) => void) => {
    if (operations.length === 0) {
      return;
    }
    // Phase 0c: the pending preview owns the engine state; resolving it first
    // keeps Accept/Reject byte-exact (no interleaved manual edits).
    if (agentPreview) {
      setDiagnostics([pendingAgentReviewDiagnostic()]);
      return;
    }
    const engine = engineRef.current;
    if (!engine) {
      setDiagnostics([
        {
          severity: "warning",
          phase: "operation",
          code: "EDITOR_SERVER_ONLY_MODE",
          message: "Local editing requires the WASM engine; the editor is in server-only mode.",
          subject: { kind: "document" },
          hint: wasmCoreFlagEnabled()
            ? "The engine module is unavailable (still loading, failed to load, or version mismatch with the API). Reload the editor or check the /wasm assets."
            : "Enable NEXT_PUBLIC_LUMEN_WASM_CORE to activate in-browser optimistic editing."
        }
      ]);
      return;
    }
    // The engine snapshot, not the React closure: correct even when two
    // batches land in the same render cycle.
    const previousScene = engine.scene;
    const result = engine.applyOperations(operations);
    if (!result.accepted) {
      setDiagnostics([
        {
          severity: "error",
          phase: "operation",
          code: "EDITOR_LOCAL_APPLY",
          message: result.message ?? "Operation was rejected by the editor engine",
          subject: selectedNodeId
            ? {
                kind: "node",
                id: selectedNodeId
              }
            : null,
          hint: "The operation was rejected by the lumen-core engine; the scene is unchanged."
        }
      ]);
      return;
    }

    commitAppliedOperations(previousScene, operations, result.scene);
    onAccepted?.(result.scene);
  };

  const applyOperation = (operation: Operation) => {
    applyOperations([operation]);
  };

  /**
   * Phase 1d: structured edits (detach/re-attach, and future container
   * conversions) run through the engine's shared lumen-core builder and
   * commit with the exact bookkeeping manual edits get — undo frame,
   * history, persistence — so freehand actions are ordinary edits.
   */
  const applyStructuredEditInstruction = (edit: StructuredEdit) => {
    if (agentPreview) {
      setDiagnostics([pendingAgentReviewDiagnostic()]);
      return;
    }
    const engine = engineRef.current;
    if (!engine?.applyStructuredEdit) {
      setDiagnostics([
        {
          severity: "warning",
          phase: "operation",
          code: "EDITOR_SERVER_ONLY_MODE",
          message: "Structured edits require the WASM engine; the editor is in server-only mode.",
          subject: { kind: "document" },
          hint: "Reload the editor or check the /wasm assets."
        }
      ]);
      return;
    }
    const previousScene = engine.scene;
    const outcome = engine.applyStructuredEdit(edit);
    if (!outcome.accepted) {
      setDiagnostics([
        {
          severity: "error",
          phase: "operation",
          code: outcome.code ?? "EDITOR_LOCAL_APPLY",
          message: outcome.message ?? "Structured edit was rejected by the editor engine",
          subject: selectedNodeId ? { kind: "node", id: selectedNodeId } : null,
          hint: "The edit was rejected by the lumen-core engine; the scene is unchanged."
        }
      ]);
      return;
    }
    commitAppliedOperations(previousScene, outcome.operations, outcome.scene);
  };

  // Dev/e2e hook (Phase 1 browser validation): lets browser tests drive
  // canonical operations through the exact pipeline manual edits use
  // (engine apply → undo frame → history → persistence). Never installed
  // in production builds.
  useEffect(() => {
    if (process.env.NODE_ENV === "production" || typeof window === "undefined") {
      return;
    }
    const debugWindow = window as typeof window & { __lumenEditorDebug?: unknown };
    debugWindow.__lumenEditorDebug = {
      applyOperations: (operations: Operation[]) => applyOperations(operations),
      getScene: () => scene,
      getEngineScene: () => engineRef.current?.scene ?? null
    };
    return () => {
      delete debugWindow.__lumenEditorDebug;
    };
  });

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
        documentId,
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

  const undoLastOperation = () => {
    if (agentPreview) {
      setDiagnostics([pendingAgentReviewDiagnostic()]);
      return;
    }
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
    replaceScene(undoFrame.scene);
    setLastOperation(nextHistory[nextHistory.length - 1] ?? null);
    setDiagnostics([]);
    setBrandCompatibilityReport(null);
    setPreflightResult(null);
    setExportResult(null);
    setWorkspaceMode("canvas");
  };

  const redoLastOperation = () => {
    if (agentPreview) {
      setDiagnostics([pendingAgentReviewDiagnostic()]);
      return;
    }
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
    replaceScene(redoFrame.scene);
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
    setEditorPanelMode("diagnostics");
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
        replaceScene(result.scene);
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
      size: normalizePageSize(input),
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
          setEditorPanelMode("diagnostics");
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
        setEditorPanelMode("diagnostics");
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
        setEditorPanelMode("diagnostics");
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
        setEditorPanelMode("diagnostics");
        return;
      }
      case "document":
        return;
    }
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

  const runExport = async (
    profile = defaultEditorExportProfile(),
    pageIds: PageId[] = activePageId ? [activePageId] : []
  ) => runExportForScene(scene, profile, pageIds, { openPreviewTab: true });

  const runExportForScene = async (
    sceneForExport: Scene,
    profile = defaultEditorExportProfile(),
    pageIds: PageId[] = activePageId ? [activePageId] : [],
    options: { openPreviewTab?: boolean } = {}
  ) => {
    const previewWindow = options.openPreviewTab ? openBlankArtifactPreviewWindow() : null;
    setEditorPanelMode("export");
    if (pageIds.length === 0) {
      previewWindow?.close();
      setDiagnostics([
        {
          severity: "warning",
          phase: "export",
          code: "EDITOR_EXPORT_PAGE_REQUIRED",
          message: "Select an artboard before exporting.",
          subject: { kind: "document" },
          hint: "Choose an artboard in the left rail or export all artboards from the Export panel."
        }
      ]);
      return;
    }

    setIsExporting(true);
    setDiagnostics([]);

    try {
      const preflight = await preflightRunner({ scene: sceneForExport });
      setPreflightResult(preflight);
      const preflightDiagnostics = exportPreflightDiagnostics(preflight);
      // Phase 0c: the preflight scene is token-BAKED (brand refs resolved to
      // literal values). It is transient export INPUT only — swapping it into
      // the live scene (the old replaceScene(preflight.scene) here) silently
      // stripped live token bindings from the user's document on every
      // export/agent apply.
      const sceneToExport = preflight.scene ?? sceneForExport;
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
        setWorkspaceMode("export");
        showArtifactInPreviewWindow(
          previewWindow,
          artifactForExportPreview(resultWithPreflightDiagnostics, pageIds)
        );
      } else if (previewWindow) {
        previewWindow.close();
      }
      logExportDiagnostics(combinedDiagnostics);
      setDiagnostics(
        result.status === "ok"
          ? []
          : result.diagnostics.length > 0
            ? result.diagnostics
            : [
                {
                  severity: "error",
                  phase: "export",
                  code: "EDITOR_EXPORT_FAILED",
                  message: "Export failed without returning detailed diagnostics.",
                  subject: { kind: "document" },
                  hint: "Inspect the browser console or API logs for the export request."
                }
              ]
      );
    } catch (error) {
      previewWindow?.close();
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
        <div className="topbar-title">
          <p className="eyebrow">ABM Design Engine</p>
          <h1>{scene.meta.title}</h1>
        </div>
        <div className="topbar-context" aria-label="Active artboard context">
          <div className="topbar-artboard-label">
            <strong>{activePage?.name ?? "No artboard"}</strong>
            <span>
              {activePage ? `${topArtboardSizeLabel(activePage)} · ${Math.round(workspaceViewport.zoom * 100)}%` : "No frame"}
            </span>
          </div>
          <EditorModeSwitch mode={editorPanelMode} onModeChange={setEditorPanelMode} />
        </div>
        <div className="toolbar" aria-label="Editor actions">
          <button type="button" onClick={() => void runPreflight()} disabled={isPreflighting}>
            <FileCheck2 aria-hidden size={16} />
            {isPreflighting ? "Validating" : "Validate"}
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
            diagnostics={diagnostics}
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
        <section className={`center-workspace${editorPanelMode === "export" ? " with-view-toggle" : ""}`}>
          {engineDisabled ? (
            <EngineDisabledBanner reason={engineDisabled.reason} detail={engineDisabled.detail} />
          ) : null}
          {agentPreview ? (
            <div className="agent-review-bar" role="toolbar" aria-label="Review agent changes">
              <div className="agent-review-toggle" role="group" aria-label="Compare agent changes">
                <button
                  type="button"
                  className={agentPreview.view === "before" ? "active" : ""}
                  aria-pressed={agentPreview.view === "before"}
                  onClick={() => setAgentPreviewView("before")}
                >
                  Before
                </button>
                <button
                  type="button"
                  className={agentPreview.view === "after" ? "active" : ""}
                  aria-pressed={agentPreview.view === "after"}
                  onClick={() => setAgentPreviewView("after")}
                >
                  After
                </button>
              </div>
              <span className="agent-review-summary">
                {agentPreview.operations.length} agent change{agentPreview.operations.length === 1 ? "" : "s"}
              </span>
              <button type="button" className="agent-review-reject" onClick={rejectAgentPreview}>
                <X aria-hidden size={15} />
                Reject
              </button>
              <button type="button" className="agent-review-accept" onClick={() => void acceptAgentPreview()}>
                <Check aria-hidden size={15} />
                Accept
              </button>
            </div>
          ) : null}
          {editorPanelMode === "export" ? (
            <div className="view-toggle" aria-label="Export preview mode">
              <button
                type="button"
                className={exportWorkspaceMode === "export" ? "active" : ""}
                onClick={() => setWorkspaceMode("export")}
              >
                Export Preview
              </button>
              <button
                type="button"
                className={exportWorkspaceMode === "compare" ? "active" : ""}
                disabled={!hasExportArtifacts}
                onClick={() => setWorkspaceMode("compare")}
              >
                Compare
              </button>
            </div>
          ) : null}
          {renderedWorkspaceMode === "compare" ? (
            <div className="compare-workspace">
              <div className="compare-pane">
                <div className="compare-heading">Canvas</div>
                <EditorCanvas
                  scene={scene}
                  activePageId={activePageId}
                  selectedNodeId={selectedNodeId}
                  onSelectNode={setSelectedNodeId}
                  onSelectPage={selectPage}
                  onOperations={applyOperations}
                  engine={engineRef.current}
                  diagnostics={diagnostics}
                  workspaceViewport={workspaceViewport}
                  onWorkspaceViewportChange={setWorkspaceViewport}
                  workspaceTool={workspaceTool}
                  onWorkspaceToolChange={setWorkspaceTool}
                  workspaceFitTarget={workspaceFitTarget}
                  onWorkspaceFitTargetChange={setWorkspaceFitTarget}
                  onOpenDiagnostics={() => setEditorPanelMode("diagnostics")}
                  onOpenExport={() => setEditorPanelMode("export")}
                  onSceneRefresh={refreshSceneFromEngine}
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
          ) : renderedWorkspaceMode === "export" ? (
            <ExportPreviewSurface
              scene={scene}
              activePageId={activePageId}
              exportResult={exportResult}
              onSelectSubject={selectDiagnosticSubject}
            />
          ) : (
            <EditorCanvas
              scene={scene}
              activePageId={activePageId}
              selectedNodeId={selectedNodeId}
              onSelectNode={setSelectedNodeId}
              onSelectPage={selectPage}
              onOperations={applyOperations}
              engine={engineRef.current}
              diagnostics={diagnostics}
              workspaceViewport={workspaceViewport}
              onWorkspaceViewportChange={setWorkspaceViewport}
              workspaceTool={workspaceTool}
              onWorkspaceToolChange={setWorkspaceTool}
              workspaceFitTarget={workspaceFitTarget}
              onWorkspaceFitTargetChange={setWorkspaceFitTarget}
              onOpenDiagnostics={() => setEditorPanelMode("diagnostics")}
              onOpenExport={() => setEditorPanelMode("export")}
              onSceneRefresh={refreshSceneFromEngine}
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
          aria-label={rightSidebarLabelForMode(editorPanelMode)}
        >
          {editorPanelMode === "agent" ? (
            <AgentChatPanel
              messages={agentMessages}
              draft={agentDraft}
              isRunning={isAgentRunning}
              proposal={agentProposal}
              pendingReview={agentPreview !== null}
              activePageId={activePageId}
              selectedNodeId={selectedNodeId}
              diagnostics={diagnostics}
              onDraftChange={setAgentDraft}
              onSend={(prompt) => void sendAgentPrompt(prompt)}
              onApplyProposal={applyAgentProposal}
              onAcceptProposal={() => void acceptAgentPreview()}
              onRejectProposal={rejectAgentPreview}
            />
          ) : editorPanelMode === "export" ? (
            <ExportPanel
              scene={scene}
              activePageId={activePageId}
              exportResult={exportResult}
              isExporting={isExporting}
              onExport={(profile, pageIds) => void runExport(profile, pageIds)}
              onSaveProfile={(profile) => applyOperation(upsertExportProfile(profile))}
              onRemoveProfile={(name) => applyOperation(removeExportProfile(name))}
              panelState={exportPanelState}
              onPanelStateChange={setExportPanelState}
            />
          ) : editorPanelMode === "diagnostics" ? (
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
                apiBaseUrl={process.env.NEXT_PUBLIC_LUMEN_API_BASE_URL ?? "http://localhost:8000"}
                onOperation={applyOperation}
                onOperations={applyOperations}
                onStructuredEdit={applyStructuredEditInstruction}
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
                panelState={exportPanelState}
                onPanelStateChange={setExportPanelState}
              />
              <OperationHistoryPanel operations={operationHistory} redoCount={redoStack.length} />
              <AssetBrowserPanel
                apiBaseUrl={process.env.NEXT_PUBLIC_LUMEN_API_BASE_URL ?? "http://localhost:8000"}
                selectedNodeId={selectedNodeId}
                selectedNodePlacement={selectedNode?.asset_placement ?? null}
                onOperations={applyOperations}
              />
              <WorstCasePreviewPanel
                apiBaseUrl={process.env.NEXT_PUBLIC_LUMEN_API_BASE_URL ?? "http://localhost:8000"}
                scene={scene}
              />
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

function EditorModeSwitch({
  mode,
  onModeChange
}: {
  mode: EditorPanelMode;
  onModeChange: (mode: EditorPanelMode) => void;
}) {
  return (
    <div className="top-mode-switch" aria-label="Editor mode">
      {EDITOR_PANEL_MODES.map((item) => (
        <button
          key={item.mode}
          type="button"
          className={mode === item.mode ? "active" : undefined}
          aria-label={item.ariaLabel}
          aria-pressed={mode === item.mode}
          onClick={() => onModeChange(item.mode)}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}

function topArtboardSizeLabel(page: Page): string {
  const descriptor = pageDescriptor(page);
  return `${formatTopbarDimension(descriptor.width)} x ${formatTopbarDimension(descriptor.height)} pt`;
}

function formatTopbarDimension(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1).replace(/\.0$/, "");
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

function artifactForExportPreview(
  result: EditorExportResult,
  pageIds: PageId[]
): EditorExportArtifact | null {
  return (
    result.artifacts.find((artifact) => artifact.page_id && pageIds.includes(artifact.page_id)) ??
    result.artifacts[0] ??
    null
  );
}

function logExportDiagnostics(diagnostics: Diagnostic[]): void {
  if (diagnostics.length === 0 || typeof console === "undefined") {
    return;
  }
  console.info(
    "[lumen-export-preview] diagnostics",
    diagnostics.map((diagnostic) => ({
      severity: diagnostic.severity,
      code: diagnostic.code,
      message: diagnostic.message,
      subject: diagnostic.subject
    }))
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

/** Reason-specific copy for the server-only-mode canvas banner. */
function engineDisabledCopy(reason: "load_failed" | "handshake_failed" | "version_mismatch"): {
  headline: string;
  fix: string;
} {
  switch (reason) {
    case "version_mismatch":
      return {
        headline: "The in-browser engine is a different build than the API.",
        fix: "Rebuild it to match, then hard-refresh (⌘⇧R):"
      };
    case "handshake_failed":
      return {
        headline: "Couldn’t verify the in-browser engine against the API.",
        fix: "Start the API, rebuild the engine, then hard-refresh (⌘⇧R):"
      };
    case "load_failed":
    default:
      return {
        headline: "The in-browser engine failed to load.",
        fix: "Build it, then hard-refresh (⌘⇧R):"
      };
  }
}

/**
 * Loud, persistent banner shown when the WASM engine is expected but not
 * active (server-only mode). Without the live engine the canvas cannot
 * hit-test, so nothing can be selected or edited — a failure that must never
 * again read as "the editor is silently broken."
 */
function EngineDisabledBanner({
  reason,
  detail
}: {
  reason: "load_failed" | "handshake_failed" | "version_mismatch";
  detail: string;
}) {
  const copy = engineDisabledCopy(reason);
  return (
    <div className="engine-disabled-banner" role="alert" data-testid="engine-disabled-banner">
      <AlertTriangle aria-hidden size={18} className="engine-disabled-banner-icon" />
      <div className="engine-disabled-banner-body">
        <strong>Canvas editing is disabled</strong>
        <span>
          {copy.headline} You can’t select or edit anything on the canvas until the in-browser
          engine is running. {copy.fix}
        </span>
        <code>
          <span className="engine-disabled-banner-cmd">npm run build:wasm</span>
          {` · ${detail}`}
        </code>
      </div>
    </div>
  );
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
