import type { ChatShellArtifactKind } from "./chat-shell";

export const ARTIFACT_PUBLISH_STATUSES = [
  "draft",
  "publishing",
  "published",
] as const;
export const ARTIFACT_SHARE_VIEWS = ["main", "advanced"] as const;
export const ARTIFACT_ADVANCED_TABS = ["page", "html"] as const;

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

export function slugifyArtifactTitle(title: string) {
  const slug = title
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 72);

  return slug || "untitled-artifact";
}

/** The host segment the share menu shows before the slug: the origin without its scheme
 * (`acme.pages.cluehq.ai`, or `acme.pages.localhost:8040` on the dev stack). */
export function publicLinkHost(origin: string | null): string {
  if (!origin) return "";
  return origin.replace(/^https?:\/\//, "").replace(/\/+$/, "");
}
