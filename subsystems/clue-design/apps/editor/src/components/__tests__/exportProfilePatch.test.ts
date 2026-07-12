import { describe, expect, it } from "vitest";
import type { ExportProfile } from "@/engine/contracts";
import { formatPatch, normalizeProfile } from "../ExportPanel";

function printPdf(): ExportProfile {
  return {
    name: "print_pdf",
    format: "pdf",
    pdf_intent: "print",
    raster: null,
    include_bleed: true,
    include_marks: true,
    embed_fonts: true
  };
}

describe("export profile format switching (W3)", () => {
  it("switching to pdf preserves include_bleed / include_marks / embed_fonts", () => {
    const svg: ExportProfile = { ...printPdf(), format: "svg" };
    const patch = formatPatch("pdf", svg);
    const next = normalizeProfile({ ...svg, ...patch });
    expect(next.format).toBe("pdf");
    expect(next.include_bleed).toBe(true);
    expect(next.include_marks).toBe(true);
    expect(next.embed_fonts).toBe(true);
    expect(next.raster).toBeNull();
  });

  it("normalizeProfile keeps include_bleed / include_marks for a pdf profile", () => {
    const next = normalizeProfile(printPdf());
    expect(next.include_bleed).toBe(true);
    expect(next.include_marks).toBe(true);
  });

  it("switching to png clears the print controls (bleed/marks/fonts off)", () => {
    const patch = formatPatch("png", printPdf());
    const next = normalizeProfile({ ...printPdf(), ...patch });
    expect(next.format).toBe("png");
    expect(next.include_bleed).toBe(false);
    expect(next.include_marks).toBe(false);
    expect(next.embed_fonts).toBe(false);
    expect(next.raster).not.toBeNull();
  });

  it("switching to svg clears the print controls", () => {
    const patch = formatPatch("svg", printPdf());
    const next = normalizeProfile({ ...printPdf(), ...patch });
    expect(next.format).toBe("svg");
    expect(next.include_bleed).toBe(false);
    expect(next.include_marks).toBe(false);
  });
});
