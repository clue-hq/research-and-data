import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Scene } from "@/engine/contracts";
import { minimalScene } from "@/fixtures/minimalScene";
import { normalizePageSize } from "@/engine/pageGeometry";
import type { WorkspaceModel } from "@/engine/workspaceLayout";
import { defaultWorkspaceViewport } from "@/engine/workspaceViewport";
import { EditorCanvas } from "../EditorCanvas";

vi.mock("../CanvasSurface", () => ({
  CanvasSurface: ({
    workspaceTool,
    workspaceFitTarget,
    workspaceModel
  }: {
    workspaceTool: string;
    workspaceFitTarget: string;
    workspaceModel: WorkspaceModel;
  }) => (
    <div
      data-testid="konva-canvas"
      data-tool={workspaceTool}
      data-fit-target={workspaceFitTarget}
      data-artboards={workspaceSummary(workspaceModel)}
      data-active-artboard={workspaceModel.activeArtboard?.pageId ?? ""}
    />
  )
}));
vi.mock("../CanvasKitCanvas", () => ({
  CanvasKitCanvas: ({
    workspaceTool,
    workspaceFitTarget,
    workspaceModel
  }: {
    workspaceTool: string;
    workspaceFitTarget: string;
    workspaceModel: WorkspaceModel;
  }) => (
    <div
      data-testid="canvaskit-canvas"
      data-tool={workspaceTool}
      data-fit-target={workspaceFitTarget}
      data-artboards={workspaceSummary(workspaceModel)}
      data-active-artboard={workspaceModel.activeArtboard?.pageId ?? ""}
    />
  )
}));

const scene = minimalScene as Scene;

const baseProps = {
  scene,
  activePageId: "page_a4",
  selectedNodeId: null,
  onSelectNode: () => {},
  onOperation: () => {},
  engine: null,
  workspaceViewport: defaultWorkspaceViewport(),
  onWorkspaceViewportChange: () => {},
  workspaceTool: "select" as const,
  onWorkspaceToolChange: () => {},
  workspaceFitTarget: "all" as const,
  onWorkspaceFitTargetChange: () => {}
};

describe("EditorCanvas renderer switch (Wave 3 C5)", () => {
  afterEach(() => {
    delete process.env.NEXT_PUBLIC_LUMEN_CANVASKIT;
  });

  it("renders the Konva canvas by default", () => {
    const { queryByTestId } = render(<EditorCanvas {...baseProps} />);
    expect(queryByTestId("konva-canvas")).not.toBeNull();
    expect(queryByTestId("konva-canvas")).toHaveAttribute("data-tool", "select");
    expect(queryByTestId("konva-canvas")).toHaveAttribute("data-fit-target", "all");
    expect(queryByTestId("canvaskit-canvas")).toBeNull();
  });

  it("renders the CanvasKit canvas when the flag is on", () => {
    process.env.NEXT_PUBLIC_LUMEN_CANVASKIT = "1";
    const { queryByTestId } = render(<EditorCanvas {...baseProps} />);
    expect(queryByTestId("canvaskit-canvas")).not.toBeNull();
    expect(queryByTestId("canvaskit-canvas")).toHaveAttribute("data-tool", "select");
    expect(queryByTestId("canvaskit-canvas")).toHaveAttribute("data-fit-target", "all");
    expect(queryByTestId("konva-canvas")).toBeNull();
  });

  it("passes the same derived multi-artboard workspace model to both renderers", () => {
    const workspaceScene = multiArtboardScene();

    const { getByTestId, unmount } = render(
      <EditorCanvas {...baseProps} scene={workspaceScene} activePageId="page_square" />
    );
    expect(getByTestId("konva-canvas")).toHaveAttribute(
      "data-artboards",
      "page_a4:793.7x1122.5@0,0|page_square:1080x1080@973.7,0"
    );
    expect(getByTestId("konva-canvas")).toHaveAttribute("data-active-artboard", "page_square");
    unmount();

    process.env.NEXT_PUBLIC_LUMEN_CANVASKIT = "1";
    const canvasKitRender = render(
      <EditorCanvas {...baseProps} scene={workspaceScene} activePageId="page_square" />
    );
    expect(canvasKitRender.getByTestId("canvaskit-canvas")).toHaveAttribute(
      "data-artboards",
      "page_a4:793.7x1122.5@0,0|page_square:1080x1080@973.7,0"
    );
    expect(canvasKitRender.getByTestId("canvaskit-canvas")).toHaveAttribute("data-active-artboard", "page_square");
  });
});

function workspaceSummary(model: WorkspaceModel): string {
  return model.artboards
    .map(
      (artboard) =>
        `${artboard.pageId}:${format(artboard.layoutWidth)}x${format(artboard.layoutHeight)}@${format(artboard.workspaceRect.x)},${format(artboard.workspaceRect.y)}`
    )
    .join("|");
}

function format(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1).replace(/\.0$/, "");
}

function multiArtboardScene(): Scene {
  const next = JSON.parse(JSON.stringify(minimalScene)) as Scene;
  next.pages.page_square = {
    ...next.pages.page_a4,
    id: "page_square",
    name: "Square Ad",
    size: normalizePageSize({ width: 1080, height: 1080, unit: "px" }),
    children: []
  };
  return next;
}
