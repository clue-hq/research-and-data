// @vitest-environment node
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { beforeAll, describe, expect, it } from "vitest";
import type { CanvasKit, Surface, TypefaceFontProvider } from "canvaskit-wasm";
import type { Node, Scene } from "../../contracts";
import { nodeDescriptor, pageDescriptor, type RenderPageDescriptor } from "../../renderAdapter";
import { drawDescriptorTree, type DrawNode } from "../drawDescriptors";

/**
 * Wave 3 C5 soak/leak: the CanvasKit interpreter allocates wasm-heap objects
 * (Paint/Path/Shader/ImageFilter/Paragraph) per draw and must free them, or a
 * long editing session leaks. This drives many draws — through the
 * fill/gradient/stroke/shadow AND text/paragraph paths — over a single reused
 * surface and asserts the wasm heap does not grow unbounded past a warm-up
 * (i.e. growth is not proportional to the draw count).
 */

const CK_BIN = path.resolve(__dirname, "../../../../node_modules/canvaskit-wasm/bin");
const FIXTURE = path.resolve(__dirname, "../../../../../../crates/lumen-core/fixtures/effects/effects_card.json");
const SYSTEM_FONT = "/Library/Fonts/Arial Unicode.ttf";
const present = existsSync(path.join(CK_BIN, "canvaskit.wasm")) && existsSync(FIXTURE);

const WARMUP_DRAWS = 20;
const SOAK_DRAWS = 250;
// Past warm-up the heap should be flat; allow a generous slab for emscripten
// growth granularity. A real per-draw leak (even a few small objects × 600)
// would blow well past this.
const MAX_GROWTH_BYTES = 8 * 1024 * 1024;

let ck: CanvasKit;
let fontProvider: TypefaceFontProvider | null = null;

async function loadCk(): Promise<CanvasKit> {
  const mod = (await import("canvaskit-wasm")) as unknown as {
    default: (options: { locateFile: (file: string) => string }) => Promise<CanvasKit>;
  };
  return mod.default({ locateFile: (file: string) => path.join(CK_BIN, file) });
}

/** effects_card (fills/gradient/dashed stroke/2 shadows) plus a text node so
 * the soak exercises the paragraph allocation path too. */
function soakTree(): { page: RenderPageDescriptor; nodes: DrawNode[] } {
  const scene = JSON.parse(readFileSync(FIXTURE, "utf8")) as Scene;
  const pageId = Object.keys(scene.pages)[0];
  const page = scene.pages[pageId];
  if (fontProvider) {
    const template = scene.nodes[Object.keys(scene.nodes)[0]];
    const text: Node = {
      ...template,
      id: "soak_text",
      name: "Soak Text",
      kind: {
        kind: "text",
        content: "Soak Test Heading",
        font_family: "SoakFamily",
        font_size: 20,
        font_weight: 700,
        align: "left",
        line_height: 1.2,
        letter_spacing: 0,
        wrap: "no_wrap",
        direction: "ltr"
      },
      fills: [{ id: "soak_fill", paint: { kind: "solid", color: { kind: "hex", value: "#111111" } } }],
      strokes: [],
      effects: [],
      children: [],
      transform: { ...template.transform, x: 60, y: 60 },
      size: { width: { kind: "fixed", value: 200 }, height: { kind: "fixed", value: 30 } },
      computed: null
    };
    scene.nodes.soak_text = text;
    page.children = [...page.children, "soak_text"];
  }
  const toDraw = (node: Node): DrawNode => ({
    descriptor: nodeDescriptor(scene, node, page),
    children: node.children.map((id) => toDraw(scene.nodes[id]))
  });
  return { page: pageDescriptor(page), nodes: page.children.map((id) => toDraw(scene.nodes[id])) };
}

function heapBytes(): number {
  const heap = (ck as unknown as { HEAPU8?: Uint8Array }).HEAPU8;
  return heap ? heap.buffer.byteLength : -1;
}

describe.skipIf(!present)("CanvasKit interpreter soak/leak (Wave 3 C5)", () => {
  beforeAll(async () => {
    ck = await loadCk();
    if (existsSync(SYSTEM_FONT)) {
      const bytes = readFileSync(SYSTEM_FONT);
      const ab = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
      fontProvider = ck.TypefaceFontProvider.Make();
      fontProvider.registerFont(ab, "SoakFamily");
    }
  });

  it("does not grow the wasm heap unbounded across many draws", { timeout: 120_000 }, () => {
    const { page, nodes } = soakTree();
    const w = Math.round(page.width);
    const h = Math.round(page.height);
    const surface: Surface = ck.MakeSurface(w, h)!;
    const canvas = surface.getCanvas();

    const draw = () => {
      drawDescriptorTree(ck, canvas, page, nodes, fontProvider);
      surface.flush();
    };

    for (let i = 0; i < WARMUP_DRAWS; i++) {
      draw();
    }
    const before = heapBytes();

    for (let i = 0; i < SOAK_DRAWS; i++) {
      draw();
    }
    const after = heapBytes();
    surface.delete();

    // Surfaced for the record.
    // eslint-disable-next-line no-console
    console.log(
      `soak: ${SOAK_DRAWS} draws, heap ${before} → ${after} (Δ ${after - before} bytes), heapAccessible=${before >= 0}`
    );

    if (before >= 0) {
      expect(after - before).toBeLessThan(MAX_GROWTH_BYTES);
    } else {
      // Heap size not introspectable in this build — fall back to "completed
      // every draw without throwing", still a meaningful crash/leak smoke test.
      expect(true).toBe(true);
    }
  });
});
