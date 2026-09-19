// @vitest-environment node
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { gzipSync } from "node:zlib";
import { beforeEach, describe, expect, it } from "../../__tests__/vitest-shim";
import type { CanvasKit, FontWeight } from "canvaskit-wasm";
import {
  boldChangesFace,
  loadCanvasKit,
  registerKitFontFaces,
  resetCanvasKitForTests,
  resolveFontFamilies,
  type CanvasKitBundle
} from "../canvaskit/loadCanvasKit";

/**
 * Wave 3 C0: the CanvasKit loader. CanvasKit runs in Node (CPU), so we init
 * it with a Node-correct locateFile injected through the loader's test seam,
 * and verify the singleton, the API surface the renderer needs, graceful
 * degradation, and the bundle budget. The browser path (default dynamic
 * import + /vendor/canvaskit/ + font fetch) is the same code with the seams unset.
 *
 * The weight-fidelity block is the regression pin for the canvas font-weight
 * defect: CanvasKit's TypefaceFontProvider does NO style matching (first
 * face registered per family wins, whatever fontStyle asks), which made the
 * canvas render single-weight typography while exports carried real weights.
 * The fix routes every request through style-qualified aliases; these tests
 * lay out real paragraphs with the REAL server-parity Inter statics and
 * assert distinct weights now shape distinctly.
 */

const CK_BIN = path.resolve(__dirname, "../../../../../../node_modules/canvaskit-wasm/bin");
const CK_WASM = path.join(CK_BIN, "canvaskit.wasm");
// The committed copy of the repo fonts/ directory — the cross-runtime parity
// contract the server embeds (vendored here as a test fixture, AD1.3).
const REPO_FONTS = path.resolve(__dirname, "./__fixtures__/fonts");
const present = existsSync(CK_WASM);

/** Real CanvasKitInit wired for Node (resolve the wasm next to the package). */
async function nodeInit(): Promise<
  (options: { locateFile: (file: string) => string }) => Promise<CanvasKit>
> {
  const mod = (await import("canvaskit-wasm")) as unknown as {
    default: (options: { locateFile: (file: string) => string }) => Promise<CanvasKit>;
  };
  return (options) =>
    mod.default({ locateFile: (file: string) => path.join(CK_BIN, path.basename(options.locateFile(file))) });
}

function fontArrayBuffer(fileName: string): ArrayBuffer {
  const bytes = readFileSync(path.join(REPO_FONTS, fileName));
  return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
}

/** fetchImpl serving the repo Inter statics by URL basename. */
function staticInterFetch(): typeof fetch {
  return (async (input: RequestInfo | URL) => {
    const url = String(input);
    const file = url.slice(url.lastIndexOf("/") + 1);
    if (!existsSync(path.join(REPO_FONTS, file))) {
      return { ok: false } as unknown as Response;
    }
    const ab = fontArrayBuffer(file);
    return { ok: true, arrayBuffer: async () => ab } as unknown as Response;
  }) as typeof fetch;
}

/** Lay out one line in the resolved family chain; returns its intrinsic width. */
function layoutWidth(
  bundle: CanvasKitBundle,
  family: string,
  weight: number,
  content = "Weight probe 0123"
): number {
  const ck = bundle.ck;
  const style = new ck.ParagraphStyle({
    textStyle: {
      fontFamilies: resolveFontFamilies(family, weight, false),
      fontSize: 32,
      fontStyle: { weight: weight as unknown as FontWeight }
    }
  });
  const builder = ck.ParagraphBuilder.MakeFromFontProvider(style, bundle.fontProvider!);
  builder.addText(content);
  const paragraph = builder.build();
  paragraph.layout(10000);
  const width = paragraph.getMaxIntrinsicWidth();
  paragraph.delete();
  builder.delete();
  return width;
}

