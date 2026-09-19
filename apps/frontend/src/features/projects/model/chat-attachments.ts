import type { ProjectComposerAttachment } from "./project-composer";

/**
 * Chat attachments (the `.md`/`.txt`/image files a marketer drops on a project
 * chat turn or the Home composer). The backend's `POST /frontend/v1/uploads`
 * owns the authoritative refusals; these limits only spare the user a round
 * trip that would come back 413/415.
 */
export const CHAT_ATTACHMENT_ACCEPT =
  ".md,.txt,.png,.jpg,.jpeg,.webp,.gif,text/markdown,text/plain,image/png,image/jpeg,image/webp,image/gif";

export const CHAT_ATTACHMENT_LIMITS = {
  maxFiles: 10,
  maxTotalBytes: 157_286_400,
  imageMaxBytes: 10_485_760,
  textMaxBytes: 5_242_880,
} as const;

export type AttachmentFamily = "text" | "image";

const TEXT = new Set(["text/markdown", "text/plain"]);
const IMAGE = new Set(["image/png", "image/jpeg", "image/webp", "image/gif"]);
const BY_EXT: Record<string, string> = {
  ".md": "text/markdown",
  ".markdown": "text/markdown",
  ".txt": "text/plain",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".webp": "image/webp",
  ".gif": "image/gif",
};

/** The media type we will claim for a file: its own, else its extension's. */
export function attachmentMediaType(file: {
  name: string;
  type: string;
}): string | null {
  const declared = file.type.toLowerCase();
  if (TEXT.has(declared) || IMAGE.has(declared)) return declared;
  const dot = file.name.lastIndexOf(".");
  return dot >= 0 ? (BY_EXT[file.name.slice(dot).toLowerCase()] ?? null) : null;
}

/** `null` for a file this chat will not carry at all. */
export function attachmentFamily(file: {
  name: string;
  type: string;
}): AttachmentFamily | null {
  const media = attachmentMediaType(file);
  if (media === null) return null;
  return TEXT.has(media) ? "text" : "image";
}

/** The first limit the incoming files would break, as its user-facing message. */
export function attachmentLimitError(
  current: readonly ProjectComposerAttachment[],
  incoming: readonly File[],
): string | null {
  if (current.length + incoming.length > CHAT_ATTACHMENT_LIMITS.maxFiles) {
    return "A message can carry at most ten files.";
  }
  for (const file of incoming) {
    const family = attachmentFamily(file);
    if (family === "image" && file.size > CHAT_ATTACHMENT_LIMITS.imageMaxBytes) {
      return `${file.name} is over 10 MB.`;
    }
    if (family === "text" && file.size > CHAT_ATTACHMENT_LIMITS.textMaxBytes) {
      return `${file.name} is over 5 MB.`;
    }
  }
  const total =
    current.reduce((n, a) => n + (a.byteCount ?? 0), 0) +
    incoming.reduce((n, f) => n + f.size, 0);
  if (total > CHAT_ATTACHMENT_LIMITS.maxTotalBytes) {
    return "Attachments on one message may total at most 150 MB.";
  }
  return null;
}

/** The six wire fields a submitted attachment ref carries. All are required. */
export interface ChatAttachmentRef {
  uploadId: string;
  artifactKey: string;
  sha256: string;
  mediaType: string;
  byteCount: number;
  filename: string;
}

/** Immutable submission refs, or `null` while any attachment is not ready. */
export function chatAttachmentSnapshot(
  attachments: readonly ProjectComposerAttachment[],
): readonly ChatAttachmentRef[] | null {
  const refs: ChatAttachmentRef[] = [];
  for (const a of attachments) {
    if (
      a.status !== "ready" ||
      !a.uploadId ||
      !a.artifactKey ||
      !a.sha256 ||
      a.byteCount === undefined
    ) {
      return null;
    }
    refs.push({
      uploadId: a.uploadId,
      artifactKey: a.artifactKey,
      sha256: a.sha256,
      mediaType: a.mediaType,
      byteCount: a.byteCount,
      filename: a.filename,
    });
  }
  return refs;
}
