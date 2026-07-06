"use client";

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type CSSProperties,
  type Dispatch,
  type SetStateAction
} from "react";
import { Bot, Check, Download, History, RotateCcw, RotateCw, X } from "lucide-react";
import { AgentChatPanel, type AcceptedTurnRecord } from "./AgentChatPanel";
import {
  DiagnosticsAlertPill,
  EditableDocumentTitle,
  EditorModeSwitch,
  EngineDisabledBanner,
  OperationHistoryPanel,
  topArtboardSizeLabel
} from "./EditorChrome";
import { BrandKitPanel } from "./BrandKitPanel";
import { EditorCanvas } from "./canvas/EditorCanvas";
import { ExportPanel } from "./ExportPanel";
import { ExportPreviewSurface } from "./ExportPreviewSurface";
import { AssetBrowserPanel } from "./AssetBrowserPanel";
import { WorstCasePreviewPanel } from "./WorstCasePreviewPanel";
import { InspectorPanel } from "./InspectorPanel";
import { TextToolbar } from "./TextToolbar";
import { LayerPanel } from "./LayerPanel";
import { PageRail } from "./PageRail";
import { ValidationPanel } from "./ValidationPanel";
import appMark from "../app/icon.svg";
import { ExportMenu } from "./ExportMenu";
import { VersionHistoryDialog } from "./HistoryPanel";
import { downloadDataUrl } from "./exportArtifactActions";
import { emptyScene } from "@/fixtures/emptyScene";
import type { BrandCompatibilityRunner } from "@/engine/brandCompatibility";
import type { BrandGovernanceRunner } from "@/engine/brandGovernance";
import {
  createStreamingAgentRunner,
  subscribeToAgentRun,
  type EditorAgentRunner
} from "@/engine/agentRunner";
import type {
  BrandKitSummary,
  Diagnostic,
  DiagnosticSubject,
  NodeId,
  Operation,
  Page,
  PageId,
  Scene
} from "@/engine/contracts";
import {
  createDocument,
  fetchBrandKitDetail,
  revertDocument,
  saveAgentInstructions,
  saveLayoutManagedEditing,
  type CreatedDocument,
  type RevertOutcome
} from "@/engine/documentStore";
import { editorApiBaseUrl } from "@/engine/editorConfig";
import {
  buildTokenColorMap,
  PLATFORM_DEFAULT_BRAND_KIT_ID,
  type BrandKitDetailPayload
} from "@/engine/tokenColors";
import {
  setTokenColorMap,
  subscribeTokenColors,
  tokenColorsGenerationSnapshot
} from "@/engine/renderAdapter";
import { postTurnSuggestions } from "@/engine/agentSuggestions";
import { mergeStickyDiagnostics } from "@/engine/diagnosticsPolicy";
import { createEditQueue, type EnqueueOptions } from "@/engine/editQueue";
import { rightSidebarLabelForMode, type EditorPanelMode } from "@/engine/editorModes";
import { arrowNudge, isEditableEventTarget, keyboardArrangeAction, keyboardHistoryAction } from "@/engine/editorKeyboard";
import { duplicatePageOperations, uniquePageId } from "@/engine/pageDuplication";
import {
  activateWasmCore,
  wasmCoreFlagEnabled,
  WasmEngine,
  type OptimisticEnginePort
} from "@/engine/wasmEngine";
import { createApiExportRunner, type EditorExportRunner } from "@/engine/exportRunner";
import { createApiPreflightRunner, type EditorPreflightRunner } from "@/engine/preflightRunner";
import {
  addPage,
  removeExportProfile,
  removeNode,
  removePage,
  updateDocumentBrand,
  updateDocumentTitle,
  updateNodeTransform,
  upsertExportProfile
} from "@/engine/operations";
import { normalizePageSize } from "@/engine/pageGeometry";
import {
  groupEdit,
  mintGroupId,
  moveAfterEdit,
  moveBeforeEdit,
  ungroupEdit,
  type StructuredEdit
} from "@/engine/structuredEdits";
import { editorRenderDiagnostics } from "@/engine/renderDiagnostics";
import {
  canGroupNodes,
  canUngroupNode,
  clampNodeTransformToParentBounds,
  firstPageId,
  getNode,
  isNodeLayoutManaged,
  nodeIdForAsset,
  pageIdForNode,
  siblingArrangeInfo
} from "@/engine/sceneQueries";
import {
  agentTurnRunningDiagnostic,
  pendingAgentReviewDiagnostic,
  useAgentTurn
} from "@/hooks/useAgentTurn";
import { useAgentInstructions } from "@/hooks/useAgentInstructions";
import { useLayoutManagedEditing } from "@/hooks/useLayoutManagedEditing";
import { useMarginGuides } from "@/hooks/useMarginGuides";
import { useBrandChecks } from "@/hooks/useBrandChecks";
import { useTurnNotification } from "@/hooks/useTurnNotification";
import { useDocumentSync, type EditQueueFactory } from "@/hooks/useDocumentSync";
import { useWorkspaceChrome } from "@/hooks/useWorkspaceChrome";
import { useEditHistory } from "@/hooks/useEditHistory";
import { useExportPreflight } from "@/hooks/useExportPreflight";
import { useTargetChips } from "@/hooks/useTargetChips";
import { compareActiveDiagnostic, useTurnCheckpoints } from "@/hooks/useTurnCheckpoints";

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
  /**
   * Checkpoint revert override (tests). The default POSTs
   * /documents/{id}/revert?checkpoint=… and fetches the reverted scene.
   */
  revertRunner?: (documentId: string, checkpoint: string) => Promise<RevertOutcome>;
  /**
   * Full brand-kit token detail fetch override (tests). The default GETs
   * /brand-kits/{id} for the document's effective kit (attached, or the
   * platform default when none is attached) to build the canvas
   * token-color map — see `useEffect` below and `engine/tokenColors.ts`.
   */
  brandKitDetailFetcher?: (brandKitId: string) => Promise<BrandKitDetailPayload | null>;
  /** 2e: the document's standing agent instructions, loaded with it. */
  initialAgentInstructions?: string | null;
  /** 2e: instructions persistence override (tests). */
  agentInstructionsSaver?: (
    documentId: string,
    instructions: string | null
  ) => Promise<string | null>;
  /** Advanced per-document opt-out from handoff-absolute, loaded with the
   * document: keep agent auto-layout live (skip both freeze seams). */
  initialLayoutManagedEditing?: boolean;
  /** Layout-managed-editing persistence override (tests). */
  layoutManagedEditingSaver?: (documentId: string, enabled: boolean) => Promise<boolean>;
}

