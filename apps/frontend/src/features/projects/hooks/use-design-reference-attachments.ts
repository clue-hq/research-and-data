"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { uploadWebAsset } from "@/features/design-editor/data/assets";
import type { ProjectComposerAttachment } from "../model/project-composer";
import type { TurnContextReference } from "../model/chat-turn";
import {
  designReferenceContextSnapshot,
  isDesignReferenceMediaType,
  MAX_DESIGN_REFERENCE_ATTACHMENTS,
} from "../model/design-reference-attachments";

export interface DesignReferenceAttachmentsController {
  attachments: readonly ProjectComposerAttachment[];
  clear(): void;
  error: string | null;
  onFiles(files: File[]): void;
  remove(attachmentId: string): void;
  snapshotContextRefs(): readonly TurnContextReference[] | null;
  submissionBlocked: boolean;
}

export function useDesignReferenceAttachments({
  enabled,
}: {
  enabled: boolean;
}): DesignReferenceAttachmentsController {
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
    // The design-leg lifecycle is an external state transition. Reset on the next task so this
    // effect itself does not synchronously cascade a second render; the surface already hides the
    // attachments immediately while the leg is closed.
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
      if (current.length + files.length > MAX_DESIGN_REFERENCE_ATTACHMENTS) {
        setError(
          `A design turn accepts at most ${MAX_DESIGN_REFERENCE_ATTACHMENTS} reference images.`,
        );
        return;
      }

      setError(null);
      const pending = files.map((file) => {
        const id = `design-reference-${crypto.randomUUID()}`;
        const url = URL.createObjectURL(file);
        objectUrls.current.set(id, url);
        return {
          attachment: {
            filename: file.name,
            id,
            mediaType: file.type || "application/octet-stream",
            status: isDesignReferenceMediaType(file.type)
              ? ("uploading" as const)
              : ("failed" as const),
            type: "file" as const,
            url,
            ...(isDesignReferenceMediaType(file.type)
              ? {}
              : { error: "Use a PNG, JPEG, WebP, or SVG image." }),
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
        void uploadWebAsset(file)
          .then((asset) => {
            const mediaType = asset.media?.mime_type ?? "";
            if (
              asset.status !== "ready" ||
              !isDesignReferenceMediaType(mediaType) ||
              !asset.media?.digest?.value
            ) {
              throw new Error("The uploaded image did not become a ready design asset.");
            }
            replaceAttachments((items) =>
              items.map((item) =>
                item.id === attachment.id
                  ? {
                      ...item,
                      assetId: asset.id,
                      filename: asset.media?.filename ?? item.filename,
                      mediaType,
                      status: "ready",
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
                          : "Image upload failed.",
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

  const snapshotContextRefs = useCallback(
    () => designReferenceContextSnapshot(attachmentsRef.current),
    [],
  );

  return {
    attachments,
    clear,
    error,
    onFiles,
    remove,
    snapshotContextRefs,
    submissionBlocked: attachments.some(
      (attachment) => attachment.status !== "ready",
    ),
  };
}
