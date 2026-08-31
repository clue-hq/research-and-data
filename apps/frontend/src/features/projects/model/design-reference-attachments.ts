import type { ProjectComposerAttachment } from "./project-composer";
import type { TurnContextReference } from "./chat-turn";

export const MAX_DESIGN_REFERENCE_ATTACHMENTS = 4;

export const DESIGN_REFERENCE_ACCEPT =
  ".png,.jpg,.jpeg,.webp,.svg,image/png,image/jpeg,image/webp,image/svg+xml";

const DESIGN_REFERENCE_MEDIA_TYPES = new Set([
  "image/png",
  "image/jpeg",
  "image/webp",
  "image/svg+xml",
]);

export function isDesignReferenceMediaType(mediaType: string): boolean {
  return DESIGN_REFERENCE_MEDIA_TYPES.has(mediaType.toLowerCase());
}

/** Immutable turn refs, or null while any visible attachment is not ready. */
export function designReferenceContextSnapshot(
  attachments: readonly ProjectComposerAttachment[],
): readonly TurnContextReference[] | null {
  if (
    attachments.some(
      (attachment) =>
        attachment.status !== "ready" || attachment.assetId === undefined,
    )
  ) {
    return null;
  }
  return attachments.map((attachment) => ({
    objectId: attachment.assetId as string,
    objectType: "design_asset",
    version: null,
  }));
}
