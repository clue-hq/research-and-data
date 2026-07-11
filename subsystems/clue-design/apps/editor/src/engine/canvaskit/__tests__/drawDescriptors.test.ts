// @vitest-environment node
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { beforeAll, describe, expect, it } from "vitest";
import type { CanvasKit, Image, Surface, TypefaceFontProvider } from "canvaskit-wasm";
import type { AssetRecord, Node, Scene, TextSpan } from "../../contracts";
import { minimalScene } from "@/fixtures/minimalScene";
import { nodeDescriptor, pageDescriptor, type RenderPageDescriptor } from "../../renderAdapter";
import { drawDescriptorTree, type DrawNode } from "../drawDescriptors";
import type { CanvasKitImageSource } from "../imageCache";

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

function render(
  scene: Scene,
  pageId: string,
  width: number,
  height: number,
  fontProvider: TypefaceFontProvider | null = null,
  images: CanvasKitImageSource | null = null
): Uint8Array {
  const surface: Surface = ck.MakeSurface(width, height)!;
  const canvas = surface.getCanvas();
  const { page, nodes } = tree(scene, pageId);
  drawDescriptorTree(ck, canvas, page, nodes, fontProvider, images);
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

/** A raster asset record (status ready) with the given natural pixel size. */
function rasterAsset(id: string, pixelWidth: number, pixelHeight: number): AssetRecord {
  return {
    id,
    label: id,
    kind: "raster_image",
    status: "ready",
    source: { kind: "workspace", asset_id: id },
    raster: {
      pixel_width: pixelWidth,
      pixel_height: pixelHeight,
      dpi_x: null,
      dpi_y: null,
      has_alpha: false,
      color_profile: null,
      aspect_ratio: null
    },
    vector: null,
    font: null,
    logo: null,
    license: null,
    provenance: {
      created_by: "test",
      created_at: "2026-06-20T00:00:00Z",
      source_label: "test fixture",
      confidence: 1,
      notes: []
    },
    tags: []
  };
}

function imageNode(
  id: string,
  x: number,
  y: number,
  w: number,
  h: number,
  assetId: string,
  placement: Node["asset_placement"]
): Node {
  const base = JSON.parse(JSON.stringify(minimalScene.nodes.node_contact_name)) as Node;
  return {
    ...base,
    id,
    name: id,
    kind: { kind: "image", asset_id: assetId, alt: "test image" },
    source_asset_id: assetId,
    asset_placement: placement,
    children: [],
    transform: { ...base.transform, x, y },
    size: { width: { kind: "fixed", value: w }, height: { kind: "fixed", value: h } },
    fills: [],
    strokes: [],
    corner: { top_left: 0, top_right: 0, bottom_right: 0, bottom_left: 0 },
    computed: { layout_bounds: { x, y, width: w, height: h }, render_bounds: { x, y, width: w, height: h } }
  };
}

/** Build a decoded raster image from raw RGBA pixels (row-major, 4 bytes/px). */
function rasterImage(width: number, height: number, rgba: number[]): Image {
  const image = ck.MakeImage(
    {
      width,
      height,
      colorType: ck.ColorType.RGBA_8888,
      alphaType: ck.AlphaType.Unpremul,
      colorSpace: ck.ColorSpace.SRGB
    },
    Uint8Array.from(rgba),
    width * 4
  );
  if (!image) {
    throw new Error("MakeImage returned null");
  }
  return image;
}

/** A single-decoded-image source keyed to one asset id. */
function imageSource(assetId: string, image: Image): CanvasKitImageSource {
  return { get: (id) => (id === assetId ? image : null) };
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

  it("draws real image pixels for a ready image node (not the gray placeholder)", () => {
    const green = [0, 200, 0, 255];
    const img = rasterImage(2, 2, [...green, ...green, ...green, ...green]);
    const node = imageNode("img", 30, 10, 40, 40, "asset_img", {
      fit: "cover",
      focal_point: null,
      alt_text: null
    });
    const scene = pxScene({ img: node }, ["img"]);
    scene.assets.asset_img = rasterAsset("asset_img", 2, 2);

    const out = render(scene, "page_a4", 100, 60, null, imageSource("asset_img", img));
    img.delete();

    const [r, g, b, a] = pixel(out, 50, 30, 100); // box center
    expect(g).toBeGreaterThan(150); // image green drawn, not the gray placeholder
    expect(r).toBeLessThan(90);
    expect(b).toBeLessThan(90);
    expect(a).toBe(255);
    // Placeholder gray is #ddd7cc (≈221,215,204) — prove we did NOT draw it.
    expect(r === 221 && g === 215 && b === 204).toBe(false);
  });

  it("honors the focal point for a cover crop (left-focal → left of image, right-focal → right)", () => {
    // 4×2 image: columns 0–1 red, columns 2–3 blue (natural ratio 2:1).
    const red = [255, 0, 0, 255];
    const blue = [0, 0, 255, 255];
    const row = [...red, ...red, ...blue, ...blue];
    const img = rasterImage(4, 2, [...row, ...row]);

    // Tall 20×60 box: a cover crop scales the image to 120×60 and slides it
    // horizontally by the focal point, so x=0 shows the red edge, x=1 the blue.
    const makeScene = (focalX: number): Scene => {
      const node = imageNode("img", 0, 0, 20, 60, "asset_img", {
        fit: "cover",
        focal_point: { x: focalX, y: 0.5 },
        alt_text: null
      });
      const scene = pxScene({ img: node }, ["img"]);
      scene.pages.page_a4 = {
        ...scene.pages.page_a4,
        size: { width: 20, height: 60, unit: "px", preset: "custom", orientation: "portrait" }
      };
      scene.assets.asset_img = rasterAsset("asset_img", 4, 2);
      return scene;
    };

    const leftFocal = render(makeScene(0), "page_a4", 20, 60, null, imageSource("asset_img", img));
    const rightFocal = render(makeScene(1), "page_a4", 20, 60, null, imageSource("asset_img", img));
    img.delete();

    const [lr, , lb] = pixel(leftFocal, 10, 30, 20);
    expect(lr).toBeGreaterThan(150); // focal x=0 → red side visible
    expect(lb).toBeLessThan(100);

    const [rr, , rb] = pixel(rightFocal, 10, 30, 20);
    expect(rb).toBeGreaterThan(150); // focal x=1 → blue side visible
    expect(rr).toBeLessThan(100);
  });

  // A4 Effects v1: the general effect pipeline draws glow / layer blur / inner
  // shadow via CanvasKit image filters, mirroring the lumen-skia recipes.
  it("draws an outer glow that bleeds color beyond the node box", () => {
    const base = rect("r", 40, 20, 20, 20, "#000000");
    const glow: Node = {
      ...base,
      effects: [{ id: "fx", kind: { kind: "glow", color: { kind: "hex", value: "#ff0000" }, opacity: 1, blur: 20, spread: 0 } }]
    };
    const withGlow = render(pxScene({ r: glow }, ["r"]), "page_a4", 100, 60);
    const without = render(pxScene({ r: base }, ["r"]), "page_a4", 100, 60);

    // A pixel 2px left of the box (box left edge x=40): white with no glow,
    // reddened by the glow bleed with it.
    expect(pixel(without, 38, 30, 100)).toEqual([255, 255, 255, 255]);
    const [r1, g1, b1] = pixel(withGlow, 38, 30, 100);
    expect(g1).toBeLessThan(255);
    expect(b1).toBeLessThan(255);
    expect(r1).toBeGreaterThan(g1); // red glow tint
  });

  it("blurs the node's own rendering with a layer blur", () => {
    const base = rect("r", 40, 20, 20, 20, "#000000");
    const blurred: Node = {
      ...base,
      effects: [{ id: "fx", kind: { kind: "layer_blur", radius: 12 } }]
    };
    const soft = render(pxScene({ r: blurred }, ["r"]), "page_a4", 100, 60);
    const sharp = render(pxScene({ r: base }, ["r"]), "page_a4", 100, 60);

    // Just outside the left edge: the sharp box leaves it white, the layer blur
    // bleeds the black body across the boundary.
    expect(pixel(sharp, 38, 30, 100)[0]).toBe(255);
    expect(pixel(soft, 38, 30, 100)[0]).toBeLessThan(220);
  });

  it("draws an inner shadow darkening the node's inner edge", () => {
    const node = rect("r", 20, 10, 60, 40, "#ffffff");
    node.effects = [
      { id: "fx", kind: { kind: "inner_shadow", color: { kind: "hex", value: "#000000" }, opacity: 1, x: 0, y: 0, blur: 10, spread: 0 } }
    ];
    const out = render(pxScene({ r: node }, ["r"]), "page_a4", 100, 60);

    // Box x 20..80, y 10..50. The center stays near white; a pixel just inside
    // the top edge is darkened by the inner shadow ring.
    const center = pixel(out, 50, 30, 100)[0];
    const edge = pixel(out, 50, 13, 100)[0];
    expect(center).toBeGreaterThan(200);
    expect(edge).toBeLessThan(center);
  });
});

