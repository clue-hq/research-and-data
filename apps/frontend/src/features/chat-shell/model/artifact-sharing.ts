import type { ChatShellArtifactKind } from "./chat-shell";

export const ARTIFACT_SHARE_EXPORT_FORMATS = ["ZIP", "PDF"] as const;
export const ARTIFACT_PUBLISH_STATUSES = [
  "draft",
  "publishing",
  "published",
] as const;
export const ARTIFACT_SHARE_VIEWS = ["main", "advanced"] as const;
export const ARTIFACT_ADVANCED_TABS = ["page", "html"] as const;

export type ArtifactShareExportFormat =
  (typeof ARTIFACT_SHARE_EXPORT_FORMATS)[number];
export type ArtifactPublishStatus =
  (typeof ARTIFACT_PUBLISH_STATUSES)[number];
export type ArtifactShareView = (typeof ARTIFACT_SHARE_VIEWS)[number];
export type ArtifactAdvancedTab = (typeof ARTIFACT_ADVANCED_TABS)[number];

export interface ArtifactPublishSettings {
  allowIndexing: boolean;
  customHtml: string;
  description: string;
  regenerateDescriptionOnPublish: boolean;
  slug: string;
  title: string;
}

export interface ArtifactPublishRequest {
  kind: ChatShellArtifactKind;
  settings: ArtifactPublishSettings;
}

export interface ArtifactShareExportRequest {
  format: ArtifactShareExportFormat;
  kind: ChatShellArtifactKind;
}

export function slugifyArtifactTitle(title: string) {
  const slug = title
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 72);

  return slug || "untitled-artifact";
}
