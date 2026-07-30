import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { WebInspectorPanel } from "../WebInspectorPanel";
import type { WebNode } from "@/engine/webDocuments";

const NODE: WebNode = {
  id: "headline",
  kind: "text",
  variant: "h1",
  classes: "",
  content: {
    schema_version: 1,
    blocks: [
      {
        type: "paragraph",
        children: [{ type: "text", text: "Hello world" }]
      }
    ]
  }
};

function renderPanel(params: {
  editingNodeId: string | null;
  richTextFormats: {
    bold: "on" | "off" | "mixed";
    italic: "on" | "off" | "mixed";
    underline: "on" | "off" | "mixed";
    strikethrough: "on" | "off" | "mixed";
  } | null;
  node?: WebNode;
}) {
  const applyOps = vi.fn();
  const formatRichText = vi.fn();
  render(
    <WebInspectorPanel
      node={params.node ?? NODE}
      nodeInfo={null}
      pageId="home"
      page={null}
      theme={null}
      dialogs={[]}
      previewComponent={vi.fn()}
      selectNode={vi.fn()}
      onReplaceImage={vi.fn()}
      onChooseBackground={vi.fn()}
      editingNodeId={params.editingNodeId}
      richTextFormats={params.richTextFormats}
      formatRichText={formatRichText}
      applyOps={applyOps}
      busy={false}
      note={null}
      error={null}
    />
  );
  return { applyOps, formatRichText };
}

describe("WebInspectorPanel selected-range formatting", () => {
  it("reflects mixed range state and sends local rich-text commands while editing", () => {
    const { applyOps, formatRichText } = renderPanel({
      editingNodeId: "headline",
      richTextFormats: {
        bold: "on",
        italic: "mixed",
        underline: "off",
        strikethrough: "off"
      }
    });

    expect(screen.getByRole("button", { name: "Bold" })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
    expect(screen.getByRole("button", { name: "Italic" })).toHaveAttribute(
      "aria-pressed",
      "mixed"
    );
    fireEvent.click(screen.getByRole("button", { name: "Underline" }));
    expect(formatRichText).toHaveBeenCalledWith("headline", "underline");
    expect(applyOps).not.toHaveBeenCalled();
  });

  it("retains whole-node class formatting outside a text edit session", () => {
    const { applyOps, formatRichText } = renderPanel({
      editingNodeId: null,
      richTextFormats: null
    });

    fireEvent.click(screen.getByRole("button", { name: "Bold" }));
    expect(formatRichText).not.toHaveBeenCalled();
    expect(applyOps).toHaveBeenCalledWith(
      [
        {
          kind: "set_node_classes",
          page_id: "home",
          id: "headline",
          classes: "font-bold"
        }
      ],
      "font_weight"
    );
  });

  it("blocks heading variants while a body node still has structured blocks", () => {
    renderPanel({
      editingNodeId: null,
      richTextFormats: null,
      node: {
        ...NODE,
        variant: "body",
        content: {
          schema_version: 1,
          blocks: [
            {
              type: "paragraph",
              children: [{ type: "text", text: "Intro" }]
            },
            {
              type: "list",
              list_type: "unordered",
              items: [
                { children: [{ type: "text", text: "First" }] }
              ]
            }
          ]
        }
      }
    });

    expect(screen.getByRole("option", { name: "body" })).toBeEnabled();
    expect(screen.getByRole("option", { name: "small" })).toBeEnabled();
    expect(screen.getByRole("option", { name: "h1" })).toBeDisabled();
    expect(screen.getByRole("option", { name: "display" })).toBeDisabled();
    expect(
      screen.getByText(
        "Convert this text to one paragraph before choosing a heading style."
      )
    ).toBeInTheDocument();
  });
});
