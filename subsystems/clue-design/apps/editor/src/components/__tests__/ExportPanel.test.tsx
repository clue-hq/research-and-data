import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { minimalScene } from "@/fixtures/minimalScene";
import type { EditorExportResult } from "@/engine/exportRunner";
import { ExportPanel } from "../ExportPanel";

describe("ExportPanel artifact actions", () => {
  const originalCreateObjectUrl = URL.createObjectURL;
  const originalRevokeObjectUrl = URL.revokeObjectURL;

  afterEach(() => {
    URL.createObjectURL = originalCreateObjectUrl;
    URL.revokeObjectURL = originalRevokeObjectUrl;
    vi.restoreAllMocks();
  });

  it("downloads artifacts through blob URLs instead of direct data URL navigation", () => {
    const createObjectURL = vi.fn(() => "blob:lumen-export");
    const revokeObjectURL = vi.fn();
    URL.createObjectURL = createObjectURL;
    URL.revokeObjectURL = revokeObjectURL;
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    render(
      <ExportPanel
        scene={minimalScene}
        activePageId="page_a4"
        exportResult={exportResult()}
        isExporting={false}
        onExport={() => {}}
        onSaveProfile={() => {}}
        onRemoveProfile={() => {}}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "Download" }));
    fireEvent.click(screen.getByRole("button", { name: "Download sidecar" }));

    expect(createObjectURL).toHaveBeenCalledTimes(2);
    expect(createObjectURL.mock.calls[0][0]).toBeInstanceOf(Blob);
    expect(createObjectURL.mock.calls[1][0]).toBeInstanceOf(Blob);
    expect(click).toHaveBeenCalledTimes(2);
  });
});

function exportResult(): EditorExportResult {
  return {
    status: "ok",
    artifacts: [
      {
        format: "svg",
        page_id: "page_a4",
        asset_id: null,
        filename: "page_a4.preview_svg.svg",
        sidecar_filename: "page_a4.preview_svg.sidecar.json",
        mime_type: "image/svg+xml",
        byte_length: 128,
        dimensions: {
          width: 595.3,
          height: 841.9,
          unit: "pt",
          source: "svg_view_box"
        },
        data_url: "data:image/svg+xml;base64,PHN2Zy8+",
        text: "<svg />",
        sidecar_json: '{"schema_version":1}',
        sidecar_summary: {
          profile_name: "preview_svg",
          page_count: 1,
          node_count: 1,
          slot_count: 0,
          page_ids: ["page_a4"],
          slot_keys: []
        }
      }
    ],
    diagnostics: []
  };
}
