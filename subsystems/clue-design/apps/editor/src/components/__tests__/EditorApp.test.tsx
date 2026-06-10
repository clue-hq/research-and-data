import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { minimalScene } from "@/fixtures/minimalScene";
import type { BrandKitSummary, Scene } from "@/engine/contracts";
import EditorApp from "../EditorApp";

vi.mock("../canvas/CanvasSurface", () => ({
  CanvasSurface: ({ selectedNodeId }: { selectedNodeId: string | null }) =>
    React.createElement("div", {
      "data-testid": "canvas-selection",
      "data-selected-node": selectedNodeId ?? ""
    })
}));

describe("EditorApp", () => {
  it("clears stale node selection when switching pages", () => {
    const scene = twoPageScene();
    render(<EditorApp initialScene={scene} initialSelectedNodeId="node_contact_name" />);

    expect(screen.getByText("Contact Name")).toBeInTheDocument();
    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-selected-node", "node_contact_name");

    fireEvent.click(screen.getByText("Second Page"));

    expect(screen.getByText("Page")).toBeInTheDocument();
    expect(screen.getByText(/Page dimensions are canonical scene data/)).toBeInTheDocument();
    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-selected-node", "");
  });

  it("attaches a Brand Kit through an update_document operation", () => {
    render(
      <EditorApp
        initialScene={twoPageScene()}
        initialSelectedNodeId={null}
        initialAvailableBrandKits={[brandKitSummary()]}
      />
    );

    fireEvent.change(screen.getByLabelText("Brand Kit"), {
      target: { value: "brand_kit_insight_health@4" }
    });

    expect(screen.getByText("brand_kit_insight_health v4")).toBeInTheDocument();
    expect(screen.getByText(/update_document/)).toBeInTheDocument();
  });

  it("runs injected Brand Kit governance and displays returned diagnostics", async () => {
    const scene = twoPageScene();
    scene.meta.brand_kit = {
      id: "brand_kit_insight_health",
      version: 4
    };
    const brandKit = brandKitSummary();
    const brandGovernanceRunner = vi.fn().mockResolvedValue({
      diagnostics: [
        {
          severity: "error",
          phase: "brand",
          code: "LUMB0807",
          message: "node headline text contrast $text.inverse on $surface.page is 1.00, below required 4.50",
          subject: {
            kind: "node",
            id: "node_contact_name"
          },
          hint: "Use a Brand Kit text token with sufficient contrast."
        }
      ]
    });

    render(
      <EditorApp
        initialScene={scene}
        initialSelectedNodeId={null}
        initialAvailableBrandKits={[brandKit]}
        brandGovernanceRunner={brandGovernanceRunner}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /brand check/i }));

    expect(await screen.findAllByText("LUMB0807")).toHaveLength(2);
    expect(screen.getAllByText(/text contrast/)).toHaveLength(2);
    expect(brandGovernanceRunner).toHaveBeenCalledWith({
      scene: expect.objectContaining({
        meta: expect.objectContaining({
          brand_kit: {
            id: "brand_kit_insight_health",
            version: 4
          }
        })
      }),
      brandKit
    });
  });
});

function brandKitSummary(): BrandKitSummary {
  return {
    id: "brand_kit_insight_health",
    version: 4,
    name: "Insight Health",
    approval_status: "generated_unreviewed",
    product_ready: true,
    source: "styles",
    tokens: {
      surface_tokens: ["surface.brand", "surface.card"],
      text_tokens: ["text.primary", "text.inverse"],
      typography_tokens: ["type.headline", "type.body"],
      spacing_tokens: ["space.md", "space.lg"],
      radius_tokens: ["radius.card"],
      opacity_tokens: ["opacity.subtle"]
    },
    authoring_rules: []
  };
}

function twoPageScene(): Scene {
  const scene = JSON.parse(JSON.stringify(minimalScene)) as Scene;
  scene.pages.page_second = {
    ...scene.pages.page_a4,
    id: "page_second",
    name: "Second Page",
    children: []
  };
  return scene;
}