// Re-exported so tests keep importing it from here; the type lives with the
// persistence hook now.
export type { EditQueueFactory } from "@/hooks/useDocumentSync";

const defaultEditQueueFactory: EditQueueFactory = (options) =>
  createEditQueue({
    apiBaseUrl: editorApiBaseUrl(),
    ...options
  });


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

const defaultRevertRunner = (documentId: string, checkpoint: string) =>
  revertDocument({ apiBaseUrl: editorApiBaseUrl() }, documentId, checkpoint);

const defaultBrandKitDetailFetcher = (brandKitId: string) =>
  fetchBrandKitDetail({ apiBaseUrl: editorApiBaseUrl() }, brandKitId);

const defaultAgentInstructionsSaver = (documentId: string, instructions: string | null) =>
  saveAgentInstructions({ apiBaseUrl: editorApiBaseUrl() }, documentId, instructions);

const defaultLayoutManagedEditingSaver = (documentId: string, enabled: boolean) =>
  saveLayoutManagedEditing({ apiBaseUrl: editorApiBaseUrl() }, documentId, enabled);

/** Models offered in the composer's model chip. Values are runtime model ids
 * (LUMEN_AGENT_MODEL format, OpenRouter-routed); "" = the runtime default. */
const AGENT_MODEL_OPTIONS = [
  { value: "", label: "Auto", hint: "default" },
  { value: "openai:anthropic/claude-opus-4.8", label: "Opus 4.8", hint: "quality" },
  { value: "openai:anthropic/claude-sonnet-5", label: "Sonnet 5", hint: "balanced" },
  { value: "openai:google/gemini-3-pro", label: "Gemini 3 Pro", hint: "fast" }
];

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
  documentCreator = defaultDocumentCreator,
  revertRunner = defaultRevertRunner,
  brandKitDetailFetcher = defaultBrandKitDetailFetcher,
  initialAgentInstructions = null,
  agentInstructionsSaver = defaultAgentInstructionsSaver,
  initialLayoutManagedEditing = false,
  layoutManagedEditingSaver = defaultLayoutManagedEditingSaver
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
  const [diagnostics, rawSetDiagnostics] = useState<Diagnostic[]>([]);
  // Every diagnostics write flows through the sticky-merge policy: a
  // persistence-class error (edits not saving, reconcile divergence, failed
  // revert) survives unrelated overwrites instead of losing the last-writer
  // race to cosmetic flows. See engine/diagnosticsPolicy.
  const setDiagnostics: Dispatch<SetStateAction<Diagnostic[]>> = (action) =>
    rawSetDiagnostics((current) =>
      mergeStickyDiagnostics(
        current,
        typeof action === "function" ? action(current) : action
      )
    );
  // The one way to CLEAR a sticky diagnostic: the flow that resolved the
  // condition says so explicitly (bypasses the sticky merge).
  const resolveDiagnosticCode = (code: string) =>
    rawSetDiagnostics((current) =>
      current.filter((diagnostic) => diagnostic.code !== code)
    );
  // When the WASM core is expected (flag on, no injected engine) but fails to
  // activate, the editor is in server-only mode: nothing on the canvas can be
  // selected or edited. That failure was previously only a buried warning
  // diagnostic; this state drives a loud, persistent canvas banner instead —
  // a rendered-but-uneditable design is the worst failure for this product.
  const [engineDisabled, setEngineDisabled] = useState<{
    reason: "load_failed" | "handshake_failed" | "version_mismatch";
    detail: string;
  } | null>(null);
  // Data-refresh signal (not workflow policy): the image-edit gate reports a
  // kept asset (Accept / Save as new) and the asset library refetches.
  const [assetLibraryRefreshToken, setAssetLibraryRefreshToken] = useState(0);
  const notifyAssetLibraryChanged = () => setAssetLibraryRefreshToken((t) => t + 1);
  // Topbar floats (presentation state): the export popover and the version
  // history dialog.
  const [isExportMenuOpen, setIsExportMenuOpen] = useState(false);
  const [isVersionHistoryOpen, setIsVersionHistoryOpen] = useState(false);
  const exportMenuAnchorRef = useRef<HTMLDivElement | null>(null);
  // Set when an export was started from the topbar menu: its artifacts
  // download directly (moda's Download) instead of opening the Export panel.
  const downloadAfterExportRef = useRef(false);
  // Model override for agent turns ("" = runtime default).
  const [agentModel, setAgentModel] = useState("");
  // Workspace chrome (panel mode, workspace mode, viewport/tool, sidebar
  // width + resizer) lives in useWorkspaceChrome — presentation state only.
  const {
    editorPanelMode,
    setEditorPanelMode,
    agentSidebarWidth,
    workspaceMode,
    setWorkspaceMode,
    workspaceViewport,
    setWorkspaceViewport,
    workspaceTool,
    setWorkspaceTool,
    workspaceFitTarget,
    setWorkspaceFitTarget,
    startAgentSidebarResize
  } = useWorkspaceChrome();
  const isAgentPanelOpen = editorPanelMode === "agent";
  const selectedNode = useMemo(() => getNode(scene, selectedNodeId), [scene, selectedNodeId]);
  const activePage = activePageId ? scene.pages[activePageId] ?? null : null;
  const brandDiagnostics = diagnostics.filter((diagnostic) => diagnostic.phase === "brand");
  // K0.5: re-render when the async brand-kit token map lands, so token
  // swatches, the Konva fallback canvas (descriptors built in render), and
  // the render diagnostics below all pick up real kit values — the map is a
  // module-level registry, so nothing else re-renders on its arrival.
  const tokenColorsGeneration = useSyncExternalStore(
    subscribeTokenColors,
    tokenColorsGenerationSnapshot,
    tokenColorsGenerationSnapshot
  );
  const renderDiagnostics = useMemo(
    () => editorRenderDiagnostics(scene, activePageId),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- tokenColorsGeneration
    // is deliberately a dep: the diagnostics consult the module-level map to
    // report only tokens actually on the heuristic fallback.
    [activePageId, scene, tokenColorsGeneration]
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

  // Brand Kit checks (effective kit, newer-version target, governance and
  // compatibility flows) live in useBrandChecks. Deps rebuilt per render.
  const {
    isBrandGovernanceRunning,
    isBrandCompatibilityRunning,
    brandCompatibilityReport,
    setBrandCompatibilityReport,
    effectiveBrandKit,
    compatibilityTarget,
    runBrandGovernance,
    runBrandCompatibility
  } = useBrandChecks({
    scene,
    availableBrandKits: initialAvailableBrandKits,
    brandGovernanceRunner,
    brandCompatibilityRunner,
    setDiagnostics
  });

  // Canvas token-paint fidelity: resolves $surface.page/$surface.card/…
  // fills to the document's real brand-kit values instead of the renderer's
  // string-heuristic fallback (every "surface" token painting one cream).
  // Precedence: the attached kit's id when the document has one, else the
  // platform default kit — mirroring server-side token resolution/export,
  // which is exactly where the canvas previously diverged from it. Sets the
  // module-level map in `engine/renderAdapter.ts` (see its doc comment for
  // why a registry rather than threading); both canvas backends and the
  // compare-pane/preview instances read that same module state, so this one
  // effect covers all of them. Keyed on the attached kit ref (not
  // `availableBrandKits` — the fetch resolves by id, it doesn't read that
  // list) so re-attaching a different kit refreshes the map. A failed fetch
  // leaves the map from the last success (or empty on first load), which
  // falls through to the pre-existing heuristic — never blocks rendering.
  useEffect(() => {
    let cancelled = false;
    const brandKitId = scene.meta.brand_kit?.id ?? PLATFORM_DEFAULT_BRAND_KIT_ID;
    brandKitDetailFetcher(brandKitId)
      .then((detail) => {
        if (!cancelled) {
          setTokenColorMap(buildTokenColorMap(detail));
        }
      })
      .catch(() => {
        // API-down or kit not found: leave the canvas on whatever map (or
        // heuristic) it already had rather than block rendering.
      });
    return () => {
      cancelled = true;
    };
  }, [scene.meta.brand_kit, brandKitDetailFetcher]);

  // The export + preflight leg (Validate/Export flows, their in-flight
  // flags and results) lives in useExportPreflight. Deps rebuilt per
  // render; activeDocumentId crosses via a lazy getter because
  // useDocumentSync is wired below (it needs the history setters).
  const {
    isPreflighting,
    isExporting,
    exportResult,
    setExportResult,
    exportPanelState,
    setExportPanelState,
    preflightResult,
    setPreflightResult,
    runExport,
    runExportForScene,
    runPreflight
  } = useExportPreflight({
    exportRunner,
    preflightRunner,
    scene,
    activePageId,
    getActiveDocumentId: () => activeDocumentId,
    replaceScene,
    setDiagnostics,
    setEditorPanelMode,
    setWorkspaceMode
  });
  const hasExportArtifacts = Boolean(exportResult?.artifacts.length);
  const exportWorkspaceMode = workspaceMode === "compare" && hasExportArtifacts ? "compare" : "export";
  const renderedWorkspaceMode = editorPanelMode === "export" ? exportWorkspaceMode : "canvas";

  // Topbar export menu: exports it started download their artifacts directly
  // (moda's Download button) instead of routing through the Export panel.
  useEffect(() => {
    if (!downloadAfterExportRef.current || !exportResult) {
      return;
    }
    downloadAfterExportRef.current = false;
    if (exportResult.status === "ok") {
      for (const artifact of exportResult.artifacts) {
        downloadDataUrl(artifact.data_url, artifact.filename);
      }
    }
  }, [exportResult]);

  // Close the export popover on any click outside its anchor.
  useEffect(() => {
    if (!isExportMenuOpen) {
      return;
    }
    const onPointerDown = (event: PointerEvent) => {
      const anchor = exportMenuAnchorRef.current;
      if (anchor && !anchor.contains(event.target as Node)) {
        setIsExportMenuOpen(false);
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [isExportMenuOpen]);

  // Local undo/redo history lives in useEditHistory (pure mechanics; the
  // agent-turn canvas-lock guards stay HERE, on the orchestration layer,
  // like every other guarded mutation path). Deps rebuilt per render.
  const {
    lastOperation,
    setLastOperation,
    undoStack,
    setUndoStack,
    redoStack,
    setRedoStack,
    operationHistory,
    setOperationHistory,
    undo: undoHistoryStep,
    redo: redoHistoryStep
  } = useEditHistory({
    scene,
    replaceScene,
    setDiagnostics,
    setBrandCompatibilityReport,
    setPreflightResult,
    setExportResult,
    setWorkspaceMode,
    // Lazy wrapper: document sync is wired below (it needs the history
    // setters), and history steps only persist from event handlers.
    persistHistoryStep: (previousScene, operations, nextScene) =>
      enqueueForPersistence(previousScene, operations, nextScene)
  });

  // Document identity + the persistence leg (auto-create, id adoption, the
  // ordered edit queue with reconcile-at-drain) live in useDocumentSync.
  // Deps rebuilt per render, like every workflow hook here.
  // While an agent preview/draft is pending, its ops live in the optimistic
  // engine but in no enqueued batch — reconcile must compare the preview's
  // base scene or every pending draft reads as divergence (assigned below,
  // after useAgentTurn; ref so the queue's closure always sees the latest).
  const previewBaseSceneRef = useRef<Scene | null>(null);
  const { activeDocumentId, enqueueForPersistence, resyncPersistence } = useDocumentSync({
    documentId,
    documentCreator,
    editQueueFactory,
    engineRef,
    sceneRef,
    previewBaseSceneRef,
    replaceScene,
    setScene,
    setDiagnostics,
    resolveDiagnosticCode,
    setUndoStack,
    setRedoStack
  });

  // 2e: per-document standing instructions — editable any time, sent with
  // every turn immediately, persisted on the document (auto-saved once a
  // fresh canvas becomes a document).
  const standingInstructions = useAgentInstructions({
    activeDocumentId,
    initialInstructions: initialAgentInstructions,
    saveRunner: agentInstructionsSaver
  });

  // Advanced per-document opt-out from handoff-absolute: applies to the
  // session immediately, persists on the document per change.
  const layoutManagedEditing = useLayoutManagedEditing({
    activeDocumentId,
    initialEnabled: initialLayoutManagedEditing,
    saveRunner: layoutManagedEditingSaver
  });

  // View preference (not per-document): renders the active page's
  // safe-area/bleed guides on the canvas.
  const marginGuides = useMarginGuides();

  /**
   * Shared post-apply bookkeeping for operations that are already applied to
   * the engine: undo frame, history, persistence. Used by the direct edit path
   * (applyOperations) and by accepting an agent preview (Phase 0c), so both
   * commit identically.
   */
  const commitAppliedOperations = (
    previousScene: Scene,
    operations: Operation[],
    nextScene: Scene,
    persistOptions?: EnqueueOptions,
    inverseOperations: Operation[] | null = null
  ) => {
    // The disposition tells the caller whether this batch gets a server
    // envelope — an Accept only offers Revert when its checkpoint will exist —
    // and the undo frame whether undoing it must persist the inverse batch.
    const disposition = enqueueForPersistence(
      previousScene,
      operations,
      nextScene,
      persistOptions
    );
    setLastOperation(operations[operations.length - 1] ?? null);
    setBrandCompatibilityReport(null);
    setPreflightResult(null);
    setExportResult(null);
    setWorkspaceMode("canvas");
    setUndoStack((stack) => [
      ...stack.slice(-49),
      {
        scene: previousScene,
        operations,
        inverseOperations,
        persisted: disposition !== "local-only"
      }
    ]);
    setRedoStack([]);
    setOperationHistory((history) => [...history, ...operations].slice(-50));
    setDiagnostics([]);
    setScene(nextScene);
    return disposition;
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
    postSystemMessage,
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
    agentInstructions: standingInstructions.instructions,
    agentModel: agentModel || null,
    layoutManagedEditing: layoutManagedEditing.enabled,
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
    applyOperations: (operations, onAccepted) => applyOperations(operations, onAccepted)
  });
  // Keep the reconcile baseline in step with the pending preview (see the
  // ref's declaration above useDocumentSync). Render-body assignment is the
  // established ref-mirror pattern here (activeDocumentIdRef et al.).
  previewBaseSceneRef.current = agentPreview?.baseScene ?? null;

  // 2e notify-when-done: a turn that settles while the agent panel is
  // closed raises a click-to-open toast (no browser Notification API).
  const { toast: turnToast, dismiss: dismissTurnToast } = useTurnNotification({
    isAgentRunning,
    isAgentPanelOpen,
    hasProposal: agentProposal?.status === "proposed"
  });

  // 2d per-turn Compare | Revert. Compare is a read-only modal view of a
  // turn's before/after snapshot (mutations locked below, same two-sided
  // pattern as the agent lock); Revert unwinds the server history to just
  // after the turn's checkpoint and adopts the authoritative scene.
  const {
    compareView,
    invalidCheckpoints,
    isReverting,
    startCompare,
    setCompareView,
    exitCompare,
    revertToTurn
  } = useTurnCheckpoints({
    engineRef,
    sceneRef,
    activeDocumentId,
    revertRunner,
    setScene,
    replaceScene,
    setDiagnostics,
    resetHistory: () => {
      setUndoStack([]);
      setRedoStack([]);
      setOperationHistory([]);
      setLastOperation(null);
    },
    resyncPersistence,
    postSystemMessage,
    turnCheckpointsInOrder: () =>
      agentMessages.flatMap((message) =>
        message.turn?.checkpoint ? [message.turn.checkpoint] : []
      )
  });

  const applyOperations = (operations: Operation[], onAccepted?: (scene: Scene) => void) => {
    if (operations.length === 0) {
      return;
    }
    if (compareView) {
      setDiagnostics([compareActiveDiagnostic()]);
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

    commitAppliedOperations(
      previousScene,
      operations,
      result.scene,
      undefined,
      result.inverseOperations ?? null
    );
    onAccepted?.(result.scene);
  };

  const applyOperation = (operation: Operation) => {
    applyOperations([operation]);
  };

  /**
   * Phase 1d: structured edits (detach/re-attach, and future container
   * conversions) run through the engine's shared lumen-core builder and
   * commit with the exact bookkeeping manual edits get — undo frame,
   * history, persistence — so freehand actions are ordinary edits. Returns
   * the post-apply engine scene (or null if blocked/rejected/unavailable) so
   * a caller that needs fresh geometry synchronously — e.g. the CanvasKit
   * gesture-gate freeze, which continues the same pointer gesture right
   * after — doesn't have to wait for the next render's `scene` prop.
   */
  const applyStructuredEditInstruction = (edit: StructuredEdit): Scene | null => {
    if (compareView) {
      setDiagnostics([compareActiveDiagnostic()]);
      return null;
    }
    if (agentPreview) {
      setDiagnostics([pendingAgentReviewDiagnostic()]);
      return null;
    }
    if (isAgentRunning) {
      setDiagnostics([agentTurnRunningDiagnostic()]);
      return null;
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
      return null;
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
      return null;
    }
    commitAppliedOperations(
      previousScene,
      outcome.operations,
      outcome.scene,
      undefined,
      outcome.inverseOperations ?? null
    );
    return outcome.scene;
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

  /** Enter Compare for an accepted turn — only while the editor is idle.
   * Queued messages block entry too: they drain at idle and would start a
   * turn underneath the read-only snapshot. */
  const compareTurn = (record: AcceptedTurnRecord, view: "before" | "after") => {
    if (agentPreview) {
      setDiagnostics([pendingAgentReviewDiagnostic()]);
      return;
    }
    if (isAgentRunning) {
      setDiagnostics([agentTurnRunningDiagnostic()]);
      return;
    }
    if (queuedAgentMessages.length > 0) {
      setDiagnostics([
        {
          severity: "warning",
          phase: "operation",
          code: "EDITOR_COMPARE_BLOCKED_QUEUE",
          message: "Queued messages are about to run — comparing would race them.",
          subject: { kind: "document" },
          hint: "Let the queued turns finish (or remove them) before comparing a past turn."
        }
      ]);
      return;
    }
    startCompare(record, view);
  };

  /** Revert to just after an accepted turn — same idle-only entry rules. */
  const revertTurn = (record: AcceptedTurnRecord) => {
    if (compareView) {
      setDiagnostics([compareActiveDiagnostic()]);
      return;
    }
    if (agentPreview) {
      setDiagnostics([pendingAgentReviewDiagnostic()]);
      return;
    }
    if (isAgentRunning) {
      setDiagnostics([agentTurnRunningDiagnostic()]);
      return;
    }
    void revertToTurn(record);
  };

  const undoLastOperation = () => {
    if (compareView) {
      setDiagnostics([compareActiveDiagnostic()]);
      return;
    }
    if (agentPreview) {
      setDiagnostics([pendingAgentReviewDiagnostic()]);
      return;
    }
    if (isAgentRunning) {
      setDiagnostics([agentTurnRunningDiagnostic()]);
      return;
    }
    undoHistoryStep();
  };

  const redoLastOperation = () => {
    if (compareView) {
      setDiagnostics([compareActiveDiagnostic()]);
      return;
    }
    if (agentPreview) {
      setDiagnostics([pendingAgentReviewDiagnostic()]);
      return;
    }
    if (isAgentRunning) {
      setDiagnostics([agentTurnRunningDiagnostic()]);
      return;
    }
    redoHistoryStep();
  };

  /** Phase 4b arrange: the keyboard-shortcut counterpart of ArrangeSection's
   * buttons — same predicates, same structured-edit path, so a shortcut and
   * its inspector button always agree on whether an action is allowed. */
  const runArrangeAction = (
    action: ReturnType<typeof keyboardArrangeAction>,
    primaryNodeId: NodeId,
    multiSelection: NodeId[]
  ) => {
    const arrangeInfo = siblingArrangeInfo(scene, primaryNodeId);
    const node = scene.nodes[primaryNodeId];
    if (!node || node.locked) {
      return;
    }
    switch (action) {
      case "to_front":
        if (arrangeInfo && !arrangeInfo.isFront) {
          applyStructuredEditInstruction(
            moveAfterEdit(primaryNodeId, arrangeInfo.siblings[arrangeInfo.siblings.length - 1])
          );
        }
        return;
      case "forward":
        if (arrangeInfo && !arrangeInfo.isFront) {
          applyStructuredEditInstruction(moveAfterEdit(primaryNodeId, arrangeInfo.siblings[arrangeInfo.index + 1]));
        }
        return;
      case "backward":
        if (arrangeInfo && !arrangeInfo.isBack) {
          applyStructuredEditInstruction(moveBeforeEdit(primaryNodeId, arrangeInfo.siblings[arrangeInfo.index - 1]));
        }
        return;
      case "to_back":
        if (arrangeInfo && !arrangeInfo.isBack) {
          applyStructuredEditInstruction(moveBeforeEdit(primaryNodeId, arrangeInfo.siblings[0]));
        }
        return;
      case "group": {
        const groupSelectionIds = multiSelection.includes(primaryNodeId) ? multiSelection : [primaryNodeId];
        if (canGroupNodes(scene, groupSelectionIds)) {
          applyStructuredEditInstruction(groupEdit(groupSelectionIds, mintGroupId(scene), "Group"));
        }
        return;
      }
      case "ungroup": {
        const groupSelectionIds = multiSelection.includes(primaryNodeId) ? multiSelection : [primaryNodeId];
        if (groupSelectionIds.length === 1 && canUngroupNode(scene, primaryNodeId)) {
          applyStructuredEditInstruction(ungroupEdit(primaryNodeId));
        }
        return;
      }
      default:
        return;
    }
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

      const arrangeAction = keyboardArrangeAction(event);
      if (arrangeAction) {
        event.preventDefault();
        runArrangeAction(arrangeAction, selectedNode.id, selectedNodeIds);
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
  }, [redoLastOperation, runArrangeAction, scene, selectedNode, selectedNodeId, selectedNodeIds, undoLastOperation]);

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
      <header className="editor-chrome">
        <div className="doc-row">
          <div className="doc-row-left">
            <span className="app-mark" aria-hidden>
              <img src={appMark.src} alt="" width={16} height={16} />
            </span>
            <div className="topbar-title">
              <p className="eyebrow">ABM Design Engine</p>
              <EditableDocumentTitle
                title={scene.meta.title}
                onRename={(title) => applyOperation(updateDocumentTitle(title))}
              />
            </div>
          </div>
          <div className="doc-row-actions" aria-label="Editor actions">
            {editorPanelMode !== "diagnostics" ? (
              <DiagnosticsAlertPill
                errorCount={
                  diagnostics.filter((diagnostic) => diagnostic.severity === "error").length
                }
                onOpen={() => setEditorPanelMode("diagnostics")}
              />
            ) : null}
            {activeDocumentId ? (
              <button
                type="button"
                className="doc-icon-button"
                aria-label="Version history"
                title="Version history"
                aria-haspopup="dialog"
                aria-expanded={isVersionHistoryOpen}
                onClick={() => setIsVersionHistoryOpen((open) => !open)}
              >
                <History aria-hidden size={16} />
              </button>
            ) : null}
            <div className="export-menu-anchor" ref={exportMenuAnchorRef}>
              <button
                type="button"
                className="btn-primary"
                aria-haspopup="dialog"
                aria-expanded={isExportMenuOpen}
                disabled={isExporting}
                onClick={() => setIsExportMenuOpen((open) => !open)}
              >
                <Download aria-hidden size={16} />
                {isExporting ? "Exporting" : "Export"}
              </button>
              {isExportMenuOpen ? (
                <ExportMenu
                  pageCount={Object.keys(scene.pages).length}
                  activePageName={activePage?.name ?? null}
                  isExporting={isExporting}
                  onDownload={(profile, scope) => {
                    setIsExportMenuOpen(false);
                    downloadAfterExportRef.current = true;
                    const pageIds =
                      scope === "all"
                        ? Object.values(scene.pages).map((page) => page.id)
                        : activePageId
                          ? [activePageId]
                          : [];
                    void runExportForScene(scene, profile, pageIds, {
                      openPreviewTab: false,
                      focusExportPanel: false
                    });
                  }}
                  onClose={() => setIsExportMenuOpen(false)}
                />
              ) : null}
            </div>
          </div>
        </div>
        <div className="tool-row" aria-label="Editing tools">
          <div className="tool-row-left">
            <button
              type="button"
              className="icon-ghost-button"
              aria-label="Undo"
              title="Undo"
              onClick={undoLastOperation}
              disabled={undoStack.length === 0 || isAgentRunning || agentPreview !== null}
            >
              <RotateCcw aria-hidden size={16} />
            </button>
            <button
              type="button"
              className="icon-ghost-button"
              aria-label="Redo"
              title="Redo"
              onClick={redoLastOperation}
              disabled={redoStack.length === 0 || isAgentRunning || agentPreview !== null}
            >
              <RotateCw aria-hidden size={16} />
            </button>
          </div>
          <span className="tool-row-separator" aria-hidden />
          <div className="topbar-context" aria-label="Active artboard context">
            <div className="topbar-artboard-label">
              <strong>{activePage?.name ?? "No artboard"}</strong>
              <span>
                {activePage
                  ? `${topArtboardSizeLabel(activePage)} · ${Math.round(workspaceViewport.zoom * 100)}%`
                  : "No frame"}
              </span>
            </div>
          </div>
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
          {turnToast ? (
            <button
              type="button"
              className={`agent-done-toast ${turnToast.tone}`}
              role="status"
              data-testid="agent-done-toast"
              onClick={() => {
                dismissTurnToast();
                setEditorPanelMode("agent");
              }}
            >
              <Bot aria-hidden size={15} />
              <span>{turnToast.message}</span>
            </button>
          ) : null}
          {compareView && !agentPreview ? (
            <div
              className="agent-review-bar turn-compare-bar"
              role="toolbar"
              aria-label="Compare a past turn"
              data-testid="turn-compare-bar"
            >
              <div className="agent-review-toggle" role="group" aria-label="Turn snapshot">
                <button
                  type="button"
                  className={compareView.view === "before" ? "active" : ""}
                  aria-pressed={compareView.view === "before"}
                  onClick={() => setCompareView("before")}
                >
                  Before
                </button>
                <button
                  type="button"
                  className={compareView.view === "after" ? "active" : ""}
                  aria-pressed={compareView.view === "after"}
                  onClick={() => setCompareView("after")}
                >
                  After
                </button>
              </div>
              <span className="agent-review-summary">
                Viewing a past turn — the canvas is read-only
              </span>
              <button type="button" className="agent-review-accept" onClick={exitCompare}>
                <Check aria-hidden size={15} />
                Back to current
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
            <>
              {!isAgentRunning && !agentPreview && !compareView ? (
                <TextToolbar selectedNode={selectedNode} onOperation={applyOperation} brandTokens={effectiveBrandKit?.tokens ?? null} />
              ) : null}
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
                onStructuredEdit={applyStructuredEditInstruction}
                layoutManagedEditing={layoutManagedEditing.enabled}
                showMarginGuides={marginGuides.showMarginGuides}
                onToggleMarginGuides={marginGuides.toggleMarginGuides}
              />
            </>
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
          className={`inspector-shell${editorPanelMode === "agent" ? " chat-mode" : ""}`}
          aria-label={rightSidebarLabelForMode(editorPanelMode)}
        >
          <EditorModeSwitch mode={editorPanelMode} onModeChange={setEditorPanelMode} />
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
              compareView={compareView}
              invalidCheckpoints={invalidCheckpoints}
              isReverting={isReverting}
              suggestions={postTurnSuggestions(scene)}
              standingInstructions={{
                draft: standingInstructions.draft,
                dirty: standingInstructions.isDirty,
                saving: standingInstructions.isSaving,
                canSave: standingInstructions.canSave,
                error: standingInstructions.saveError,
                onDraftChange: standingInstructions.setDraft,
                onSave: () => void standingInstructions.save()
              }}
              activePageId={activePageId}
              selectedNodeId={selectedNodeId}
              diagnostics={diagnostics}
              onRemoveTargetChip={removeTargetChip}
              onClearTargetChips={clearTargetChips}
              onDraftChange={setAgentDraft}
              onSend={(prompt) => {
                // Compare is read-only: a send would seed the turn from the
                // displayed snapshot, not the live design.
                if (compareView) {
                  setDiagnostics([compareActiveDiagnostic()]);
                  return;
                }
                void sendAgentPrompt(prompt);
              }}
              onQueueMessage={(content) => {
                // Queueing while comparing would drain immediately (the
                // editor is idle) and start a turn under the read-only view.
                if (compareView) {
                  setDiagnostics([compareActiveDiagnostic()]);
                  return;
                }
                queueAgentMessage(content);
              }}
              onRemoveQueuedMessage={removeQueuedAgentMessage}
              onApplyProposal={applyAgentProposal}
              onAcceptProposal={() => void acceptAgentPreview()}
              onRejectProposal={rejectAgentPreview}
              onCompareTurn={compareTurn}
              onExitCompare={exitCompare}
              onRevertTurn={revertTurn}
              brandKits={initialAvailableBrandKits}
              attachedBrandKit={scene.meta.brand_kit ?? null}
              onAttachBrandKit={(kit) =>
                applyOperation(
                  updateDocumentBrand({ id: kit.id, version: kit.version }, scene.meta.medium)
                )
              }
              modelOptions={AGENT_MODEL_OPTIONS}
              model={agentModel}
              onModelChange={setAgentModel}
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
            <>
              <ValidationPanel
                scene={scene}
                activePageId={activePageId}
                selectedNodeId={selectedNodeId}
                diagnostics={diagnostics}
                renderDiagnostics={renderDiagnostics}
                lastOperation={lastOperation}
                preflightResult={preflightResult}
                onSelectSubject={selectDiagnosticSubject}
                onRunPreflight={() => void runPreflight()}
                isPreflighting={isPreflighting}
              />
              <OperationHistoryPanel operations={operationHistory} redoCount={redoStack.length} />
            </>
          ) : editorPanelMode === "assets" ? (
            <AssetBrowserPanel
              apiBaseUrl={editorApiBaseUrl()}
              selectedNodeId={selectedNodeId}
              selectedNodePlacement={selectedNode?.asset_placement ?? null}
              refreshToken={assetLibraryRefreshToken}
              onOperations={applyOperations}
            />
          ) : (
            <>
              <InspectorPanel
                scene={scene}
                activePage={activePage}
                selectedNode={selectedNode}
                selectedNodeId={selectedNodeId}
                selectedNodeIds={selectedNodeIds}
                brandTokens={effectiveBrandKit?.tokens ?? null}
                diagnostics={diagnostics}
                renderDiagnostics={renderDiagnostics}
                apiBaseUrl={editorApiBaseUrl()}
                onOperation={applyOperation}
                onOperations={applyOperations}
                onStructuredEdit={applyStructuredEditInstruction}
                onSelectSubject={selectDiagnosticSubject}
                layoutManagedEditing={layoutManagedEditing.enabled}
                onSetLayoutManagedEditing={layoutManagedEditing.setEnabled}
                onAssetLibraryChanged={notifyAssetLibraryChanged}
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
              <WorstCasePreviewPanel apiBaseUrl={editorApiBaseUrl()} scene={scene} />
            </>
          )}
        </aside>
      </div>
      {isVersionHistoryOpen && activeDocumentId ? (
        <VersionHistoryDialog
          apiBaseUrl={editorApiBaseUrl()}
          documentId={activeDocumentId}
          onClose={() => setIsVersionHistoryOpen(false)}
          onDocumentChanged={() => void refreshSceneFromEngine()}
        />
      ) : null}
    </main>
  );
}


