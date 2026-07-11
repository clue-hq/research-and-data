// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";
import { collectKitFontFaceRefs, loadKitFontFaces, resetKitDomFontsForTests } from "../kitFonts";
import { registerKitFontFaces } from "../canvaskit/loadCanvasKit";

vi.mock("../canvaskit/loadCanvasKit", async (importOriginal) => ({
  // Keep the real `fontFaceDescriptors` (pure helper); only the provider
  // registration is stubbed so the DOM leg can be exercised in isolation.
  ...(await importOriginal<typeof import("../canvaskit/loadCanvasKit")>()),
  registerKitFontFaces: vi.fn(() => true)
}));

/** K3 canvas leg: kit JSON → face refs → fetched bytes → provider registration. */

const KIT = {
  tokens: {},
  assets: {
    fonts: {
      brand: {
        family: "Aeonik",
        faces: [
          { weight: 400, style: "normal", asset_id: "asset_regular" },
          { weight: 700, style: "normal", asset_id: "asset_bold" },
          { weight: 300, style: "italic", asset_id: null }
        ]
      },
      mono: { family: "", faces: [{ asset_id: "asset_ignored" }] }
    }
  }
} as never;

describe("kitFonts (K3 canvas leg)", () => {
  beforeEach(() => {
    vi.mocked(registerKitFontFaces).mockClear();
  });

  it("collects only faces with stored asset ids, tagged with the group family", () => {
    // A7b: refs carry the kit-declared weight/style for the DOM FontFace descriptors.
    expect(collectKitFontFaceRefs(KIT)).toEqual([
      { assetId: "asset_regular", family: "Aeonik", weight: 400, style: "normal" },
      { assetId: "asset_bold", family: "Aeonik", weight: 700, style: "normal" }
    ]);
    expect(collectKitFontFaceRefs(null)).toEqual([]);
    expect(collectKitFontFaceRefs({ tokens: {} } as never)).toEqual([]);
  });

  it("fetches each face's bytes and registers them under the kit family", async () => {
    const bytes = new ArrayBuffer(8);
    const fetchImpl = vi.fn(async (input: URL | RequestInfo) => {
      const url = String(input);
      if (url.endsWith("/assets/asset_bold/bytes")) {
        return { ok: false } as Response; // one face missing → skipped, not fatal
      }
      return { ok: true, arrayBuffer: async () => bytes } as unknown as Response;
    }) as unknown as typeof fetch;

    const registered = await loadKitFontFaces(
      { apiBaseUrl: "http://api.test", fetchImpl },
      KIT
    );

    expect(registered).toBe(true);
    expect(vi.mocked(registerKitFontFaces)).toHaveBeenCalledWith([
      { key: "Aeonik@asset_regular", family: "Aeonik", bytes, weight: 400, style: "normal" }
    ]);
  });

  it("surfaces a client diagnostic for each face whose bytes fail to load (no longer silent)", async () => {
    const bytes = new ArrayBuffer(8);
    const fetchImpl = vi.fn(async (input: URL | RequestInfo) => {
      const url = String(input);
      if (url.endsWith("/assets/asset_bold/bytes")) {
        return { ok: false, status: 404 } as Response; // fetched, missing
      }
      if (url.endsWith("/assets/asset_regular/bytes")) {
        throw new TypeError("network down"); // threw
      }
      return { ok: true, arrayBuffer: async () => bytes } as unknown as Response;
    }) as unknown as typeof fetch;

    const diagnostics: unknown[] = [];
    await loadKitFontFaces(
      {
        apiBaseUrl: "http://api.test",
        fetchImpl,
        onFaceDiagnostic: (diagnostic) => diagnostics.push(diagnostic)
      },
      KIT
    );

    // Both declared+stored faces failed → one diagnostic each, none swallowed.
    expect(diagnostics).toHaveLength(2);
    expect(diagnostics).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          severity: "warning",
          code: "EDITOR_KIT_FONT_FACE_UNAVAILABLE",
          subject: { kind: "asset", id: "asset_bold" }
        }),
        expect.objectContaining({
          code: "EDITOR_KIT_FONT_FACE_UNAVAILABLE",
          subject: { kind: "asset", id: "asset_regular" }
        })
      ])
    );
  });

  it("reports no face diagnostics when every stored face loads", async () => {
    const bytes = new ArrayBuffer(8);
    const fetchImpl = vi.fn(
      async () => ({ ok: true, arrayBuffer: async () => bytes }) as unknown as Response
    ) as unknown as typeof fetch;
    const diagnostics: unknown[] = [];
    const registered = await loadKitFontFaces(
      {
        apiBaseUrl: "http://api.test",
        fetchImpl,
        onFaceDiagnostic: (diagnostic) => diagnostics.push(diagnostic)
      },
      KIT
    );
    expect(registered).toBe(true);
    expect(diagnostics).toEqual([]);
  });

  it("resolves false without touching the provider when the kit has no stored faces", async () => {
    const fetchImpl = vi.fn() as unknown as typeof fetch;
    expect(
      await loadKitFontFaces({ apiBaseUrl: "http://api.test", fetchImpl }, { tokens: {} } as never)
    ).toBe(false);
    expect(fetchImpl).not.toHaveBeenCalled();
    expect(vi.mocked(registerKitFontFaces)).not.toHaveBeenCalled();
  });
});