const SYSTEM_FONT = "/Library/Fonts/Arial Unicode.ttf";

describe.skipIf(!present || !existsSync(SYSTEM_FONT))("CanvasKit text rendering (Wave 3 C4)", () => {
  let fontProvider: TypefaceFontProvider;
  const family = "TestFamily";

  beforeAll(async () => {
    if (!ck) {
      ck = await loadCk();
    }
    const bytes = readFileSync(SYSTEM_FONT);
    const ab = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    fontProvider = ck.TypefaceFontProvider.Make();
    fontProvider.registerFont(ab, family);
  });

  it("draws glyphs (dark pixels) inside the text box via SkParagraph", () => {
    const base = JSON.parse(JSON.stringify(minimalScene.nodes.node_contact_name)) as Node;
    const text: Node = {
      ...base,
      id: "t",
      kind: {
        kind: "text",
        content: "HELLO",
        font_family: family,
        font_size: 36,
        font_weight: 700,
        align: "left",
        line_height: 1.2,
        letter_spacing: 0,
        wrap: "no_wrap",
        direction: "ltr"
      },
      fills: [{ id: "t_fill", paint: { kind: "solid", color: { kind: "hex", value: "#000000" } } }],
      strokes: [],
      transform: { ...base.transform, x: 0, y: 0 },
      size: { width: { kind: "fixed", value: 200 }, height: { kind: "fixed", value: 50 } },
      computed: {
        layout_bounds: { x: 0, y: 0, width: 200, height: 50 },
        render_bounds: { x: 0, y: 0, width: 200, height: 50 }
      }
    };
    const pixels = render(pxScene({ t: text }, ["t"]), "page_a4", 200, 50, fontProvider);

    // Scan the text band for any dark (drawn-glyph) pixel.
    let darkCount = 0;
    for (let y = 5; y < 45; y++) {
      for (let x = 0; x < 200; x++) {
        const [r] = pixel(pixels, x, y, 200);
        if (r < 80) {
          darkCount++;
        }
      }
    }
    expect(darkCount).toBeGreaterThan(20);
  });

  // Regression: centered/right-aligned no-wrap text used to lay out at a
  // near-infinite width and paint at x=0, so SkParagraph anchored the glyphs
  // within that width and pushed them ~quadrillions of px off-canvas (button
  // labels / badges never painted, though the SVG export was fine). The draw
  // path now mirrors the exporter's NoWrap arm: measure the natural width,
  // then offset the block per alignment against the real node width.
  const BOX_W = 200;
  const glyphStats = (align: "left" | "center" | "right"): { count: number; centroid: number } => {
    const base = JSON.parse(JSON.stringify(minimalScene.nodes.node_contact_name)) as Node;
    const text: Node = {
      ...base,
      id: "t",
      kind: {
        kind: "text",
        content: "HI",
        font_family: family,
        font_size: 30,
        font_weight: 700,
        align,
        line_height: 1.2,
        letter_spacing: 0,
        wrap: "no_wrap",
        max_lines: 1,
        direction: "ltr"
      },
      fills: [{ id: "t_fill", paint: { kind: "solid", color: { kind: "hex", value: "#000000" } } }],
      strokes: [],
      transform: { ...base.transform, x: 0, y: 0 },
      // Box far wider than the short glyph run so alignment actually shifts it.
      size: { width: { kind: "fixed", value: BOX_W }, height: { kind: "fixed", value: 50 } },
      computed: {
        layout_bounds: { x: 0, y: 0, width: BOX_W, height: 50 },
        render_bounds: { x: 0, y: 0, width: BOX_W, height: 50 }
      }
    };
    const pixels = render(pxScene({ t: text }, ["t"]), "page_a4", BOX_W, 50, fontProvider);
    let count = 0;
    let sumX = 0;
    for (let y = 5; y < 45; y++) {
      for (let x = 0; x < BOX_W; x++) {
        if (pixel(pixels, x, y, BOX_W)[0] < 80) {
          count++;
          sumX += x;
        }
      }
    }
    return { count, centroid: count > 0 ? sumX / count : NaN };
  };

  it("no-wrap text paints on-canvas for every alignment (not off at infinity)", () => {
    // Before the fix, center/right laid out at ~MAX_SAFE_INTEGER width and
    // painted at x=0, so the glyphs anchored quadrillions of px right of the
    // box and NONE of them landed on the 200px surface.
    for (const align of ["left", "center", "right"] as const) {
      expect(glyphStats(align).count).toBeGreaterThan(20);
    }
  });

  it("no-wrap alignment shifts the glyph block within the real box", () => {
    const left = glyphStats("left").centroid;
    const center = glyphStats("center").centroid;
    const right = glyphStats("right").centroid;
    // Every centroid is inside the box, and they march left → center → right.
    for (const c of [left, center, right]) {
      expect(c).toBeGreaterThan(0);
      expect(c).toBeLessThan(BOX_W);
    }
    expect(center).toBeGreaterThan(left);
    expect(right).toBeGreaterThan(center);
  });

  // A6b D7: a span with a distinct fill paints a two-color headline — the base
  // run keeps the node fill (black) and the span run paints its own color (red).
  it("paints a two-color headline: base run node fill, span run span fill", () => {
    const base = JSON.parse(JSON.stringify(minimalScene.nodes.node_contact_name)) as Node;
    const text: Node = {
      ...base,
      id: "t",
      kind: {
        kind: "text",
        content: "HELLO WORLD",
        font_family: family,
        font_size: 36,
        font_weight: 700,
        align: "left",
        line_height: 1.2,
        letter_spacing: 0,
        wrap: "no_wrap",
        direction: "ltr",
        // "WORLD" (bytes 6..11) painted red; "HELLO " stays the node fill.
        spans: [{ start: 6, end: 11, fill: { kind: "solid", color: { kind: "hex", value: "#ff0000" } } }]
      },
      fills: [{ id: "t_fill", paint: { kind: "solid", color: { kind: "hex", value: "#000000" } } }],
      strokes: [],
      transform: { ...base.transform, x: 0, y: 0 },
      size: { width: { kind: "fixed", value: 400 }, height: { kind: "fixed", value: 50 } },
      computed: {
        layout_bounds: { x: 0, y: 0, width: 400, height: 50 },
        render_bounds: { x: 0, y: 0, width: 400, height: 50 }
      }
    };
    const pixels = render(pxScene({ t: text }, ["t"]), "page_a4", 400, 50, fontProvider);

    let blackGlyphs = 0;
    let redGlyphs = 0;
    for (let y = 5; y < 45; y++) {
      for (let x = 0; x < 400; x++) {
        const [r, g, b] = pixel(pixels, x, y, 400);
        if (r < 80 && g < 80 && b < 80) {
          blackGlyphs++; // dark = base "HELLO" glyphs
        } else if (r > 150 && g < 90 && b < 90) {
          redGlyphs++; // red = span "WORLD" glyphs
        }
      }
    }
    // Both colors present: the base run is black, the span run is red.
    expect(blackGlyphs).toBeGreaterThan(20);
    expect(redGlyphs).toBeGreaterThan(20);
  });

  // A7b: exercise the italic slant plumbing through BOTH paragraph builders.
  // The system test font carries no separate italic face, so Skia snaps to
  // upright (D2 — no synthetic slant): the assertion is that the block-italic
  // path AND the spanned per-run override path (an italic block with a
  // de-italicizing span) both render glyphs without error. Real slant fidelity
  // is the review gate's job (a provisioned italic face + gate.py/browser).
  const italicScene = (spans?: TextSpan[]): Node => {
    const base = JSON.parse(JSON.stringify(minimalScene.nodes.node_contact_name)) as Node;
    return {
      ...base,
      id: "t",
      kind: {
        kind: "text",
        content: "HELLO WORLD",
        font_family: family,
        font_size: 36,
        font_weight: 400,
        align: "left",
        line_height: 1.2,
        letter_spacing: 0,
        wrap: "no_wrap",
        direction: "ltr",
        italic: true,
        ...(spans ? { spans } : {})
      },
      fills: [{ id: "t_fill", paint: { kind: "solid", color: { kind: "hex", value: "#000000" } } }],
      strokes: [],
      transform: { ...base.transform, x: 0, y: 0 },
      size: { width: { kind: "fixed", value: 400 }, height: { kind: "fixed", value: 50 } },
      computed: {
        layout_bounds: { x: 0, y: 0, width: 400, height: 50 },
        render_bounds: { x: 0, y: 0, width: 400, height: 50 }
      }
    };
  };

  const darkGlyphCount = (node: Node): number => {
    const pixels = render(pxScene({ t: node }, ["t"]), "page_a4", 400, 50, fontProvider);
    let dark = 0;
    for (let y = 5; y < 45; y++) {
      for (let x = 0; x < 400; x++) {
        if (pixel(pixels, x, y, 400)[0] < 80) {
          dark++;
        }
      }
    }
    return dark;
  };

  it("renders a block-italic text node (slant plumbed to the base builder)", () => {
    expect(darkGlyphCount(italicScene())).toBeGreaterThan(20);
  });

  it("renders an italic block with a de-italicizing span (override merge path)", () => {
    // "WORLD" (bytes 6..11) carries italic:false inside the italic block — the
    // spanned builder resolves `span.italic ?? block` per run and must render.
    expect(darkGlyphCount(italicScene([{ start: 6, end: 11, italic: false }]))).toBeGreaterThan(20);
  });
});
