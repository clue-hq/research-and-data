import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { minimalScene } from "@/fixtures/minimalScene";
import type { ExportProfile } from "@/engine/contracts";
import type { EditorExportResult } from "@/engine/exportRunner";
import { ExportPanel, type ExportPanelState } from "../ExportPanel";

function printPdfProfile(): ExportProfile {
  return {
    name: "print_pdf",
    format: "pdf",
    pdf_intent: "print",
    raster: null,
    include_bleed: false,
    include_marks: false,
    embed_fonts: true
  };
}

function panelState(profile: ExportProfile): ExportPanelState {
  return { profileName: profile.name, scope: "active", draftProfile: profile };
}

function okResult(printReady: EditorExportResult["printReady"]): EditorExportResult {
  return {
    status: "ok",
    diagnostics: [],
    artifacts: [
      {
        format: "pdf",
        page_id: "page_a4",
        asset_id: null,
        filename: "page_a4.pdf",
        sidecar_filename: null,
        mime_type: "application/pdf",
        byte_length: 8,
        dimensions: null,
        data_url: "data:application/pdf;base64,AAAA",
        text: null,
        sidecar_json: null,
        sidecar_summary: null
      }
    ],
    printReady
  };
}

function renderPanel(overrides: Partial<Parameters<typeof ExportPanel>[0]> = {}) {
  const onPanelStateChange = vi.fn();
  render(
    <ExportPanel
      scene={minimalScene}
      activePageId="page_a4"
      exportResult={null}
      isExporting={false}
      onExport={() => {}}
      onSaveProfile={() => {}}
      onRemoveProfile={() => {}}
      panelState={panelState(printPdfProfile())}
      onPanelStateChange={onPanelStateChange}
      printFeatureEnabled
      {...overrides}
    />
  );
  return onPanelStateChange;
}

describe("ExportPanel print controls (W3)", () => {
  it("hides the bleed/marks checkbox when the print feature is off", () => {
    renderPanel({ printFeatureEnabled: false });
    expect(screen.queryByRole("checkbox", { name: "Include bleed + crop marks" })).not.toBeInTheDocument();
  });

  it("shows the checkbox for a pdf profile when the feature is on and toggles both flags", () => {
    const onPanelStateChange = renderPanel();
    const checkbox = screen.getByRole("checkbox", { name: "Include bleed + crop marks" });
    expect(checkbox).not.toBeChecked();

    fireEvent.click(checkbox);
    expect(onPanelStateChange).toHaveBeenCalledTimes(1);
    const next = onPanelStateChange.mock.calls[0][0] as ExportPanelState;
    expect(next.draftProfile).toMatchObject({ include_bleed: true, include_marks: true });
  });

  it("does not show the checkbox for a non-pdf profile", () => {
    renderPanel({ panelState: panelState({ ...printPdfProfile(), format: "png", raster: { scale: 1, dpi: 96 } }) });
    expect(screen.queryByRole("checkbox", { name: "Include bleed + crop marks" })).not.toBeInTheDocument();
  });

  it("renders the print-ready block with the status pill and notable rules", () => {
    renderPanel({
      exportResult: okResult({
        ruleset: "commercial-print-v1",
        status: "warn",
        rules: [
          { id: "bleed_present", status: "pass", detail: "bleed present" },
          { id: "min_dpi", status: "warn", detail: "Image below 300dpi" }
        ]
      })
    });
    expect(screen.getByText("Print-ready with warnings")).toBeInTheDocument();
    // The clean (pass) rule collapses away; only the warning surfaces.
    expect(screen.getByText("Image below 300dpi")).toBeInTheDocument();
    expect(screen.queryByText("bleed present")).not.toBeInTheDocument();
  });

  it("shows a dismissible nudge for a print PDF with no bleed while the feature is off", () => {
    renderPanel({
      printFeatureEnabled: false,
      exportResult: okResult(null)
    });
    const nudge = screen.getByRole("note");
    expect(nudge).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Dismiss print hint" }));
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });

  it("does not nudge when the feature is on", () => {
    renderPanel({ exportResult: okResult(null) });
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });
});
