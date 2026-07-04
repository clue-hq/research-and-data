import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { minimalScene } from "@/fixtures/minimalScene";
import type { BrandTokenCatalog, Node } from "@/engine/contracts";
import { RawStyleSection } from "../RawStyleSection";

const baseNode = minimalScene.nodes.node_contact_name;

function node(overrides: Partial<Node> = {}): Node {
  return { ...structuredClone(baseNode), ...overrides } as Node;
}

const catalog: BrandTokenCatalog = {
  text_tokens: ["text.primary"],
  surface_tokens: ["surface.brand"]
};

describe("RawStyleSection", () => {
  it("uses the token-first ColorSwatchControl for the fill color, not a bare color input", () => {
    render(<RawStyleSection selectedNode={node()} brandTokens={catalog} onOperation={vi.fn()} />);
    const trigger = screen.getByLabelText("Fill color");
    expect(trigger.tagName).toBe("BUTTON");
    expect(trigger).not.toHaveAttribute("type", "color");
  });

  it("opens the popover with brand tokens threaded from the caller", () => {
    render(<RawStyleSection selectedNode={node()} brandTokens={catalog} onOperation={vi.fn()} />);
    fireEvent.click(screen.getByLabelText("Fill color"));
    expect(screen.getByTitle("$surface.brand")).toBeInTheDocument();
  });

  it("still renders the stroke color as a plain native color input (unchanged)", () => {
    render(<RawStyleSection selectedNode={node()} onOperation={vi.fn()} />);
    expect(screen.getByLabelText("Stroke Color")).toHaveAttribute("type", "color");
  });

  it("guards a gradient fill instead of offering a destructive replace", () => {
    const gradientNode = node({
      fills: [
        {
          id: "paint_a",
          paint: { kind: "linear_gradient", angle: 0, stops: [{ color: { kind: "hex", value: "#ff0000" }, position: 0 }] }
        }
      ]
    });
    render(<RawStyleSection selectedNode={gradientNode} onOperation={vi.fn()} />);
    fireEvent.click(screen.getByLabelText("Fill color"));
    expect(screen.getByText("Gradient fill — edit in Appearance")).toBeInTheDocument();
  });
});
