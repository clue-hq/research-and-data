import assert from "node:assert/strict";
import { it } from "node:test";
import type { Diagnostic, Scene } from "../engine/scene/contracts";
import type { EditorExportResult } from "../engine/scene/exportRunner";
import { HARVESTED_AD_PAGE } from "./__fixtures__/scene-nodes";
import {
  exportFilename,
  exportStatusFor,
  parseSceneExportRequest,
  previewAnchorsMatch,
  previewCacheKey,
  previewCacheLookup,
  previewCacheStore,
  previewRenderMode,
  sceneExportProfile,
  sceneExportResultMessage,
  sceneExportScaleMultiplier,
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
    advisoryCodes: [],
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

it("a failed export names the error that blocked it, not a warning listed before it", () => {
  assert.equal(
    sceneExportResultMessage(
      "PNG",
      exportResult({
        status: "failed",
        diagnostics: [
          { ...diagnostic("font asset brand is not marked subsettable for PDF export"), severity: "warning", code: "LUMB0614" },
          { ...diagnostic("image focal point outside 0..1"), code: "LUMV0821" },
        ],
      }),
    ),
    "image focal point outside 0..1",
  );
});

it("an error the API let through is never named as the reason an export failed", () => {
  assert.equal(
    sceneExportResultMessage(
      "PNG",
      exportResult({
        status: "failed",
        advisoryCodes: ["LUMV0903"],
        diagnostics: [
          { ...diagnostic("text node separator exceeds available height"), code: "LUMV0903" },
          { ...diagnostic("image focal point outside 0..1"), code: "LUMV0821" },
        ],
      }),
    ),
    "image focal point outside 0..1",
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

// ── AD4.D step 3: the scale mapping, shared with the request parse ─────────

it("the menu's scale labels map to the profile's raster multiplier", () => {
  assert.equal(sceneExportScaleMultiplier("1x"), 1);
  assert.equal(sceneExportScaleMultiplier("2x"), 2);
  assert.equal(sceneExportScaleMultiplier("3x"), 3);
  assert.equal(sceneExportScaleMultiplier("4x"), 4);
});

it("an absent or unrecognized scale is 1x, exactly as the request parse reads it", () => {
  assert.equal(sceneExportScaleMultiplier(undefined), 1);
  assert.equal(sceneExportScaleMultiplier("8x"), 1);
  assert.equal(sceneExportScaleMultiplier(2), 1);
  // The preview leg and the download listener must never disagree about what
  // the menu asked for — same input, same multiplier.
  assert.equal(
    sceneExportScaleMultiplier("3x"),
    parseSceneExportRequest({ format: "PNG", kind: "ad", scale: "3x" })?.scale,
  );
});

// ── AD4.D step 3: the (format, scale) preview cache ────────────────────────

/** A SECOND scene value that is structurally identical to the first. The cache
 * anchors on OBJECT IDENTITY (ruling R-D13) — the engine mirrors a new scene
 * object up on every accepted write — so this must invalidate even though a
 * deep comparison would call it the same document. */
const RELAID_AD_PAGE: Scene = { ...HARVESTED_AD_PAGE };

it("§1.11: PNG preview keys are distinct per scale", () => {
  const keys = new Set([
    previewCacheKey("PNG", 1),
    previewCacheKey("PNG", 2),
    previewCacheKey("PNG", 3),
    previewCacheKey("PNG", 4),
  ]);
  assert.equal(keys.size, 4);
});

it("§1.11: SVG and PDF key at scale 1 whatever the scale says — their profiles do not vary by scale, so a scale flip must not re-export", () => {
  assert.equal(previewCacheKey("SVG", 4), previewCacheKey("SVG", 1));
  assert.equal(previewCacheKey("PDF", 3), previewCacheKey("PDF", 1));
  // …and the three formats never collide with each other.
  assert.notEqual(previewCacheKey("SVG", 1), previewCacheKey("PDF", 1));
  assert.notEqual(previewCacheKey("SVG", 1), previewCacheKey("PNG", 1));
});

it("a stored entry is served back for the same document, scene and key", () => {
  const cache = previewCacheStore(
    null,
    "doc-1",
    HARVESTED_AD_PAGE,
    previewCacheKey("PNG", 2),
    "data:image/png;base64,AAA",
  );
  assert.equal(
    previewCacheLookup(cache, "doc-1", HARVESTED_AD_PAGE, previewCacheKey("PNG", 2)),
    "data:image/png;base64,AAA",
  );
});

it("an empty cache serves nothing", () => {
  assert.equal(
    previewCacheLookup(null, "doc-1", HARVESTED_AD_PAGE, previewCacheKey("PNG", 1)),
    null,
  );
});

it("another (format, scale) misses rather than serving the wrong render", () => {
  const cache = previewCacheStore(
    null,
    "doc-1",
    HARVESTED_AD_PAGE,
    previewCacheKey("PNG", 2),
    "data:image/png;base64,AAA",
  );
  assert.equal(
    previewCacheLookup(cache, "doc-1", HARVESTED_AD_PAGE, previewCacheKey("PNG", 4)),
    null,
  );
  assert.equal(
    previewCacheLookup(cache, "doc-1", HARVESTED_AD_PAGE, previewCacheKey("SVG", 2)),
    null,
  );
});

it("R-D13: a new scene object invalidates every entry — the document moved", () => {
  const cache = previewCacheStore(
    null,
    "doc-1",
    HARVESTED_AD_PAGE,
    previewCacheKey("PNG", 2),
    "data:image/png;base64,AAA",
  );
  assert.equal(
    previewCacheLookup(cache, "doc-1", RELAID_AD_PAGE, previewCacheKey("PNG", 2)),
    null,
  );
});

it("another document's cache is never served to this one", () => {
  const cache = previewCacheStore(
    null,
    "doc-1",
    HARVESTED_AD_PAGE,
    previewCacheKey("PNG", 2),
    "data:image/png;base64,AAA",
  );
  assert.equal(
    previewCacheLookup(cache, "doc-2", HARVESTED_AD_PAGE, previewCacheKey("PNG", 2)),
    null,
  );
});

it("storing under a moved scene starts a fresh map rather than accumulating stale renders", () => {
  const first = previewCacheStore(
    null,
    "doc-1",
    HARVESTED_AD_PAGE,
    previewCacheKey("PNG", 2),
    "data:image/png;base64,OLD",
  );
  const second = previewCacheStore(
    first,
    "doc-1",
    RELAID_AD_PAGE,
    previewCacheKey("SVG", 1),
    "data:image/svg+xml,NEW",
  );
  assert.equal(second.entries.size, 1);
  assert.equal(
    previewCacheLookup(second, "doc-1", RELAID_AD_PAGE, previewCacheKey("PNG", 2)),
    null,
  );
  assert.equal(
    previewCacheLookup(second, "doc-1", RELAID_AD_PAGE, previewCacheKey("SVG", 1)),
    "data:image/svg+xml,NEW",
  );
});

it("storing under a moved document starts a fresh map too", () => {
  const first = previewCacheStore(
    null,
    "doc-1",
    HARVESTED_AD_PAGE,
    previewCacheKey("PNG", 2),
    "data:image/png;base64,OLD",
  );
  const second = previewCacheStore(
    first,
    "doc-2",
    HARVESTED_AD_PAGE,
    previewCacheKey("PNG", 2),
    "data:image/png;base64,NEW",
  );
  assert.equal(second.entries.size, 1);
  assert.equal(second.forDocumentId, "doc-2");
  assert.equal(
    previewCacheLookup(second, "doc-2", HARVESTED_AD_PAGE, previewCacheKey("PNG", 2)),
    "data:image/png;base64,NEW",
  );
});

it("a second entry under the same anchors joins the first — the key space is 3 formats x 4 scales, so nothing is evicted", () => {
  const first = previewCacheStore(
    null,
    "doc-1",
    HARVESTED_AD_PAGE,
    previewCacheKey("PNG", 2),
    "data:image/png;base64,TWO",
  );
  const second = previewCacheStore(
    first,
    "doc-1",
    HARVESTED_AD_PAGE,
    previewCacheKey("PNG", 4),
    "data:image/png;base64,FOUR",
  );
  assert.equal(second.entries.size, 2);
  assert.equal(
    previewCacheLookup(second, "doc-1", HARVESTED_AD_PAGE, previewCacheKey("PNG", 2)),
    "data:image/png;base64,TWO",
  );
  assert.equal(
    previewCacheLookup(second, "doc-1", HARVESTED_AD_PAGE, previewCacheKey("PNG", 4)),
    "data:image/png;base64,FOUR",
  );
  // The value handed in is never mutated — a store returns a new cache.
  assert.equal(first.entries.size, 1);
});

// ── AD4.D step 3: how the preview region renders each payload ─────────────

it("a raster and a vector render both go in an <img>", () => {
  assert.equal(previewRenderMode("data:image/png;base64,AAA"), "img");
  assert.equal(previewRenderMode("data:image/svg+xml;base64,AAA"), "img");
  assert.equal(previewRenderMode("DATA:IMAGE/PNG;base64,AAA"), "img");
});

it("a PDF goes in an <iframe>, mirroring the standalone editor's own branch", () => {
  // `ExportPreviewSurface.tsx:64-71` branches on `format === "pdf"` for exactly
  // this reason: `<img src="data:application/pdf,...">` is a broken-image glyph.
  assert.equal(previewRenderMode("data:application/pdf;base64,AAA"), "iframe");
  assert.equal(previewRenderMode("DATA:APPLICATION/PDF;base64,AAA"), "iframe");
});

it("anything else renders nothing — the designed empty region beats a broken element", () => {
  assert.equal(previewRenderMode("data:application/octet-stream,AAA"), null);
  assert.equal(previewRenderMode("data:text/plain,hello"), null);
  // Not a data URL at all — nothing this lane produces, refused anyway.
  assert.equal(previewRenderMode("https://example.com/a.png"), null);
  assert.equal(previewRenderMode(""), null);
});

// ── AD4.D step 3: the shared anchor comparison ────────────────────────────

it("anchors match only for the same document AND the same scene object", () => {
  const anchored = { forDocumentId: "doc-1", forScene: HARVESTED_AD_PAGE };
  assert.equal(previewAnchorsMatch(anchored, "doc-1", HARVESTED_AD_PAGE), true);
  assert.equal(previewAnchorsMatch(anchored, "doc-2", HARVESTED_AD_PAGE), false);
  // R-D13: a structurally identical relaid scene is a DIFFERENT anchor.
  assert.equal(previewAnchorsMatch(anchored, "doc-1", RELAID_AD_PAGE), false);
});

it("nothing anchored matches nothing", () => {
  assert.equal(previewAnchorsMatch(null, "doc-1", HARVESTED_AD_PAGE), false);
});

// ── AD4.D final review: which stamped status the menu's span announces ─────

it("a status stamped with the live document is announced", () => {
  assert.deepEqual(
    exportStatusFor(
      { failed: false, forDocumentId: "doc-1", message: "PNG exported" },
      "doc-1",
    ),
    { failed: false, message: "PNG exported" },
  );
});

it("a status about another document is not announced under this one", () => {
  assert.equal(
    exportStatusFor(
      { failed: false, forDocumentId: "doc-1", message: "PNG exported" },
      "doc-2",
    ),
    null,
  );
  assert.equal(
    exportStatusFor(
      { failed: false, forDocumentId: "doc-1", message: "PNG exported" },
      null,
    ),
    null,
  );
});

it("nothing said yet announces nothing", () => {
  assert.equal(exportStatusFor(null, "doc-1"), null);
});

it("a pre-load refusal SURVIVES the document arriving — the span must never fall back to the optimistic line about an export that never ran", () => {
  const refusal = {
    failed: true,
    forDocumentId: null,
    message: "No document to export",
  };
  const announced = { failed: true, message: "No document to export" };
  // Announced during the pre-load window…
  assert.deepEqual(exportStatusFor(refusal, null), announced);
  // …and still announced once a document loads, rather than evaporating and
  // letting the controller's "PNG export requested at 1x" speak for an export
  // that was refused.
  assert.deepEqual(exportStatusFor(refusal, "doc-1"), announced);
  assert.deepEqual(exportStatusFor(refusal, "doc-2"), announced);
});

// The bug this shape exists for: a failure must be distinguishable from a
// success by the menu, so it can render VISIBLY instead of only to a screen
// reader. Before `failed`, both were the same bare string.
it("the failure flag rides through to the menu, so a refusal is not mistaken for an outcome", () => {
  assert.deepEqual(
    exportStatusFor(
      { failed: true, forDocumentId: "doc-1", message: "raster budget exceeded" },
      "doc-1",
    ),
    { failed: true, message: "raster budget exceeded" },
  );
  assert.deepEqual(
    exportStatusFor(
      { failed: false, forDocumentId: "doc-1", message: "Exporting PNG…" },
      "doc-1",
    ),
    { failed: false, message: "Exporting PNG…" },
  );
});
