import { describe, expect, it } from "vitest";
import type { Diagnostic } from "../contracts";
import type { EditorExportArtifact, EditorExportResult } from "../exportRunner";
import { exportPreviewApprovalState } from "../exportPreviewApproval";

describe("export preview approval", () => {
  it("marks matching exports with no blocking diagnostics ready for approval", () => {
    const state = exportPreviewApprovalState({
      artifact: artifact(),
      exportResult: result("ok"),
      parityStatus: "match",
      diagnostics: []
    });

    expect(state).toMatchObject({
      status: "ready",
      title: "Ready for approval",
      blocking_count: 0,
      warning_count: 0
    });
  });

  it("marks matching exports with warnings as warning review", () => {
    const state = exportPreviewApprovalState({
      artifact: artifact(),
      exportResult: result("ok"),
      parityStatus: "match",
      diagnostics: [diagnostic("warning")]
    });

    expect(state).toMatchObject({
      status: "warning",
      title: "Review warnings before approval",
      blocking_count: 0,
      warning_count: 1
    });
  });

  it("fails closed with specific reasons for missing artifacts, export failures, parity mismatches, and errors", () => {
    const cases = [
      {
        label: "missing artifact",
        artifact: null,
        exportResult: result("ok"),
        parityStatus: "match" as const,
        diagnostics: [],
        message: "Generate a preview for the selected artboard before approving this artifact."
      },
      {
        label: "empty artifact payload",
        artifact: {
          ...artifact(),
          data_url: null
        },
        exportResult: result("ok"),
        parityStatus: "match" as const,
        diagnostics: [],
        message: "Generate a preview for the selected artboard before approving this artifact."
      },
      {
        label: "export failed",
        artifact: artifact(),
        exportResult: result("failed"),
        parityStatus: "match" as const,
        diagnostics: [],
        message: "The latest export failed. Resolve export diagnostics and generate a new preview."
      },
      {
        label: "parity mismatch",
        artifact: artifact(),
        exportResult: result("ok"),
        parityStatus: "mismatch" as const,
        diagnostics: [],
        message: "Canvas and export preview parity has not been confirmed for the selected artboard."
      },
      {
        label: "error diagnostic",
        artifact: artifact(),
        exportResult: result("ok"),
        parityStatus: "match" as const,
        diagnostics: [diagnostic("error")],
        message: "1 blocking diagnostic must be resolved before approval."
      }
    ];

    for (const testCase of cases) {
      const state = exportPreviewApprovalState(testCase);

      expect(state.status, testCase.label).toBe("blocked");
      expect(state.title, testCase.label).toBe("Not ready for approval");
      expect(state.message, testCase.label).toBe(testCase.message);
    }
  });
});

function result(status: EditorExportResult["status"]): EditorExportResult {
  return {
    status,
    diagnostics: [],
    artifacts: status === "ok" ? [artifact()] : [],
    printReady: null
  };
}

function artifact(): EditorExportArtifact {
  return {
    format: "svg",
    page_id: "page_a4",
    asset_id: null,
    filename: "page_a4.preview_svg.svg",
    sidecar_filename: null,
    mime_type: "image/svg+xml",
    byte_length: 128,
    dimensions: {
      width: 1080,
      height: 1080,
      unit: "scene",
      source: "svg_view_box"
    },
    data_url: "data:image/svg+xml;base64,PHN2Zy8+",
    text: "<svg />",
    sidecar_json: null,
    sidecar_summary: null
  };
}

function diagnostic(severity: Diagnostic["severity"]): Diagnostic {
  return {
    severity,
    phase: "export",
    code: `TEST_${severity.toUpperCase()}`,
    message: `${severity} diagnostic`,
    subject: null,
    hint: null
  };
}
