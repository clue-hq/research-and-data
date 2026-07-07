// @vitest-environment node
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { gzipSync } from "node:zlib";
import { beforeEach, describe, expect, it } from "vitest";
import type { CanvasKit } from "canvaskit-wasm";
import { loadCanvasKit, registerKitFontFaces, resetCanvasKitForTests } from "../loadCanvasKit";

/**
 * Wave 3 C0: the CanvasKit loader. CanvasKit runs in Node (CPU), so we init
 * it with a Node-correct locateFile injected through the loader's test seam,
 * and verify the singleton, the API surface the renderer needs, graceful
 * degradation, and the bundle budget. The browser path (default dynamic
 * import + /canvaskit/ + font fetch) is the same code with the seams unset.
 */

const CK_BIN = path.resolve(__dirname, "../../../../node_modules/canvaskit-wasm/bin");
const CK_WASM = path.join(CK_BIN, "canvaskit.wasm");
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

  it("registers the Inter font under its alias when the fetch succeeds", async () => {
    const init = await nodeInit();
    const fontPath = path.resolve(__dirname, "../../../../public/fonts/InterVariable.ttf");
    if (!existsSync(fontPath)) {
      return; // font asset not fetched in this environment; skip silently
    }
    const fontBytes = readFileSync(fontPath);
    const ab = fontBytes.buffer.slice(fontBytes.byteOffset, fontBytes.byteOffset + fontBytes.byteLength);
    const fetchImpl = (async () =>
      ({ ok: true, arrayBuffer: async () => ab }) as unknown as Response) as typeof fetch;
    const bundle = await loadCanvasKit({ init, fetchImpl });
    expect(bundle?.fontProvider).not.toBeNull();

    // The provider resolves "Inter" (the alias) — a paragraph builds and lays out.
    const ck = bundle!.ck;
    const style = new ck.ParagraphStyle({ textStyle: { fontFamilies: ["Inter"], fontSize: 24 } });
    const builder = ck.ParagraphBuilder.MakeFromFontProvider(style, bundle!.fontProvider!);
    builder.addText("Inter");
    const paragraph = builder.build();
    paragraph.layout(1000);
    expect(paragraph.getMaxIntrinsicWidth()).toBeGreaterThan(0);
    paragraph.delete();
    builder.delete();
  });

  it("K3: kit font faces registered before AND after init both shape paragraphs", async () => {
    const init = await nodeInit();
    const fontPath = path.resolve(__dirname, "../../../../public/fonts/InterVariable.ttf");
    if (!existsSync(fontPath)) {
      return; // font asset not fetched in this environment; skip silently
    }
    const fontBytes = readFileSync(fontPath);
    const ab = fontBytes.buffer.slice(fontBytes.byteOffset, fontBytes.byteOffset + fontBytes.byteLength);
    const fetchImpl = (async () =>
      ({ ok: true, arrayBuffer: async () => ab }) as unknown as Response) as typeof fetch;

    // Queued BEFORE the bundle exists: applied when the provider is created.
    // (Registered under a kit family alias — resolution is by family string.)
    expect(
      registerKitFontFaces([{ key: "Aeonik@asset_a", family: "Aeonik", bytes: ab }])
    ).toBe(false);
    const bundle = await loadCanvasKit({ init, fetchImpl });
    expect(bundle?.fontProvider).not.toBeNull();

    const ck = bundle!.ck;
    const layoutWidth = (family: string): number => {
      const style = new ck.ParagraphStyle({ textStyle: { fontFamilies: [family], fontSize: 24 } });
      const builder = ck.ParagraphBuilder.MakeFromFontProvider(style, bundle!.fontProvider!);
      builder.addText("Brand type");
      const paragraph = builder.build();
      paragraph.layout(1000);
      const width = paragraph.getMaxIntrinsicWidth();
      paragraph.delete();
      builder.delete();
      return width;
    };
    expect(layoutWidth("Aeonik")).toBeGreaterThan(0);

    // Registered AFTER init on the live provider → true (caller bumps memos).
    expect(
      registerKitFontFaces([{ key: "Source Sans 3@asset_b", family: "Source Sans 3", bytes: ab }])
    ).toBe(true);
    expect(layoutWidth("Source Sans 3")).toBeGreaterThan(0);

    // Same key again → deduped, no memo churn.
    expect(
      registerKitFontFaces([{ key: "Source Sans 3@asset_b", family: "Source Sans 3", bytes: ab }])
    ).toBe(false);
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
