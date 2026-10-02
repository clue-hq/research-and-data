import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { WebInspectorPanel } from "../WebInspectorPanel";
import type {
  CustomComponentArtifact,
  WebNode
} from "@/engine/webDocuments";
import type { FragmentAssetOption } from "../WebFragmentInspector";
import type { FragmentCard } from "@/engine/webFragmentCards";

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
  artifact?: CustomComponentArtifact | null;
  republishRequired?: boolean;
  fragmentCard?: FragmentCard | null;
  dormantSections?: FragmentCard[];
  documentAssets?: FragmentAssetOption[];
}) {
  const applyOps = vi.fn();
  const formatRichText = vi.fn();
  const onEditCustomComponentWithAI = vi.fn();
  const onRepublish = vi.fn();
  const onGenerateFragmentPreview = vi.fn();
  const onActivateFragment = vi.fn();
  const onRetireFragment = vi.fn();
  render(
    <WebInspectorPanel
      node={params.node ?? NODE}
      nodeInfo={null}
      pageId="home"
      page={null}
      pages={[]}
      theme={null}
      dialogs={[]}
      previewComponent={vi.fn()}
      selectNode={vi.fn()}
      onReplaceImage={vi.fn()}
      onChooseBackground={vi.fn()}
      editingNodeId={params.editingNodeId}
      richTextFormats={params.richTextFormats}
      formatRichText={formatRichText}
      customComponentArtifact={params.artifact ?? null}
      customComponentArtifactStatus={params.artifact ? "ready" : "idle"}
      customComponentArtifactError={null}
      customComponentRuntime={null}
      customComponentRepublishRequired={params.republishRequired ?? false}
      onEditCustomComponentWithAI={onEditCustomComponentWithAI}
      onRepublish={onRepublish}
      fragmentCard={params.fragmentCard ?? null}
      fragmentCardStatus={params.fragmentCard ? "ready" : "idle"}
      fragmentCardError={null}
      dormantSections={params.dormantSections ?? []}
      documentAssets={params.documentAssets ?? []}
      onGenerateFragmentPreview={onGenerateFragmentPreview}
      onActivateFragment={onActivateFragment}
      onRetireFragment={onRetireFragment}
      fragmentActionBusy={false}
      fragmentActionError={null}
      applyOps={applyOps}
      busy={false}
      note={null}
      error={null}
    />
  );
  return {
    applyOps,
    formatRichText,
    onEditCustomComponentWithAI,
    onRepublish,
    onGenerateFragmentPreview,
    onActivateFragment,
    onRetireFragment
  };
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

describe("WebInspectorPanel custom-component foundation", () => {
  const artifact: CustomComponentArtifact = {
    artifact_id: `ccart_${"a".repeat(64)}`,
    account_id: "acc_alpha",
    slug: "book-a-call",
    manifest: {
      schema_version: 2,
      meta: {
        name: "Book a Call",
        description: "A typed booking callout."
      },
      props_schema: {
        type: "object",
        additionalProperties: false,
        required: ["headline", "count", "showLogo", "tone"],
        properties: {
          headline: { type: "string" },
          count: { type: "number" },
          showLogo: { type: "boolean" },
          tone: { type: "string", enum: ["warm", "direct"] }
        }
      },
      defaults: {
        headline: "Book a call",
        count: 3,
        showLogo: true,
        tone: "warm"
      },
      warnings: [
        {
          code: "CCW0203",
          severity: "warning",
          category: "first_frame",
          message: "First frame uses a deterministic fallback."
        }
      ],
      browser: { format: "esm", react: "host-singleton" }
    },
    provenance: { source_version: 4, compiler_version: "test" }
  };

  it("inspects immutable identity, generated props, and class-backed size controls", () => {
    const { applyOps } = renderPanel({
      editingNodeId: null,
      richTextFormats: null,
      artifact,
      node: {
        id: "cc_booking",
        kind: "custom_component",
        classes: "w-[420px] h-[200px]",
        slug: "book-a-call",
        artifact_id: `ccart_${"a".repeat(64)}`,
        props: {
          headline: "Book a call",
          count: 3,
          showLogo: true,
          tone: "warm"
        }
      }
    });

    expect(screen.getByText("Book a Call")).toBeInTheDocument();
    expect(screen.getByText(`ccart_${"a".repeat(64)}`)).toBeInTheDocument();
    expect(screen.getByText("CCW0203")).toBeInTheDocument();
    expect(screen.getByLabelText("headline custom component prop")).toHaveValue(
      "Book a call"
    );
    expect(screen.getByLabelText("count custom component prop")).toHaveValue(3);
    expect(screen.getByLabelText("show Logo custom component prop")).toBeChecked();
    expect(screen.getByLabelText("tone custom component prop")).toHaveValue("warm");

    fireEvent.change(screen.getByLabelText("tone custom component prop"), {
      target: { value: "direct" }
    });
    expect(applyOps).toHaveBeenCalledWith(
      [
        {
          kind: "set_node_props",
          page_id: "home",
          id: "cc_booking",
          props: {
            kind: "custom_component",
            slug: "book-a-call",
            artifact_id: `ccart_${"a".repeat(64)}`,
            props: {
              headline: "Book a call",
              count: 3,
              showLogo: true,
              tone: "direct"
            }
          }
        }
      ],
      "set_custom_component_props"
    );
    applyOps.mockClear();

    fireEvent.change(screen.getByLabelText("headline custom component prop"), {
      target: { value: "Talk to sales" }
    });
    fireEvent.blur(screen.getByLabelText("headline custom component prop"));
    expect(applyOps).toHaveBeenLastCalledWith(
      [
        expect.objectContaining({
          kind: "set_node_props",
          props: expect.objectContaining({
            props: expect.objectContaining({ headline: "Talk to sales" })
          })
        })
      ],
      "set_custom_component_props"
    );
    applyOps.mockClear();

    fireEvent.change(screen.getByLabelText("count custom component prop"), {
      target: { value: "8" }
    });
    fireEvent.blur(screen.getByLabelText("count custom component prop"));
    expect(applyOps).toHaveBeenLastCalledWith(
      [
        expect.objectContaining({
          props: expect.objectContaining({
            props: expect.objectContaining({ count: 8 })
          })
        })
      ],
      "set_custom_component_props"
    );
    applyOps.mockClear();

    fireEvent.click(screen.getByLabelText("show Logo custom component prop"));
    expect(applyOps).toHaveBeenLastCalledWith(
      [
        expect.objectContaining({
          props: expect.objectContaining({
            props: expect.objectContaining({ showLogo: false })
          })
        })
      ],
      "set_custom_component_props"
    );
    expect(screen.getByPlaceholderText("Default · computed width")).toHaveValue(
      "w-[420px]"
    );
    expect(screen.getByPlaceholderText("Default · computed height")).toHaveValue(
      "h-[200px]"
    );
  });

  it("surfaces the republish state and AI authoring entry point", () => {
    const node: WebNode = {
      id: "cc_booking",
      kind: "custom_component",
      classes: "",
      slug: "book-a-call",
      artifact_id: artifact.artifact_id,
      props: { headline: "Book", count: 1, showLogo: true, tone: "warm" }
    };
    const { onEditCustomComponentWithAI, onRepublish } = renderPanel({
      editingNodeId: null,
      richTextFormats: null,
      node,
      artifact,
      republishRequired: true
    });

    fireEvent.click(screen.getByRole("button", { name: "Republish" }));
    expect(onRepublish).toHaveBeenCalledOnce();
    fireEvent.click(
      screen.getByRole("button", { name: "Edit Book a Call with AI" })
    );
    expect(onEditCustomComponentWithAI).toHaveBeenCalledWith(node);
  });
});
