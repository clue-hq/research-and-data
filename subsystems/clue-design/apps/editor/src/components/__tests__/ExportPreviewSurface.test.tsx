import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { minimalScene } from "@/fixtures/minimalScene";
import type { EditorExportResult } from "@/engine/exportRunner";
import { ExportPreviewSurface } from "../ExportPreviewSurface";

describe("ExportPreviewSurface", () => {
  it("renders SVG export artifacts with approval metadata", () => {
    const exportResult: EditorExportResult = {
      status: "ok",
      artifacts: [
        {
          format: "svg",
          page_id: "page_a4",
          asset_id: null,
          filename: "page_a4.preview_svg.svg",
          sidecar_filename: null,
          mime_type: "image/svg+xml",
          byte_length: 128,
          dimensions: {
            width: 793.7,
            height: 1122.52,
            unit: "scene",
            source: "svg_view_box"
          },
          data_url: "data:image/svg+xml;base64,PHN2Zy8+",
          text: '<svg viewBox="0 0 793.7 1122.52"><text data-lumen-node-id="node_contact_name">Dr. Priya Sharma</text></svg>',
          sidecar_json: null,
          sidecar_summary: {
            profile_name: "preview_svg",
            page_count: 1,
            node_count: 1,
            slot_count: 1,
            page_ids: ["page_a4"],
            slot_keys: ["contact.full_name"]
          }
        }
      ],
      diagnostics: []
    };

    render(<ExportPreviewSurface scene={minimalScene} activePageId="page_a4" exportResult={exportResult} />);

    expect(screen.getByTitle("Export preview artifact")).toHaveAttribute("src", "data:image/svg+xml;base64,PHN2Zy8+");
    expect(screen.getByLabelText("Export preview artifact details")).toBeInTheDocument();
    expect(screen.getByText("SVG · page page_a4")).toBeInTheDocument();
    expect(screen.getByText("128 bytes")).toBeInTheDocument();
    expect(screen.getByText("page_a4.preview_svg.svg")).toBeInTheDocument();
    expect(screen.getByText("793.70 x 1122.52 scene · svg_view_box")).toBeInTheDocument();
    const scope = within(screen.getByLabelText("Export preview scope"));
    expect(scope.getByText("A4 Letter")).toBeInTheDocument();
    expect(scope.getByText("preview_svg")).toBeInTheDocument();
    expect(screen.getByText("preview_svg · 1 page · 1 node · 1 slot · slots contact.full_name")).toBeInTheDocument();
    expect(screen.getByText("Ready for approval")).toBeInTheDocument();
    expect(screen.getByText(/matches the canvas page and has no blocking diagnostics/)).toBeInTheDocument();
  });

  it("renders PNG export artifacts as image previews with raster dimensions", () => {
    const exportResult: EditorExportResult = {
      status: "ok",
      artifacts: [
        {
          format: "png",
          page_id: "page_a4",
          asset_id: null,
          filename: "page_a4.preview_png.png",
          sidecar_filename: null,
          mime_type: "image/png",
          byte_length: 4096,
          dimensions: {
            width: 1588,
            height: 2245,
            unit: "px",
            source: "raster_profile"
          },
          data_url: "data:image/png;base64,AAAA",
          text: null,
          sidecar_json: null,
          sidecar_summary: null
        }
      ],
      diagnostics: []
    };

    render(<ExportPreviewSurface scene={minimalScene} activePageId="page_a4" exportResult={exportResult} />);

    expect(screen.getByRole("img", { name: "Export preview artifact" })).toHaveAttribute("src", "data:image/png;base64,AAAA");
    expect(screen.getByText("PNG · page page_a4")).toBeInTheDocument();
    expect(screen.getByText("4096 bytes")).toBeInTheDocument();
    expect(screen.getByText("1588 x 2245 px · raster_profile")).toBeInTheDocument();
  });

  it("does not show another page's export artifact for the active page", () => {
    const exportResult: EditorExportResult = {
      status: "ok",
      artifacts: [
        {
          format: "svg",
          page_id: "page_second",
          asset_id: null,
          filename: "page_second.preview_svg.svg",
          sidecar_filename: null,
          mime_type: "image/svg+xml",
          byte_length: 128,
          dimensions: {
            width: 793.7,
            height: 1122.52,
            unit: "scene",
            source: "svg_view_box"
          },
          data_url: "data:image/svg+xml;base64,PHN2Zy8+",
          text: '<svg viewBox="0 0 793.7 1122.52"></svg>',
          sidecar_json: null,
          sidecar_summary: null
        }
      ],
      diagnostics: []
    };

    render(<ExportPreviewSurface scene={minimalScene} activePageId="page_a4" exportResult={exportResult} />);

    expect(screen.getByText("Export the active page to preview the artifact.")).toBeInTheDocument();
    expect(screen.getByText("Not ready for approval")).toBeInTheDocument();
    expect(screen.getByText("Generate a preview for the selected artboard before approving this artifact.")).toBeInTheDocument();
    expect(screen.getByText("EDITOR_EXPORT_PARITY_ARTIFACT_REQUIRED")).toBeInTheDocument();
    expect(screen.queryByTitle("Export preview artifact")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Export preview artifact details")).not.toBeInTheDocument();
  });

  it("shows warning approval state for non-blocking export diagnostics", () => {
    const exportResult: EditorExportResult = {
      status: "ok",
      artifacts: [
        {
          format: "svg",
          page_id: "page_a4",
          asset_id: null,
          filename: "page_a4.preview_svg.svg",
          sidecar_filename: null,
          mime_type: "image/svg+xml",
          byte_length: 128,
          dimensions: {
            width: 793.7,
            height: 1122.52,
            unit: "scene",
            source: "svg_view_box"
          },
          data_url: "data:image/svg+xml;base64,PHN2Zy8+",
          text: '<svg viewBox="0 0 793.7 1122.52"><text data-lumen-node-id="node_contact_name">Dr. Priya Sharma</text></svg>',
          sidecar_json: null,
          sidecar_summary: null
        }
      ],
      diagnostics: [
        {
          severity: "warning",
          phase: "export",
          code: "LUME_PRINT_FONT_EMBEDDING",
          message: "PDF font embedding is not available for this preview profile.",
          subject: null,
          hint: "Use the export diagnostics before final print approval."
        }
      ]
    };

    render(<ExportPreviewSurface scene={minimalScene} activePageId="page_a4" exportResult={exportResult} />);

    expect(screen.getByText("Review warnings before approval")).toBeInTheDocument();
    expect(screen.getByText("1 warning should be reviewed before handoff.")).toBeInTheDocument();
    expect(screen.getByText("LUME_PRINT_FONT_EMBEDDING")).toBeInTheDocument();
  });

  it("shows export adapter diagnostics alongside parity diagnostics and blocks approval", () => {
    const onSelectSubject = vi.fn();
    const exportResult: EditorExportResult = {
      status: "failed",
      artifacts: [],
      diagnostics: [
        {
          severity: "warning",
          phase: "export",
          code: "LUME_PRINT_FONT_EMBEDDING",
          message: "PDF font embedding is not available for this preview profile.",
          subject: null,
          hint: "Use the export diagnostics before final print approval."
        },
        {
          severity: "warning",
          phase: "export",
          code: "LUME0418",
          message: "Text node overflows the PDF render box.",
          subject: {
            kind: "node",
            id: "node_contact_name"
          },
          hint: "Resize the node before final approval."
        }
      ]
    };

    render(
      <ExportPreviewSurface
        scene={minimalScene}
        activePageId="page_a4"
        exportResult={exportResult}
        onSelectSubject={onSelectSubject}
      />
    );

    expect(screen.getByText("No export")).toBeInTheDocument();
    expect(screen.getByText("Not ready for approval")).toBeInTheDocument();
    expect(screen.getByText("EDITOR_EXPORT_PARITY_ARTIFACT_REQUIRED")).toBeInTheDocument();
    expect(screen.getByText("LUME_PRINT_FONT_EMBEDDING")).toBeInTheDocument();
    expect(screen.getByText("PDF font embedding is not available for this preview profile.")).toBeInTheDocument();
    expect(screen.getByText("LUME0418")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /show node node_contact_name/i }));

    expect(onSelectSubject).toHaveBeenCalledWith({
      kind: "node",
      id: "node_contact_name"
    });
  });
});
