import type { Diagnostic } from "./contracts";
import type { EditorExportArtifact, EditorExportResult } from "./exportRunner";
import type { ExportParityReport } from "./exportParity";

export interface ExportPreviewApprovalState {
  status: "ready" | "warning" | "blocked";
  title: string;
  message: string;
  blocking_count: number;
  warning_count: number;
}

export function exportPreviewApprovalState({
  artifact,
  exportResult,
  parityStatus,
  diagnostics
}: {
  artifact: EditorExportArtifact | null;
  exportResult: EditorExportResult | null;
  parityStatus: ExportParityReport["status"];
  diagnostics: Diagnostic[];
}): ExportPreviewApprovalState {
  const blockingCount = diagnostics.filter((diagnostic) => diagnostic.severity === "error").length;
  const warningCount = diagnostics.filter((diagnostic) => diagnostic.severity === "warning").length;

  if (!artifact?.data_url) {
    return {
      status: "blocked",
      title: "Not ready for approval",
      message: "Generate a preview for the selected artboard before approving this artifact.",
      blocking_count: blockingCount,
      warning_count: warningCount
    };
  }

  if (exportResult?.status !== "ok") {
    return {
      status: "blocked",
      title: "Not ready for approval",
      message: "The latest export failed. Resolve export diagnostics and generate a new preview.",
      blocking_count: blockingCount,
      warning_count: warningCount
    };
  }

  if (parityStatus !== "match") {
    return {
      status: "blocked",
      title: "Not ready for approval",
      message: "Canvas and export preview parity has not been confirmed for the selected artboard.",
      blocking_count: blockingCount,
      warning_count: warningCount
    };
  }

  if (blockingCount > 0) {
    return {
      status: "blocked",
      title: "Not ready for approval",
      message: `${blockingCount} blocking diagnostic${blockingCount === 1 ? "" : "s"} must be resolved before approval.`,
      blocking_count: blockingCount,
      warning_count: warningCount
    };
  }

  if (warningCount > 0) {
    return {
      status: "warning",
      title: "Review warnings before approval",
      message: `${warningCount} warning${warningCount === 1 ? "" : "s"} should be reviewed before handoff.`,
      blocking_count: 0,
      warning_count: warningCount
    };
  }

  return {
    status: "ready",
    title: "Ready for approval",
    message: "The active export artifact matches the canvas page and has no blocking diagnostics.",
    blocking_count: 0,
    warning_count: 0
  };
}
