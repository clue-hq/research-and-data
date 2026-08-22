import type { ImageExportFormat } from "@/features/chat-shell/model/image-export";
import type { ExportProfile } from "../engine/scene/contracts";

/**
 * AD4.D step 1: the pure export adapter for the SCENE (ad) lane — the menu's
 * export vocabulary (docs/specs/ad-editor-integration/
 * ad-inspector-mapping-contract.md §1.11: formats PNG / SVG / PDF, scale 1x–4x
 * raster-only) translated into the engine's `ExportProfile` wire contract.
 *
 * Pure by construction: no React, no transport, no ambient environment. A
 * later slice hands these profiles to the `clue:artifact-export-request`
 * listener; this module only computes them.
 */

/** Screen-resolution raster. The engine's own `preview_png` profile pins the
 * same 96 dpi; the ad menu's 1x–4x scale multiplies it, so 4x is the
 * high-resolution deliverable rather than a separate print dpi. */
const PNG_EXPORT_DPI = 96;

/**
 * The ad menu's three export profiles (§1.11).
 *
 * `scale` applies to PNG alone — raster is a PNG-only parameter in the
 * ratified export model, mirrored by `imageExportSupportsScale` — so the SVG
 * and PDF profiles ignore the argument and carry `raster: null`.
 *
 * `embed_fonts` differs by format for one reason, stated by the engine's own
 * `defaultEditorExportProfile` (engine/scene/exportRunner.ts): a vector
 * deliverable "depends on viewer-installed fonts" without its own @font-face
 * payloads — and that applies twice over here, to the downloaded file AND to
 * the menu's collapsible preview region, which renders the result as an image
 * and so cannot reach document fonts. SVG and PDF must therefore carry their
 * glyph payloads; a PNG raster has already baked the glyphs into pixels, so
 * embedding fonts in it would be dead weight.
 *
 * `include_marks: false` is stated explicitly on every profile: the field is
 * optional on the wire, but per the contract's own comment the editor "sends
 * it on every profile it constructs".
 */
export function sceneExportProfile(
  format: ImageExportFormat,
  scale: 1 | 2 | 3 | 4
): ExportProfile {
  switch (format) {
    case "PNG":
      return {
        name: "ad_png",
        format: "png",
        pdf_intent: null,
        raster: { scale, dpi: PNG_EXPORT_DPI },
        include_bleed: false,
        include_marks: false,
        embed_fonts: false,
      };
    case "SVG":
      return {
        name: "ad_svg",
        format: "svg",
        pdf_intent: null,
        raster: null,
        include_bleed: false,
        include_marks: false,
        embed_fonts: true,
      };
    case "PDF":
      return {
        name: "ad_pdf",
        format: "pdf",
        // Digital intent. Print intent (with bleed and marks) enters only
        // after its mockups are approved — contract §1.11.
        pdf_intent: "preview",
        raster: null,
        include_bleed: false,
        include_marks: false,
        embed_fonts: true,
      };
  }
}

/** Characters no filesystem or Content-Disposition header should have to
 * carry: the Windows-reserved set plus ASCII control codes. A whole run
 * becomes ONE space so `Spring<<<>>>Sale` reads as two words, not eight. */
const FILENAME_HOSTILE_RUN = /[/\\:*?"<>|\u0000-\u001F]+/g;
const WHITESPACE_RUN = /\s+/g;

/** A title that sanitizes away to nothing still has to download as something. */
const FILENAME_FALLBACK = "export";

/**
 * The download filename for an ad export: a sanitized title plus the format's
 * extension (§1.11). Spaces are preserved — this is a human-facing filename,
 * not a URL slug, so it deliberately does NOT go through
 * `slugifyArtifactTitle` (the public-share slug) or the engine's
 * `safeFilenamePart` (which underscores every non-alphanumeric).
 */
export function exportFilename(title: string, format: ImageExportFormat): string {
  const sanitized =
    title
      .trim()
      .replace(FILENAME_HOSTILE_RUN, " ")
      .replace(WHITESPACE_RUN, " ")
      .trim() || FILENAME_FALLBACK;

  return `${sanitized}.${format.toLowerCase()}`;
}
