import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ExportProfile } from "@/engine/contracts";
import { ExportMenu, type ExportMenuScope } from "../ExportMenu";
import { RASTER_SCALE_PRESETS } from "../ExportPanel";

function renderMenu() {
  const onDownload = vi.fn<(profile: ExportProfile, scope: ExportMenuScope) => void>();
  render(
    <ExportMenu
      pageCount={2}
      activePageName="Page one"
      isExporting={false}
      onDownload={onDownload}
      onClose={() => {}}
    />
  );
  return onDownload;
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
});
