import { describe, expect, it } from "vitest";

import {
  bgColorFacet,
  directionFacet,
  displayFacet,
  gapFacet,
  marginXFacet,
  paddingXFacet,
  paddingYFacet,
  textAlignFacet,
  textColorFacet,
  textSizeFacet,
  webClassFacets
} from "../webClassFacets";

describe("textColor facet", () => {
  it("parses a theme-color token and ignores sizes/alignment", () => {
    expect(textColorFacet.parse("text-primary")).toBe("primary");
    expect(textColorFacet.parse("p-4 text-slate-700 font-bold")).toBe("slate-700");
    expect(textColorFacet.parse("text-lg")).toBeNull();
    expect(textColorFacet.parse("text-center")).toBeNull();
    expect(textColorFacet.parse("text-balance")).toBeNull();
    expect(textColorFacet.parse("flex gap-4")).toBeNull();
  });

  it("round-trips parse/set", () => {
    expect(textColorFacet.parse(textColorFacet.set("", "accent"))).toBe("accent");
    expect(textColorFacet.parse(textColorFacet.set("text-ink", "accent"))).toBe("accent");
  });

  it("replaces only the color token, preserving size + alignment siblings", () => {
    const next = textColorFacet.set("text-lg text-ink text-center font-bold", "accent");
    // size/alignment/unknown survive; color swapped
    expect(next).toContain("text-lg");
    expect(next).toContain("text-center");
    expect(next).toContain("font-bold");
    expect(next).toContain("text-accent");
    expect(next).not.toContain("text-ink");
    expect(textColorFacet.parse(next)).toBe("accent");
    expect(textSizeFacet.parse(next)).toBe("lg");
    expect(textAlignFacet.parse(next)).toBe("center");
  });

  it("clears with null and leaves other utilities intact", () => {
    const next = textColorFacet.set("text-ink text-lg font-bold", null);
    expect(next).toBe("text-lg font-bold");
    expect(textColorFacet.parse(next)).toBeNull();
  });
});

describe("textSize facet", () => {
  it("parses only ramp sizes", () => {
    expect(textSizeFacet.parse("text-2xl text-primary")).toBe("2xl");
    expect(textSizeFacet.parse("text-primary")).toBeNull();
  });

  it("swaps size without touching color", () => {
    const next = textSizeFacet.set("text-primary text-sm", "4xl");
    expect(textSizeFacet.parse(next)).toBe("4xl");
    expect(textColorFacet.parse(next)).toBe("primary");
  });
});

describe("textAlign facet", () => {
  it("parses/sets alignment independently", () => {
    expect(textAlignFacet.parse("text-right text-ink")).toBe("right");
    const next = textAlignFacet.set("text-ink text-lg", "center");
    expect(textAlignFacet.parse(next)).toBe("center");
    expect(textColorFacet.parse(next)).toBe("ink");
    expect(textSizeFacet.parse(next)).toBe("lg");
  });
});

describe("bgColor facet", () => {
  it("parses a color token and excludes gradient dirs + keywords", () => {
    expect(bgColorFacet.parse("bg-surface")).toBe("surface");
    expect(bgColorFacet.parse("bg-gradient-to-r")).toBeNull();
    expect(bgColorFacet.parse("bg-linear-to-br")).toBeNull();
    expect(bgColorFacet.parse("bg-cover")).toBeNull();
    expect(bgColorFacet.parse("bg-center")).toBeNull();
    expect(bgColorFacet.parse("bg-no-repeat")).toBeNull();
  });

  it("swaps color while keeping a gradient direction utility", () => {
    const next = bgColorFacet.set("bg-gradient-to-r bg-surface", "accent");
    expect(next).toContain("bg-gradient-to-r");
    expect(bgColorFacet.parse(next)).toBe("accent");
  });
});

describe("display + direction facets (no collision)", () => {
  it("parses display without eating flex-col", () => {
    expect(displayFacet.parse("flex flex-col gap-4")).toBe("flex");
    expect(directionFacet.parse("flex flex-col gap-4")).toBe("col");
  });

  it("editing display leaves direction intact and vice versa", () => {
    const a = displayFacet.set("flex flex-col", "grid");
    expect(displayFacet.parse(a)).toBe("grid");
    expect(directionFacet.parse(a)).toBe("col");

    const b = directionFacet.set("flex flex-col", "row");
    expect(directionFacet.parse(b)).toBe("row");
    expect(displayFacet.parse(b)).toBe("flex");
  });
});

describe("gap facet (axis collapse)", () => {
  it("reports only the base gap", () => {
    expect(gapFacet.parse("gap-4")).toBe("4");
    expect(gapFacet.parse("gap-x-2 gap-y-6")).toBeNull();
    expect(gapFacet.parse("gap-4 gap-x-2")).toBe("4");
  });

  it("set collapses axis gaps into one base gap", () => {
    const next = gapFacet.set("gap-x-2 gap-y-6 p-4", "8");
    expect(gapFacet.parse(next)).toBe("8");
    expect(next).not.toContain("gap-x-2");
    expect(next).not.toContain("gap-y-6");
    expect(next).toContain("p-4");
  });

  it("clears gap with null", () => {
    expect(gapFacet.set("gap-4 flex", null)).toBe("flex");
  });
});

describe("spacing facets", () => {
  it("parse/set padding + margin axes independently", () => {
    expect(paddingXFacet.parse("px-4 py-2")).toBe("4");
    expect(paddingYFacet.parse("px-4 py-2")).toBe("2");
    const next = paddingXFacet.set("px-4 py-2 mx-6", "8");
    expect(paddingXFacet.parse(next)).toBe("8");
    expect(paddingYFacet.parse(next)).toBe("2");
    expect(marginXFacet.parse(next)).toBe("6");
  });
});

describe("survival guarantees", () => {
  it("preserves unrecognized utilities verbatim across any set", () => {
    const src = "rounded-lg shadow-md ring-2 custom-thing";
    for (const facet of Object.values(webClassFacets)) {
      const next = facet.set(src, "x");
      for (const token of ["rounded-lg", "shadow-md", "ring-2", "custom-thing"]) {
        expect(next).toContain(token);
      }
    }
  });

  it("never touches variant-prefixed tokens on set and never reports them on parse", () => {
    const src = "md:gap-8 hover:bg-accent gap-4 bg-surface";
    // parse sees base only
    expect(gapFacet.parse(src)).toBe("4");
    expect(bgColorFacet.parse(src)).toBe("surface");
    // set preserves the prefixed variants verbatim
    const nextGap = gapFacet.set(src, "6");
    expect(nextGap).toContain("md:gap-8");
    expect(gapFacet.parse(nextGap)).toBe("6");
    const nextBg = bgColorFacet.set(src, "ink");
    expect(nextBg).toContain("hover:bg-accent");
    expect(bgColorFacet.parse(nextBg)).toBe("ink");
  });

  it("clearing an absent family is a no-op that keeps other tokens", () => {
    expect(textColorFacet.set("flex gap-4", null)).toBe("flex gap-4");
  });
});
