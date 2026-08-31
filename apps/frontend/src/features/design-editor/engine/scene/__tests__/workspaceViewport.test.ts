import { describe, expect, it } from "../../__tests__/vitest-shim";
import {
  clampWorkspacePanToKeepVisible,
  fitWorkspaceRectToViewport,
  panWorkspaceViewport,
  screenToWorkspace,
  workspaceRectToScreen,
  workspaceToScreen,
  zoomWorkspaceViewportAtPoint
} from "../workspaceViewport";

describe("workspace viewport", () => {
  it("fits a workspace rect in the viewport", () => {
    const viewport = fitWorkspaceRectToViewport({
      viewport: { width: 1200, height: 800 },
      rect: { x: 0, y: 0, width: 2400, height: 1200 },
      margin: 120
    });

    expect(viewport.zoom).toBeCloseTo((1200 - 120) / 2400, 3);
    const screen = workspaceRectToScreen({ x: 0, y: 0, width: 2400, height: 1200 }, viewport);
    expect(screen.width).toBeLessThanOrEqual(1200 - 120);
    expect(screen.height).toBeLessThanOrEqual(800 - 120);
    expect(screen.x).toBeCloseTo((1200 - screen.width) / 2, 3);
  });

  it("round trips screen and workspace points", () => {
    const viewport = { zoom: 0.5, pan: { x: 120, y: 80 } };
    const workspace = screenToWorkspace({ x: 420, y: 280 }, viewport);
    const screen = workspaceToScreen(workspace, viewport);

    expect(workspace).toEqual({ x: 600, y: 400 });
    expect(screen).toEqual({ x: 420, y: 280 });
  });

  it("zooms around the pointer by preserving the pointed workspace coordinate", () => {
    const viewport = { zoom: 1, pan: { x: 0, y: 0 } };
    const pointer = { x: 300, y: 200 };
    const before = screenToWorkspace(pointer, viewport);
    const afterViewport = zoomWorkspaceViewportAtPoint(viewport, pointer, 1.5);
    const after = screenToWorkspace(pointer, afterViewport);

    expect(before).toEqual(after);
    expect(afterViewport.zoom).toBe(1.5);
    expect(afterViewport.pan).toEqual({ x: -150, y: -100 });
  });

  it("pans in screen space without changing zoom", () => {
    const viewport = panWorkspaceViewport({ zoom: 0.75, pan: { x: 10, y: 20 } }, { x: -50, y: 30 });

    expect(viewport).toEqual({ zoom: 0.75, pan: { x: -40, y: 50 } });
  });

  it("keeps at least part of the workspace visible after extreme pan", () => {
    const viewport = clampWorkspacePanToKeepVisible(
      { zoom: 1, pan: { x: -5000, y: 4000 } },
      { x: 0, y: 0, width: 1000, height: 800 },
      { width: 900, height: 600 },
      96
    );
    const screen = workspaceRectToScreen({ x: 0, y: 0, width: 1000, height: 800 }, viewport);

    expect(screen.x + screen.width).toBeGreaterThanOrEqual(96);
    expect(screen.y).toBeLessThanOrEqual(600 - 96);
  });
});
