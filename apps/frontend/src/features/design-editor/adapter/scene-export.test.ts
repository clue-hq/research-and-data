import assert from "node:assert/strict";
import { it } from "node:test";
import { exportFilename, sceneExportProfile } from "./scene-export";

it("§1.11: the PNG profile rasterizes at the requested scale, dpi 96, without embedded fonts", () => {
  assert.deepEqual(sceneExportProfile("PNG", 1), {
    name: "ad_png",
    format: "png",
    pdf_intent: null,
    raster: { scale: 1, dpi: 96 },
    include_bleed: false,
    include_marks: false,
    embed_fonts: false,
  });
});

it("§1.11: PNG at 2x rasterizes at scale 2, dpi 96", () => {
  assert.deepEqual(sceneExportProfile("PNG", 2), {
    name: "ad_png",
    format: "png",
    pdf_intent: null,
    raster: { scale: 2, dpi: 96 },
    include_bleed: false,
    include_marks: false,
    embed_fonts: false,
  });
});

it("§1.11: PNG at 3x rasterizes at scale 3, dpi 96", () => {
  assert.deepEqual(sceneExportProfile("PNG", 3), {
    name: "ad_png",
    format: "png",
    pdf_intent: null,
    raster: { scale: 3, dpi: 96 },
    include_bleed: false,
    include_marks: false,
    embed_fonts: false,
  });
});

it("§1.11: PNG at 4x rasterizes at scale 4, dpi 96", () => {
  assert.deepEqual(sceneExportProfile("PNG", 4), {
    name: "ad_png",
    format: "png",
    pdf_intent: null,
    raster: { scale: 4, dpi: 96 },
    include_bleed: false,
    include_marks: false,
    embed_fonts: false,
  });
});

it("§1.11: the SVG profile carries no raster and embeds its fonts", () => {
  assert.deepEqual(sceneExportProfile("SVG", 1), {
    name: "ad_svg",
    format: "svg",
    pdf_intent: null,
    raster: null,
    include_bleed: false,
    include_marks: false,
    embed_fonts: true,
  });
});

it("§1.11: scale is a PNG-only parameter, so SVG at 4x equals SVG at 1x", () => {
  assert.deepEqual(sceneExportProfile("SVG", 4), sceneExportProfile("SVG", 1));
});

it("§1.11: the PDF profile is preview-intent, unrasterized, and embeds its fonts", () => {
  assert.deepEqual(sceneExportProfile("PDF", 1), {
    name: "ad_pdf",
    format: "pdf",
    pdf_intent: "preview",
    raster: null,
    include_bleed: false,
    include_marks: false,
    embed_fonts: true,
  });
});

it("§1.11: scale is a PNG-only parameter, so PDF at 4x equals PDF at 1x", () => {
  assert.deepEqual(sceneExportProfile("PDF", 4), sceneExportProfile("PDF", 1));
});

it("§1.11: a plain title keeps its spaces and takes the format's extension", () => {
  assert.equal(exportFilename("My Ad", "PNG"), "My Ad.png");
});

it("§1.11: the extension is the lowercased format for all three formats", () => {
  assert.equal(exportFilename("My Ad", "PNG"), "My Ad.png");
  assert.equal(exportFilename("My Ad", "SVG"), "My Ad.svg");
  assert.equal(exportFilename("My Ad", "PDF"), "My Ad.pdf");
});

it("§1.11: path-hostile characters and control chars each become one space", () => {
  assert.equal(
    exportFilename('a/b\\c:d*e?f"g<h>i|j\u0007k', "PNG"),
    "a b c d e f g h i j k.png"
  );
});

it("§1.11: a run of stripped characters collapses to a single space", () => {
  assert.equal(exportFilename("Spring<<<>>>Sale", "SVG"), "Spring Sale.svg");
});

it("§1.11: surrounding and repeated whitespace is trimmed and collapsed", () => {
  assert.equal(exportFilename("  My   Big    Ad  ", "PNG"), "My Big Ad.png");
});

it("§1.11: an empty title falls back to export", () => {
  assert.equal(exportFilename("", "PDF"), "export.pdf");
});

it("§1.11: a whitespace-only title falls back to export", () => {
  assert.equal(exportFilename("   \t \n ", "PDF"), "export.pdf");
});

it("§1.11: a title of only stripped characters falls back to export", () => {
  assert.equal(exportFilename('///???"|', "SVG"), "export.svg");
});
