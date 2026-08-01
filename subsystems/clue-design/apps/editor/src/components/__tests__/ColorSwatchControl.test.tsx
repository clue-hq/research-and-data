import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { minimalScene } from "@/fixtures/minimalScene";
import type { BrandTokenCatalog, Fill, Node } from "@/engine/contracts";
import { setTokenColorMap } from "@/engine/renderAdapter";
import { ColorSwatchControl, isGradientGuarded } from "../ColorSwatchControl";

const baseTextNode = minimalScene.nodes.node_contact_name;

function node(overrides: Partial<Node> = {}): Node {
  return { ...structuredClone(baseTextNode), ...overrides } as Node;
}

function shapeNode(overrides: Partial<Node> = {}): Node {
  return { ...node({ kind: { kind: "rect" } } as Partial<Node>), ...overrides } as Node;
}

function solid(hex: string): Fill {
  return { id: "paint_a", paint: { kind: "solid", color: { kind: "hex", value: hex } } };
}

function tokenFillValue(token: string): Fill {
  return { id: "paint_a", paint: { kind: "token", token } };
}

function gradientFill(): Fill {
  return {
    id: "paint_a",
    paint: { kind: "linear_gradient", angle: 45, stops: [{ color: { kind: "hex", value: "#ff0000" }, position: 0 }] }
  };
}

const catalog: BrandTokenCatalog = {
  text_tokens: ["text.primary", "text.inverse"],
  surface_tokens: ["surface.brand", "surface.card"],
  border_tokens: ["border.default"]
};

describe("isGradientGuarded", () => {
  it("is false for a single solid or token fill", () => {
    expect(isGradientGuarded([solid("#112233")])).toBe(false);
    expect(isGradientGuarded([tokenFillValue("surface.brand")])).toBe(false);
    expect(isGradientGuarded([])).toBe(false);
  });

  it("is true for a gradient fill", () => {
    expect(isGradientGuarded([gradientFill()])).toBe(true);
  });

  it("is true for a multi-layer fill stack even if all solid", () => {
    expect(isGradientGuarded([solid("#112233"), solid("#445566")])).toBe(true);
  });
});

