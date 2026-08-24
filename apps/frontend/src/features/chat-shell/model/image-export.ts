// §2 delta (contract row 6 / §1.11): JPEG is dropped in v1 — the export menu
// offers PNG / SVG / PDF only, and scale (raster) now means PNG alone.
export const IMAGE_EXPORT_FORMATS = ["PNG", "SVG", "PDF"] as const;
export const IMAGE_EXPORT_SCALES = ["1x", "2x", "3x", "4x"] as const;

export type ImageExportFormat = (typeof IMAGE_EXPORT_FORMATS)[number];
export type ImageExportScale = (typeof IMAGE_EXPORT_SCALES)[number];

export function imageExportSupportsScale(format: ImageExportFormat) {
  return format === "PNG";
}

// Transparent-background export is held at contract Gate G-E (no engine support verified 2026-08-20); restore verbatim if the founder authorizes the engine change.

/**
 * AD4.D step 3 (§1.11): which element the export menu's designed preview region
 * hosts for a given render. Two, because the standalone editor's own
 * `ExportPreviewSurface.tsx:64-77` branches the same way — a PDF needs the
 * browser's PDF viewer in a frame, everything else is an image.
 */
export type ImageExportPreviewRenderMode = "img" | "iframe";

/**
 * A render the preview region can actually show. The URL and the element that
 * hosts it travel as ONE value so "a payload with no way to render it" is not a
 * state any consumer can be handed — the decision is made once, upstream, and
 * an absent value is the region's honest empty state (ruling R-D14).
 */
export interface ImageExportPreview {
  dataUrl: string;
  mode: ImageExportPreviewRenderMode;
}
