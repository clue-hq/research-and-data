// @vitest-environment node
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it, beforeAll } from "vitest";
import type { CanvasKit, Surface } from "canvaskit-wasm";
import type { Node, Scene } from "../../contracts";
import {
  nodeDescriptor,
  pageDescriptor,
  type RenderPageDescriptor
} from "../../renderAdapter";
import { drawDescriptorTree, type DrawNode } from "../drawDescriptors";

/**
 * Wave 3 C5 visual-regression: the CanvasKit descriptor interpreter rendered
 * against the canonical Skia EXPORT golden for the same scene
 * (`crates/lumen-skia/tests/goldens/effects_card.png`). The effects_card
 * fixture is the rich case — gradient stack, dashed round-cap stroke, and a
 * two-shadow stack, no text — so this is a pure cross-engine fidelity check
 * (the spike measured 0.003% on this exact card vs a resvg baseline). A
 * regression in the interpreter (paint stacks, contour dash, shadow chain)
 * pushes the perceptual diff over the bar and fails the test.
 */

const CK_BIN = path.resolve(__dirname, "../../../../node_modules/canvaskit-wasm/bin");
const FIXTURE = path.resolve(__dirname, "../../../../../../crates/lumen-core/fixtures/effects/effects_card.json");
const GOLDEN = path.resolve(__dirname, "../../../../../../crates/lumen-skia/tests/goldens/effects_card.png");
const present = existsSync(path.join(CK_BIN, "canvaskit.wasm")) && existsSync(FIXTURE) && existsSync(GOLDEN);

// A pixel "differs" when any channel is off by more than this (8-bit). Absorbs
// sub-LSB anti-aliasing / blur rounding while catching real render errors.
const CHANNEL_TOLERANCE = 32;
// Allowed fraction of differing pixels. Baseline (2026-06-13): the interpreter
// renders effects_card at ~1.19% differing pixels vs the Skia export, and a
// visual comparison confirms the card/gradient/soft-shadow/fills are pixel-
// faithful — the difference is entirely the dashed round-cap stroke's
// dash-phase + AA along the border. A real regression (a missing shadow, wrong
// gradient, or absent fill) changes thousands of interior pixels and blows past
// this bar.
const MAX_DIFF_FRACTION = 0.018;

let ck: CanvasKit;

async function loadCk(): Promise<CanvasKit> {
  const mod = (await import("canvaskit-wasm")) as unknown as {
    default: (options: { locateFile: (file: string) => string }) => Promise<CanvasKit>;
  };
  return mod.default({ locateFile: (file: string) => path.join(CK_BIN, file) });
}

function scene(): Scene {
  return JSON.parse(readFileSync(FIXTURE, "utf8")) as Scene;
}

function tree(s: Scene, pageId: string): { page: RenderPageDescriptor; nodes: DrawNode[] } {
  const page = s.pages[pageId];
  const toDraw = (node: Node): DrawNode => ({
    descriptor: nodeDescriptor(s, node, page),
    children: node.children.map((id) => toDraw(s.nodes[id]))
  });
  return { page: pageDescriptor(page), nodes: page.children.map((id) => toDraw(s.nodes[id])) };
}

function readSurface(surface: Surface, w: number, h: number): Uint8Array {
  const img = surface.makeImageSnapshot();
  const px = img.readPixels(0, 0, {
    width: w,
    height: h,
    colorType: ck.ColorType.RGBA_8888,
    alphaType: ck.AlphaType.Unpremul,
    colorSpace: ck.ColorSpace.SRGB
  }) as Uint8Array;
  img.delete();
  return px;
}

describe.skipIf(!present)("CanvasKit visual regression vs Skia export golden (Wave 3 C5)", () => {
  beforeAll(async () => {
    ck = await loadCk();
  });

  it("renders effects_card within the perceptual-diff bar of the Skia export", () => {
    const s = scene();
    const pageId = Object.keys(s.pages)[0];
    const { page, nodes } = tree(s, pageId);
    const w = Math.round(page.width);
    const h = Math.round(page.height);

    // Render via the CanvasKit interpreter.
    const surface = ck.MakeSurface(w, h)!;
    drawDescriptorTree(ck, surface.getCanvas(), page, nodes, null);
    surface.flush();
    const rendered = readSurface(surface, w, h);
    surface.delete();

    // Decode the Skia export golden with CanvasKit.
    const goldenImage = ck.MakeImageFromEncoded(readFileSync(GOLDEN))!;
    expect(goldenImage).toBeTruthy();
    expect(goldenImage.width()).toBe(w);
    expect(goldenImage.height()).toBe(h);
    const golden = goldenImage.readPixels(0, 0, {
      width: w,
      height: h,
      colorType: ck.ColorType.RGBA_8888,
      alphaType: ck.AlphaType.Unpremul,
      colorSpace: ck.ColorSpace.SRGB
    }) as Uint8Array;
    goldenImage.delete();

    // Perceptual diff: fraction of pixels whose max channel delta exceeds the
    // tolerance.
    let differing = 0;
    let maxDelta = 0;
    const totalPixels = w * h;
    for (let i = 0; i < rendered.length; i += 4) {
      const dr = Math.abs(rendered[i] - golden[i]);
      const dg = Math.abs(rendered[i + 1] - golden[i + 1]);
      const db = Math.abs(rendered[i + 2] - golden[i + 2]);
      const d = Math.max(dr, dg, db);
      if (d > maxDelta) maxDelta = d;
      if (d > CHANNEL_TOLERANCE) differing++;
    }
    const fraction = differing / totalPixels;
    // Surfaced for the baseline record.
    // eslint-disable-next-line no-console
    console.log(
      `effects_card vs Skia export: ${differing}/${totalPixels} px differ (${(fraction * 100).toFixed(3)}%), maxChannelDelta=${maxDelta}`
    );

    expect(fraction).toBeLessThan(MAX_DIFF_FRACTION);
  });
});
