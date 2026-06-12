import { describe, expect, it } from "vitest";
import { minimalScene } from "@/fixtures/minimalScene";
import type { Scene } from "../contracts";
import { canvasDirectEditNotice, isCanvasDirectGeometryEditable } from "../canvasSelection";

describe("canvas selection helpers", () => {
  it("allows direct canvas transforms for unlocked free-positioned nodes", () => {
    const scene = cloneScene();

    expect(isCanvasDirectGeometryEditable(scene, "node_contact_name")).toBe(true);
    expect(canvasDirectEditNotice(scene, "node_contact_name")).toBeNull();
  });

  it("explains locked selections", () => {
    const scene = cloneScene();
    scene.nodes.node_contact_name.locked = true;

    expect(isCanvasDirectGeometryEditable(scene, "node_contact_name")).toBe(false);
    expect(canvasDirectEditNotice(scene, "node_contact_name")).toMatch(/Selection is locked/);
  });

  it("explains auto-layout managed selections", () => {
    const scene = cloneScene();
    scene.nodes.node_stack = {
      ...scene.nodes.node_contact_name,
      id: "node_stack",
      name: "Stack",
      kind: {
        kind: "auto_layout",
        direction: "column",
        wrap: false
      },
      children: ["node_contact_name"],
      locked: false
    };
    scene.nodes.node_contact_name.locked = false;
    scene.pages.page_a4.children = ["node_stack"];

    expect(isCanvasDirectGeometryEditable(scene, "node_contact_name")).toBe(false);
    expect(canvasDirectEditNotice(scene, "node_contact_name")).toMatch(/auto-layout parent/);
  });

  it("omits notices for missing selections", () => {
    const scene = cloneScene();

    expect(isCanvasDirectGeometryEditable(scene, null)).toBe(false);
    expect(canvasDirectEditNotice(scene, null)).toBeNull();
    expect(canvasDirectEditNotice(scene, "missing_node")).toBeNull();
  });
});

function cloneScene(): Scene {
  return JSON.parse(JSON.stringify(minimalScene)) as Scene;
}
