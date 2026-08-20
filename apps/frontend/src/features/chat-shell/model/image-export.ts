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
