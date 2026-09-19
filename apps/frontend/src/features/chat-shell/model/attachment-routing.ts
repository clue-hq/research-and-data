import { attachmentFamily } from "@/features/projects/model/chat-attachments";

/**
 * Ruling 4 (2026-09-18): while an ad leg is open, images keep the
 * design-reference route — the marketer dropping a reference picture onto an
 * open ad means "look like this", not "read this file". Everything else, and
 * everything when no ad leg is open, is an ordinary chat attachment.
 */
export function routeAttachmentFiles(
  files: readonly File[],
  designReferencesEnabled: boolean,
): { design: File[]; chat: File[] } {
  const design: File[] = [];
  const chat: File[] = [];
  for (const file of files) {
    if (designReferencesEnabled && attachmentFamily(file) === "image") {
      design.push(file);
    } else {
      chat.push(file);
    }
  }
  return { design, chat };
}
