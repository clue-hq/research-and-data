// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";
import { collectKitFontFaceRefs, loadKitFontFaces } from "../kitFonts";
import { registerKitFontFaces } from "../canvaskit/loadCanvasKit";

vi.mock("../canvaskit/loadCanvasKit", () => ({
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
    expect(collectKitFontFaceRefs(KIT)).toEqual([
      { assetId: "asset_regular", family: "Aeonik" },
      { assetId: "asset_bold", family: "Aeonik" }
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
      { key: "Aeonik@asset_regular", family: "Aeonik", bytes }
    ]);
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
