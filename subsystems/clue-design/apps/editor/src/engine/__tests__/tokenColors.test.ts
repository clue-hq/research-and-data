import { describe, expect, it } from "vitest";
import {
  buildTokenColorMap,
  PLATFORM_DEFAULT_BRAND_KIT_ID,
  resolveTokenColor,
  type BrandKitDetailPayload
} from "../tokenColors";

/**
 * Realistic fixture: the platform default kit's semantic color tokens as
 * `ensure_platform_color_tokens` (`crates/lumen-core/src/brand.rs`) writes
 * them at load time — hex `{value:{default:{kind:"hex",value}}}` shape, the
 * same three tokens the 4d bug report used (surface.page/card/inverse all
 * painting one cream). Real values: surface.page=#FFFFFF, surface.card=
 * #FFFFFF, surface.inverse=#0F172A.
 */
const platformDefaultKit: BrandKitDetailPayload = {
  tokens: {
    colors: {
      "surface.page": {
        value: { default: { kind: "hex", value: "#FFFFFF" } }
      },
      "surface.card": {
        value: { default: { kind: "hex", value: "#FFFFFF" } }
      },
      "surface.inverse": {
        value: { default: { kind: "hex", value: "#0F172A" } }
      },
      "surface.brand": {
        value: { default: { kind: "hex", value: "#155E75" } }
      },
      "text.inverse": {
        value: { default: { kind: "hex", value: "#FFFFFF" } }
      }
    },
    aliases: {
      "brand.primary": { token: "surface.brand" },
      "color.surface": { token: "surface.brand" }
    }
  }
};

describe("buildTokenColorMap", () => {
  it("resolves platform-default surface tokens to their real, distinct hex values", () => {
    const map = buildTokenColorMap(platformDefaultKit);

    expect(map["surface.page"]).toBe("#FFFFFF");
    expect(map["surface.card"]).toBe("#FFFFFF");
    expect(map["surface.inverse"]).toBe("#0F172A");
    // surface.inverse must be the dark one among the three.
    expect(map["surface.inverse"]).not.toBe(map["surface.page"]);
    expect(map["surface.inverse"]).not.toBe(map["surface.card"]);
  });

  it("resolves an alias chain within tokens.colors (kind: alias)", () => {
    const kit: BrandKitDetailPayload = {
      tokens: {
        colors: {
          "palette.neutral.50": {
            value: { default: { kind: "hex", value: "#F8FAFC" } }
          },
          "surface.page": {
            value: { default: { kind: "alias", token: "palette.neutral.50" } }
          }
        }
      }
    };

    const map = buildTokenColorMap(kit);
    expect(map["surface.page"]).toBe("#F8FAFC");
  });

  it("resolves a multi-hop alias chain", () => {
    const kit: BrandKitDetailPayload = {
      tokens: {
        colors: {
          "palette.neutral.950": {
            value: { default: { kind: "hex", value: "#020617" } }
          },
          "surface.inverse": {
            value: { default: { kind: "alias", token: "palette.neutral.950" } }
          },
          "brand.dark": {
            value: { default: { kind: "alias", token: "surface.inverse" } }
          }
        }
      }
    };

    const map = buildTokenColorMap(kit);
    expect(map["brand.dark"]).toBe("#020617");
  });

  it("drops a cyclic alias chain instead of looping forever", () => {
    const kit: BrandKitDetailPayload = {
      tokens: {
        colors: {
          "a.token": { value: { default: { kind: "alias", token: "b.token" } } },
          "b.token": { value: { default: { kind: "alias", token: "a.token" } } }
        }
      }
    };

    const map = buildTokenColorMap(kit);
    expect(map["a.token"]).toBeUndefined();
    expect(map["b.token"]).toBeUndefined();
  });

  it("passes oklch tokens through as CSS oklch()", () => {
    const kit: BrandKitDetailPayload = {
      tokens: {
        colors: {
          "palette.primary.500": {
            value: { default: { kind: "oklch", l: 0.58, c: 0.14, h: 149.6, alpha: 1 } }
          }
        }
      }
    };

    const map = buildTokenColorMap(kit);
    expect(map["palette.primary.500"]).toBe("oklch(0.58 0.14 149.6 / 1)");
  });

  it("resolves the top-level tokens.aliases map to the aliased color", () => {
    const map = buildTokenColorMap(platformDefaultKit);
    expect(map["brand.primary"]).toBe("#155E75");
    expect(map["color.surface"]).toBe("#155E75");
  });

  it("returns an empty map for a null/undefined kit", () => {
    expect(buildTokenColorMap(null)).toEqual({});
    expect(buildTokenColorMap(undefined)).toEqual({});
  });

  it("drops entries with malformed or unknown value kinds", () => {
    const kit: BrandKitDetailPayload = {
      tokens: {
        colors: {
          "bad.token": { value: { default: { kind: "unknown_kind" } } },
          "missing.value": {},
          "bad.hex": { value: { default: { kind: "hex" } } }
        }
      }
    };

    const map = buildTokenColorMap(kit);
    expect(map["bad.token"]).toBeUndefined();
    expect(map["missing.value"]).toBeUndefined();
    expect(map["bad.hex"]).toBeUndefined();
  });
});

describe("resolveTokenColor", () => {
  it("looks up a bare token name", () => {
    const map = buildTokenColorMap(platformDefaultKit);
    expect(resolveTokenColor(map, "surface.page")).toBe("#FFFFFF");
  });

  it("strips a leading $ before lookup", () => {
    const map = buildTokenColorMap(platformDefaultKit);
    expect(resolveTokenColor(map, "$surface.inverse")).toBe("#0F172A");
  });

  it("returns null for a token the map doesn't know", () => {
    const map = buildTokenColorMap(platformDefaultKit);
    expect(resolveTokenColor(map, "surface.nonexistent")).toBeNull();
  });

  it("returns null against an empty map", () => {
    expect(resolveTokenColor({}, "surface.page")).toBeNull();
  });
});

describe("PLATFORM_DEFAULT_BRAND_KIT_ID", () => {
  it("matches the server-seeded platform default kit id", () => {
    expect(PLATFORM_DEFAULT_BRAND_KIT_ID).toBe("brand_kit_platform_default");
  });
});
