import type { ProjectComposerAttachment } from "./project-composer";

const DOCX =
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
const PPTX =
  "application/vnd.openxmlformats-officedocument.presentationml.presentation";
const XLSX =
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

/**
 * Chat attachments (the `.md`/`.txt`/document/image files a marketer drops on a
 * project chat turn or the Home composer). The backend's
 * `POST /frontend/v1/uploads` owns the authoritative refusals; these limits only
 * spare the user a round trip that would come back 413/415. A document is
 * stored as-is — nothing here converts it.
 */
export const CHAT_ATTACHMENT_ACCEPT = [
  ".md",
  ".txt",
  ".pdf",
  ".docx",
  ".pptx",
  ".xlsx",
  ".csv",
  ".json",
  ".png",
  ".jpg",
  ".jpeg",
  ".webp",
  ".gif",
  ".svg",
  ".heic",
  ".heif",
  ".avif",
  ".tif",
  ".tiff",
  ".bmp",
  ".ico",
  "text/markdown",
  "text/plain",
  "application/pdf",
  DOCX,
  PPTX,
  XLSX,
  "text/csv",
  "application/json",
  "image/png",
  "image/jpeg",
  "image/webp",
  "image/gif",
  "image/svg+xml",
  "image/heic",
  "image/heif",
  "image/avif",
  "image/tiff",
  "image/bmp",
  "image/x-icon",
].join(",");

export const CHAT_ATTACHMENT_LIMITS = {
  maxFiles: 10,
  maxTotalBytes: 157_286_400,
  imageMaxBytes: 10_485_760,
  textMaxBytes: 5_242_880,
  documentMaxBytes: 26_214_400,
} as const;

export type AttachmentFamily = "text" | "image" | "document";

const TEXT = new Set(["text/markdown", "text/plain"]);
const IMAGE = new Set([
  "image/png",
  "image/jpeg",
  "image/webp",
  "image/gif",
  // Spec 2026-10-30 §3.6: the server shows a model a PNG copy of these, and
  // opens an SVG as a file.
  "image/svg+xml",
  "image/heic",
  "image/heif",
  "image/avif",
  "image/tiff",
  "image/bmp",
  "image/x-icon",
]);
const DOCUMENT = new Set([
  "application/pdf",
  DOCX,
  PPTX,
  XLSX,
  "text/csv",
  "application/json",
]);
const BY_EXT: Record<string, string> = {
  ".md": "text/markdown",
  ".markdown": "text/markdown",
  ".txt": "text/plain",
  ".pdf": "application/pdf",
  ".docx": DOCX,
  ".pptx": PPTX,
  ".xlsx": XLSX,
  ".csv": "text/csv",
  ".json": "application/json",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".webp": "image/webp",
  ".gif": "image/gif",
  ".svg": "image/svg+xml",
  ".heic": "image/heic",
  ".heif": "image/heif",
  ".avif": "image/avif",
  ".tif": "image/tiff",
  ".tiff": "image/tiff",
  ".bmp": "image/bmp",
  ".ico": "image/x-icon",
};

/**
 * The media type we will claim for a file: its own, else its extension's.
 * Browsers routinely report a document as `application/octet-stream` (or a
 * `.csv` as `application/vnd.ms-excel`), so an unrecognised declared type falls
 * through to the extension exactly as `.md` always has.
 */
export function attachmentMediaType(file: {
  name: string;
  type: string;
}): string | null {
  const declared = file.type.toLowerCase();
  if (TEXT.has(declared) || IMAGE.has(declared) || DOCUMENT.has(declared)) {
    return declared;
  }
  const dot = file.name.lastIndexOf(".");
  return dot >= 0 ? (BY_EXT[file.name.slice(dot).toLowerCase()] ?? null) : null;
}

/**
 * Whether a browser can draw this image as a preview. HEIC/HEIF and TIFF are
 * accepted attachments (the agent is shown a PNG copy) but most browsers
 * cannot draw them, so their chips show the image icon instead of a broken
 * thumbnail.
 */
export function canPreviewInBrowser(mediaType: string): boolean {
  const type = mediaType.toLowerCase();
  return IMAGE.has(type) && !NO_BROWSER_PREVIEW.has(type);
}

const NO_BROWSER_PREVIEW = new Set(["image/heic", "image/heif", "image/tiff"]);

/** `null` for a file this chat will not carry at all. */
export function attachmentFamily(file: {
  name: string;
  type: string;
}): AttachmentFamily | null {
  const media = attachmentMediaType(file);
  if (media === null) return null;
  if (TEXT.has(media)) return "text";
  if (DOCUMENT.has(media)) return "document";
  return "image";
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
    if (
      family === "image" &&
      file.size > CHAT_ATTACHMENT_LIMITS.imageMaxBytes
    ) {
      return `${file.name} is over 10 MB.`;
    }
    if (family === "text" && file.size > CHAT_ATTACHMENT_LIMITS.textMaxBytes) {
      return `${file.name} is over 5 MB.`;
    }
    if (
      family === "document" &&
      file.size > CHAT_ATTACHMENT_LIMITS.documentMaxBytes
    ) {
      return `${file.name} is over 25 MB.`;
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
