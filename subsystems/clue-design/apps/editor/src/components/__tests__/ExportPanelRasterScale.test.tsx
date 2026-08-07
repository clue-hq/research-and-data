import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { minimalScene } from "@/fixtures/minimalScene";
import type { ExportProfile, Page } from "@/engine/contracts";
import { estimatePngPixelSize } from "@/engine/exportRunner";
import { ExportPanel, RASTER_SCALE_PRESETS, type ExportPanelState } from "../ExportPanel";

function pngProfile(overrides: Partial<ExportProfile> = {}): ExportProfile {
  return {
    name: "preview_png",
    format: "png",
    pdf_intent: null,
    raster: { scale: 1, dpi: 96 },
    include_bleed: false,
    include_marks: false,
    embed_fonts: false,
    ...overrides
  };
}

function panelState(profile: ExportProfile): ExportPanelState {
  return { profileName: profile.name, scope: "active", draftProfile: profile };
}

function renderPanel(profile: ExportProfile) {
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
      panelState={panelState(profile)}
      onPanelStateChange={onPanelStateChange}
    />
  );
  return onPanelStateChange;
}

describe("ExportPanel raster scale selector", () => {
  it("shows the Size select with all presets for a png profile", () => {
    renderPanel(pngProfile());
    const select = screen.getByRole("combobox", { name: /Size/ });
    const values = [...select.querySelectorAll("option")].map((option) => option.textContent);
    expect(values).toEqual(RASTER_SCALE_PRESETS.map((preset) => `${preset}x`));
  });

  it("does not show the Size select for vector formats", () => {
    renderPanel({ ...pngProfile(), format: "svg", raster: null });
    expect(screen.queryByRole("combobox", { name: /Size/ })).not.toBeInTheDocument();
  });

  it("writes raster.scale through the profile draft and keeps the dpi", () => {
    const onPanelStateChange = renderPanel(pngProfile({ raster: { scale: 1, dpi: 300 } }));
    fireEvent.change(screen.getByRole("combobox", { name: /Size/ }), { target: { value: "3" } });
    const next = onPanelStateChange.mock.calls[0][0] as ExportPanelState;
    expect(next.draftProfile?.raster).toEqual({ scale: 3, dpi: 300 });
  });

  it("shows the estimated output pixel size for the active page", () => {
    // page_a4 is a raw 210x297mm page: 210/25.4*96 = 794 px at 1x.
    renderPanel(pngProfile());
    expect(screen.getByText("794 × 1123 px")).toBeInTheDocument();
  });

  it("keeps a non-preset saved scale visible in the options", () => {
    renderPanel(pngProfile({ raster: { scale: 2.5, dpi: 96 } }));
    const select = screen.getByRole("combobox", { name: /Size/ }) as HTMLSelectElement;
    expect(select.value).toBe("2.5");
    expect(screen.getByRole("option", { name: "2.5x" })).toBeInTheDocument();
  });

  it("warns when the estimate exceeds the server raster budget", () => {
    // 210x297mm at 1200 dpi and 4x is ~2.2 GP — far over the 150 MP ceiling.
    renderPanel(pngProfile({ raster: { scale: 4, dpi: 1200 } }));
    expect(screen.getByText(/exceeds the 150 MP export limit/)).toBeInTheDocument();
  });
});

describe("estimatePngPixelSize", () => {
  const basePage: Page = {
    id: "page_test",
    name: "Test",
    size: {
      width: 810,
      height: 810,
      unit: "pt",
      preset: "custom",
      orientation: "portrait",
      source: { width: 1080, height: 1080, unit: "px" },
      output: { physical: null, raster: { width_px: 1080, height_px: 1080 } }
    },
    children: [],
    bleed: null,
    safe_area: null,
    background: []
  };

  it("scales canonical pt layout for px-authored pages (figma multiplier semantics)", () => {
    // Mirrors page_pixel_size: canonical page + raster profile without a
    // physical size falls back to layout pt x scale (px == pt, 1:1).
    expect(estimatePngPixelSize(basePage, { scale: 2, dpi: 96 })).toEqual({
      width: 1620,
      height: 1620
    });
  });

  it("uses the raster hint when the profile has no raster block", () => {
    expect(estimatePngPixelSize(basePage, null)).toEqual({ width: 1080, height: 1080 });
  });

  it("uses physical size x dpi x scale for physical pages", () => {
    const physicalPage: Page = {
      ...basePage,
      size: {
        ...basePage.size,
        width: 595.2756,
        height: 841.8898,
        output: {
          physical: { width: 210, height: 297, unit: "mm" },
          raster: null
        }
      }
    };
    // A4 at 300 dpi: 2480 x 3508 (the engine's own test expectation).
    expect(estimatePngPixelSize(physicalPage, { scale: 1, dpi: 300 })).toEqual({
      width: 2480,
      height: 3508
    });
    expect(estimatePngPixelSize(physicalPage, { scale: 2, dpi: 300 })).toEqual({
      width: 4961,
      height: 7016
    });
  });
});
