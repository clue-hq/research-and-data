// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "../../__tests__/vitest-shim";

/**
 * Ported at AD1.6. Upstream this file opens with vitest module mocking:
 *
 *   import { collectKitFontFaceRefs, ... } from "../kitFonts";
 *   import { registerKitFontFaces } from "../canvaskit/loadCanvasKit";
 *   vi.mock("../canvaskit/loadCanvasKit", async (importOriginal) => ({
 *     ...(await importOriginal<...>()),
 *     registerKitFontFaces: vi.fn(() => true)
 *   }));
 *
 * `tsx --test` transpiles to CommonJS, where esbuild's interop makes every
 * export a non-configurable getter — so the shim mocks by swapping the whole
 * `require.cache` entry before the module under test is first required (see
 * `vi.mock`'s doc). That forces exactly two mechanical adaptations, and
 * nothing else in this file changed:
 *   1. the mocked module is named by `require.resolve(...)`, and the stub is
 *      read off `vi.mock`'s return value instead of a hoisted import;
 *   2. the module under test is pulled in with a body-level `require(...)`
 *      (a hoisted `import` would capture the real exports first).
 * The stubbed surface is identical: the real `fontFaceDescriptors` /
 * `effectiveFaceMeta` are kept, only `registerKitFontFaces` is replaced.
 */

// Keep the real `fontFaceDescriptors` (pure helper); only the provider
// registration is stubbed so the DOM leg can be exercised in isolation.
const loadCanvasKitMock = vi.mock(
  require.resolve("../canvaskit/loadCanvasKit"),
  (original) => ({ ...original, registerKitFontFaces: vi.fn(() => true) })
);
const registerKitFontFaces = loadCanvasKitMock.registerKitFontFaces;
const {
  collectKitFontFaceRefs,
  collectKitFontFamilyRefs,
  loadKitFontFaces,
  resetKitDomFontsForTests,
} = require("../kitFonts") as typeof import("../kitFonts");

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
    vi.mocked(registerKitFontFaces).mockImplementation(() => true);
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

  it("surfaces CanvasKit registration failures instead of rejecting silently", async () => {
    vi.mocked(registerKitFontFaces).mockImplementation(() => {
      throw new Error("invalid font bytes");
    });
    const bytes = new ArrayBuffer(8);
    const fetchImpl = vi.fn(
      async () =>
        ({ ok: true, arrayBuffer: async () => bytes }) as unknown as Response
    ) as unknown as typeof fetch;
    const diagnostics: unknown[] = [];

    expect(
      await loadKitFontFaces(
        {
          apiBaseUrl: "http://api.test",
          fetchImpl,
          onFaceDiagnostic: (diagnostic) => diagnostics.push(diagnostic),
        },
        KIT
      )
    ).toBe(false);
    expect(diagnostics).toHaveLength(2);
    expect((diagnostics[0] as { message: string }).message).toContain(
      "CanvasKit registration failed: invalid font bytes"
    );
  });

  it("resolves false without touching the provider when the kit has no stored faces", async () => {
    const fetchImpl = vi.fn() as unknown as typeof fetch;
    expect(
      await loadKitFontFaces({ apiBaseUrl: "http://api.test", fetchImpl }, { tokens: {} } as never)
    ).toBe(false);
    expect(fetchImpl).not.toHaveBeenCalled();
    expect(vi.mocked(registerKitFontFaces)).not.toHaveBeenCalled();
  });

  it("states the deterministic Inter fallback when a pinned kit declares a family with zero faces", async () => {
    const sohneKit = {
      tokens: {
        typography: {
          headline: {
            value: {
              default: { kind: "style", font_family: "sohne-var" },
            },
          },
        },
      },
      assets: {
        fonts: {
          primary: { family: "sohne-var", faces: [] },
        },
      },
    } as never;
    const fetchImpl = vi.fn() as unknown as typeof fetch;
    const diagnostics: unknown[] = [];

    expect(collectKitFontFamilyRefs(sohneKit)).toEqual([
      { family: "sohne-var", assetIds: [] },
    ]);
    const registered = await loadKitFontFaces(
      {
        apiBaseUrl: "http://api.test",
        fetchImpl,
        onFaceDiagnostic: (diagnostic) => diagnostics.push(diagnostic),
      },
      sohneKit
    );

    expect(registered).toBe(false);
    expect(fetchImpl).not.toHaveBeenCalled();
    expect(diagnostics).toHaveLength(1);
    expect(diagnostics[0]).toEqual(
      expect.objectContaining({
        severity: "warning",
        code: "EDITOR_KIT_FONT_FAMILY_UNAVAILABLE",
        subject: { kind: "document" },
      })
    );
    const diagnostic = diagnostics[0] as { message: string; hint: string };
    expect(diagnostic.message).toContain("sohne-var");
    expect(diagnostic.message).toContain("deterministic Inter fallback");
    expect(diagnostic.hint).toContain("licensed TTF/OTF");
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
    // A kit face without a declared weight (and unparseable bytes in this
    // fixture) registers at the explicit 400 default — the same effective
    // weight the browser would assume, but deterministic and identical to
    // the CanvasKit leg's face registry.
    expect(result.added).toEqual([
      { family: "Aeonik", bytes: expect.any(ArrayBuffer), descriptors: { style: "normal", weight: "400" } }
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

it("does not register a font download that completes after its context became stale", async () => {
  const before = vi.mocked(registerKitFontFaces).mock.calls.length;
  const completions: Array<(response:Response)=>void> = [];
  let current = true;
  const result = loadKitFontFaces({ apiBaseUrl:"http://localhost:8002", isCurrent:()=>current,
    fetchImpl: (()=>new Promise<Response>(resolve=>completions.push(resolve))) as typeof fetch }, KIT);
  expect(completions.length).toBe(2);
  current=false;
  for(const resolve of completions) resolve(new Response(new Uint8Array([1,2,3])));
  expect(await result).toBe(false);
  expect(vi.mocked(registerKitFontFaces).mock.calls.length).toBe(before);
});
