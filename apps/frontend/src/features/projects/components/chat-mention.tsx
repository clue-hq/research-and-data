"use client";

import Image from "next/image";
import { useState } from "react";
import { ContactAvatar } from "@/features/accounts/components/contact-avatar";
import type { ProjectEntity } from "../model/project-workspace";
import { ProjectIcon } from "./project-icon";
import styles from "./project-flow.module.css";

/** Shared identity treatment; Slate owns editing and the transcript stays read-only. */
export function ChatMentionVisual({
  entityType,
  icon,
  imagePath,
  label,
}: {
  entityType: string;
  icon?: ProjectEntity["icon"];
  imagePath?: string;
  label: string;
}) {
  const [failedImage, setFailedImage] = useState<string>();
  const typeIcon = icon ?? (entityType === "project_document"
    ? "file-text"
    : entityType === "design_document" || entityType === "design_node"
      ? "image"
      : entityType === "account" || entityType === "contact" ? undefined : "file-text");

  return (
    <span className={styles.chatMentionVisual}>
      {typeIcon ? (
        <ProjectIcon name={typeIcon} size={14} />
      ) : entityType === "contact" ? (
        <ContactAvatar name={label} size={16} src={imagePath} />
      ) : (
        <Image
          alt=""
          aria-hidden="true"
          className={styles.chatMentionLogo}
          height={16}
          onError={() => setFailedImage(imagePath)}
          src={imagePath && failedImage !== imagePath ? imagePath : "/icons/building.svg"}
          unoptimized
          width={16}
        />
      )}
      <span className={styles.chatMentionLabel}>{label}</span>
    </span>
  );
}
