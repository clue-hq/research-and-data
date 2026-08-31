import { describe, expect, it } from "./vitest-shim";

import {
  alignItemsFacet,
  bgColorFacet,
  directionFacet,
  displayFacet,
  elementDimensionValue,
  flexWrapFacet,
  fontWeightFacet,
  gapFacet,
  gridColumnsFacet,
  heightFacet,
  italicFacet,
  justifyContentFacet,
  lineHeightFacet,
  lineThroughFacet,
  marginXFacet,
  objectFitFacet,
  objectPositionFacet,
  paddingXFacet,
  paddingYFacet,
  radiusBottomLeftFacet,
  radiusBottomRightFacet,
  radiusFacet,
  radiusTopLeftFacet,
  radiusTopRightFacet,
  setElementDimensionClass,
  setElementSizePixels,
  textAlignFacet,
  textColorFacet,
  textSizeFacet,
  underlineFacet,
  widthFacet,
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

describe("dimension facets and class-backed resize", () => {
  it("reads base width/height without consuming constraints or breakpoint overrides", () => {
    const classes = "w-full h-auto min-w-0 max-w-xl md:w-1/2 lg:h-96";
    expect(widthFacet.parse(classes)).toBe("full");
    expect(heightFacet.parse(classes)).toBe("auto");
    expect(widthFacet.set(classes, "[420px]")).toBe(
      "h-auto min-w-0 max-w-xl md:w-1/2 lg:h-96 w-[420px]"
    );
  });

  it("splits size-* when only one dimension changes", () => {
    expect(elementDimensionValue("size-10", "width")).toBe("10");
    expect(elementDimensionValue("size-10", "height")).toBe("10");
    expect(setElementDimensionClass("size-10 rounded-full", "width", "[96px]")).toBe(
      "rounded-full h-10 w-[96px]"
    );
    expect(setElementDimensionClass("size-10 object-cover", "height", "auto")).toBe(
      "object-cover w-10 h-auto"
    );
  });

  it("writes a corner resize as canonical arbitrary-pixel classes", () => {
    const next = setElementSizePixels(
      "size-10 md:w-full rounded-xl",
      { widthPx: 321.4, heightPx: 88.6 }
    );
    expect(next).toBe("md:w-full rounded-xl w-[321px] h-[89px]");
    expect(widthFacet.parse(next)).toBe("[321px]");
    expect(heightFacet.parse(next)).toBe("[89px]");
  });

  it("is a no-op when the requested class is already authored", () => {
    const classes = "flex w-[320px] md:w-full";
    expect(setElementDimensionClass(classes, "width", "[320px]")).toBe(classes);
  });
});

describe("expanded inspector facets", () => {
  it("edits flex alignment, wrap, and grid columns independently", () => {
    const classes = "flex flex-col justify-between items-center flex-wrap grid-cols-3 gap-6";
    expect(justifyContentFacet.parse(classes)).toBe("between");
    expect(alignItemsFacet.parse(classes)).toBe("center");
    expect(flexWrapFacet.parse(classes)).toBe("wrap");
    expect(gridColumnsFacet.parse(classes)).toBe("3");
    expect(justifyContentFacet.set(classes, "end")).toContain("justify-end");
    expect(alignItemsFacet.set(classes, "stretch")).toContain("items-stretch");
    expect(flexWrapFacet.set(classes, "nowrap")).toContain("flex-nowrap");
    expect(gridColumnsFacet.set(classes, "4")).toContain("grid-cols-4");
  });

  it("keeps typography and image projections disjoint", () => {
    const classes =
      "font-semibold leading-relaxed italic underline line-through object-cover object-center";
    expect(fontWeightFacet.parse(classes)).toBe("semibold");
    expect(lineHeightFacet.parse(classes)).toBe("relaxed");
    expect(italicFacet.parse(classes)).toBe("italic");
    expect(underlineFacet.parse(classes)).toBe("underline");
    expect(lineThroughFacet.parse(classes)).toBe("line-through");
    expect(objectFitFacet.parse(classes)).toBe("cover");
    expect(objectPositionFacet.parse(classes)).toBe("center");
    expect(objectFitFacet.set(classes, "contain")).toContain("object-contain");
    expect(objectPositionFacet.set(classes, "top")).toContain("object-top");
  });
});

describe("radius facets (all corners + per corner)", () => {
  it("parses an arbitrary px radius and the named Tailwind scale as the token suffix", () => {
    expect(radiusFacet.parse("rounded-[8px]")).toBe("[8px]");
    expect(radiusFacet.parse("p-4 rounded-lg shadow-md")).toBe("lg");
    expect(radiusFacet.parse("rounded-sm")).toBe("sm");
    expect(radiusFacet.parse("rounded-2xl")).toBe("2xl");
    expect(radiusFacet.parse("rounded-full")).toBe("full");
    expect(radiusFacet.parse("rounded-none")).toBe("none");
    expect(radiusFacet.parse("flex gap-4")).toBeNull();
  });

  it("reports no value for the bare `rounded` default but still owns it on set", () => {
    expect(radiusFacet.parse("rounded shadow-md")).toBeNull();
    expect(radiusFacet.set("rounded shadow-md", "[8px]")).toBe("shadow-md rounded-[8px]");
    expect(radiusFacet.set("rounded shadow-md", null)).toBe("shadow-md");
  });

  it("parses each corner independently", () => {
    const classes = "rounded-tl-[4px] rounded-tr-lg rounded-bl-[12px] rounded-br-full";
    expect(radiusTopLeftFacet.parse(classes)).toBe("[4px]");
    expect(radiusTopRightFacet.parse(classes)).toBe("lg");
    expect(radiusBottomLeftFacet.parse(classes)).toBe("[12px]");
    expect(radiusBottomRightFacet.parse(classes)).toBe("full");
    expect(radiusTopLeftFacet.parse("rounded-tr-[4px]")).toBeNull();
  });

  it("sets on an empty class string and replaces an existing radius token", () => {
    expect(radiusFacet.set("", "[8px]")).toBe("rounded-[8px]");
    expect(radiusFacet.set("rounded-lg", "[12px]")).toBe("rounded-[12px]");
    expect(radiusTopLeftFacet.set("", "[4px]")).toBe("rounded-tl-[4px]");
    expect(radiusTopLeftFacet.set("rounded-tl-xl", "[4px]")).toBe("rounded-tl-[4px]");
  });

  it("preserves unrelated tokens verbatim and in order", () => {
    expect(radiusFacet.set("flex items-center rounded-lg shadow-md ring-2", "[8px]")).toBe(
      "flex items-center shadow-md ring-2 rounded-[8px]"
    );
  });

  it("never touches a variant-prefixed radius token", () => {
    const src = "hover:rounded-lg md:rounded-tl-[2px] rounded-sm";
    expect(radiusFacet.parse(src)).toBe("sm");
    expect(radiusTopLeftFacet.parse(src)).toBeNull();
    expect(radiusFacet.set(src, "[8px]")).toBe(
      "hover:rounded-lg md:rounded-tl-[2px] rounded-[8px]"
    );
  });

  it("keeps all-corners and per-corner families disjoint in both directions", () => {
    const classes = "rounded-lg rounded-tl-[4px]";
    expect(radiusFacet.parse(classes)).toBe("lg");
    expect(radiusTopLeftFacet.parse(classes)).toBe("[4px]");
    expect(radiusFacet.parse("rounded-tl-[4px]")).toBeNull();
    expect(radiusTopLeftFacet.parse("rounded-full")).toBeNull();
    expect(radiusFacet.set(classes, "[8px]")).toBe("rounded-tl-[4px] rounded-[8px]");
    expect(radiusTopLeftFacet.set(classes, "[2px]")).toBe("rounded-lg rounded-tl-[2px]");
    expect(radiusBottomRightFacet.set(classes, "[6px]")).toBe(
      "rounded-lg rounded-tl-[4px] rounded-br-[6px]"
    );
  });

  it("leaves the side radius utilities it doesn't model verbatim", () => {
    const src = "rounded-t-lg rounded-s-xl rounded-sm";
    expect(radiusFacet.parse(src)).toBe("sm");
    expect(radiusFacet.set(src, "[8px]")).toBe("rounded-t-lg rounded-s-xl rounded-[8px]");
  });

  it("clears with null and round-trips parse/set", () => {
    expect(radiusBottomLeftFacet.set("rounded-bl-[4px] flex", null)).toBe("flex");
    expect(radiusFacet.parse(radiusFacet.set("", "[10px]"))).toBe("[10px]");
    expect(radiusTopRightFacet.parse(radiusTopRightFacet.set("rounded-tr", "[3px]"))).toBe(
      "[3px]"
    );
  });
});

describe("survival guarantees", () => {
  it("preserves unrecognized utilities verbatim across any set", () => {
    const src = "tracking-wide shadow-md ring-2 custom-thing";
    for (const facet of Object.values(webClassFacets)) {
      const next = facet.set(src, "x");
      for (const token of ["tracking-wide", "shadow-md", "ring-2", "custom-thing"]) {
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
