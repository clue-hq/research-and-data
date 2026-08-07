import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ExportProfile, Page, Rect } from "@/engine/contracts";
import { ExportMenu, type ExportMenuScope } from "../ExportMenu";
import { RASTER_SCALE_PRESETS } from "../ExportPanel";

const BLEED: Rect = { x: -9, y: -9, width: 18, height: 18 };

function makePage(id: string, name: string, bleed: Rect | null): Page {
  return {
    id,
    name,
    size: { width: 612, height: 792, unit: "pt", preset: "us_letter", orientation: "portrait" },
    children: [],
    bleed,
    safe_area: null,
    background: []
  };
}

function renderMenu(
  options: { pages?: Page[]; activePageId?: string | null } = {}
) {
  const pages = options.pages ?? [
    makePage("page-1", "Page one", BLEED),
    makePage("page-2", "Page two", BLEED)
  ];
  const activePageId = options.activePageId ?? "page-1";
  const onDownload = vi.fn<(profile: ExportProfile, scope: ExportMenuScope) => void>();
  render(
    <ExportMenu
      pages={pages}
      activePageId={activePageId}
      isExporting={false}
      onDownload={onDownload}
      onClose={() => {}}
    />
  );
  return onDownload;
}

/** Switch the popover to a print-intent PDF (the only combination that exposes
 * the bleed/marks control and its pre-export nudge). */
function selectPrintPdf() {
  fireEvent.change(screen.getByRole("combobox", { name: /File type/ }), {
    target: { value: "pdf" }
  });
  fireEvent.change(screen.getByRole("combobox", { name: /Intent/ }), {
    target: { value: "print" }
  });
}