describe("ColorSwatchControl", () => {
  it("renders an empty-state swatch for a node with no fills", () => {
    render(<ColorSwatchControl node={node({ fills: [] })} onEdit={vi.fn()} />);
    expect(document.querySelector(".color-swatch-preview.empty")).toBeInTheDocument();
  });

  it("opens a popover with brand token groups, text tokens first for a text node", () => {
    render(<ColorSwatchControl node={node()} brandTokens={catalog} onEdit={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Fill color" }));

    const groupLabels = screen.getAllByText(/Text|Surface|Palette/).map((el) => el.textContent);
    expect(groupLabels[0]).toBe("Text");
    expect(screen.getByRole("listbox", { name: "Text" })).toBeInTheDocument();
    expect(screen.getByRole("listbox", { name: "Surface" })).toBeInTheDocument();
    expect(screen.getByRole("listbox", { name: "Palette" })).toBeInTheDocument();
  });

  it("groups surface tokens first for a non-text node", () => {
    render(<ColorSwatchControl node={shapeNode()} brandTokens={catalog} onEdit={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Fill color" }));

    const groupLabels = screen.getAllByText(/Text|Surface|Palette/).map((el) => el.textContent);
    expect(groupLabels[0]).toBe("Surface");
    expect(screen.queryByRole("listbox", { name: "Text" })).not.toBeInTheDocument();
  });

  it("emits a token fill (no style_token authored) when a brand swatch is picked", () => {
    const onEdit = vi.fn<(fills: Fill[]) => void>();
    render(<ColorSwatchControl node={node()} brandTokens={catalog} onEdit={onEdit} />);
    fireEvent.click(screen.getByRole("button", { name: "Fill color" }));

    fireEvent.click(screen.getByTitle("$text.primary"));

    expect(onEdit).toHaveBeenCalledTimes(1);
    const fills = onEdit.mock.calls[0][0];
    expect(fills).toEqual([{ id: expect.stringContaining("_fill"), paint: { kind: "token", token: "text.primary" } }]);
    // The operation carries only a fills field — no style_token key anywhere.
    expect(JSON.stringify(fills)).not.toContain("style_token");
  });

  it("emits a solid hex fill when the custom picker is used", () => {
    const onEdit = vi.fn<(fills: Fill[]) => void>();
    render(<ColorSwatchControl node={node()} brandTokens={catalog} onEdit={onEdit} />);
    fireEvent.click(screen.getByRole("button", { name: "Fill color" }));

    fireEvent.change(screen.getByLabelText("Custom color"), { target: { value: "#ff00aa" } });

    expect(onEdit).toHaveBeenCalledWith([
      { id: expect.stringContaining("_fill"), paint: { kind: "solid", color: { kind: "hex", value: "#ff00aa" } } }
    ]);
  });

  it("shows the gradient-clobber guard state and offers no destructive controls for a gradient fill", () => {
    const onEdit = vi.fn();
    render(<ColorSwatchControl node={node({ fills: [gradientFill()] })} brandTokens={catalog} onEdit={onEdit} />);

    expect(document.querySelector(".color-swatch-preview.mixed")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Fill color" }));
    expect(screen.getByText("Gradient fill — edit in Appearance")).toBeInTheDocument();
    expect(screen.queryByLabelText("Custom color")).not.toBeInTheDocument();
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(onEdit).not.toHaveBeenCalled();
  });

  it("shows the gradient-clobber guard state for a multi-fill stack", () => {
    render(<ColorSwatchControl node={node({ fills: [solid("#112233"), solid("#445566")] })} onEdit={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Fill color" }));
    expect(screen.getByText("Gradient fill — edit in Appearance")).toBeInTheDocument();
  });

  it("disables the trigger on a locked node", () => {
    render(<ColorSwatchControl node={node({ locked: true })} onEdit={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Fill color" })).toBeDisabled();
  });

  describe("real resolved swatch colors (R1d)", () => {
    afterEach(() => {
      setTokenColorMap({});
    });

    it("paints token chips and the token trigger preview with the resolved color", () => {
      setTokenColorMap({ "text.primary": "#112233", "surface.brand": "#445566" });
      render(
        <ColorSwatchControl node={node({ fills: [tokenFillValue("text.primary")] })} brandTokens={catalog} onEdit={vi.fn()} />
      );

      // Trigger preview: inline background = exactly what the canvas paints.
      const preview = document.querySelector(".color-swatch-preview.token") as HTMLElement;
      expect(preview).toBeInTheDocument();
      expect(preview.style.background).toBe("rgb(17, 34, 51)");
      expect(preview.title).toBe("$text.primary");

      // Popover chips carry the resolved inline background too.
      fireEvent.click(screen.getByRole("button", { name: "Fill color" }));
      const chip = screen.getByTitle("$surface.brand") as HTMLElement;
      expect(chip.style.background).toBe("rgb(68, 85, 102)");

      // The token name survives for assistive tech, visually hidden.
      const badge = chip.querySelector(".color-swatch-token-badge");
      expect(badge?.textContent).toBe("surface.brand");
    });

    it("a token missing from the map falls back to the paint path's heuristic color", () => {
      render(
        <ColorSwatchControl node={node({ fills: [tokenFillValue("text.primary")] })} brandTokens={catalog} onEdit={vi.fn()} />
      );
      const preview = document.querySelector(".color-swatch-preview.token") as HTMLElement;
      expect(preview.style.background).toBe("rgb(39, 35, 29)"); // #27231d — the "text" heuristic bucket
    });

    it("empty and mixed states carry no inline background and keep their classes", () => {
      const { unmount } = render(<ColorSwatchControl node={node({ fills: [] })} onEdit={vi.fn()} />);
      const empty = document.querySelector(".color-swatch-preview.empty") as HTMLElement;
      expect(empty).toBeInTheDocument();
      expect(empty.getAttribute("style")).toBeNull();
      unmount();

      render(<ColorSwatchControl node={node({ fills: [gradientFill()] })} onEdit={vi.fn()} />);
      const mixed = document.querySelector(".color-swatch-preview.mixed") as HTMLElement;
      expect(mixed).toBeInTheDocument();
      expect(mixed.getAttribute("style")).toBeNull();
    });
  });
});
