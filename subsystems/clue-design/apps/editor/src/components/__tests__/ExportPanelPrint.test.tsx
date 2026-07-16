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
  it("hides the print-finish select when the print feature is off", () => {
    renderPanel({ printFeatureEnabled: false });
    expect(screen.queryByRole("combobox", { name: /Bleed & marks/ })).not.toBeInTheDocument();
  });

  it("shows the finish select for a pdf profile and 'bleed + marks' sets both flags", () => {
    const onPanelStateChange = renderPanel();
    const select = screen.getByRole("combobox", { name: /Bleed & marks/ }) as HTMLSelectElement;
    expect(select.value).toBe("none");

    fireEvent.change(select, { target: { value: "bleed_marks" } });
    expect(onPanelStateChange).toHaveBeenCalledTimes(1);
    const next = onPanelStateChange.mock.calls[0][0] as ExportPanelState;
    expect(next.draftProfile).toMatchObject({ include_bleed: true, include_marks: true });
  });

  it("'bleed only' sets include_bleed without include_marks", () => {
    const onPanelStateChange = renderPanel();
    fireEvent.change(screen.getByRole("combobox", { name: /Bleed & marks/ }), {
      target: { value: "bleed" }
    });
    const next = onPanelStateChange.mock.calls[0][0] as ExportPanelState;
    expect(next.draftProfile).toMatchObject({ include_bleed: true, include_marks: false });
  });

  it("'none' clears both flags", () => {
    const onPanelStateChange = renderPanel({
      panelState: panelState({ ...printPdfProfile(), include_bleed: true, include_marks: true })
    });
    const select = screen.getByRole("combobox", { name: /Bleed & marks/ }) as HTMLSelectElement;
    expect(select.value).toBe("bleed_marks");

    fireEvent.change(select, { target: { value: "none" } });
    const next = onPanelStateChange.mock.calls[0][0] as ExportPanelState;
    expect(next.draftProfile).toMatchObject({ include_bleed: false, include_marks: false });
  });

  it("a bleed-only saved profile round-trips: the select reads 'bleed'", () => {
    renderPanel({
      panelState: panelState({ ...printPdfProfile(), include_bleed: true, include_marks: false })
    });
    const select = screen.getByRole("combobox", { name: /Bleed & marks/ }) as HTMLSelectElement;
    expect(select.value).toBe("bleed");
  });

  it("does not show the finish select for a non-pdf profile", () => {
    renderPanel({ panelState: panelState({ ...printPdfProfile(), format: "png", raster: { scale: 1, dpi: 96 } }) });
    expect(screen.queryByRole("combobox", { name: /Bleed & marks/ })).not.toBeInTheDocument();
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

  it("shows the booklet checkbox for a pdf profile when the feature is on and sets imposition", () => {
    const onPanelStateChange = renderPanel();
    const checkbox = screen.getByRole("checkbox", { name: "Booklet imposition (2-up saddle-stitch)" });
    expect(checkbox).not.toBeChecked();

    fireEvent.click(checkbox);
    expect(onPanelStateChange).toHaveBeenCalledTimes(1);
    const next = onPanelStateChange.mock.calls[0][0] as ExportPanelState;
    expect(next.draftProfile).toMatchObject({ imposition: "booklet" });
  });

  it("clears imposition when the booklet checkbox is unchecked", () => {
    const onPanelStateChange = renderPanel({
      panelState: panelState({ ...printPdfProfile(), imposition: "booklet" })
    });
    const checkbox = screen.getByRole("checkbox", { name: "Booklet imposition (2-up saddle-stitch)" });
    expect(checkbox).toBeChecked();

    fireEvent.click(checkbox);
    const next = onPanelStateChange.mock.calls[0][0] as ExportPanelState;
    expect(next.draftProfile?.imposition).toBeUndefined();
  });

  it("hides the booklet checkbox when the print feature is off", () => {
    renderPanel({ printFeatureEnabled: false });
    expect(
      screen.queryByRole("checkbox", { name: "Booklet imposition (2-up saddle-stitch)" })
    ).not.toBeInTheDocument();
  });

  it("does not show the booklet checkbox for a non-pdf profile", () => {
    renderPanel({ panelState: panelState({ ...printPdfProfile(), format: "png", raster: { scale: 1, dpi: 96 } }) });
    expect(
      screen.queryByRole("checkbox", { name: "Booklet imposition (2-up saddle-stitch)" })
    ).not.toBeInTheDocument();
  });

  it("shows the proof checkbox for a pdf profile when the feature is on and sets proof", () => {
    const onPanelStateChange = renderPanel();
    const checkbox = screen.getByRole("checkbox", { name: "Proof export (marks + slug + control strip)" });
    expect(checkbox).not.toBeChecked();

    fireEvent.click(checkbox);
    expect(onPanelStateChange).toHaveBeenCalledTimes(1);
    const next = onPanelStateChange.mock.calls[0][0] as ExportPanelState;
    expect(next.draftProfile).toMatchObject({ proof: true });
  });

  it("clears proof when the proof checkbox is unchecked", () => {
    const onPanelStateChange = renderPanel({
      panelState: panelState({ ...printPdfProfile(), proof: true })
    });
    // When proof is on, the inline "Not for production" note joins the label's
    // accessible name, so match by prefix.
    const checkbox = screen.getByRole("checkbox", { name: /^Proof export/ });
    expect(checkbox).toBeChecked();

    fireEvent.click(checkbox);
    const next = onPanelStateChange.mock.calls[0][0] as ExportPanelState;
    expect(next.draftProfile?.proof).toBeUndefined();
  });

  it("hides the proof checkbox when the print feature is off", () => {
    renderPanel({ printFeatureEnabled: false });
    expect(
      screen.queryByRole("checkbox", { name: "Proof export (marks + slug + control strip)" })
    ).not.toBeInTheDocument();
  });

  it("does not show the proof checkbox for a non-pdf profile", () => {
    renderPanel({ panelState: panelState({ ...printPdfProfile(), format: "png", raster: { scale: 1, dpi: 96 } }) });
    expect(
      screen.queryByRole("checkbox", { name: "Proof export (marks + slug + control strip)" })
    ).not.toBeInTheDocument();
  });

  it("shows the not-for-production note only when proof is on", () => {
    const { rerender } = renderTestPanel(panelState(printPdfProfile()));
    expect(screen.queryByText(/Not for production runs/i)).not.toBeInTheDocument();

    rerender(panelState({ ...printPdfProfile(), proof: true }));
    expect(screen.getByText(/Not for production runs/i)).toBeInTheDocument();
    expect(screen.getByText(/LUME0431/)).toBeInTheDocument();
  });

  it("shows the CMYK checkbox for a print-intent pdf and writes color:cmyk when toggled on", () => {
    const onPanelStateChange = renderPanel();
    const checkbox = screen.getByRole("checkbox", { name: "CMYK for offset press (print intent only)" });
    expect(checkbox).not.toBeChecked();

    fireEvent.click(checkbox);
    expect(onPanelStateChange).toHaveBeenCalledTimes(1);
    const next = onPanelStateChange.mock.calls[0][0] as ExportPanelState;
    expect(next.draftProfile).toMatchObject({ color: "cmyk" });
  });

  it("clears color when the CMYK checkbox is unchecked", () => {
    const onPanelStateChange = renderPanel({
      panelState: panelState({ ...printPdfProfile(), color: "cmyk" })
    });
    const checkbox = screen.getByRole("checkbox", { name: "CMYK for offset press (print intent only)" });
    expect(checkbox).toBeChecked();

    fireEvent.click(checkbox);
    const next = onPanelStateChange.mock.calls[0][0] as ExportPanelState;
    expect(next.draftProfile?.color).toBeUndefined();
  });

  it("hides the CMYK checkbox for a preview-intent pdf", () => {
    renderPanel({ panelState: panelState({ ...printPdfProfile(), pdf_intent: "preview" }) });
    expect(
      screen.queryByRole("checkbox", { name: "CMYK for offset press (print intent only)" })
    ).not.toBeInTheDocument();
  });

  it("hides the CMYK checkbox when the print feature is off", () => {
    renderPanel({ printFeatureEnabled: false });
    expect(
      screen.queryByRole("checkbox", { name: "CMYK for offset press (print intent only)" })
    ).not.toBeInTheDocument();
  });

  it("does not show the CMYK checkbox for a non-pdf profile", () => {
    renderPanel({ panelState: panelState({ ...printPdfProfile(), format: "png", raster: { scale: 1, dpi: 96 } }) });
    expect(
      screen.queryByRole("checkbox", { name: "CMYK for offset press (print intent only)" })
    ).not.toBeInTheDocument();
  });

  it("strips color:cmyk when proof is turned on — the strip stays sRGB", () => {
    // proof + cmyk is a hard server error (export.cmyk_proof_conflict); the
    // panel must never compose the pair. Proof wins.
    const onPanelStateChange = renderPanel({
      panelState: panelState({ ...printPdfProfile(), color: "cmyk" })
    });
    fireEvent.click(
      screen.getByRole("checkbox", { name: /Proof export/ })
    );
    const next = onPanelStateChange.mock.calls[0][0] as ExportPanelState;
    expect(next.draftProfile?.proof).toBe(true);
    expect(next.draftProfile?.color).toBeUndefined();
  });

  it("disables the CMYK checkbox while proof is on and explains why", () => {
    renderPanel({
      panelState: panelState({ ...printPdfProfile(), proof: true })
    });
    expect(
      screen.getByRole("checkbox", { name: /CMYK for offset press/ })
    ).toBeDisabled();
    expect(screen.getByText(/control strip stays sRGB/)).toBeInTheDocument();
  });

  it("shows the imposed-marks note beside the bleed control only when booklet is on", () => {
    const { rerender } = renderTestPanel(panelState(printPdfProfile()));
    expect(screen.queryByText(/imposed booklet sheets/i)).not.toBeInTheDocument();

    rerender(panelState({ ...printPdfProfile(), imposition: "booklet" }));
    expect(screen.getByText(/imposed booklet sheets/i)).toBeInTheDocument();
    expect(screen.getByText(/LUME0430/)).toBeInTheDocument();
  });
});

function renderTestPanel(state: ExportPanelState) {
  const view = render(
    <ExportPanel
      scene={minimalScene}
      activePageId="page_a4"
      exportResult={null}
      isExporting={false}
      onExport={() => {}}
      onSaveProfile={() => {}}
      onRemoveProfile={() => {}}
      panelState={state}
      onPanelStateChange={() => {}}
      printFeatureEnabled
    />
  );
  return {
    rerender: (next: ExportPanelState) =>
      view.rerender(
        <ExportPanel
          scene={minimalScene}
          activePageId="page_a4"
          exportResult={null}
          isExporting={false}
          onExport={() => {}}
          onSaveProfile={() => {}}
          onRemoveProfile={() => {}}
          panelState={next}
          onPanelStateChange={() => {}}
          printFeatureEnabled
        />
      )
  };
}