describe("ExportMenu (topbar export popover)", () => {
  it("offers the full shared raster-scale preset list for PNG", () => {
    renderMenu();
    const select = screen.getByRole("combobox", { name: /Size/ });
    const values = [...select.querySelectorAll("option")].map((option) =>
      Number((option as HTMLOptionElement).value)
    );
    expect(values).toEqual(RASTER_SCALE_PRESETS);
  });

  it("composes the PNG profile from the chosen preset scale", () => {
    const onDownload = renderMenu();
    fireEvent.change(screen.getByRole("combobox", { name: /Size/ }), {
      target: { value: "3" }
    });
    fireEvent.click(screen.getByRole("button", { name: /Download/ }));
    const [profile] = onDownload.mock.calls[0];
    expect(profile.format).toBe("png");
    expect(profile.raster).toEqual({ scale: 3, dpi: 288 });
  });

  it("fractional presets compose integral dpi", () => {
    const onDownload = renderMenu();
    fireEvent.change(screen.getByRole("combobox", { name: /Size/ }), {
      target: { value: "0.5" }
    });
    fireEvent.click(screen.getByRole("button", { name: /Download/ }));
    const [profile] = onDownload.mock.calls[0];
    expect(profile.raster).toEqual({ scale: 0.5, dpi: 48 });
  });

  it("SVG downloads embed fonts", () => {
    const onDownload = renderMenu();
    fireEvent.change(screen.getByRole("combobox", { name: /File type/ }), {
      target: { value: "svg" }
    });
    fireEvent.click(screen.getByRole("button", { name: /Download/ }));
    const [profile] = onDownload.mock.calls[0];
    expect(profile.format).toBe("svg");
    expect(profile.embed_fonts).toBe(true);
  });

  describe("print finish (bleed & marks) control", () => {
    it("is hidden for PNG, SVG, and preview-intent PDF", () => {
      renderMenu();
      // PNG (default)
      expect(screen.queryByRole("combobox", { name: /Bleed & marks/ })).toBeNull();
      // SVG
      fireEvent.change(screen.getByRole("combobox", { name: /File type/ }), {
        target: { value: "svg" }
      });
      expect(screen.queryByRole("combobox", { name: /Bleed & marks/ })).toBeNull();
      // PDF, preview intent
      fireEvent.change(screen.getByRole("combobox", { name: /File type/ }), {
        target: { value: "pdf" }
      });
      expect(screen.queryByRole("combobox", { name: /Bleed & marks/ })).toBeNull();
    });

    it("is shown with bleed + crop marks selected by default for print-intent PDF", () => {
      renderMenu();
      selectPrintPdf();
      const select = screen.getByRole("combobox", { name: /Bleed & marks/ }) as HTMLSelectElement;
      expect(select.value).toBe("bleed_marks");
    });

    it("default finish emits include_bleed + include_marks", () => {
      const onDownload = renderMenu();
      selectPrintPdf();
      fireEvent.click(screen.getByRole("button", { name: /Download/ }));
      const [profile] = onDownload.mock.calls[0];
      expect(profile.format).toBe("pdf");
      expect(profile.pdf_intent).toBe("print");
      expect(profile.include_bleed).toBe(true);
      expect(profile.include_marks).toBe(true);
    });

    it("bleed-only finish emits include_bleed without include_marks", () => {
      const onDownload = renderMenu();
      selectPrintPdf();
      fireEvent.change(screen.getByRole("combobox", { name: /Bleed & marks/ }), {
        target: { value: "bleed" }
      });
      fireEvent.click(screen.getByRole("button", { name: /Download/ }));
      const [profile] = onDownload.mock.calls[0];
      expect(profile.include_bleed).toBe(true);
      expect(profile.include_marks).toBe(false);
    });

    it("finish 'none' drops both include_bleed and include_marks", () => {
      const onDownload = renderMenu();
      selectPrintPdf();
      fireEvent.change(screen.getByRole("combobox", { name: /Bleed & marks/ }), {
        target: { value: "none" }
      });
      fireEvent.click(screen.getByRole("button", { name: /Download/ }));
      const [profile] = onDownload.mock.calls[0];
      expect(profile.include_bleed).toBe(false);
      expect(profile.include_marks).toBe(false);
    });

    it("preview-intent PDF always emits bleed/marks false", () => {
      const onDownload = renderMenu();
      fireEvent.change(screen.getByRole("combobox", { name: /File type/ }), {
        target: { value: "pdf" }
      });
      fireEvent.click(screen.getByRole("button", { name: /Download/ }));
      const [profile] = onDownload.mock.calls[0];
      expect(profile.pdf_intent).toBe("preview");
      expect(profile.include_bleed).toBe(false);
      expect(profile.include_marks).toBe(false);
    });
  });

  describe("pre-export bleed nudge", () => {
    const note = () => screen.queryByRole("note");

    it("is hidden when the in-scope artboards all have a bleed rect", () => {
      renderMenu({ activePageId: "page-1" });
      selectPrintPdf();
      // Scope defaults to "all" (2 pages), both with bleed.
      expect(note()).toBeNull();
    });

    it("warns when a print PDF exports an artboard with no bleed rect", () => {
      renderMenu({
        pages: [makePage("page-1", "Page one", null), makePage("page-2", "Page two", BLEED)],
        activePageId: "page-1"
      });
      selectPrintPdf();
      // Scope "all": one of two artboards lacks bleed.
      const shown = note();
      expect(shown).not.toBeNull();
      expect(shown?.textContent).toMatch(/no bleed area/i);
    });

    it("respects the Pages scope — a bleed-less active page nudges under 'current' scope", () => {
      renderMenu({
        pages: [makePage("page-1", "Page one", null), makePage("page-2", "Page two", BLEED)],
        activePageId: "page-2"
      });
      selectPrintPdf();
      // Default scope "all" already nudges (page-1 has no bleed).
      expect(note()).not.toBeNull();
      // Narrow to the active page (page-2, which HAS bleed): nudge clears.
      fireEvent.change(screen.getByRole("combobox", { name: /Pages/ }), {
        target: { value: "active" }
      });
      expect(note()).toBeNull();
      // Point the active page at the bleed-less artboard: nudge returns.
    });

    it("nudge follows the active bleed-less page under 'current' scope", () => {
      renderMenu({
        pages: [makePage("page-1", "Page one", null), makePage("page-2", "Page two", BLEED)],
        activePageId: "page-1"
      });
      selectPrintPdf();
      fireEvent.change(screen.getByRole("combobox", { name: /Pages/ }), {
        target: { value: "active" }
      });
      expect(note()).not.toBeNull();
      expect(note()?.textContent).toMatch(/this artboard has no bleed area/i);
    });

    it("does not warn for a preview-intent PDF even without bleed", () => {
      renderMenu({
        pages: [makePage("page-1", "Page one", null)],
        activePageId: "page-1"
      });
      fireEvent.change(screen.getByRole("combobox", { name: /File type/ }), {
        target: { value: "pdf" }
      });
      expect(note()).toBeNull();
    });
  });
});
