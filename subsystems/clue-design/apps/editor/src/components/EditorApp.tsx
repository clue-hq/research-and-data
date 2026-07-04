"use client";

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type Dispatch,
  type PointerEvent as ReactPointerEvent,
  type SetStateAction
} from "react";
import { AlertTriangle, Bot, Check, Download, FileCheck2, History, PanelRightClose, RotateCcw, RotateCw, X } from "lucide-react";
import { AgentChatPanel } from "./AgentChatPanel";
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
  createStreamingAgentRunner,
  subscribeToAgentRun,
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
import { createDocument, type CreatedDocument } from "@/engine/documentStore";
import { editorApiBaseUrl } from "@/engine/editorConfig";
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
import {
  agentTurnRunningDiagnostic,
  pendingAgentReviewDiagnostic,
  useAgentTurn
} from "@/hooks/useAgentTurn";
import { useTargetChips } from "@/hooks/useTargetChips";

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
  /**
   * Phase 2a: document auto-creation override (tests). With no documentId,
   * the first persisting action creates a document server-side (Moda's
   * "every canvas is a doc") and the editor adopts the returned id.
   */
  documentCreator?: (scene: Scene) => Promise<CreatedDocument>;
}

export type EditQueueFactory = (options: {
  documentId: string;
  localScene: () => Scene;
  onReconcile: (event: ReconcileEvent) => void;
}) => EditQueuePort;

const defaultEditQueueFactory: EditQueueFactory = (options) =>
  createEditQueue({
    apiBaseUrl: editorApiBaseUrl(),
    ...options
  });

export interface EditorHistoryFrame {
  scene: Scene;
  operations: Operation[];
}

const defaultExportRunner = createApiExportRunner({
  apiBaseUrl: editorApiBaseUrl()
});

const defaultPreflightRunner = createApiPreflightRunner({
  apiBaseUrl: editorApiBaseUrl()
});

const defaultAgentRunner = createStreamingAgentRunner({
  apiBaseUrl: editorApiBaseUrl()
});

// 2b resume: rejoin an in-flight run's SSE stream after a tab reload. Bound to
// the same base URL as the default runner; only fires when a run id survives
// in sessionStorage, so injected test runners never reach it.
const defaultResumeRun = (
  runId: string,
  onEvent: Parameters<typeof subscribeToAgentRun>[0]["onEvent"]
) => subscribeToAgentRun({ apiBaseUrl: editorApiBaseUrl(), runId, onEvent });

