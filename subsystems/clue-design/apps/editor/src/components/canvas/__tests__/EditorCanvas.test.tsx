import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Scene } from "@/engine/contracts";
import { minimalScene } from "@/fixtures/minimalScene";
import { EditorCanvas } from "../EditorCanvas";

vi.mock("../CanvasSurface", () => ({
  CanvasSurface: () => <div data-testid="konva-canvas" />
}));
vi.mock("../CanvasKitCanvas", () => ({
  CanvasKitCanvas: () => <div data-testid="canvaskit-canvas" />
}));

const scene = minimalScene as Scene;

const baseProps = {
  scene,
  activePageId: "page_a4",
  selectedNodeId: null,
  onSelectNode: () => {},
  onOperation: () => {},
  engine: null
};

describe("EditorCanvas renderer switch (Wave 3 C5)", () => {
  afterEach(() => {
    delete process.env.NEXT_PUBLIC_LUMEN_CANVASKIT;
  });

  it("renders the Konva canvas by default", () => {
    const { queryByTestId } = render(<EditorCanvas {...baseProps} />);
    expect(queryByTestId("konva-canvas")).not.toBeNull();
    expect(queryByTestId("canvaskit-canvas")).toBeNull();
  });

  it("renders the CanvasKit canvas when the flag is on", () => {
    process.env.NEXT_PUBLIC_LUMEN_CANVASKIT = "1";
    const { queryByTestId } = render(<EditorCanvas {...baseProps} />);
    expect(queryByTestId("canvaskit-canvas")).not.toBeNull();
    expect(queryByTestId("konva-canvas")).toBeNull();
  });
});
