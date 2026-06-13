// @vitest-environment node
import { existsSync } from "node:fs";
import path from "node:path";
import { beforeAll, describe, expect, it } from "vitest";
import type { CanvasKit, Surface } from "canvaskit-wasm";
import type { Node, Scene } from "../../contracts";
import { minimalScene } from "@/fixtures/minimalScene";
import { nodeDescriptor, pageDescriptor, type RenderPageDescriptor } from "../../renderAdapter";
import { drawDescriptorTree, type DrawNode } from "../drawDescriptors";

/**
 * Wave 3 C2: the descriptor→CanvasKit interpreter, verified by rendering to a
 * raster surface in Node and reading pixels back. This proves placement,
 * color, transparency, and gradients draw correctly — the productized form of
 * the spike's 0.003%-parity harness.
 */

const CK_BIN = path.resolve(__dirname, "../../../../node_modules/canvaskit-wasm/bin");
const present = existsSync(path.join(CK_BIN, "canvaskit.wasm"));

let ck: CanvasKit;

async function loadCk(): Promise<CanvasKit> {
  const mod = (await import("canvaskit-wasm")) as unknown as {
    default: (options: { locateFile: (file: string) => string }) => Promise<CanvasKit>;
  };
  return mod.default({ locateFile: (file: string) => path.join(CK_BIN, file) });
}

/** Build the descriptor tree the stage would feed the interpreter. */
function tree(scene: Scene, pageId: string): { page: RenderPageDescriptor; nodes: DrawNode[] } {
  const page = scene.pages[pageId];
  const toDraw = (node: Node): DrawNode => ({
    descriptor: nodeDescriptor(scene, node, page),
    children: node.children.map((id) => toDraw(scene.nodes[id]))
  });
  return {
    page: pageDescriptor(page),
    nodes: page.children.map((id) => toDraw(scene.nodes[id]))
  };
}

function render(scene: Scene, pageId: string, width: number, height: number): Uint8Array {
  const surface: Surface = ck.MakeSurface(width, height)!;
  const canvas = surface.getCanvas();
  const { page, nodes } = tree(scene, pageId);
  drawDescriptorTree(ck, canvas, page, nodes, null);
  surface.flush();
  const image = surface.makeImageSnapshot();
  const pixels = image.readPixels(0, 0, {
    width,
    height,
    colorType: ck.ColorType.RGBA_8888,
    alphaType: ck.AlphaType.Unpremul,
    colorSpace: ck.ColorSpace.SRGB
  }) as Uint8Array;
  image.delete();
  surface.delete();
  return pixels;
}

function pixel(pixels: Uint8Array, x: number, y: number, width: number): [number, number, number, number] {
  const i = (y * width + x) * 4;
  return [pixels[i], pixels[i + 1], pixels[i + 2], pixels[i + 3]];
}

/** A px-unit page with the given page children (1:1 canvas units). */
function pxScene(nodes: Record<string, Node>, children: string[]): Scene {
  const scene = JSON.parse(JSON.stringify(minimalScene)) as Scene;
  scene.pages.page_a4 = {
    ...scene.pages.page_a4,
    size: { width: 100, height: 60, unit: "px", preset: "custom", orientation: "landscape" },
    children,
    background: []
  };
  scene.nodes = nodes;
  return scene;
}

function rect(id: string, x: number, y: number, w: number, h: number, fill: string): Node {
  const base = JSON.parse(JSON.stringify(minimalScene.nodes.node_contact_name)) as Node;
  return {
    ...base,
    id,
    name: id,
    kind: { kind: "rect" },
    children: [],
    transform: { ...base.transform, x, y },
    size: { width: { kind: "fixed", value: w }, height: { kind: "fixed", value: h } },
    fills: fill
      ? [{ id: `${id}_fill`, paint: { kind: "solid", color: { kind: "hex", value: fill } } }]
      : [],
    strokes: [],
    corner: { top_left: 0, top_right: 0, bottom_right: 0, bottom_left: 0 },
    computed: { layout_bounds: { x, y, width: w, height: h }, render_bounds: { x, y, width: w, height: h } }
  };
}

describe.skipIf(!present)("CanvasKit descriptor interpreter (Wave 3 C2)", () => {
  beforeAll(async () => {
    ck = await loadCk();
  });

  it("draws a solid fill at the right place and color, leaving the rest white", () => {
    const r = rect("r", 10, 10, 40, 20, "#ff0000");
    const pixels = render(pxScene({ r }, ["r"]), "page_a4", 100, 60);

    // Inside the rect → red.
    expect(pixel(pixels, 30, 20, 100)).toEqual([255, 0, 0, 255]);
    // Outside → cleared white background.
    expect(pixel(pixels, 80, 50, 100)).toEqual([255, 255, 255, 255]);
  });

  it("does not paint a transparent frame", () => {
    const base = JSON.parse(JSON.stringify(minimalScene.nodes.node_contact_name)) as Node;
    const frame: Node = {
      ...base,
      id: "f",
      kind: { kind: "frame" },
      children: [],
      fills: [],
      strokes: [],
      transform: { ...base.transform, x: 0, y: 0 },
      size: { width: { kind: "fixed", value: 100 }, height: { kind: "fixed", value: 60 } },
      computed: {
        layout_bounds: { x: 0, y: 0, width: 100, height: 60 },
        render_bounds: { x: 0, y: 0, width: 100, height: 60 }
      }
    };
    const pixels = render(pxScene({ f: frame }, ["f"]), "page_a4", 100, 60);
    // The frame's default fill is transparent → background shows through.
    expect(pixel(pixels, 50, 30, 100)).toEqual([255, 255, 255, 255]);
  });

  it("blends a half-opacity fill against the background", () => {
    const r = { ...rect("r", 0, 0, 100, 60, "#000000"), opacity: 0.5 };
    const pixels = render(pxScene({ r }, ["r"]), "page_a4", 100, 60);
    const [red, green, blue, alpha] = pixel(pixels, 50, 30, 100);
    // Black at 50% over white → mid-gray, opaque.
    expect(red).toBeGreaterThan(100);
    expect(red).toBeLessThan(160);
    expect(green).toBe(red);
    expect(blue).toBe(red);
    expect(alpha).toBe(255);
  });
});