const defaultDocumentCreator = (scene: Scene) =>
  createDocument({ apiBaseUrl: editorApiBaseUrl() }, scene);

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
  editQueueFactory = defaultEditQueueFactory,
  documentCreator = defaultDocumentCreator
}: EditorAppProps = {}) {
  const [scene, setScene] = useState<Scene>(initialScene);
  // Phase 2a: document identity is state, not just a prop — an unsaved canvas
  // adopts a server-minted id at its first persisting action (auto-create).
  const [activeDocumentId, setActiveDocumentId] = useState<string | null>(documentId ?? null);
  const activeDocumentIdRef = useRef<string | null>(activeDocumentId);
  activeDocumentIdRef.current = activeDocumentId;
  const documentCreationRef = useRef<Promise<string | null> | null>(null);
  // The optimistic engine owns local edit application (Track E): the WASM
  // core, loaded behind the flag (or injected by tests). Until it is
  // active the editor is in server-only mode. `replaceScene` keeps the
  // engine in sync with every non-operation scene replacement (agent
  // drafts, preflight, undo frames).
  const engineRef = useRef<OptimisticEnginePort | null>(optimisticEngine ?? null);
  const sceneRef = useRef<Scene>(scene);
  sceneRef.current = scene;
  const [activePageId, setActivePageId] = useState<PageId | null>(() => firstPageId(initialScene));
  // Selection is a SET: shift/Cmd+click builds a multi-node selection whose
  // members become the agent's edit-target chips. The PRIMARY selection (the
  // most recently clicked node) is derived from the set and drives every
  // single-node concern unchanged — inspector, keyboard, transform handles.
  // Multi-drag/transform is intentionally out of scope; the set is for
  // targeting, and secondary members render as plain outlines (no handles).
  const [selectedNodeIds, setSelectedNodeIds] = useState<NodeId[]>(
    initialSelectedNodeId ? [initialSelectedNodeId] : []
  );
  const selectedNodeId =
    selectedNodeIds.length > 0 ? selectedNodeIds[selectedNodeIds.length - 1] : null;
  const selectNode = (nodeId: NodeId | null, additive = false) => {
    if (!nodeId) {
      setSelectedNodeIds([]);
      return;
    }
    if (additive) {
      // shift/Cmd+click toggles: add if absent, remove if already selected
      // (shift+click a chipped node again to drop it from the group).
      setSelectedNodeIds((current) =>
        current.includes(nodeId)
          ? current.filter((id) => id !== nodeId)
          : [...current, nodeId]
      );
      return;
    }
    setSelectedNodeIds([nodeId]);
  };
  // Back-compat adapter for consumers that still think single-selection
  // (useAgentTurn's preview flow, diagnostic jumps, page changes): a plain
  // set collapses the selection to that one node; a functional updater sees
  // the current primary. Keeps ~10 existing setSelectedNodeId(...) calls
  // untouched.
  const setSelectedNodeId: Dispatch<SetStateAction<NodeId | null>> = (action) => {
    setSelectedNodeIds((current) => {
      const primary = current.length > 0 ? current[current.length - 1] : null;
      const next =
        typeof action === "function"
          ? (action as (prev: NodeId | null) => NodeId | null)(primary)
          : action;
      return next ? [next] : [];
    });
  };
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
    // Drop any selected node (primary or secondary) that no longer exists —
    // deleting a node also unchips it.
    setSelectedNodeIds((current) => {
      const next = current.filter((id) => scene.nodes[id]);
      return next.length === current.length ? current : next;
    });
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
  const ensureEditQueue = (queueDocumentId: string): EditQueuePort => {
    editQueueRef.current ??= editQueueFactory({
      documentId: queueDocumentId,
      localScene: () => engineRef.current?.scene ?? sceneRef.current,
      onReconcile: (event) => {
        if (event.serverScene) {
          replaceScene(event.serverScene);
        }
        setDiagnostics([event.diagnostic]);
      }
    });
    return editQueueRef.current;
  };

  /**
   * Phase 2a: adopt a freshly-created document id. Local scenes carry the
   * shared `doc_untitled` placeholder id; the server minted the real one, so
   * every local copy of the scene (engine, React state, undo/redo frames)
   * must switch to it — otherwise the first persistence reconcile flags a
   * false divergence on `meta.id`. The URL gains `?document=<id>` so a
   * reload reopens this document.
   */
  const adoptCreatedDocument = (newDocumentId: string) => {
    const patchSceneId = (input: Scene): Scene => ({
      ...input,
      meta: { ...input.meta, id: newDocumentId }
    });
    activeDocumentIdRef.current = newDocumentId;
    setActiveDocumentId(newDocumentId);
    const engine = engineRef.current;
    if (engine) {
      engine.reset(patchSceneId(engine.scene));
      setScene(engine.scene);
    } else {
      setScene((current) => patchSceneId(current));
    }
    setUndoStack((stack) => stack.map((frame) => ({ ...frame, scene: patchSceneId(frame.scene) })));
    setRedoStack((stack) => stack.map((frame) => ({ ...frame, scene: patchSceneId(frame.scene) })));
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      url.searchParams.set("document", newDocumentId);
      window.history.replaceState(null, "", url);
    }
  };

  const enqueueForPersistence = (
    previousScene: Scene,
    operations: Operation[],
    nextScene: Scene
  ) => {
    const engine = engineRef.current;
    if (!engine || engine.kind !== "wasm") {
      return;
    }
    const existingDocumentId = activeDocumentIdRef.current;
    if (existingDocumentId) {
      ensureEditQueue(existingDocumentId).enqueueOperations(operations);
      return;
    }
    // Phase 2a auto-create: the first persisting action turns this canvas
    // into a document. Batches that land while creation is in flight ride
    // behind it in order.
    if (documentCreationRef.current) {
      documentCreationRef.current = documentCreationRef.current.then((createdId) => {
        if (createdId) {
          ensureEditQueue(createdId).enqueueOperations(operations);
        }
        return createdId;
      });
      return;
    }
    // An empty canvas is not a creatable document (LUMV0100: a scene needs at
    // least one page); seed from the post-op scene instead and skip
    // enqueueing the triggering batch — for that case the creation IS its
    // persistence. If even the post-op scene is still empty (say, a title
    // edit before any artboard exists), stay local: the scene carries those
    // changes into the eventual creation seed.
    const seedFromPrevious = Object.keys(previousScene.pages).length > 0;
    const seedScene = seedFromPrevious ? previousScene : nextScene;
    if (Object.keys(seedScene.pages).length === 0) {
      return;
    }
    documentCreationRef.current = documentCreator(seedScene)
      .then((created) => {
        adoptCreatedDocument(created.documentId);
        if (seedFromPrevious) {
          ensureEditQueue(created.documentId).enqueueOperations(operations);
        }
        return created.documentId;
      })
      .catch((error: unknown) => {
        // Editing continues locally; the next persisting action retries.
        documentCreationRef.current = null;
        setDiagnostics([
          {
            severity: "error",
            phase: "operation",
            code: "EDITOR_DOCUMENT_CREATE_FAILED",
            message:
              error instanceof Error
                ? `Creating a document for this design failed: ${error.message}`
                : "Creating a document for this design failed.",
            subject: { kind: "document" },
            hint: "Local editing continues, but nothing is persisted yet. Check the API connection — the next edit retries."
          }
        ]);
        return null;
      });
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
    enqueueForPersistence(previousScene, operations, nextScene);
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
        ...(activeDocumentId ? { documentId: activeDocumentId } : {})
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

  // 2c selection chips: the agent's edit targets mirror the selection set.
  // Removing a chip de-selects that node; Clear de-selects all.
  const { chips: targetChips, targetNodeIds } = useTargetChips(scene, selectedNodeIds);
  const removeTargetChip = (nodeId: NodeId) => selectNode(nodeId, true);
  const clearTargetChips = () => selectNode(null);

  // The agent-turn state machine (run → propose → preview → Accept/Reject,
  // plus the message queue) lives in useAgentTurn. The deps object is
  // rebuilt every render so the hook's callbacks always close over the
  // current scene/selection — exactly like the closures they replaced.
  // applyOperations is passed through a lazy wrapper: it is defined below
  // this call because it guards on the turn state the hook owns (the other
  // half of the canvas lock), and it only runs from event handlers.
  const {
    isAgentRunning,
    agentDraft,
    setAgentDraft,
    agentMessages,
    agentProposal,
    agentPreview,
    queuedAgentMessages,
    runEvents,
    sendAgentPrompt,
    queueAgentMessage,
    removeQueuedAgentMessage,
    applyAgentProposal,
    acceptAgentPreview,
    rejectAgentPreview,
    setAgentPreviewView
  } = useAgentTurn({
    agentRunner,
    resumeRun: defaultResumeRun,
    engineRef,
    scene,
    activeDocumentId,
    activePageId,
    selectedNodeId,
    targetNodeIds,
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
    applyOperations: (operations, onAccepted) => applyOperations(operations, onAccepted)
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
    if (isAgentRunning) {
      setDiagnostics([agentTurnRunningDiagnostic()]);
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
    if (isAgentRunning) {
      setDiagnostics([agentTurnRunningDiagnostic()]);
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

  const undoLastOperation = () => {
    if (agentPreview) {
      setDiagnostics([pendingAgentReviewDiagnostic()]);
      return;
    }
    if (isAgentRunning) {
      setDiagnostics([agentTurnRunningDiagnostic()]);
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
    if (isAgentRunning) {
      setDiagnostics([agentTurnRunningDiagnostic()]);
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
          <button
            type="button"
            onClick={undoLastOperation}
            disabled={undoStack.length === 0 || isAgentRunning || agentPreview !== null}
          >
            <RotateCcw aria-hidden size={16} />
            Undo
          </button>
          <button
            type="button"
            onClick={redoLastOperation}
            disabled={redoStack.length === 0 || isAgentRunning || agentPreview !== null}
          >
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
            selectedNodeIds={selectedNodeIds}
            onSelectNode={selectNode}
            onOperation={applyOperation}
          />
        </div>
        <section className={`center-workspace${editorPanelMode === "export" ? " with-view-toggle" : ""}`}>
          {engineDisabled ? (
            <EngineDisabledBanner reason={engineDisabled.reason} detail={engineDisabled.detail} />
          ) : null}
          {isAgentRunning && !agentPreview ? (
            <div
              className="agent-designing-banner"
              role="status"
              data-testid="agent-designing-banner"
            >
              <Bot aria-hidden size={15} />
              <span>Agent is designing — please wait to edit</span>
              <span className="agent-designing-dots" aria-hidden>
                <i />
                <i />
                <i />
              </span>
            </div>
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
                  selectedNodeIds={selectedNodeIds}
                  onSelectNode={selectNode}
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
              selectedNodeIds={selectedNodeIds}
              onSelectNode={selectNode}
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
              queuedMessages={queuedAgentMessages}
              runEvents={runEvents}
              targetChips={targetChips}
              activePageId={activePageId}
              selectedNodeId={selectedNodeId}
              diagnostics={diagnostics}
              onRemoveTargetChip={removeTargetChip}
              onClearTargetChips={clearTargetChips}
              onDraftChange={setAgentDraft}
              onSend={(prompt) => void sendAgentPrompt(prompt)}
              onQueueMessage={queueAgentMessage}
              onRemoveQueuedMessage={removeQueuedAgentMessage}
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
                apiBaseUrl={editorApiBaseUrl()}
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
                apiBaseUrl={editorApiBaseUrl()}
                selectedNodeId={selectedNodeId}
                selectedNodePlacement={selectedNode?.asset_placement ?? null}
                onOperations={applyOperations}
              />
              <WorstCasePreviewPanel apiBaseUrl={editorApiBaseUrl()} scene={scene} />
              {activeDocumentId ? (
                <HistoryPanel apiBaseUrl={editorApiBaseUrl()} documentId={activeDocumentId} />
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
