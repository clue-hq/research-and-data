// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  collectReferencedLibraryFaceRefs,
  fetchFontLibrary,
  loadLibraryFontFaces,
  resetFontLibraryForTests,
  type FontLibrary
} from "../libraryFonts";
import { registerKitFontFaces } from "../canvaskit/loadCanvasKit";

vi.mock("../canvaskit/loadCanvasKit", () => ({
  registerKitFontFaces: vi.fn(() => true)
}));

/** Curated font library: manifest → scene-filtered face refs → fetched bytes
 * → provider registration, lazily by the families the scene references. */

const LIBRARY: FontLibrary = {
  version: 1,
  families: [
    {
      slug: "aeonik",
      family: "Aeonik",
      category: "sans",
      tone: "neutral",
      faces: [
        { weight: 400, style: "normal", asset_id: "asset_regular" },
        { weight: 700, style: "normal", asset_id: "asset_bold" }
      ]
    },
    {
      slug: "canela",
      family: "Canela",
      category: "serif",
      tone: "editorial",
      faces: [{ weight: 400, style: "normal", asset_id: "asset_canela" }]
    },
    // Malformed rows the collector must skip.
    { slug: "empty-name", family: "", faces: [{ weight: 400, asset_id: "asset_ignored" }] } as never,
    { slug: "no-faces", family: "Ghost", faces: [] }
  ]
};

/** A scene that mentions only "Aeonik" (not Canela/Ghost). */
const SCENE = { nodes: { t1: { type: "text", font_family: "Aeonik", text: "hi" } } };

const manifestResponse = (library: FontLibrary) =>
  ({ ok: true, json: async () => library }) as unknown as Response;

