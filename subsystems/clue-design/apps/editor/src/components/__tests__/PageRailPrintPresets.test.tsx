import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { emptyScene } from "@/fixtures/emptyScene";
import { PageRail, type CustomPageInput } from "../PageRail";

function renderRail(printFeatureEnabled: boolean, onAddCustomPage = vi.fn()) {
  render(
    <PageRail
      scene={emptyScene}
      activePageId={null}
      printFeatureEnabled={printFeatureEnabled}
      onSelectPage={() => {}}
      onAddCustomPage={onAddCustomPage}
      onDuplicatePage={() => {}}
      onRemovePage={() => {}}
    />
  );
  return onAddCustomPage;
}

describe("PageRail print presets (W3)", () => {
  it("hides the print presets when the print feature is off", () => {
    renderRail(false);
    expect(screen.queryByRole("button", { name: "A4 print" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "US Letter print" })).not.toBeInTheDocument();
    // Existing non-print quick sizes still render.
    expect(screen.getByRole("button", { name: "1080x1080" })).toBeInTheDocument();
  });

  it("shows the print presets when the print feature is on", () => {
    renderRail(true);
    expect(screen.getByRole("button", { name: "A4 print" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "US Letter print" })).toBeInTheDocument();
  });

  it("adds an A4 print page marked print=true with the mm source size", () => {
    const onAdd = renderRail(true);
    fireEvent.click(screen.getByRole("button", { name: "A4 print" }));
    {
      const addButtons = screen.getAllByRole("button", { name: "Add artboard" });
      fireEvent.click(addButtons[addButtons.length - 1]);
    }

    expect(onAdd).toHaveBeenCalledTimes(1);
    const input = onAdd.mock.calls[0][0] as CustomPageInput;
    expect(input).toMatchObject({ name: "A4 print", width: 210, height: 297, unit: "mm", print: true });
  });

  it("adds a non-print quick size with print=false", () => {
    const onAdd = renderRail(true);
    fireEvent.click(screen.getByRole("button", { name: "1200x628" }));
    {
      const addButtons = screen.getAllByRole("button", { name: "Add artboard" });
      fireEvent.click(addButtons[addButtons.length - 1]);
    }

    const input = onAdd.mock.calls[0][0] as CustomPageInput;
    expect(input.print).toBe(false);
  });

  it("clears the print marker when a dimension is edited after choosing a print preset", () => {
    const onAdd = renderRail(true);
    fireEvent.click(screen.getByRole("button", { name: "A4 print" }));
    fireEvent.change(screen.getByLabelText("Custom artboard width"), { target: { value: "300" } });
    {
      const addButtons = screen.getAllByRole("button", { name: "Add artboard" });
      fireEvent.click(addButtons[addButtons.length - 1]);
    }

    const input = onAdd.mock.calls[0][0] as CustomPageInput;
    expect(input.print).toBe(false);
  });
});
