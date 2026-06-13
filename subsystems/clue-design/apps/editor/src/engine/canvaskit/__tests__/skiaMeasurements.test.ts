// @vitest-environment node
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { beforeAll, describe, expect, it } from "vitest";
import type { CanvasKit, FontMgr } from "canvaskit-wasm";
import type { Node, Scene } from "../../contracts";
import { minimalScene } from "@/fixtures/minimalScene";
import { measureParagraph, skiaMeasurements } from "../skiaMeasurements";

/**
 * Wave 3 C4: the SkParagraph measurement provider. Verified with a system
 * font in Node; production ships InterVariable. Proves the payload shape and
 * that wider/larger text measures larger — the metrics the engine injects.
 */

const CK_BIN = path.resolve(__dirname, "../../../../node_modules/canvaskit-wasm/bin");
const SYSTEM_FONT = "/Library/Fonts/Arial Unicode.ttf";
const present = existsSync(path.join(CK_BIN, "canvaskit.wasm")) && existsSync(SYSTEM_FONT);

let ck: CanvasKit;
let fontMgr: FontMgr;
let family: string;

describe.skipIf(!present)("SkParagraph measurement provider (Wave 3 C4)", () => {
  beforeAll(async () => {
    const mod = (await import("canvaskit-wasm")) as unknown as {
      default: (options: { locateFile: (file: string) => string }) => Promise<CanvasKit>;
    };
    ck = await mod.default({ locateFile: (file: string) => path.join(CK_BIN, file) });
    const bytes = readFileSync(SYSTEM_FONT);
    const ab = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    fontMgr = ck.FontMgr.FromData(ab)!;
    family = fontMgr.getFamilyName(0);
  });

  it("measures wider text wider and taller text taller", () => {
    const base = measureParagraph(ck, fontMgr, {
      content: "Hi",
      fontFamily: family,
      fontSize: 20,
      fontWeight: 400,
      lineHeight: 1.2,
      letterSpacing: 0
    });
    const longer = measureParagraph(ck, fontMgr, {
      content: "Hello there, world",
      fontFamily: family,
      fontSize: 20,
      fontWeight: 400,
      lineHeight: 1.2,
      letterSpacing: 0
    });
    const bigger = measureParagraph(ck, fontMgr, {
      content: "Hi",
      fontFamily: family,
      fontSize: 40,
      fontWeight: 400,
      lineHeight: 1.2,
      letterSpacing: 0
    });
    expect(base.width).toBeGreaterThan(0);
    expect(longer.width).toBeGreaterThan(base.width);
    expect(bigger.height).toBeGreaterThan(base.height);
  });

  it("emits one metric per text node with the engine's key fields", () => {
    const scene = JSON.parse(JSON.stringify(minimalScene)) as Scene;
    // Add a non-text node to confirm it is ignored.
    const rect: Node = {
      ...scene.nodes.node_contact_name,
      id: "rect",
      kind: { kind: "rect" },
      children: []
    };
    scene.nodes.rect = rect;
    (scene.nodes.node_contact_name.kind as { font_family: string }).font_family = family;

    const metrics = skiaMeasurements(ck, fontMgr, scene);
    expect(metrics).toHaveLength(1); // only the text node
    const m = metrics[0];
    expect(m.content).toBe("Dr. Priya Sharma");
    expect(m.font_family).toBe(family);
    expect(m.width).toBeGreaterThan(0);
    expect(m.height).toBeGreaterThan(0);
    expect(m.wrap).toBe("wrap");
    expect(m.direction).toBe("ltr");
    expect(m.max_lines).toBeNull();
  });
});
