import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import * as ReactKonva from "react-konva";
import { minimalScene } from "@/fixtures/minimalScene";
import type { Scene } from "@/engine/contracts";
import type { SnapGuide } from "@/engine/canvasOperations";
import { SceneNode } from "../SceneNode";

/**
 * `react-konva` cannot mount for real in this project's jsdom suite — Konva's
 * Node entry point does a bare `require("canvas")`, and the `canvas` native
 * package isn't (and shouldn't be) part of this repo's dependencies just for
 * tests. So, matching this codebase's existing convention of mocking the
 * Konva boundary (see `EditorCanvas.test.tsx`'s mocks of `CanvasSurface` /
 * `CanvasKitCanvas`), every `react-konva` primitive is replaced with a plain
 * DOM pass-through here. That's enough to render `SceneNode`'s real React
 * tree and invoke its real (non-Konva) event handler props directly — which
 * is exactly where the guide-reporting logic lives.
 */
vi.mock("react-konva", () => {
  const passthrough =
    (name: string) =>
    ({ children, ...rest }: Record<string, unknown>) => {
      const attrs: Record<string, unknown> = { "data-konva": name };
      for (const [key, value] of Object.entries(rest)) {
        if (typeof value !== "function") {
          attrs[`data-${key.toLowerCase()}`] = String(value);
        }
      }
      return <div {...attrs}>{children as never}</div>;
    };
  return {
    Group: passthrough("Group"),
    Line: passthrough("Line"),
    Path: passthrough("Path"),
    Rect: passthrough("Rect"),
    Text: passthrough("Text")
  };
});

function customPixelScene(): Scene {
  const scene = JSON.parse(JSON.stringify(minimalScene)) as Scene;
  scene.pages.page_a4.size = {
    width: 1080,
    height: 1080,
    unit: "px",
    preset: "custom",
    orientation: "landscape"
  };
  return scene;
}

/** Grabs the prop of a given name passed to react-konva's mocked `Group` by
 * intercepting the mock's call args instead of relying on DOM event
 * dispatch (Konva drag/transform events don't exist in jsdom). */
function renderSceneNodeAndCaptureGroupHandler(
  handlerName: "onDragMove" | "onDragEnd" | "onTransform" | "onTransformEnd",
  scene: Scene,
  onGuidesChange: (guides: SnapGuide[]) => void
): (event: unknown) => void {
  let captured: ((event: unknown) => void) | null = null;
  const reactKonva = ReactKonva as unknown as Record<string, (props: Record<string, unknown>) => unknown>;
  const originalGroup = reactKonva.Group;
  reactKonva.Group = (props: Record<string, unknown>) => {
    if (props.name === "scene-node" && typeof props[handlerName] === "function" && !captured) {
      captured = props[handlerName] as (event: unknown) => void;
    }
    return originalGroup(props);
  };

  render(
    <SceneNode
      scene={scene}
      page={scene.pages.page_a4}
      nodeId="node_contact_name"
      pageOrigin={{ x: 0, y: 0 }}
      selectedNodeId={null}
      onSelectNode={() => {}}
      onOperation={() => {}}
      registerNode={() => {}}
      onGuidesChange={onGuidesChange}
    />
  );

  if (!captured) {
    throw new Error(`SceneNode did not wire a ${handlerName} handler`);
  }
  return captured;
}

function fakeDragEvent(x: number, y: number): unknown {
  return { target: { x: () => x, y: () => y } };
}

function fakeTransformEvent(x: number, y: number, rotation: number, scaleX: number, scaleY: number): unknown {
  return {
    target: {
      x: () => x,
      y: () => y,
      rotation: () => rotation,
      scaleX: () => scaleX,
      scaleY: () => scaleY
    }
  };
}

describe("SceneNode snap guide reporting (Konva fallback)", () => {
  it("reports an engaged guide while dragging near the page's left edge", () => {
    const scene = customPixelScene();
    const guideUpdates: SnapGuide[][] = [];
    const onDragMove = renderSceneNodeAndCaptureGroupHandler("onDragMove", scene, (guides) =>
      guideUpdates.push(guides)
    );

    onDragMove(fakeDragEvent(2, 40));

    // "from"/"to" span the FULL page height (1080), not the dragged box's
    // own extent — a Moda-style full-bleed guide line.
    expect(guideUpdates.at(-1)).toEqual([{ axis: "x", position: 0, from: 0, to: 1080 }]);
  });

  it("reports no guides while dragging far from any snap target", () => {
    const scene = customPixelScene();
    const guideUpdates: SnapGuide[][] = [];
    const onDragMove = renderSceneNodeAndCaptureGroupHandler("onDragMove", scene, (guides) =>
      guideUpdates.push(guides)
    );

    onDragMove(fakeDragEvent(300, 300));

    expect(guideUpdates.at(-1)).toEqual([]);
  });

  it("clears guides on drag end", () => {
    const scene = customPixelScene();
    const guideUpdates: SnapGuide[][] = [];
    const onDragEnd = renderSceneNodeAndCaptureGroupHandler("onDragEnd", scene, (guides) =>
      guideUpdates.push(guides)
    );

    onDragEnd(fakeDragEvent(2, 40));

    expect(guideUpdates.at(-1)).toEqual([]);
  });

  it("reports a guide while a live resize snaps its trailing edge to the page bound", () => {
    const scene = customPixelScene();
    const guideUpdates: SnapGuide[][] = [];
    const onTransform = renderSceneNodeAndCaptureGroupHandler("onTransform", scene, (guides) =>
      guideUpdates.push(guides)
    );

    // Matches "reports a guide for a resize that snaps its trailing edge to
    // the page bound" in canvasOperations.test.ts: scaleX = 1004/160.
    onTransform(fakeTransformEvent(72, 72, 0, 1004 / 160, 1));

    // Spans the full page height (1080), not the resized box's own extent.
    expect(guideUpdates.at(-1)).toEqual([{ axis: "x", position: 1080, from: 0, to: 1080 }]);
  });

  it("clears guides on transform end", () => {
    const scene = customPixelScene();
    const guideUpdates: SnapGuide[][] = [];
    const onTransformEnd = renderSceneNodeAndCaptureGroupHandler("onTransformEnd", scene, (guides) =>
      guideUpdates.push(guides)
    );

    onTransformEnd(fakeTransformEvent(72, 72, 0, 1004 / 160, 1));

    expect(guideUpdates.at(-1)).toEqual([]);
  });

  it("never reports guides for a locked node", () => {
    const scene = customPixelScene();
    scene.nodes.node_contact_name.locked = true;
    const guideUpdates: SnapGuide[][] = [];
    const onDragMove = renderSceneNodeAndCaptureGroupHandler("onDragMove", scene, (guides) =>
      guideUpdates.push(guides)
    );

    onDragMove(fakeDragEvent(2, 40));

    expect(guideUpdates).toEqual([]);
  });
});
