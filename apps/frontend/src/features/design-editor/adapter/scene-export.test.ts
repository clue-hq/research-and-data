import assert from "node:assert/strict";
import { it } from "node:test";
import type { Diagnostic } from "../engine/scene/contracts";
import type { EditorExportResult } from "../engine/scene/exportRunner";
import {
  exportFilename,
  parseSceneExportRequest,
  sceneExportProfile,
  sceneExportResultMessage,
} from "./scene-export";

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

// ── AD4.D step 2: the request parse ────────────────────────────────────────

it("the image menu's PNG detail parses to its format, scale and title", () => {
  assert.deepEqual(
    parseSceneExportRequest({
      format: "PNG",
      kind: "ad",
      scale: "2x",
      title: "Spring Sale",
    }),
    { format: "PNG", scale: 2, title: "Spring Sale" },
  );
});

it("every menu format parses", () => {
  for (const format of ["PNG", "SVG", "PDF"] as const) {
    assert.deepEqual(parseSceneExportRequest({ format, kind: "ad", title: "Ad" }), {
      format,
      scale: 1,
      title: "Ad",
    });
  }
});

it("every menu scale parses to its integer multiplier", () => {
  const scales = [
    ["1x", 1],
    ["2x", 2],
    ["3x", 3],
    ["4x", 4],
  ] as const;
  for (const [scale, expected] of scales) {
    assert.equal(
      parseSceneExportRequest({ format: "PNG", kind: "ad", scale })?.scale,
      expected,
    );
  }
});

it("an absent scale (the menu's own SVG/PDF shape) is 1x", () => {
  assert.equal(
    parseSceneExportRequest({ format: "SVG", kind: "ad", scale: undefined })?.scale,
    1,
  );
});

it("an unrecognized scale is 1x rather than a refusal", () => {
  assert.equal(parseSceneExportRequest({ format: "PNG", kind: "ad", scale: "8x" })?.scale, 1);
  assert.equal(parseSceneExportRequest({ format: "PNG", kind: "ad", scale: 2 })?.scale, 1);
});

it("a missing or empty title is null — the hook falls back", () => {
  assert.equal(parseSceneExportRequest({ format: "PNG", kind: "ad" })?.title, null);
  assert.equal(parseSceneExportRequest({ format: "PNG", kind: "ad", title: "" })?.title, null);
  assert.equal(parseSceneExportRequest({ format: "PNG", kind: "ad", title: 7 })?.title, null);
});

it("the SHARING menu's ZIP request is not a scene export", () => {
  assert.equal(parseSceneExportRequest({ format: "ZIP", kind: "ad" }), null);
});

it("the sharing menu's PDF request IS a scene export (same format vocabulary)", () => {
  assert.deepEqual(parseSceneExportRequest({ format: "PDF", kind: "ad" }), {
    format: "PDF",
    scale: 1,
    title: null,
  });
});

it("another artifact kind is never this lane's export", () => {
  assert.equal(parseSceneExportRequest({ format: "PNG", kind: "web" }), null);
  assert.equal(parseSceneExportRequest({ format: "PNG" }), null);
});

it("junk details parse to null rather than throwing", () => {
  assert.equal(parseSceneExportRequest(null), null);
  assert.equal(parseSceneExportRequest(undefined), null);
  assert.equal(parseSceneExportRequest("PNG"), null);
  assert.equal(parseSceneExportRequest({ format: 3, kind: "ad" }), null);
  assert.equal(parseSceneExportRequest({ format: "png", kind: "ad" }), null);
});

// ── AD4.D step 2: the outcome message ──────────────────────────────────────

function diagnostic(message: string): Diagnostic {
  return {
    severity: "error",
    phase: "export",
    code: "LUME0000",
    message,
    subject: null,
    hint: null,
  };
}

function exportResult(overrides: Partial<EditorExportResult>): EditorExportResult {
  return {
    status: "ok",
    diagnostics: [],
    artifacts: [],
    printReady: null,
    ...overrides,
  };
}

it("a successful export reports the format that came back", () => {
  assert.equal(
    sceneExportResultMessage("PNG", exportResult({ status: "ok" })),
    "PNG exported",
  );
});

it("a failed export reports the FIRST diagnostic — the engine's own words", () => {
  assert.equal(
    sceneExportResultMessage(
      "SVG",
      exportResult({
        status: "failed",
        diagnostics: [diagnostic("raster budget exceeded"), diagnostic("second")],
      }),
    ),
    "raster budget exceeded",
  );
});

it("a failure with no diagnostics still says something honest", () => {
  assert.equal(
    sceneExportResultMessage("PDF", exportResult({ status: "failed" })),
    "PDF export failed",
  );
});

it("a failure whose first diagnostic is blank falls back rather than saying nothing", () => {
  assert.equal(
    sceneExportResultMessage(
      "PNG",
      exportResult({ status: "failed", diagnostics: [diagnostic("   ")] }),
    ),
    "PNG export failed",
  );
});