describe.skipIf(!present)("CanvasKit loader (Wave 3 C0)", () => {
  beforeEach(() => {
    resetCanvasKitForTests();
  });

  it("initializes CanvasKit and exposes the API the renderer needs", async () => {
    const init = await nodeInit();
    const bundle = await loadCanvasKit({ init });
    expect(bundle).not.toBeNull();
    const ck = bundle!.ck;
    // The draw-path surface, paint stack, dash contour, shadow stack, and text.
    const hasSurfaceFactory =
      typeof ck.MakeRasterDirectSurface === "function" || typeof ck.MakeSurface === "function";
    expect(hasSurfaceFactory).toBe(true);
    expect(ck.Paint).toBeTruthy();
    expect(ck.Path).toBeTruthy();
    expect(typeof ck.ImageFilter.MakeDropShadow).toBe("function");
    expect(ck.ParagraphBuilder).toBeTruthy();
    expect(ck.TypefaceFontProvider).toBeTruthy();
    // No fetchImpl supplied → the font is optional, not fatal.
    expect(bundle!.fontProvider).toBeNull();
  });

  it("caches the module so the wasm instantiates exactly once", async () => {
    const init = await nodeInit();
    const first = await loadCanvasKit({ init });
    const second = await loadCanvasKit({ init });
    expect(first).toBe(second);
    expect(first!.ck).toBe(second!.ck);
  });

  it("registers the Inter statics with weight aliases and shapes paragraphs", async () => {
    const init = await nodeInit();
    const bundle = await loadCanvasKit({ init, fetchImpl: staticInterFetch() });
    expect(bundle?.fontProvider).not.toBeNull();

    // The chain leads with the byte-parsed weight alias of the selected face.
    expect(resolveFontFamilies("Inter", 700, false)).toEqual(["Inter::w700", "Inter"]);
    // Weight snap mirrors the server's CSS3 matching over {400,600,700,800}.
    expect(resolveFontFamilies("Inter", 500, false)[0]).toBe("Inter::w400");
    expect(resolveFontFamilies("Inter", 900, false)[0]).toBe("Inter::w800");
    expect(resolveFontFamilies("Inter", 300, false)[0]).toBe("Inter::w400");

    expect(layoutWidth(bundle!, "Inter", 400)).toBeGreaterThan(0);
  });

  it("weight-fidelity pin: distinct weights select distinct faces (the canvas single-weight bug)", async () => {
    const init = await nodeInit();
    const bundle = await loadCanvasKit({ init, fetchImpl: staticInterFetch() });
    expect(bundle?.fontProvider).not.toBeNull();

    const w400 = layoutWidth(bundle!, "Inter", 400);
    const w700 = layoutWidth(bundle!, "Inter", 700);
    const w800 = layoutWidth(bundle!, "Inter", 800);
    // Before the alias fix all three were pixel-identical (first face wins).
    expect(w700).toBeGreaterThan(w400);
    expect(w800).toBeGreaterThan(w700);
    // Unavailable weights snap exactly like the server (LUMS0104 semantics).
    expect(layoutWidth(bundle!, "Inter", 500)).toBe(w400);
    expect(layoutWidth(bundle!, "Inter", 900)).toBe(w800);
  });

  it("unknown families fall back to Inter at the requested weight (server resolve_family)", async () => {
    const init = await nodeInit();
    const bundle = await loadCanvasKit({ init, fetchImpl: staticInterFetch() });
    expect(bundle?.fontProvider).not.toBeNull();

    expect(resolveFontFamilies("No Such Family", 800, false)).toEqual([
      "No Such Family",
      "Inter::w800",
      "Inter"
    ]);
    const unknownBold = layoutWidth(bundle!, "No Such Family", 800);
    expect(unknownBold).toBe(layoutWidth(bundle!, "Inter", 800));
  });

  it("K3: kit font faces registered before AND after init both shape at their parsed weight", async () => {
    const init = await nodeInit();
    const regular = fontArrayBuffer("Inter-Regular.ttf");
    const extraBold = fontArrayBuffer("Inter-ExtraBold.ttf");

    // Queued BEFORE the bundle exists: applied when the provider is created.
    // No declared weight/style — the OS/2 meta parsed from the bytes drives
    // the aliases (the server parses bytes the same way).
    expect(
      registerKitFontFaces([{ key: "Aeonik@asset_a", family: "Aeonik", bytes: regular }])
    ).toBe(false);
    const bundle = await loadCanvasKit({ init, fetchImpl: staticInterFetch() });
    expect(bundle?.fontProvider).not.toBeNull();
    expect(layoutWidth(bundle!, "Aeonik", 400)).toBeGreaterThan(0);

    // Registered AFTER init on the live provider → true (caller bumps memos).
    expect(
      registerKitFontFaces([{ key: "Aeonik@asset_b", family: "Aeonik", bytes: extraBold }])
    ).toBe(true);
    expect(resolveFontFamilies("Aeonik", 800, false)[0]).toBe("Aeonik::w800");
    // The two-face kit family now shapes weight-distinctly on canvas.
    expect(layoutWidth(bundle!, "Aeonik", 800)).toBeGreaterThan(layoutWidth(bundle!, "Aeonik", 400));

    // Same key again → deduped, no memo churn.
    expect(
      registerKitFontFaces([{ key: "Aeonik@asset_b", family: "Aeonik", bytes: extraBold }])
    ).toBe(false);
  });

  it("measurement leg: skiaMeasurements' paragraph measurer shapes at the requested weight", async () => {
    // The same broken provider also poisoned text MEASUREMENT (wrap/clamp
    // decisions computed at the wrong weight). Pin the measurer directly.
    const { measureParagraph } = await import("../canvaskit/skiaMeasurements");
    const init = await nodeInit();
    const bundle = await loadCanvasKit({ init, fetchImpl: staticInterFetch() });
    expect(bundle?.fontProvider).not.toBeNull();

    const measure = (fontWeight: number) =>
      measureParagraph(bundle!.ck, bundle!.fontProvider!, {
        content: "Measured at weight",
        fontFamily: "Inter",
        fontSize: 32,
        fontWeight,
        lineHeight: 1.2,
        letterSpacing: 0
      });
    expect(measure(800).width).toBeGreaterThan(measure(400).width);
    // Snapped weights measure exactly as the face they snap to.
    expect(measure(500).width).toBe(measure(400).width);
  });

  it("degrades to null when CanvasKit init fails (editor stays on Konva)", async () => {
    const bundle = await loadCanvasKit({ init: () => Promise.reject(new Error("boom")) });
    expect(bundle).toBeNull();
  });

  it("keeps the canvaskit wasm within the C0 bundle budget (<3MB gzip)", () => {
    const gz = gzipSync(readFileSync(CK_WASM)).length;
    expect(gz).toBeLessThan(3 * 1024 * 1024);
  });
});

