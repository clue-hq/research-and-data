import type { DesignDocumentKind } from "@/features/design-editor/model/artifact";
import type { ProjectArtifact } from "@/features/projects/model/project-workspace";
import type { ChatShellArtifactKind } from "./chat-shell";

/**
 * Contract 8: the ONE place a gallery/library card becomes an editor kind.
 *
 * A card that carries its document kind opens in exactly that editor. A card
 * without one (an older source, a fixture) keeps the gallery's historical
 * derivation — `website → web`, anything else → `ad` — which is exactly what the
 * four call sites did inline before `site` existed.
 */
export function chatShellKindForCard(card: {
  documentKind?: DesignDocumentKind;
  type?: ProjectArtifact["type"];
}): ChatShellArtifactKind {
  if (card.documentKind) return card.documentKind;
  return card.type === "website" ? "web" : "ad";
}

/** A website to the marketer, whichever engine draws it. */
export function isWebsiteKind(kind: string | null | undefined): kind is "web" | "site" {
  return kind === "web" || kind === "site";
}
