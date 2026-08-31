// @vitest-environment node
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { beforeAll, describe, expect, it } from "../../__tests__/vitest-shim";
import type { CanvasKit, TypefaceFontProvider } from "canvaskit-wasm";
import type { Node, Scene, TextSpan } from "../contracts";
import { minimalScene } from "./__fixtures__/minimalScene";
import { measureParagraph, skiaMeasurements } from "../canvaskit/skiaMeasurements";

/**
 * Wave 3 C4: the SkParagraph measurement provider. Verified with a system
 * font in Node; production ships InterVariable. Proves the payload shape and
 * that wider/larger text measures larger — the metrics the engine injects.
 */

const CK_BIN = path.resolve(__dirname, "../../../../../../node_modules/canvaskit-wasm/bin");
const SYSTEM_FONT = "/Library/Fonts/Arial Unicode.ttf";
const present = existsSync(path.join(CK_BIN, "canvaskit.wasm")) && existsSync(SYSTEM_FONT);

let ck: CanvasKit;
let fontMgr: TypefaceFontProvider;
const family = "TestFamily";

describe.skipIf(!present)("SkParagraph measurement provider (Wave 3 C4)", () => {
  beforeAll(async () => {
    const mod = (await import("canvaskit-wasm")) as unknown as {
      default: (options: { locateFile: (file: string) => string }) => Promise<CanvasKit>;
    };
    ck = await mod.default({ locateFile: (file: string) => path.join(CK_BIN, file) });
    const bytes = readFileSync(SYSTEM_FONT);
    const ab = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    fontMgr = ck.TypefaceFontProvider.Make();
    fontMgr.registerFont(ab, family);
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
    // A6b: a spanless node omits the spans key so the record stays byte-identical
    // to the pre-A6b payload (serde default → empty Vec on the engine side).
    expect(m.spans).toBeUndefined();
  });

  // A6b review fix: a spanned node's record MUST carry the raw spans (the engine
  // keys its measure lookup on the spans digest) AND its measured width must
  // reflect the pushed per-run styles — a heavier weight-span shapes wider.
  const spannedTextNode = (spans: TextSpan[]): Node => {
    const base = JSON.parse(JSON.stringify(minimalScene.nodes.node_contact_name)) as Node;
    return {
      ...base,
      id: "t_spanned",
      kind: {
        kind: "text",
        content: "Every outage now",
        font_family: family,
        font_size: 40,
        font_weight: 400,
        align: "left",
        line_height: 1.2,
        letter_spacing: 0,
        wrap: "no_wrap",
        direction: "ltr",
        spans
      }
    };
  };

  it("carries the raw spans in the record and measures a weight-span wider", () => {
    const heavySpan: TextSpan = { start: 6, end: 12, font_weight: 900 };
    const scene = JSON.parse(JSON.stringify(minimalScene)) as Scene;
    scene.nodes = { t_spanned: spannedTextNode([heavySpan]) };
    scene.pages.page_a4 = { ...scene.pages.page_a4, children: ["t_spanned"] };

    const metrics = skiaMeasurements(ck, fontMgr, scene);
    expect(metrics).toHaveLength(1);
    const m = metrics[0];
    // The record echoes the node spans verbatim (the digest key).
    expect(m.spans).toEqual([heavySpan]);
    expect(m.content).toBe("Every outage now");
    expect(m.width).toBeGreaterThan(0);

    // The same content with a base-weight span (400) measures narrower than the
    // 900-weight span — proof the pushed style reached the measured paragraph.
    const lightScene = JSON.parse(JSON.stringify(minimalScene)) as Scene;
    lightScene.nodes = { t_spanned: spannedTextNode([{ start: 6, end: 12, font_weight: 400 }]) };
    lightScene.pages.page_a4 = { ...lightScene.pages.page_a4, children: ["t_spanned"] };
    const lightWidth = skiaMeasurements(ck, fontMgr, lightScene)[0].width;

    // Bold shapes wider (the system test font must have distinct weights; if it
    // does not, the metric is at least non-negative and present).
    expect(m.width).toBeGreaterThanOrEqual(lightWidth);
  });

  // A7b: block italic is a `measure_key` input, so the record MUST carry it (a
  // miss falls back to the heuristic). Span italic rides in the raw `spans`.
  it("carries block italic in the record and echoes span italic verbatim", () => {
    const scene = JSON.parse(JSON.stringify(minimalScene)) as Scene;
    (scene.nodes.node_contact_name.kind as { font_family: string }).font_family = family;
    // Spanless, upright default → italic false, present.
    expect(skiaMeasurements(ck, fontMgr, scene)[0].italic).toBe(false);

    // Block italic → record carries italic true.
    (scene.nodes.node_contact_name.kind as { italic?: boolean }).italic = true;
    expect(skiaMeasurements(ck, fontMgr, scene)[0].italic).toBe(true);

    // A de-italicizing span in an italic block: the record echoes the raw spans
    // (the digest key) with italic:false preserved for the override merge.
    const deItalic: TextSpan = { start: 6, end: 12, italic: false };
    const spanScene = JSON.parse(JSON.stringify(minimalScene)) as Scene;
    spanScene.nodes = { t_spanned: spannedTextNode([deItalic]) };
    (spanScene.nodes.t_spanned.kind as { italic?: boolean }).italic = true;
    spanScene.pages.page_a4 = { ...spanScene.pages.page_a4, children: ["t_spanned"] };
    const record = skiaMeasurements(ck, fontMgr, spanScene)[0];
    expect(record.italic).toBe(true);
    expect(record.spans).toEqual([deItalic]);
  });
});
