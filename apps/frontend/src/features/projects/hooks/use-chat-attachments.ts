"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { uploadChatFile } from "../data/uploads.repository";
import type { ProjectComposerAttachment } from "../model/project-composer";
import type { ChatAttachmentRef } from "../model/chat-attachments";
import {
  attachmentFamily,
  attachmentLimitError,
  attachmentMediaType,
  chatAttachmentSnapshot,
} from "../model/chat-attachments";

export interface ChatAttachmentsController {
  attachments: readonly ProjectComposerAttachment[];
  clear(): void;
  error: string | null;
  onFiles(files: File[]): void;
  remove(attachmentId: string): void;
  snapshot(): readonly ChatAttachmentRef[] | null;
  submissionBlocked: boolean;
}

const UNSUPPORTED =
  "Use a .md, .txt, .pdf, .docx, .pptx, .xlsx, .csv or .json file, or a PNG, JPEG, WebP or GIF image.";

export function useChatAttachments({
  enabled,
}: {
  enabled: boolean;
}): ChatAttachmentsController {
  const [attachments, setAttachments] = useState<ProjectComposerAttachment[]>([]);
  const [error, setError] = useState<string | null>(null);
  const attachmentsRef = useRef<ProjectComposerAttachment[]>([]);
  const objectUrls = useRef(new Map<string, string>());

  const replaceAttachments = useCallback(
    (
      update: (
        current: ProjectComposerAttachment[],
      ) => ProjectComposerAttachment[],
    ) => {
      setAttachments((current) => {
        const next = update(current);
        attachmentsRef.current = next;
        return next;
      });
    },
    [],
  );

  const clear = useCallback(() => {
    for (const url of objectUrls.current.values()) URL.revokeObjectURL(url);
    objectUrls.current.clear();
    attachmentsRef.current = [];
    setAttachments([]);
    setError(null);
  }, []);

  useEffect(() => {
    if (enabled) return;
    // Being disabled is an external state transition. Reset on the next task so
    // this effect itself does not synchronously cascade a second render; the
    // surface already hides the attachments immediately while it is disabled.
    const reset = window.setTimeout(clear, 0);
    return () => window.clearTimeout(reset);
  }, [clear, enabled]);

  useEffect(
    () => () => {
      for (const url of objectUrls.current.values()) URL.revokeObjectURL(url);
      objectUrls.current.clear();
    },
    [],
  );

  const onFiles = useCallback(
    (files: File[]) => {
      if (!enabled || files.length === 0) return;
      const current = attachmentsRef.current;
      const limit = attachmentLimitError(current, files);
      if (limit) {
        setError(limit);
        return;
      }

      setError(null);
      const pending = files.map((file) => {
        const id = `chat-attachment-${crypto.randomUUID()}`;
        const family = attachmentFamily(file);
        // Only an image has a preview worth an object URL; a text file's chip
        // shows its name, so minting one would leak a URL for nothing.
        const url = family === "image" ? URL.createObjectURL(file) : "";
        if (url) objectUrls.current.set(id, url);
        return {
          attachment: {
            filename: file.name,
            id,
            mediaType:
              attachmentMediaType(file) ||
              file.type ||
              "application/octet-stream",
            status: family === null ? ("failed" as const) : ("uploading" as const),
            type: "file" as const,
            url,
            ...(family === null ? { error: UNSUPPORTED } : {}),
          },
          file,
        };
      });
      replaceAttachments((items) => [
        ...items,
        ...pending.map((item) => item.attachment),
      ]);

      for (const { attachment, file } of pending) {
        if (attachment.status === "failed") continue;
        void uploadChatFile(file)
          .then((upload) => {
            replaceAttachments((items) =>
              items.map((item) =>
                item.id === attachment.id
                  ? {
                      ...item,
                      artifactKey: upload.artifactKey,
                      byteCount: upload.byteCount,
                      filename: upload.filename,
                      mediaType: upload.mediaType,
                      sha256: upload.sha256,
                      status: "ready",
                      uploadId: upload.uploadId,
                    }
                  : item,
              ),
            );
          })
          .catch((failure: unknown) => {
            replaceAttachments((items) =>
              items.map((item) =>
                item.id === attachment.id
                  ? {
                      ...item,
                      error:
                        failure instanceof Error
                          ? failure.message
                          : "Upload failed.",
                      status: "failed",
                    }
                  : item,
              ),
            );
          });
      }
    },
    [enabled, replaceAttachments],
  );

  const remove = useCallback(
    (attachmentId: string) => {
      const url = objectUrls.current.get(attachmentId);
      if (url) URL.revokeObjectURL(url);
      objectUrls.current.delete(attachmentId);
      replaceAttachments((items) =>
        items.filter((attachment) => attachment.id !== attachmentId),
      );
      setError(null);
    },
    [replaceAttachments],
  );

  const snapshot = useCallback(
    () => chatAttachmentSnapshot(attachmentsRef.current),
    [],
  );

  return {
    attachments,
    clear,
    error,
    onFiles,
    remove,
    snapshot,
    submissionBlocked: attachments.some(
      (attachment) => attachment.status !== "ready",
    ),
  };
}
