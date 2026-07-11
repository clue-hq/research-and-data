import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { minimalScene } from "@/fixtures/minimalScene";
import type { BrandTokenCatalog, Node, Operation } from "@/engine/contracts";
import { updateNodeFills, updateTextNode } from "@/engine/operations";
import { TextToolbar } from "../TextToolbar";

const baseTextNode = minimalScene.nodes.node_contact_name;

function textNode(overrides: Partial<Extract<Node["kind"], { kind: "text" }>> = {}, locked = false): Node {
  const node = structuredClone(baseTextNode);
  node.kind = { ...node.kind, ...overrides } as Node["kind"];
  node.locked = locked;
  return node;
}

describe("TextToolbar", () => {
  it("renders nothing without a text selection", () => {
    const { container, rerender } = render(<TextToolbar selectedNode={null} onOperation={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();

    const frame: Node = { ...structuredClone(baseTextNode), kind: { kind: "frame" } };
    rerender(<TextToolbar selectedNode={frame} onOperation={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("binds the selected node's typography values", () => {
    render(<TextToolbar selectedNode={textNode()} onOperation={vi.fn()} />);

    expect(screen.getByLabelText("Font family")).toHaveValue("Inter");
    expect(screen.getByLabelText("Font weight")).toHaveValue("600");
    expect(screen.getByLabelText("Font size")).toHaveValue(18);
    expect(screen.getByLabelText("Align left")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("Align center")).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByLabelText("Line height")).toHaveValue(1.2);
    expect(screen.getByLabelText("Letter spacing")).toHaveValue(0);
  });

  it("emits canonical updateTextNode operations", () => {
    const node = textNode();
    const onOperation = vi.fn<(operation: Operation) => void>();
    render(<TextToolbar selectedNode={node} onOperation={onOperation} />);

    fireEvent.change(screen.getByLabelText("Font size"), { target: { value: "44" } });
    expect(onOperation).toHaveBeenLastCalledWith(updateTextNode(node, { font_size: 44 }));

    fireEvent.change(screen.getByLabelText("Font weight"), { target: { value: "700" } });
    expect(onOperation).toHaveBeenLastCalledWith(updateTextNode(node, { font_weight: 700 }));

    fireEvent.click(screen.getByLabelText("Align center"));
    expect(onOperation).toHaveBeenLastCalledWith(updateTextNode(node, { align: "center" }));

    fireEvent.change(screen.getByLabelText("Line height"), { target: { value: "1.4" } });
    expect(onOperation).toHaveBeenLastCalledWith(updateTextNode(node, { line_height: 1.4 }));

    fireEvent.change(screen.getByLabelText("Letter spacing"), { target: { value: "0.5" } });
    expect(onOperation).toHaveBeenLastCalledWith(updateTextNode(node, { letter_spacing: 0.5 }));

    fireEvent.change(screen.getByLabelText("Font family"), { target: { value: "Space Grotesk" } });
    expect(onOperation).toHaveBeenLastCalledWith(updateTextNode(node, { font_family: "Space Grotesk" }));
  });

  it("shows the style-role chip only while the node is bound", () => {
    const { rerender } = render(
      <TextToolbar selectedNode={textNode({ style_token: "type.h1" })} onOperation={vi.fn()} />
    );
    expect(screen.getByTestId("text-toolbar-token-chip")).toHaveTextContent("type.h1");

    rerender(<TextToolbar selectedNode={textNode()} onOperation={vi.fn()} />);
    expect(screen.queryByTestId("text-toolbar-token-chip")).not.toBeInTheDocument();
  });

  it("offers the node's off-scale weight without losing it in the picker", () => {
    render(<TextToolbar selectedNode={textNode({ font_weight: 650 })} onOperation={vi.fn()} />);
    expect(screen.getByLabelText("Font weight")).toHaveValue("650");
  });

  it("disables every control on a locked node", () => {
    render(<TextToolbar selectedNode={textNode({}, true)} onOperation={vi.fn()} />);

    expect(screen.getByLabelText("Font family")).toBeDisabled();
    expect(screen.getByLabelText("Font weight")).toBeDisabled();
    expect(screen.getByLabelText("Font size")).toBeDisabled();
    expect(screen.getByLabelText("Align left")).toBeDisabled();
    expect(screen.getByLabelText("Line height")).toBeDisabled();
    expect(screen.getByLabelText("Letter spacing")).toBeDisabled();
    expect(screen.getByLabelText("Text color")).toBeDisabled();
  });

  it("renders the color swatch at the right end, after the style-role chip", () => {
    render(<TextToolbar selectedNode={textNode({ style_token: "type.h1" })} onOperation={vi.fn()} />);
    const toolbar = screen.getByTestId("text-toolbar");
    const chip = screen.getByTestId("text-toolbar-token-chip");
    const swatch = screen.getByLabelText("Text color");
    const children = Array.from(toolbar.children);
    expect(children.indexOf(chip)).toBeLessThan(children.indexOf(swatch.parentElement ?? swatch));
    expect(children.indexOf(swatch.parentElement ?? swatch)).toBe(children.length - 1);
  });

  it("recoloring via the swatch emits a plain fills UpdateNode — no style_token field authored", () => {
    const node = textNode({ style_token: "type.h1" });
    const onOperation = vi.fn<(operation: Operation) => void>();
    render(<TextToolbar selectedNode={node} onOperation={onOperation} />);

    fireEvent.click(screen.getByLabelText("Text color"));
    fireEvent.change(screen.getByLabelText("Custom color"), { target: { value: "#123456" } });

    expect(onOperation).toHaveBeenCalledTimes(1);
    const operation = onOperation.mock.calls[0][0];
    expect(operation).toEqual(
      updateNodeFills(node, [{ id: expect.stringContaining("_fill"), paint: { kind: "solid", color: { kind: "hex", value: "#123456" } } }])
    );
    expect(JSON.stringify(operation)).not.toContain("style_token");
  });

  it("renders the vertical-alignment group and reflects the node's valign", () => {
    render(<TextToolbar selectedNode={textNode({ valign: "center" })} onOperation={vi.fn()} />);
    expect(screen.getByLabelText("Vertical align top")).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByLabelText("Vertical align center")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("Vertical align bottom")).toHaveAttribute("aria-pressed", "false");
  });

  it("defaults the vertical-alignment group to top when valign is absent", () => {
    render(<TextToolbar selectedNode={textNode()} onOperation={vi.fn()} />);
    expect(screen.getByLabelText("Vertical align top")).toHaveAttribute("aria-pressed", "true");
  });

  it("dispatches updateTextNode with the chosen valign", () => {
    const node = textNode();
    const onOperation = vi.fn<(operation: Operation) => void>();
    render(<TextToolbar selectedNode={node} onOperation={onOperation} />);

    fireEvent.click(screen.getByLabelText("Vertical align bottom"));
    expect(onOperation).toHaveBeenLastCalledWith(updateTextNode(node, { valign: "bottom" }));

    fireEvent.click(screen.getByLabelText("Vertical align center"));
    expect(onOperation).toHaveBeenLastCalledWith(updateTextNode(node, { valign: "center" }));
  });

  it("disables the vertical-alignment group on a hug-height node (D6)", () => {
    const node = textNode();
    node.size = { ...node.size, height: { kind: "hug" } };
    render(<TextToolbar selectedNode={node} onOperation={vi.fn()} />);
    const center = screen.getByLabelText("Vertical align center");
    expect(center).toBeDisabled();
    expect(center).toHaveAttribute("title", "No effect with hug height");
  });

  it("passes brand tokens through to the swatch popover", () => {
    const brandTokens: BrandTokenCatalog = { text_tokens: ["text.primary"] };
    render(<TextToolbar selectedNode={textNode()} onOperation={vi.fn()} brandTokens={brandTokens} />);
    fireEvent.click(screen.getByLabelText("Text color"));
    expect(screen.getByTitle("$text.primary")).toBeInTheDocument();
  });
});