describe("libraryFonts — manifest fetch", () => {
  beforeEach(() => {
    resetFontLibraryForTests();
  });

  it("fetches + parses the manifest once, caching the resolved library", async () => {
    const fetchImpl = vi.fn(async () => manifestResponse(LIBRARY)) as unknown as typeof fetch;
    const first = await fetchFontLibrary({ apiBaseUrl: "http://api.test", fetchImpl });
    const second = await fetchFontLibrary({ apiBaseUrl: "http://api.test", fetchImpl });
    expect(first).toBe(second);
    expect(first.families).toHaveLength(4);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(String((vi.mocked(fetchImpl).mock.calls[0] as unknown[])[0])).toContain("/font-library");
  });

  it("negatively caches a non-ok response as an empty library without refetching", async () => {
    const fetchImpl = vi.fn(async () => ({ ok: false }) as Response) as unknown as typeof fetch;
    const first = await fetchFontLibrary({ apiBaseUrl: "http://api.test", fetchImpl });
    const second = await fetchFontLibrary({ apiBaseUrl: "http://api.test", fetchImpl });
    expect(first.families).toEqual([]);
    expect(second).toBe(first);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("negatively caches a thrown fetch (API down) as an empty library", async () => {
    const fetchImpl = vi.fn(async () => {
      throw new Error("ECONNREFUSED");
    }) as unknown as typeof fetch;
    const library = await fetchFontLibrary({ apiBaseUrl: "http://api.test", fetchImpl });
    await fetchFontLibrary({ apiBaseUrl: "http://api.test", fetchImpl });
    expect(library.families).toEqual([]);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });
});

describe("libraryFonts — scene-filtered ref collection", () => {
  it("collects faces only for families whose name appears in the scene JSON", () => {
    const sceneJson = JSON.stringify(SCENE);
    expect(collectReferencedLibraryFaceRefs(LIBRARY, sceneJson)).toEqual([
      { assetId: "asset_regular", family: "Aeonik" },
      { assetId: "asset_bold", family: "Aeonik" }
    ]);
  });

  it("returns nothing when no referenced family appears + skips empty-name/empty-face families", () => {
    const sceneJson = JSON.stringify({ nodes: { t1: { font_family: "Helvetica" } } });
    expect(collectReferencedLibraryFaceRefs(LIBRARY, sceneJson)).toEqual([]);
  });

  it("collects across multiple referenced families", () => {
    const sceneJson = JSON.stringify({ a: "Aeonik", b: "Canela" });
    expect(collectReferencedLibraryFaceRefs(LIBRARY, sceneJson)).toEqual([
      { assetId: "asset_regular", family: "Aeonik" },
      { assetId: "asset_bold", family: "Aeonik" },
      { assetId: "asset_canela", family: "Canela" }
    ]);
  });
});

describe("libraryFonts — canvas leg", () => {
  beforeEach(() => {
    vi.mocked(registerKitFontFaces).mockClear();
    resetFontLibraryForTests();
  });

  it("fetches each referenced face's bytes and registers them under the family", async () => {
    const bytes = new ArrayBuffer(8);
    const fetchImpl = vi.fn(async (input: URL | RequestInfo) => {
      const url = String(input);
      if (url.endsWith("/font-library")) {
        return manifestResponse(LIBRARY);
      }
      if (url.endsWith("/assets/asset_bold/bytes")) {
        return { ok: false } as Response; // one face missing → skipped, not fatal
      }
      return { ok: true, arrayBuffer: async () => bytes } as unknown as Response;
    }) as unknown as typeof fetch;

    const registered = await loadLibraryFontFaces(SCENE, { apiBaseUrl: "http://api.test", fetchImpl });

    expect(registered).toBe(true);
    expect(vi.mocked(registerKitFontFaces)).toHaveBeenCalledWith([
      { key: "Aeonik@asset_regular", family: "Aeonik", bytes }
    ]);
  });

  it("resolves false without fetching bytes when the scene references no library family", async () => {
    const fetchImpl = vi.fn(async (input: URL | RequestInfo) =>
      manifestResponse(LIBRARY)
    ) as unknown as typeof fetch;
    const registered = await loadLibraryFontFaces(
      { nodes: {} },
      { apiBaseUrl: "http://api.test", fetchImpl }
    );
    expect(registered).toBe(false);
    // Only the manifest was fetched — no /assets/*/bytes calls.
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(vi.mocked(registerKitFontFaces)).not.toHaveBeenCalled();
  });

  it("resolves false on an empty library without touching the provider", async () => {
    const fetchImpl = vi.fn(async () => ({ ok: false }) as Response) as unknown as typeof fetch;
    const registered = await loadLibraryFontFaces(SCENE, { apiBaseUrl: "http://api.test", fetchImpl });
    expect(registered).toBe(false);
    expect(vi.mocked(registerKitFontFaces)).not.toHaveBeenCalled();
  });

  it("does not re-fetch bytes for a face already loaded on a prior call", async () => {
    const bytes = new ArrayBuffer(8);
    const byteFetches: string[] = [];
    const fetchImpl = vi.fn(async (input: URL | RequestInfo) => {
      const url = String(input);
      if (url.endsWith("/font-library")) {
        return manifestResponse(LIBRARY);
      }
      byteFetches.push(url);
      return { ok: true, arrayBuffer: async () => bytes } as unknown as Response;
    }) as unknown as typeof fetch;

    const opts = { apiBaseUrl: "http://api.test", fetchImpl };
    const first = await loadLibraryFontFaces(SCENE, opts);
    const second = await loadLibraryFontFaces(SCENE, opts);

    expect(first).toBe(true);
    // Second call: both Aeonik faces already loaded → no new bytes, no register.
    expect(second).toBe(false);
    expect(byteFetches).toEqual([
      "http://api.test/assets/asset_regular/bytes",
      "http://api.test/assets/asset_bold/bytes"
    ]);
    expect(vi.mocked(registerKitFontFaces)).toHaveBeenCalledTimes(1);
  });
});

/** DOM leg: same fetched bytes → document.fonts under the declared family,
 * so DOM-rendered surfaces (Export Preview SVG) stop falling back to serif. */
describe("libraryFonts — DOM leg (document.fonts registration)", () => {
  const fetchOk = () => {
    const bytes = new ArrayBuffer(8);
    return vi.fn(async (input: URL | RequestInfo) => {
      if (String(input).endsWith("/font-library")) {
        return manifestResponse({ version: 1, families: [LIBRARY.families[0]] });
      }
      return { ok: true, arrayBuffer: async () => bytes } as unknown as Response;
    }) as unknown as typeof fetch;
  };

  const withDomFonts = async (fn: () => Promise<void>) => {
    const OriginalFontFace = (globalThis as { FontFace?: unknown }).FontFace;
    const originalDocument = (globalThis as { document?: unknown }).document;
    const added: Array<{ family: string; bytes: ArrayBuffer }> = [];
    const loadCalls = { count: 0 };

    class MockFontFace {
      family: string;
      bytes: ArrayBuffer;
      constructor(family: string, bytes: ArrayBuffer) {
        this.family = family;
        this.bytes = bytes;
      }
      async load() {
        loadCalls.count += 1;
        return this;
      }
    }

    const fontsAdd = vi.fn((face: MockFontFace) => added.push({ family: face.family, bytes: face.bytes }));
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
    resetFontLibraryForTests();
  });

  it("registers fetched faces into document.fonts under the declared family", async () => {
    const result = await withDomFonts(async function () {
      await loadLibraryFontFaces(SCENE, { apiBaseUrl: "http://api.test", fetchImpl: fetchOk() });
    });
    // Aeonik has two faces (regular + bold) → two document.fonts additions.
    expect(result.loadCalls.count).toBe(2);
    expect(result.added).toEqual([
      { family: "Aeonik", bytes: expect.any(ArrayBuffer) },
      { family: "Aeonik", bytes: expect.any(ArrayBuffer) }
    ]);
    expect(result.fontsAdd).toHaveBeenCalledTimes(2);
  });

  it("is a clean no-op where FontFace is undefined (jsdom/node)", async () => {
    const OriginalFontFace = (globalThis as { FontFace?: unknown }).FontFace;
    if (OriginalFontFace !== undefined) {
      delete (globalThis as Record<string, unknown>).FontFace;
    }
    try {
      const registered = await loadLibraryFontFaces(SCENE, {
        apiBaseUrl: "http://api.test",
        fetchImpl: fetchOk()
      });
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
