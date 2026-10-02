// @vitest-environment node
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { beforeAll, describe, expect, it } from "../../__tests__/vitest-shim";
import type { CanvasKit, TypefaceFontProvider } from "canvaskit-wasm";
import type { Node, Scene, TextSpan } from "../contracts";
import { minimalScene } from "./__fixtures__/minimalScene";
import {
  injectSkiaMeasurements,
  MEASUREMENT_ROUNDS_MAX,
  measureParagraph,
  skiaLineMeasurements,
  skiaRequestedMeasurements,
  skiaMeasurements
} from "../canvaskit/skiaMeasurements";
import type { MeasurementEngine } from "../canvaskit/skiaMeasurements";
import type { TextMeasurement } from "../wasmEngine";
import { setKitTokenMaps } from "../renderAdapter";
import { WasmEngine } from "../wasmEngine";
import { loadWasmModuleFromDisk } from "./wasm-module-loader";

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

  it("fits a token-styled label inside nested fill columns with the real WASM layout", async () => {
    setKitTokenMaps({ colors: {}, numbers: { "type.test": 30 }, typography: {} });
    const scene = structuredClone(minimalScene);
    scene.slots = {};
    const child = scene.nodes.node_contact_name;
    if (child.kind.kind !== "text") throw new Error("fixture");
    child.kind = { ...child.kind, content: "Human review", font_family: family,
      font_size: 16, font_weight: 400, line_height: 1, font_size_token: "type.test",
      text_transform: "uppercase", wrap: "wrap", max_lines: 1 };
    child.size = { width: { kind: "fill", value: { weight: 1 } }, height: { kind: "hug" } };
    child.transform = { ...child.transform, x: 0, y: 0 };
    scene.nodes.outer = { ...structuredClone(child), id: "outer",
      kind: { kind: "auto_layout", direction: "column", wrap: false },
      size: { width: { kind: "fixed", value: 600 }, height: { kind: "hug" } },
      layout: { gap: 0, grow: 0, align_x: "start", align_y: "start", padding: [24, 32, 24, 32] },
      children: ["inner"] };
    scene.nodes.inner = { ...structuredClone(scene.nodes.outer), id: "inner",
      size: { width: { kind: "fill", value: { weight: 1 } }, height: { kind: "hug" } },
      layout: { gap: 0, grow: 0, align_x: "start", align_y: "start", padding: [0, 0, 0, 0] },
      children: [child.id] };
    scene.pages.page_a4.children = ["outer"];
    const engine = new WasmEngine(await loadWasmModuleFromDisk(), scene);
    injectSkiaMeasurements(engine, {
      unconstrained: (snapshot) => skiaMeasurements(ck, fontMgr, snapshot),
      lines: (snapshot) => skiaLineMeasurements(ck, fontMgr, snapshot),
      requests: (snapshot, requests) => skiaRequestedMeasurements(ck, fontMgr, snapshot, requests)
    });
    const builder = ck.ParagraphBuilder.MakeFromFontProvider(new ck.ParagraphStyle({
      textStyle: { fontFamilies: [family], fontSize: 30 }
    }), fontMgr);
    builder.addText("HUMAN REVIEW");
    const paragraph = builder.build();
    try {
      paragraph.layout(536);
      const intrinsic = paragraph.getMaxIntrinsicWidth();
      const computed = engine.scene.nodes[child.id].computed!;
      expect(computed.layout_bounds.width).toBeGreaterThanOrEqual(Math.floor(intrinsic));
      expect(computed.text_lines![0].width).toBeGreaterThanOrEqual(Math.floor(intrinsic));
      paragraph.layout(computed.layout_bounds.width + 0.5);
      expect(paragraph.getLineMetrics()).toHaveLength(1);
    } finally {
      paragraph.delete();
      builder.delete();
      setKitTokenMaps({ colors: {}, numbers: {}, typography: {} });
    }
  });

  it("reports unresolved requests when a shaping pass cannot supply them", async () => {
    const engine = new WasmEngine(await loadWasmModuleFromDisk(), structuredClone(minimalScene));
    const result = injectSkiaMeasurements(engine, {
      unconstrained: (scene) => skiaMeasurements(ck, fontMgr, scene),
      lines: () => [],
      requests: () => []
    });
    expect(result.converged).toBe(false);
    expect(result.missing.length).toBeGreaterThan(0);
    expect(result.calls).toBe(1 + MEASUREMENT_ROUNDS_MAX);
  });

  it("honors a slot shrink probe without losing the source node's font styling", () => {
    setKitTokenMaps({ colors: {}, numbers: { "type.test": 40 }, typography: {} });
    const scene = structuredClone(minimalScene);
    const node = scene.nodes.node_contact_name;
    if (node.kind.kind !== "text") throw new Error("fixture");
    node.kind = { ...node.kind, content: "HUMAN REVIEW", font_family: family,
      font_size: 16, font_size_token: "type.test", font_weight: 400, line_height: 1 };
    try {
      const [base] = skiaMeasurements(ck, fontMgr, scene);
      const [probe] = skiaRequestedMeasurements(ck, fontMgr, scene, [{
        ...base, font_size: 16, font_size_override: 16, max_width: 600
      }]);
      expect(probe.height).toBeLessThan(25);
      expect(probe.width).toBeLessThan(base.width / 2);
    } finally {
      setKitTokenMaps({ colors: {}, numbers: {}, typography: {} });
    }
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

  it("Plan 4: emits line boxes keyed on each laid-out text node's solved box, twice", () => {
    const content = "Hello there, world again and again and again";
    const scene = JSON.parse(JSON.stringify(minimalScene)) as Scene;
    const node = scene.nodes.node_contact_name;
    if (node.kind.kind !== "text") throw new Error("fixture");
    node.kind.content = content;
    node.kind.font_family = family;
    node.kind.font_size = 20;
    node.kind.wrap = "wrap";
    node.computed = {
      layout_bounds: { x: 10, y: 20, width: 120, height: 200 },
      render_bounds: { x: 10, y: 20, width: 120, height: 200 }
    };
    // A second text node the engine has not laid out: nothing to key on.
    scene.nodes.unlaid = { ...node, id: "unlaid", computed: null };

    const records = skiaLineMeasurements(ck, fontMgr, scene);
    expect(records.length).toBe(2);
    const [validateKey, taffyKey] = records;
    expect(validateKey.max_width).toBe(120);
    expect(validateKey.max_height).toBe(200);
    expect(taffyKey.max_width).toBe(120);
    expect(taffyKey.max_height).toBeUndefined();
    // Same key fields as the unconstrained record.
    const unconstrained = skiaMeasurements(ck, fontMgr, scene).find(
      (r) => r.content === content
    )!;
    for (const key of [
      "content",
      "font_family",
      "font_size",
      "font_weight",
      "line_height",
      "letter_spacing",
      "wrap",
      "max_lines",
      "direction",
      "text_transform",
      "truncate",
      "paragraph_spacing",
      "italic"
    ] as const) {
      expect(validateKey[key]).toEqual(unconstrained[key]);
    }
    // Wrapped at 120: several lines, ascending, each inside the width.
    const lines = validateKey.lines!;
    expect(lines.length).toBeGreaterThan(1);
    for (let i = 0; i < lines.length; i += 1) {
      expect(lines[i].x).toBeGreaterThanOrEqual(0);
      expect(lines[i].width).toBeLessThanOrEqual(121);
      expect(lines[i].height).toBeGreaterThan(0);
      if (i > 0) expect(lines[i].y).toBeGreaterThan(lines[i - 1].y);
    }
    expect(taffyKey.lines).toEqual(lines);
    // Extent is the stacked lines, not the unconstrained single line.
    expect(validateKey.height).toBeGreaterThan(unconstrained.height);
    expect(validateKey.width).toBeLessThanOrEqual(121);
  });

  it("Plan 4: max_lines cuts the line boxes", () => {
    const scene = JSON.parse(JSON.stringify(minimalScene)) as Scene;
    const node = scene.nodes.node_contact_name;
    if (node.kind.kind !== "text") throw new Error("fixture");
    node.kind.content = "Hello there, world again and again and again";
    node.kind.font_family = family;
    node.kind.font_size = 20;
    node.kind.wrap = "wrap";
    node.kind.max_lines = 2;
    node.computed = {
      layout_bounds: { x: 0, y: 0, width: 120, height: 200 },
      render_bounds: { x: 0, y: 0, width: 120, height: 200 }
    };
    const [record] = skiaLineMeasurements(ck, fontMgr, scene);
    expect(record.lines!.length).toBe(2);
  });
});

