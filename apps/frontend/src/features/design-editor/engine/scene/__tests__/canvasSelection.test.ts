import { describe, expect, it } from "../../__tests__/vitest-shim";
import { minimalScene } from "./__fixtures__/minimalScene";
import type { Node, Scene } from "../contracts";
import {
  canvasDirectEditNotice,
  containerSelectionGeometry,
  isCanvasDirectGeometryEditable
} from "../canvasSelection";

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

describe("container selection geometry", () => {
  it("returns the container box, label, and laid-out child outlines", () => {
    const scene = containerScene();

    const geometry = containerSelectionGeometry(scene, "hero");

    expect(geometry).not.toBeNull();
    expect(geometry?.label).toBe("Hero");
    expect(geometry?.container).toEqual({ x: 40, y: 40, width: 400, height: 300 });
    expect(geometry?.children).toEqual([
      { x: 60, y: 60, width: 200, height: 40 },
      { x: 60, y: 120, width: 160, height: 80 }
    ]);
  });

  it("skips children that have not been laid out yet", () => {
    const scene = containerScene();
    scene.nodes.box.computed = null;

    const geometry = containerSelectionGeometry(scene, "hero");

    expect(geometry?.children).toEqual([{ x: 60, y: 60, width: 200, height: 40 }]);
  });

  it("returns null for a leaf node, an empty container, and a container without computed", () => {
    const scene = containerScene();

    // Leaf text node — not a container.
    expect(containerSelectionGeometry(scene, "headline")).toBeNull();
    // Container present but no computed bounds yet.
    scene.nodes.hero.computed = null;
    expect(containerSelectionGeometry(scene, "hero")).toBeNull();
    // Empty container (no children) is not treated as a container.
    scene.nodes.hero.computed = { layout_bounds: bounds(40, 40, 400, 300), render_bounds: bounds(40, 40, 400, 300) };
    scene.nodes.hero.children = [];
    expect(containerSelectionGeometry(scene, "hero")).toBeNull();
  });

  it("returns null for a null or missing selection", () => {
    const scene = containerScene();

    expect(containerSelectionGeometry(scene, null)).toBeNull();
    expect(containerSelectionGeometry(scene, "missing")).toBeNull();
  });
});

function cloneScene(): Scene {
  return JSON.parse(JSON.stringify(minimalScene)) as Scene;
}

function bounds(x: number, y: number, width: number, height: number) {
  return { x, y, width, height };
}

/** A hero frame (40,40 400x300) holding a headline text and a box rect. */
function containerScene(): Scene {
  const scene = cloneScene();
  const template = scene.nodes.node_contact_name;
  const hero: Node = {
    ...template,
    id: "hero",
    name: "Hero",
    kind: { kind: "frame" },
    children: ["headline", "box"],
    computed: { layout_bounds: bounds(40, 40, 400, 300), render_bounds: bounds(40, 40, 400, 300) }
  };
  const headline: Node = {
    ...template,
    id: "headline",
    name: "Headline",
    kind: { ...template.kind },
    children: [],
    computed: { layout_bounds: bounds(60, 60, 200, 40), render_bounds: bounds(60, 60, 200, 40) }
  };
  const box: Node = {
    ...template,
    id: "box",
    name: "Box",
    kind: { kind: "rect" },
    children: [],
    computed: { layout_bounds: bounds(60, 120, 160, 80), render_bounds: bounds(60, 120, 160, 80) }
  };
  scene.nodes = { hero, headline, box };
  scene.pages.page_a4.children = ["hero"];
  return scene;
}
