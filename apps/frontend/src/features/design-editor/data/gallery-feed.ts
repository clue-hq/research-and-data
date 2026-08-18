import type { ProjectArtifact } from "@/features/projects/model/project-workspace";
import { toProjectArtifact } from "../adapter/gallery";
import type { DesignArtifactRepository } from "./artifact.repository";

/**
 * The gallery's server-fetched data: the project's real cards plus the
 * artifact-id → design-document-id map every openable card needs (the W1.3
 * read seam's join). One shape, two mounts — the artifact route's
 * `EditorSurface` and the chats route's artifact rail consume it identically.
 */
export interface GalleryFeed {
  cards: ProjectArtifact[];
  documentIds: Record<string, string>;
}

const EMPTY_FEED: GalleryFeed = { cards: [], documentIds: {} };

/**
 * Slice 3 (gallery leg-derived feed), extracted for the chat-flow mount: the
 * project's design-artifact list — the gallery's data. The same refusal
 * posture as the single artifact resolve: any failure — the fetch OR the card
 * mapping (an unparseable timestamp throws in `toProjectArtifact`) — is an
 * empty feed, never a crash (a project with no legs is legitimately empty;
 * ruling 1).
 */
export async function loadGalleryFeed(
  repository: DesignArtifactRepository,
  projectId: string,
): Promise<GalleryFeed> {
  try {
    const listed = await repository.list(projectId);
    return {
      cards: listed.map((item) => toProjectArtifact(item)),
      documentIds: Object.fromEntries(
        listed.map((item) => [item.id, item.documentId]),
      ),
    };
  } catch {
    return EMPTY_FEED;
  }
}
