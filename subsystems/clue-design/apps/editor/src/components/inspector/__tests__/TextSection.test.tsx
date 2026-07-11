import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { minimalScene } from "@/fixtures/minimalScene";
import type { Node, Operation } from "@/engine/contracts";
import { updateTextNode } from "@/engine/operations";
import { TextSection } from "../TextSection";

const baseTextNode = minimalScene.nodes.node_contact_name;

type TextNode = Node & { kind: Extract<Node["kind"], { kind: "text" }> };

function textNode(overrides: Partial<Extract<Node["kind"], { kind: "text" }>> = {}, locked = false): TextNode {
  const node = structuredClone(baseTextNode) as TextNode;
  node.kind = { ...node.kind, ...overrides };
  node.locked = locked;
  return node;
}

describe("TextSection — A7a vertical alignment", () => {
  it("binds the V-Align select to the node's valign (defaulting to top)", () => {
    render(<TextSection selectedNode={textNode()} onOperation={vi.fn()} />);
    expect(screen.getByLabelText("V-Align")).toHaveValue("top");
  });

  it("reflects an explicit valign", () => {
    render(<TextSection selectedNode={textNode({ valign: "bottom" })} onOperation={vi.fn()} />);
    expect(screen.getByLabelText("V-Align")).toHaveValue("bottom");
  });

  it("dispatches updateTextNode with the chosen valign on change", () => {
    const node = textNode();
    const onOperation = vi.fn<(operation: Operation) => void>();
    render(<TextSection selectedNode={node} onOperation={onOperation} />);

    fireEvent.change(screen.getByLabelText("V-Align"), { target: { value: "center" } });
    expect(onOperation).toHaveBeenLastCalledWith(updateTextNode(node, { valign: "center" }));
  });

  it("disables the V-Align select on a hug-height node with an explanatory tooltip (D6)", () => {
    const node = textNode();
    node.size = { ...node.size, height: { kind: "hug" } };
    render(<TextSection selectedNode={node} onOperation={vi.fn()} />);
    const select = screen.getByLabelText("V-Align");
    expect(select).toBeDisabled();
    expect(select).toHaveAttribute("title", "No effect with hug height");
  });

  it("disables the V-Align select on a locked node", () => {
    render(<TextSection selectedNode={textNode({}, true)} onOperation={vi.fn()} />);
    expect(screen.getByLabelText("V-Align")).toBeDisabled();
  });
});

describe("TextSection — A7b italic", () => {
  it("binds the Italic toggle to the node's italic (defaulting off)", () => {
    const { rerender } = render(<TextSection selectedNode={textNode()} onOperation={vi.fn()} />);
    expect(screen.getByLabelText("Italic")).not.toBeChecked();
    rerender(<TextSection selectedNode={textNode({ italic: true })} onOperation={vi.fn()} />);
    expect(screen.getByLabelText("Italic")).toBeChecked();
  });

  it("dispatches updateTextNode toggling italic on change", () => {
    const node = textNode();
    const onOperation = vi.fn<(operation: Operation) => void>();
    render(<TextSection selectedNode={node} onOperation={onOperation} />);

    fireEvent.click(screen.getByLabelText("Italic"));
    expect(onOperation).toHaveBeenLastCalledWith(updateTextNode(node, { italic: true }));
  });

  it("disables the Italic toggle on a locked node", () => {
    render(<TextSection selectedNode={textNode({}, true)} onOperation={vi.fn()} />);
    expect(screen.getByLabelText("Italic")).toBeDisabled();
  });
});
