import type { Metadata } from "next";
import { EditorSurface } from "@/features/chat-shell/components/editor-surface";
import { backendDesignArtifactRepository } from "@/features/design-editor/data/artifact.repository.server";
import type { DesignArtifactRepository } from "@/features/design-editor/data/artifact.repository";
import { loadGalleryFeed } from "@/features/design-editor/data/gallery-feed";
import type { ChatShellArtifact } from "@/features/design-editor/model/artifact";

export const metadata: Metadata = {
  title: "Project artifact",
};

interface ProjectArtifactPageProps {
  params: Promise<{ artifactId: string; projectId: string }>;
}

/**
 * W2.1: resolve the route's artifact through the W1.3 read seam, server-side
 * over the shared authenticated repository. Any refusal — not-found, auth
 * unavailable (fixture dev), backend unreachable — resolves to null and the
 * shell mounts the dummy's own empty-state artifact exactly as W0.4 shipped
 * it (geometry stable, nothing fabricated beyond the ratified "Web output"
 * placeholder). A RENDER failure, by contrast, is surfaced by the canvas's
 * error state.
 */
async function loadArtifact(
  repository: DesignArtifactRepository,
  projectId: string,
  artifactId: string,
): Promise<ChatShellArtifact | null> {
  try {
    return await repository.get(projectId, artifactId);
  } catch {
    return null;
  }
}

export default async function ProjectArtifactPage({
  params,
}: ProjectArtifactPageProps) {
  const { artifactId, projectId } = await params;
  const repository = backendDesignArtifactRepository();
  const [artifact, feed] = await Promise.all([
    loadArtifact(repository, projectId, artifactId),
    loadGalleryFeed(repository, projectId),
  ]);

  // Every listed document is openable from the gallery, so the id→document
  // map covers the whole feed, not just the route's artifact. The route
  // artifact may legitimately be absent from the feed (a legless document —
  // ruling 1's accepted gap); its own entry rides along regardless.
  const documentIds = { ...feed.documentIds };
  if (artifact) {
    documentIds[artifact.id] = artifact.documentId;
  }

  return (
    <EditorSurface
      artifacts={feed.cards}
      documentIds={documentIds}
      initial={{
        artifactId,
        openArtifacts: [
          artifact
            ? { id: artifact.id, kind: artifact.kind, title: artifact.title }
            : { id: artifactId, kind: "web", title: "Web output" },
        ],
        projectId,
      }}
    />
  );
}
