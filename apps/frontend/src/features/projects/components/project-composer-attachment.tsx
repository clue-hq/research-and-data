import {
  Attachment,
  AttachmentHoverCard,
  AttachmentHoverCardContent,
  AttachmentHoverCardTrigger,
  AttachmentInfo,
  AttachmentPreview,
  AttachmentRemove,
  getAttachmentLabel,
  getMediaCategory,
} from "@/components/ai-elements/attachments";
import type { ProjectComposerAttachment as ProjectComposerAttachmentData } from "../model/project-composer";

export function ProjectComposerAttachment({
  attachment,
  onRemove,
}: {
  attachment: ProjectComposerAttachmentData;
  onRemove: (attachmentId: string) => void;
}) {
  const label = getAttachmentLabel(attachment);
  const mediaCategory = getMediaCategory(attachment);

  return (
    <AttachmentHoverCard>
      <AttachmentHoverCardTrigger
        closeDelay={100}
        delay={250}
        render={<div className="w-fit" />}
      >
        <Attachment
          aria-busy={attachment.status === "uploading"}
          aria-invalid={attachment.status === "failed" || undefined}
          data={attachment}
          onRemove={() => onRemove(attachment.id)}
        >
          <div className="relative size-5 shrink-0">
            <div className="absolute inset-0 transition-opacity group-hover:opacity-0">
              <AttachmentPreview />
            </div>
            <AttachmentRemove
              className="absolute inset-0"
              label={`Remove ${attachment.filename}`}
            />
          </div>
          <AttachmentInfo
            className={attachment.status === "failed" ? "text-destructive" : undefined}
          />
        </Attachment>
      </AttachmentHoverCardTrigger>
      <AttachmentHoverCardContent>
        <div className="space-y-2">
          {mediaCategory === "image" && attachment.url ? (
            // AI Elements accepts blob URLs from the local file picker.
            // eslint-disable-next-line @next/next/no-img-element
            <img
              alt={label}
              className="max-h-64 w-64 rounded-md object-contain"
              src={attachment.url}
            />
          ) : null}
          <div className="space-y-1 px-0.5">
            <p className="font-medium text-sm leading-none">{label}</p>
            <p className="text-muted-foreground text-xs">{attachment.mediaType}</p>
            {attachment.status === "uploading" ? (
              <p className="text-muted-foreground text-xs" role="status">
                Uploading…
              </p>
            ) : null}
            {attachment.status === "failed" ? (
              <p className="text-destructive text-xs" role="alert">
                {attachment.error ?? "Upload failed."}
              </p>
            ) : null}
          </div>
        </div>
      </AttachmentHoverCardContent>
    </AttachmentHoverCard>
  );
}