/**
 * Plan 1 item B (2026-09-04): the toolbar's Bold gate. `registerKitFontFaces`
 * records a family's faces SYNCHRONOUSLY into the registry — no wasm, no
 * provider — so this block runs whether or not the CanvasKit artifact is
 * present, unlike the suite above.
 */
describe("boldChangesFace (Plan 1 item B)", () => {
  beforeEach(() => {
    resetCanvasKitForTests();
  });

  it("is false for a single-face family and true once a heavier face registers", () => {
    const regular = fontArrayBuffer("Inter-Regular.ttf");
    const bold = fontArrayBuffer("Inter-Bold.ttf");
    registerKitFontFaces([{ key: "seasonMix@a", family: "seasonMix", bytes: regular }]);
    expect(boldChangesFace("seasonMix")).toBe(false);
    registerKitFontFaces([{ key: "seasonMix@b", family: "seasonMix", bytes: bold }]);
    expect(boldChangesFace("seasonMix")).toBe(true);
  });

  it("an unregistered family answers for Inter, like hasItalicFace", () => {
    expect(boldChangesFace("Nope")).toBe(false); // nothing registered at all
    registerKitFontFaces([
      { key: "Inter@r", family: "Inter", bytes: fontArrayBuffer("Inter-Regular.ttf") },
      { key: "Inter@b", family: "Inter", bytes: fontArrayBuffer("Inter-Bold.ttf") }
    ]);
    expect(boldChangesFace("Nope")).toBe(true);
  });
});
