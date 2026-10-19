// The site element inspector's image panel (plan 5), as pure decisions: what the Fit row shows and the
// image's whole new override after choosing Fill or Fit (ruling R3). Replace, alt text and Stroke are
// the dock's image field, the session's alt commit and the box panel's Stroke.
import type { StyleOverride } from "@clue/site-kit/edits";
import type { ComputedImage } from "@clue/site-kit/editor-protocol";

export const FIT_SAME_NOTE = "This image is shown at its own shape, so Fill and Fit look the same here.";

export type ImageFit = "fill" | "fit";

/** What the Fit row shows: the override's fit, else the drawn one; live only where the box's shape
 * differs from the picture's own. */
export function imagePanelValues(override: StyleOverride | null, image: ComputedImage): { fit: ImageFit | null; fitLive: boolean } {
  return { fit: override?.imageFit ?? image.fit, fitLive: image.fitMatters };
}

/** The image's whole new override after choosing a fit; the same override when nothing changes, null
 * where fit does not apply. */
export function imageFitPatch(override: StyleOverride | null, fit: ImageFit, image: ComputedImage): StyleOverride | null {
  if (!image.fitMatters) return null;
  const base = override ?? {};
  return base.imageFit === fit ? base : { ...base, imageFit: fit };
}
