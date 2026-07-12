import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { minimalScene } from "@/fixtures/minimalScene";
import type { EditorExportResult } from "@/engine/exportRunner";
import { ExportPreviewSurface } from "../ExportPreviewSurface";

describe("ExportPreviewSurface", () => {
  it("renders SVG export artifacts as clean artifact previews", () => {
    render(
      <ExportPreviewSurface
        scene={minimalScene}
        activePageId="page_a4"
        exportResult={exportResult("svg", "data:image/svg+xml;base64,PHN2Zy8+")}
      />
    );

    expect(screen.getByRole("img", { name: "Export preview artifact" })).toHaveAttribute(
      "src",
      "data:image/svg+xml;base64,PHN2Zy8+"
    );
    expect(screen.queryByText("Ready for approval")).not.toBeInTheDocument();
    expect(screen.queryByText("Parity OK")).not.toBeInTheDocument();
  });

  it("renders PNG export artifacts as clean artifact previews", () => {
    render(
      <ExportPreviewSurface
        scene={minimalScene}
        activePageId="page_a4"
        exportResult={exportResult("png", "data:image/png;base64,AAAA")}
      />
    );

    expect(screen.getByRole("img", { name: "Export preview artifact" })).toHaveAttribute(
      "src",
      "data:image/png;base64,AAAA"
    );
  });

  it("does not show another page's export artifact for the active page", () => {
    const result = exportResult("svg", "data:image/svg+xml;base64,PHN2Zy8+");
    result.artifacts[0].page_id = "page_second";

    render(<ExportPreviewSurface scene={minimalScene} activePageId="page_a4" exportResult={result} />);

    expect(screen.getByText("Export the active page to preview the artifact.")).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: "Export preview artifact" })).not.toBeInTheDocument();
    expect(screen.queryByText("Not ready for approval")).not.toBeInTheDocument();
  });

  it("does not show export diagnostics in the preview surface", () => {
    const result = exportResult("svg", "data:image/svg+xml;base64,PHN2Zy8+");
    result.diagnostics = [
      {
        severity: "warning",
        phase: "export",
        code: "LUME_PRINT_FONT_EMBEDDING",
        message: "PDF font embedding is not available for this preview profile.",
        subject: null,
        hint: "Use the export diagnostics before final print approval."
      }
    ];

    render(<ExportPreviewSurface scene={minimalScene} activePageId="page_a4" exportResult={result} />);

    expect(screen.getByRole("img", { name: "Export preview artifact" })).toBeInTheDocument();
    expect(screen.queryByText("LUME_PRINT_FONT_EMBEDDING")).not.toBeInTheDocument();
    expect(screen.queryByText("PDF font embedding is not available for this preview profile.")).not.toBeInTheDocument();
  });
});

function exportResult(format: "svg" | "png", dataUrl: string): EditorExportResult {
  return {
    status: "ok",
    artifacts: [
      {
        format,
        page_id: "page_a4",
        asset_id: null,
        filename: `page_a4.preview_${format}.${format}`,
        sidecar_filename: null,
        mime_type: format === "svg" ? "image/svg+xml" : "image/png",
        byte_length: 128,
        dimensions: {
          width: 793.7,
          height: 1122.52,
          unit: format === "svg" ? "scene" : "px",
          source: format === "svg" ? "svg_view_box" : "raster_profile"
        },
        data_url: dataUrl,
        text: format === "svg" ? "<svg />" : null,
        sidecar_json: null,
        sidecar_summary: null
      }
    ],
    diagnostics: [],
    printReady: null
  };
}
