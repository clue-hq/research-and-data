// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "../../__tests__/vitest-shim";
import type { FontLibrary } from "../libraryFonts";

/**
 * Ported at AD1.6. Upstream this file opens with vitest module mocking:
 *
 *   import { collectKitFontFaceRefs, ... } from "../libraryFonts";
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
  collectReferencedLibraryFaceRefs,
  fetchFontLibrary,
  loadLibraryFontFaces,
  resetFontLibraryForTests
} = require("../libraryFonts") as typeof import("../libraryFonts");

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
    const diagnostics: unknown[] = [];
    const fetchImpl = vi.fn(async () =>
      ({ ok: false, status: 503 }) as Response
    ) as unknown as typeof fetch;
    const first = await fetchFontLibrary({ apiBaseUrl: "http://api.test", fetchImpl });
    const second = await fetchFontLibrary({
      apiBaseUrl: "http://api.test",
      fetchImpl,
      onFaceDiagnostic: (diagnostic) => diagnostics.push(diagnostic),
    });
    expect(first.families).toEqual([]);
    expect(second).toBe(first);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(diagnostics).toEqual([
      expect.objectContaining({
        code: "EDITOR_FONT_LIBRARY_UNAVAILABLE",
        message: expect.stringContaining("HTTP 503"),
      }),
    ]);
  });

  it("negatively caches a thrown fetch (API down) as an empty library", async () => {
    const diagnostics: unknown[] = [];
    const fetchImpl = vi.fn(async () => {
      throw new Error("ECONNREFUSED");
    }) as unknown as typeof fetch;
    const library = await fetchFontLibrary({
      apiBaseUrl: "http://api.test",
      fetchImpl,
      onFaceDiagnostic: (diagnostic) => diagnostics.push(diagnostic),
    });
    await fetchFontLibrary({ apiBaseUrl: "http://api.test", fetchImpl });
    expect(library.families).toEqual([]);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(diagnostics).toHaveLength(1);
    expect((diagnostics[0] as { message: string }).message).toContain(
      "ECONNREFUSED"
    );
  });
});

describe("libraryFonts — scene-filtered ref collection", () => {
  it("collects faces only for families whose name appears in the scene JSON", () => {
    const sceneJson = JSON.stringify(SCENE);
    // A7b: refs now carry the manifest weight/style for the DOM FontFace descriptors.
    expect(collectReferencedLibraryFaceRefs(LIBRARY, sceneJson)).toEqual([
      { assetId: "asset_regular", family: "Aeonik", weight: 400, style: "normal" },
      { assetId: "asset_bold", family: "Aeonik", weight: 700, style: "normal" }
    ]);
  });

  it("returns nothing when no referenced family appears + skips empty-name/empty-face families", () => {
    const sceneJson = JSON.stringify({ nodes: { t1: { font_family: "Helvetica" } } });
    expect(collectReferencedLibraryFaceRefs(LIBRARY, sceneJson)).toEqual([]);
  });

  it("collects across multiple referenced families", () => {
    const sceneJson = JSON.stringify({ a: "Aeonik", b: "Canela" });
    expect(collectReferencedLibraryFaceRefs(LIBRARY, sceneJson)).toEqual([
      { assetId: "asset_regular", family: "Aeonik", weight: 400, style: "normal" },
      { assetId: "asset_bold", family: "Aeonik", weight: 700, style: "normal" },
      { assetId: "asset_canela", family: "Canela", weight: 400, style: "normal" }
    ]);
  });
});

describe("libraryFonts — canvas leg", () => {
  beforeEach(() => {
    vi.mocked(registerKitFontFaces).mockClear();
    vi.mocked(registerKitFontFaces).mockImplementation(() => true);
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
    // A7b: the fetched face carries weight/style (the CanvasKit leg ignores
    // them; the DOM leg turns them into FontFace descriptors).
    expect(vi.mocked(registerKitFontFaces)).toHaveBeenCalledWith([
      { key: "Aeonik@asset_regular", family: "Aeonik", bytes, weight: 400, style: "normal" }
    ]);
  });

  it("surfaces referenced face failures instead of silently keeping the fallback", async () => {
    const diagnostics: unknown[] = [];
    const fetchImpl = vi.fn(async (input: URL | RequestInfo) => {
      if (String(input).endsWith("/font-library")) {
        return manifestResponse({
          version: 1,
          families: [
            {
              slug: "aeonik",
              family: "Aeonik",
              faces: [{ asset_id: "asset_missing", weight: 400 }],
            },
          ],
        });
      }
      return { ok: false, status: 404 } as Response;
    }) as unknown as typeof fetch;

    const registered = await loadLibraryFontFaces(SCENE, {
      apiBaseUrl: "http://api.test",
      fetchImpl,
      onFaceDiagnostic: (diagnostic) => diagnostics.push(diagnostic),
    });

    expect(registered).toBe(false);
    expect(diagnostics).toHaveLength(1);
    expect(diagnostics[0]).toEqual(
      expect.objectContaining({
        code: "EDITOR_LIBRARY_FONT_FACE_UNAVAILABLE",
        subject: { kind: "asset", id: "asset_missing" },
      })
    );
    expect((diagnostics[0] as { message: string }).message).toContain(
      "deterministic Inter fallback"
    );
  });

  it("surfaces CanvasKit registration failures instead of rejecting silently", async () => {
    vi.mocked(registerKitFontFaces).mockImplementation(() => {
      throw new Error("invalid font bytes");
    });
    const bytes = new ArrayBuffer(8);
    const diagnostics: unknown[] = [];
    const fetchImpl = vi.fn(async (input: URL | RequestInfo) =>
      String(input).endsWith("/font-library")
        ? manifestResponse({ version: 1, families: [LIBRARY.families[1]] })
        : ({ ok: true, arrayBuffer: async () => bytes } as unknown as Response)
    ) as unknown as typeof fetch;

    expect(
      await loadLibraryFontFaces(
        { nodes: { headline: { font_family: "Canela" } } },
        {
          apiBaseUrl: "http://api.test",
          fetchImpl,
          onFaceDiagnostic: (diagnostic) => diagnostics.push(diagnostic),
        }
      )
    ).toBe(false);
    expect(diagnostics).toHaveLength(1);
    expect(diagnostics[0]).toEqual(
      expect.objectContaining({
        code: "EDITOR_LIBRARY_FONT_FACE_UNAVAILABLE",
        subject: { kind: "asset", id: "asset_canela" },
      })
    );
    expect((diagnostics[0] as { message: string }).message).toContain(
      "CanvasKit registration failed: invalid font bytes"
    );
  });

  it("re-reports a session-permanent registration failure on every later run", async () => {
    vi.mocked(registerKitFontFaces).mockImplementation(() => {
      throw new Error("invalid font bytes");
    });
    const bytes = new ArrayBuffer(8);
    const fetchImpl = vi.fn(async (input: URL | RequestInfo) =>
      String(input).endsWith("/font-library")
        ? manifestResponse({ version: 1, families: [LIBRARY.families[1]] })
        : ({ ok: true, arrayBuffer: async () => bytes } as unknown as Response)
    ) as unknown as typeof fetch;
    const scene = { nodes: { headline: { font_family: "Canela" } } };
    await loadLibraryFontFaces(scene, {
      apiBaseUrl: "http://api.test",
      fetchImpl,
      onFaceDiagnostic: () => undefined,
    });

    // The face is marked loaded, so a later run (the caller's effect re-runs
    // on every scene change and REPLACES its diagnostic state) takes the
    // nothing-new-to-fetch early return — the degradation diagnostic must
    // still be re-emitted or the banner clears while the fallback persists.
    const diagnostics: unknown[] = [];
    expect(
      await loadLibraryFontFaces(scene, {
        apiBaseUrl: "http://api.test",
        fetchImpl,
        onFaceDiagnostic: (diagnostic) => diagnostics.push(diagnostic),
      })
    ).toBe(false);
    expect(diagnostics).toHaveLength(1);
    expect(diagnostics[0]).toEqual(
      expect.objectContaining({
        code: "EDITOR_LIBRARY_FONT_FACE_UNAVAILABLE",
        subject: { kind: "asset", id: "asset_canela" },
      })
    );
  });

  it("resolves false without fetching bytes when the scene references no library family", async () => {
    const fetchImpl = vi.fn(async () =>
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
    resetFontLibraryForTests();
  });

  it("registers fetched faces into document.fonts under the declared family", async () => {
    const result = await withDomFonts(async function () {
      await loadLibraryFontFaces(SCENE, { apiBaseUrl: "http://api.test", fetchImpl: fetchOk() });
    });
    // Aeonik has two faces (regular + bold) → two document.fonts additions.
    // A7b: each carries its weight/style descriptors (the D5 collision fix).
    expect(result.loadCalls.count).toBe(2);
    expect(result.added).toEqual([
      { family: "Aeonik", bytes: expect.any(ArrayBuffer), descriptors: { style: "normal", weight: "400" } },
      { family: "Aeonik", bytes: expect.any(ArrayBuffer), descriptors: { style: "normal", weight: "700" } }
    ]);
    expect(result.fontsAdd).toHaveBeenCalledTimes(2);
  });

  it("registers an italic face with style:italic descriptors (A7b D5 collision fix)", async () => {
    const italicLibrary: FontLibrary = {
      version: 1,
      families: [
        {
          slug: "newsreader",
          family: "Newsreader",
          faces: [
            { weight: 400, style: "normal", asset_id: "asset_upright" },
            { weight: 400, style: "italic", asset_id: "asset_italic" }
          ]
        }
      ]
    };
    const bytes = new ArrayBuffer(8);
    const fetchImpl = vi.fn(async (input: URL | RequestInfo) => {
      if (String(input).endsWith("/font-library")) {
        return manifestResponse(italicLibrary);
      }
      return { ok: true, arrayBuffer: async () => bytes } as unknown as Response;
    }) as unknown as typeof fetch;
    const scene = { nodes: { t1: { font_family: "Newsreader" } } };

    const result = await withDomFonts(async function () {
      await loadLibraryFontFaces(scene, { apiBaseUrl: "http://api.test", fetchImpl });
    });
    // The upright and italic faces of ONE family register as distinct DOM faces
    // — no collision at (family, normal, 400).
    expect(result.added).toEqual([
      { family: "Newsreader", bytes: expect.any(ArrayBuffer), descriptors: { style: "normal", weight: "400" } },
      { family: "Newsreader", bytes: expect.any(ArrayBuffer), descriptors: { style: "italic", weight: "400" } }
    ]);
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

it("does not install stale library bytes or suppress a later current retry", async () => {
  resetFontLibraryForTests();
  const before = vi.mocked(registerKitFontFaces).mock.calls.length;
  let current=true;
  const fetchImpl = (async (url:unknown)=>String(url).endsWith("/font-library")
    ? new Response(JSON.stringify(LIBRARY), {headers:{"content-type":"application/json"}})
    : { ok:true, arrayBuffer:async()=>{current=false;return new ArrayBuffer(4);} }) as typeof fetch;
  const result = await loadLibraryFontFaces({font_family:"Aeonik"}, {
    apiBaseUrl:"http://localhost:8002",fetchImpl,isCurrent:()=>current });
  expect(result).toBe(false);
  expect(vi.mocked(registerKitFontFaces).mock.calls.length).toBe(before);
  current=true;
  const freshFetch = (async()=>new Response(new Uint8Array([1,2,3]))) as typeof fetch;
  expect(await loadLibraryFontFaces({font_family:"Aeonik"}, {apiBaseUrl:"http://localhost:8002",fetchImpl:freshFetch,isCurrent:()=>current})).toBe(true);
});
