import type { ProjectDocument } from "@/features/projects/model/project-documents";
import type { ProjectArtifact } from "@/features/projects/model/project-workspace";
import type { ChatShellOpenArtifact } from "./chat-shell";

/**
 * Where a click on a gallery card lands.
 *
 * Lifted from the branch's chat-shell-view, which routes the card by its
 * document type: an **account-list** card (`type: "table"`) IS the project's
 * target-accounts table, so it opens the rail's own target-accounts SURFACE
 * rather than an artifact tab — there is no canvas to mount for it, and the
 * `website → web, else ad` kind derivation would otherwise file it under the ad
 * editor. Every other card opens exactly as it does today.
 *
 * The rule lives here, not in the component, so the chat surface only
 * transports it (the same discipline as `chat-dock` and `artifact-auto-open`)
 * and so it can be tested under the repo's DOM-less runner.
 */

/**
 * The slice of a feed card this decision reads. A `GalleryArtifact`'s `source`
 * satisfies it structurally — the narrow shape is so the rule states its own
 * inputs and the tests do not have to build whole gallery cards (the same shape
 * discipline as `AutoOpenFeedArtifact`).
 */
export interface GalleryCardArtifact {
  id: string;
  title: string;
  type?: ProjectArtifact["type"];
  document?: ProjectDocument;
}

export type GalleryCardTarget =
  | { artifact: ChatShellOpenArtifact; surface: "artifact" }
  | { surface: "target-accounts" }
  | { surface: "plan"; documentPath: string };

export function galleryCardTarget(
  card: GalleryCardArtifact,
): GalleryCardTarget {
  if (card.document) return { surface: "plan", documentPath: card.document.path };
  if (card.type === "table") return { surface: "target-accounts" };
  return {
    artifact: {
      id: card.id,
      // The gallery's own kind derivation, unchanged.
      kind: card.type === "website" ? "web" : "ad",
      title: card.title,
    },
    surface: "artifact",
  };
}