/** DOM leg: same fetched bytes → document.fonts under the declared family,
 * so DOM-rendered surfaces (Export Preview SVG) stop falling back to serif. */
describe("kitFonts (DOM leg — document.fonts registration)", () => {
  const SINGLE_KIT = {
    tokens: {},
    assets: { fonts: { brand: { family: "Aeonik", faces: [{ asset_id: "asset_regular" }] } } }
  } as never;

  const fetchOk = () => {
    const bytes = new ArrayBuffer(8);
    return vi.fn(async () => ({ ok: true, arrayBuffer: async () => bytes }) as unknown as Response) as unknown as typeof fetch;
  };

  const withDomFonts = async (fn: () => Promise<void>) => {
    const OriginalFontFace = (globalThis as { FontFace?: unknown }).FontFace;
    const originalDocument = (globalThis as { document?: unknown }).document;
    const added: Array<{ family: string; bytes: ArrayBuffer; descriptors?: unknown }> = [];
    const loadCalls = { count: 0 };

    class MockFontFace {
      family: string;
      bytes: ArrayBuffer;
      descriptors?: unknown;
      constructor(family: string, bytes: ArrayBuffer, descriptors?: unknown) {
        this.family = family;
        this.bytes = bytes;
        this.descriptors = descriptors;
      }
      async load() {
        loadCalls.count += 1;
        return this;
      }
    }

    const fontsAdd = vi.fn((face: MockFontFace) =>
      added.push({ family: face.family, bytes: face.bytes, descriptors: face.descriptors })
    );
    (globalThis as Record<string, unknown>).FontFace = MockFontFace;
    (globalThis as Record<string, unknown>).document = { fonts: { add: fontsAdd } };
    try {
      await fn.call({ added, fontsAdd, loadCalls });
      return { added, fontsAdd, loadCalls };
    } finally {
      if (OriginalFontFace === undefined) {
        delete (globalThis as Record<string, unknown>).FontFace;
      } else {
        (globalThis as Record<string, unknown>).FontFace = OriginalFontFace;
      }
      if (originalDocument === undefined) {
        delete (globalThis as Record<string, unknown>).document;
      } else {
        (globalThis as Record<string, unknown>).document = originalDocument;
      }
    }
  };

  beforeEach(() => {
    vi.mocked(registerKitFontFaces).mockClear();
    resetKitDomFontsForTests();
  });

  it("registers fetched faces into document.fonts under the declared family", async () => {
    const result = await withDomFonts(async function () {
      await loadKitFontFaces({ apiBaseUrl: "http://api.test", fetchImpl: fetchOk() }, SINGLE_KIT);
    });
    expect(result.loadCalls.count).toBe(1);
    // A7b: a kit face without a declared weight yields a style-only descriptor
    // (browser keeps its default weight rather than an invalid "undefined").
    expect(result.added).toEqual([
      { family: "Aeonik", bytes: expect.any(ArrayBuffer), descriptors: { style: "normal" } }
    ]);
    expect(result.fontsAdd).toHaveBeenCalledTimes(1);
  });

  it("passes style:italic descriptors for an italic kit face (A7b D5 collision fix)", async () => {
    const ITALIC_KIT = {
      tokens: {},
      assets: {
        fonts: {
          brand: {
            family: "Newsreader",
            faces: [
              { weight: 400, style: "normal", asset_id: "asset_upright" },
              { weight: 400, style: "italic", asset_id: "asset_italic" }
            ]
          }
        }
      }
    } as never;
    const result = await withDomFonts(async function () {
      await loadKitFontFaces({ apiBaseUrl: "http://api.test", fetchImpl: fetchOk() }, ITALIC_KIT);
    });
    expect(result.added).toEqual([
      { family: "Newsreader", bytes: expect.any(ArrayBuffer), descriptors: { style: "normal", weight: "400" } },
      { family: "Newsreader", bytes: expect.any(ArrayBuffer), descriptors: { style: "italic", weight: "400" } }
    ]);
  });

  it("is idempotent — a second load of the same face adds nothing new", async () => {
    const result = await withDomFonts(async function () {
      await loadKitFontFaces({ apiBaseUrl: "http://api.test", fetchImpl: fetchOk() }, SINGLE_KIT);
      await loadKitFontFaces({ apiBaseUrl: "http://api.test", fetchImpl: fetchOk() }, SINGLE_KIT);
    });
    expect(result.fontsAdd).toHaveBeenCalledTimes(1);
    expect(result.added).toHaveLength(1);
  });

  it("is a clean no-op where FontFace is undefined (jsdom/node)", async () => {
    const OriginalFontFace = (globalThis as { FontFace?: unknown }).FontFace;
    if (OriginalFontFace !== undefined) {
      delete (globalThis as Record<string, unknown>).FontFace;
    }
    try {
      const registered = await loadKitFontFaces(
        { apiBaseUrl: "http://api.test", fetchImpl: fetchOk() },
        SINGLE_KIT
      );
      // The canvas leg still runs; only the DOM leg is skipped.
      expect(registered).toBe(true);
      expect(vi.mocked(registerKitFontFaces)).toHaveBeenCalledTimes(1);
    } finally {
      if (OriginalFontFace !== undefined) {
        (globalThis as Record<string, unknown>).FontFace = OriginalFontFace;
      }
    }
  });
});