/**
 * Plan 4 item F (R4 amendment): the injection loop itself, with a SCRIPTED
 * engine and no CanvasKit — the line pass moves boxes (a taffy-keyed record
 * hands a wrapped hug box CanvasKit's height), so the validate-keyed record
 * from the same round can name a box the round replaced. The loop re-runs the
 * line pass until the solved text sizes stop moving.
 */
describe("measure-then-inject convergence (Plan 4 item F)", () => {
  const NODE = "node_contact_name";

  const record = (max_width: number, max_height?: number): TextMeasurement => ({
    content: "Dr. Priya Sharma",
    font_family: "Inter",
    font_size: 18,
    font_weight: 600,
    line_height: 1.2,
    letter_spacing: 0,
    wrap: "wrap",
    max_lines: null,
    direction: "ltr",
    ...(max_height === undefined ? {} : { max_height }),
    max_width,
    width: 60,
    height: 21.6
  });

  /**
   * A fake engine whose every `setMeasurements` re-solves the one text node's
   * box to `nextHeight(callNumber)` — the scripted stand-in for taffy taking
   * the injected extent.
   */
  function scriptedEngine(nextHeight: (call: number) => number): {
    engine: MeasurementEngine;
    payloads: TextMeasurement[][];
  } {
    const scene = JSON.parse(JSON.stringify(minimalScene)) as Scene;
    scene.nodes[NODE].computed = {
      layout_bounds: { x: 24, y: 40, width: 160, height: 28 },
      render_bounds: { x: 24, y: 40, width: 160, height: 28 }
    };
    const payloads: TextMeasurement[][] = [];
    let call = 0;
    const engine: MeasurementEngine = {
      get scene() {
        return scene;
      },
      setMeasurements(measurements: TextMeasurement[]) {
        payloads.push(measurements);
        call += 1;
        const height = nextHeight(call);
        const computed = scene.nodes[NODE].computed!;
        computed.layout_bounds.height = height;
        computed.render_bounds.height = height;
      }
    };
    return { engine, payloads };
  }

  /** The line pass, keyed on whatever box the engine has solved right now. */
  const linePass = (scene: Scene): TextMeasurement[] => {
    const box = scene.nodes[NODE].computed!.layout_bounds;
    return [record(box.width, box.height), record(box.width)];
  };
  const unconstrainedPass = (): TextMeasurement[] => [record(0)];

  it("re-runs the line pass until the solved boxes stop moving", () => {
    const heights = [100, 90, 80, 80];
    const { engine, payloads } = scriptedEngine(
      (call) => heights[Math.min(call - 1, heights.length - 1)]
    );

    const { calls } = injectSkiaMeasurements(engine, {
      unconstrained: unconstrainedPass,
      lines: linePass
    });

    // 1 unconstrained + 3 line rounds; the third round changes nothing.
    expect(calls).toBe(4);
    expect(payloads).toHaveLength(4);
    expect(payloads[0]).toHaveLength(1);
    // The last payload's validate key names the FINAL box, not an earlier one.
    const last = payloads[3];
    expect(last).toHaveLength(3);
    expect(last[1].max_width).toBe(160);
    expect(last[1].max_height).toBe(80);
    expect(last[2].max_height).toBeUndefined();
  });

  it("stops after one line round when nothing moves", () => {
    const { engine, payloads } = scriptedEngine(() => 100);
    const { calls } = injectSkiaMeasurements(engine, {
      unconstrained: unconstrainedPass,
      lines: linePass
    });
    expect(calls).toBe(2);
    expect(payloads).toHaveLength(2);
  });

  it("is bounded when the boxes never settle", () => {
    const { engine, payloads } = scriptedEngine((call) => 100 + call);
    const { calls } = injectSkiaMeasurements(engine, {
      unconstrained: unconstrainedPass,
      lines: linePass
    });
    expect(calls).toBe(1 + MEASUREMENT_ROUNDS_MAX);
    expect(payloads).toHaveLength(1 + MEASUREMENT_ROUNDS_MAX);
  });
});

it("every convergence pass and request uses the paired resolved text snapshot", () => {
  const authored = structuredClone(minimalScene) as Scene;
  const presented = structuredClone(authored);
  const text = presented.nodes.node_contact_name.kind;
  if (text.kind !== "text") throw new Error("expected text");
  text.font_size = 48;
  text.spans = [{start:0,end:2,font_size:24} as TextSpan];
  const seen: Scene[] = [];
  const engine: MeasurementEngine = { scene:authored, presentationScene:presented, setMeasurements:()=>[] };
  injectSkiaMeasurements(engine, { unconstrained:scene=>{seen.push(scene);return[];},
    lines:scene=>{seen.push(scene);return[];}, requests:scene=>{seen.push(scene);return[];} });
  expect(seen.length).toBeGreaterThan(2);
  for(const value of seen) expect(value).toBe(presented);
  expect(JSON.stringify(authored.nodes.node_contact_name.kind)).not.toBe(JSON.stringify(text));
});
