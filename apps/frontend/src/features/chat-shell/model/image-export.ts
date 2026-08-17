export const IMAGE_EXPORT_FORMATS = ["PNG", "JPEG", "SVG", "PDF"] as const;
export const IMAGE_EXPORT_SCALES = ["1x", "2x", "3x", "4x"] as const;

export type ImageExportFormat = (typeof IMAGE_EXPORT_FORMATS)[number];
export type ImageExportScale = (typeof IMAGE_EXPORT_SCALES)[number];

export function imageExportSupportsScale(format: ImageExportFormat) {
  return format === "PNG" || format === "JPEG";
}

export function imageExportSupportsTransparency(format: ImageExportFormat) {
  return format === "PNG" || format === "SVG";
}
