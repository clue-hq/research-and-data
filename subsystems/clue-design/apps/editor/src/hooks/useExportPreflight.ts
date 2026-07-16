import { useState, type Dispatch, type SetStateAction } from "react";
import {
  openBlankArtifactPreviewWindow,
  showArtifactInPreviewWindow
} from "@/components/exportArtifactActions";
import type { ExportPanelState } from "@/components/ExportPanel";
import type { Diagnostic, PageId, Scene } from "@/engine/contracts";
import type { EditorPanelMode } from "@/engine/editorModes";
import {
  defaultEditorExportProfile,
  type EditorExportArtifact,
  type EditorExportResult,
  type EditorExportRunner
} from "@/engine/exportRunner";
import type {
  EditorPreflightResult,
  EditorPreflightRunner
} from "@/engine/preflightRunner";

/**
 * The export + preflight leg of the editor shell: the Validate and Export
 * flows, their in-flight flags, and their result state. Server-side runners
 * do the work; this hook owns sequencing and the diagnostics each outcome
 * surfaces.
 *
 * The deps object is rebuilt every render (same closure semantics as the
 * inline originals) — never memoize it. `getActiveDocumentId` is a lazy
 * getter because document identity lives in useDocumentSync, which is wired
 * AFTER this hook (it needs the history setters); the getter only runs from
 * event handlers, well after both hooks are live.
 */
export interface UseExportPreflightDeps {
  exportRunner: EditorExportRunner;
  preflightRunner: EditorPreflightRunner;
  scene: Scene;
  activePageId: PageId | null;
  getActiveDocumentId: () => string | null;
  replaceScene: (nextScene: Scene) => void;
  setDiagnostics: Dispatch<SetStateAction<Diagnostic[]>>;
  setEditorPanelMode: Dispatch<SetStateAction<EditorPanelMode>>;
  setWorkspaceMode: Dispatch<SetStateAction<"canvas" | "export" | "compare">>;
}

export function useExportPreflight(deps: UseExportPreflightDeps) {
  const {
    exportRunner,
    preflightRunner,
    scene,
    activePageId,
    getActiveDocumentId,
    replaceScene,
    setDiagnostics,
    setEditorPanelMode,
    setWorkspaceMode
  } = deps;

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

  const runExport = async (
    profile = defaultEditorExportProfile(),
    pageIds: PageId[] = activePageId ? [activePageId] : []
  ) => runExportForScene(scene, profile, pageIds, { openPreviewTab: true });

  /**
   * Returns the export result (with preflight diagnostics folded in) so
   * callers can act on THEIR OWN export's outcome — e.g. the topbar menu
   * downloads the artifacts it requested. Aborted or failed requests
   * return null; per-call intent must never outlive the call (the old
   * ambient download flag leaked across exports when a request aborted).
   */
  const runExportForScene = async (
    sceneForExport: Scene,
    profile = defaultEditorExportProfile(),
    pageIds: PageId[] = activePageId ? [activePageId] : [],
    options: { openPreviewTab?: boolean; focusExportPanel?: boolean } = {}
  ): Promise<EditorExportResult | null> => {
    const previewWindow = options.openPreviewTab ? openBlankArtifactPreviewWindow() : null;
    // The topbar export menu runs "silently" (no panel switch, no preview
    // tab) and downloads the artifacts instead.
    if (options.focusExportPanel !== false) {
      setEditorPanelMode("export");
    }
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
      return null;
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
      const activeDocumentId = getActiveDocumentId();
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
      return resultWithPreflightDiagnostics;
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
      return null;
    } finally {
      setIsExporting(false);
    }
  };

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

  return {
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
  };
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
