"use client";

import { useMemo, useState } from "react";
import { Download, FileCheck2, PanelRightClose, RotateCcw, Send } from "lucide-react";
import { BrandKitPanel } from "./BrandKitPanel";
import { CanvasSurface } from "./canvas/CanvasSurface";
import { InspectorPanel } from "./InspectorPanel";
import { PageRail } from "./PageRail";
import { ValidationPanel } from "./ValidationPanel";
import { minimalScene } from "@/fixtures/minimalScene";
import type { BrandCompatibilityRunner } from "@/engine/brandCompatibility";
import type { BrandGovernanceRunner } from "@/engine/brandGovernance";
import type {
  BrandCompatibilityReport,
  BrandKitRef,
  BrandKitSummary,
  Diagnostic,
  NodeId,
  Operation,
  PageId,
  Scene
} from "@/engine/contracts";
import { localEditorEngine } from "@/engine/editorEngine";
import { firstPageId, getNode } from "@/engine/sceneQueries";

export interface EditorAppProps {
  initialScene?: Scene;
  initialSelectedNodeId?: NodeId | null;
  initialAvailableBrandKits?: BrandKitSummary[];
  brandGovernanceRunner?: BrandGovernanceRunner;
  brandCompatibilityRunner?: BrandCompatibilityRunner;
}

export default function EditorApp({
  initialScene = minimalScene,
  initialSelectedNodeId = "node_contact_name",
  initialAvailableBrandKits = [],
  brandGovernanceRunner,
  brandCompatibilityRunner
}: EditorAppProps = {}) {
  const [scene, setScene] = useState<Scene>(initialScene);
  const [activePageId, setActivePageId] = useState<PageId | null>(() => firstPageId(initialScene));
  const [selectedNodeId, setSelectedNodeId] = useState<NodeId | null>(initialSelectedNodeId);
  const [diagnostics, setDiagnostics] = useState<Diagnostic[]>([]);
  const [lastOperation, setLastOperation] = useState<Operation | null>(null);
  const [undoStack, setUndoStack] = useState<Scene[]>([]);
  const [isBrandGovernanceRunning, setIsBrandGovernanceRunning] = useState(false);
  const [isBrandCompatibilityRunning, setIsBrandCompatibilityRunning] = useState(false);
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

  const applyOperation = (operation: Operation) => {
    setLastOperation(operation);
    setBrandCompatibilityReport(null);
    setScene((currentScene) => {
      const result = localEditorEngine.applyOperation(currentScene, operation);
      if (result.accepted) {
        setUndoStack((stack) => [...stack.slice(-49), currentScene]);
        setDiagnostics([]);
        return result.scene;
      }

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
    });
  };

  const undoLastOperation = () => {
    setUndoStack((stack) => {
      const previousScene = stack[stack.length - 1];
      if (!previousScene) {
        return stack;
      }
      setScene(previousScene);
      setLastOperation(null);
      setDiagnostics([]);
      return stack.slice(0, -1);
    });
  };

  const runValidationPlaceholder = () => {
    setDiagnostics([
      {
        severity: "advice",
        phase: "validation",
        code: "EDITOR_VALIDATION_PORT",
        message: "Validation UI is wired; checked Rust validation will plug into this port later.",
        subject: null,
        hint: "This branch intentionally does not redefine core validation semantics."
      }
    ]);
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

  return (
    <main className="editor-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">ABM Design Engine</p>
          <h1>{scene.meta.title}</h1>
        </div>
        <div className="toolbar" aria-label="Editor actions">
          <button type="button" onClick={runValidationPlaceholder}>
            <FileCheck2 aria-hidden size={16} />
            Validate
          </button>
          <button type="button" disabled>
            <Send aria-hidden size={16} />
            Agent
          </button>
          <button type="button" disabled>
            <Download aria-hidden size={16} />
            Export
          </button>
          <button type="button" onClick={undoLastOperation} disabled={undoStack.length === 0}>
            <RotateCcw aria-hidden size={16} />
            Undo
          </button>
        </div>
      </header>
      <div className="workspace-grid">
        <PageRail scene={scene} activePageId={activePageId} onSelectPage={selectPage} />
        <CanvasSurface
          scene={scene}
          activePageId={activePageId}
          selectedNodeId={selectedNodeId}
          onSelectNode={setSelectedNodeId}
          onOperation={applyOperation}
        />
        <aside className="inspector-shell">
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
            onOperation={applyOperation}
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
          />
          <ValidationPanel diagnostics={diagnostics} lastOperation={lastOperation} />
        </aside>
      </div>
    </main>
  );
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
