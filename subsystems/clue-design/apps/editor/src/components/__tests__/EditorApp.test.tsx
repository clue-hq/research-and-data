import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { minimalScene } from "@/fixtures/minimalScene";
import type { Scene } from "@/engine/contracts";
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

    expect(screen.getByText("Select a node on the canvas.")).toBeInTheDocument();
    expect(screen.getByTestId("canvas-selection")).toHaveAttribute("data-selected-node", "");
  });
});

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
