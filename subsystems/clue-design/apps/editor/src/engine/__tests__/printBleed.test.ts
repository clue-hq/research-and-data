import { describe, expect, it } from "vitest";
import type { PageSize } from "../contracts";
import { DEFAULT_BLEED_PT, DEFAULT_SAFE_AREA_PT, printBleedRect, printSafeAreaRect } from "../printBleed";

// A4 in canonical pt space (210×297mm → 595.276×841.89pt).
const a4: PageSize = {
  width: 595.276,
  height: 841.89,
  unit: "pt",
  preset: "custom",
  orientation: "portrait"
};

describe("printBleed defaults", () => {
  it("3mm bleed and 5mm safe-area resolve to the expected pt values", () => {
    expect(DEFAULT_BLEED_PT).toBeCloseTo(8.5039, 3);
    expect(DEFAULT_SAFE_AREA_PT).toBeCloseTo(14.1732, 3);
  });

  it("bleed rect outsets on every side (negative origin, +2b in each axis)", () => {
    const bleed = printBleedRect(a4);
    expect(bleed.x).toBeCloseTo(-8.5039, 3);
    expect(bleed.y).toBeCloseTo(-8.5039, 3);
    expect(bleed.width).toBeCloseTo(a4.width + 8.5039 * 2, 3);
    expect(bleed.height).toBeCloseTo(a4.height + 8.5039 * 2, 3);
  });

  it("safe-area rect insets on every side (+inset origin, -2i in each axis)", () => {
    const safe = printSafeAreaRect(a4);
    expect(safe.x).toBeCloseTo(14.1732, 3);
    expect(safe.y).toBeCloseTo(14.1732, 3);
    expect(safe.width).toBeCloseTo(a4.width - 14.1732 * 2, 3);
    expect(safe.height).toBeCloseTo(a4.height - 14.1732 * 2, 3);
  });

  it("safe-area clamps to a positive box for a tiny page", () => {
    const tiny: PageSize = { ...a4, width: 10, height: 10 };
    const safe = printSafeAreaRect(tiny);
    expect(safe.width).toBeGreaterThanOrEqual(1);
    expect(safe.height).toBeGreaterThanOrEqual(1);
  });

  it("honors explicit overrides", () => {
    const bleed = printBleedRect(a4, 10);
    expect(bleed.x).toBe(-10);
    expect(bleed.width).toBe(a4.width + 20);
  });
});
