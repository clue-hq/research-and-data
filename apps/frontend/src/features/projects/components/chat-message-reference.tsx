import { isWebsiteKind } from "@/features/chat-shell/model/artifact-kind";
import type { ChatMessageRef } from "../model/chat-message";
import {
  chatUploadBytesUrl,
  designReferenceThumbnailUrl,
} from "../model/chat-message-presentation";
import type { ProjectEntity } from "../model/project-workspace";
import { canPreviewInBrowser } from "../model/chat-attachments";
import { ChatAttachment } from "./chat-attachment";
import { ChatMentionVisual } from "./chat-mention";
import styles from "./project-flow.module.css";

const contextLabels: Record<string, string> = {
  account: "Selected account",
  contact: "Selected contact",
  project_document: "Selected file",
  design_document: "Selected design",
  design_node: "Selected design element",
};

/** References keep their durable identity; only their presentation is shared with drafts. */
export function ChatMessageReference({
  reference,
  entity,
}: {
  reference: ChatMessageRef;
  entity?: ProjectEntity;
}) {
  if (reference.flavor === "attachment" || reference.objectType === "design_asset") {
    const isAsset = reference.objectType === "design_asset";
    return (
      <ChatAttachment
        attachment={{
          id: reference.objectId,
          type: "file",
          filename: reference.label ?? (isAsset ? "Reference image" : "Attachment"),
          mediaType: reference.mediaType ?? (isAsset ? "image/png" : "application/octet-stream"),
          url: isAsset
            ? reference.thumbnailDigest ? designReferenceThumbnailUrl(reference.thumbnailDigest) : ""
            : reference.uploadId && !undrawableImage(reference.mediaType)
              ? chatUploadBytesUrl(reference.uploadId)
              : "",
        }}
      />
    );
  }

  const label = entity?.label ?? reference.label ?? contextLabels[reference.objectType] ?? "Reference";
  return (
    <span
      className={styles.chatMention}
      data-entity-id={reference.objectId}
      data-entity-type={reference.objectType}
      title={entity?.secondaryLabel ? `${label} · ${entity.secondaryLabel}` : label}
    >
      <ChatMentionVisual
        entityType={reference.objectType}
        icon={entity?.icon ?? (isWebsiteKind(reference.kind) ? "web" : undefined)}
        imagePath={entity?.imagePath}
        label={label}
      />
    </span>
  );
}

/** An image a browser cannot draw (HEIC, HEIF, TIFF): its chip shows the icon, not a broken thumbnail. */
function undrawableImage(mediaType: string | null | undefined): boolean {
  const type = (mediaType ?? "").toLowerCase();
  return type.startsWith("image/") && !canPreviewInBrowser(type);
}
