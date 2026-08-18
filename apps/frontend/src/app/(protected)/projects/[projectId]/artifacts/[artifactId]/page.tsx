import type { Metadata } from "next";
import { fetchAuthenticatedClueBackend } from "@/auth/authenticated-backend";
import { EditorSurface } from "@/features/chat-shell/components/editor-surface";
import { toProjectArtifact } from "@/features/design-editor/adapter/gallery";
import {
  httpDesignArtifactRepository,
  type DesignArtifactRepository,
} from "@/features/design-editor/data/artifact.repository";
import type { ChatShellArtifact } from "@/features/design-editor/model/artifact";
import type { ProjectArtifact } from "@/features/projects/model/project-workspace";

export const metadata: Metadata = {
  title: "Project artifact",
};

interface ProjectArtifactPageProps {
  params: Promise<{ artifactId: string; projectId: string }>;
}

/**
 * W2.1: resolve the route's artifact through the W1.3 read seam, server-side
 * over the authenticated backend primitive (a Server Component cannot call
 * the origin-relative BFF; both paths share the same provider-proof and
 * workspace-header seam). Any refusal — not-found, auth unavailable (fixture
 * dev), backend unreachable — resolves to null and the shell mounts the
 * dummy's own empty-state artifact exactly as W0.4 shipped it (geometry
 * stable, nothing fabricated beyond the ratified "Web output" placeholder).
 * A RENDER failure, by contrast, is surfaced by the canvas's error state.
 */
function backendRepository(): DesignArtifactRepository {
  return httpDesignArtifactRepository({
    baseUrl: "",
    fetchImpl: (input, init) =>
      fetchAuthenticatedClueBackend(String(input), init),
  });
}

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

/**
 * Slice 3 (gallery leg-derived feed): the project's design-artifact list —
 * the gallery's data. The same refusal posture as the single resolve: any
 * failure — the fetch OR the card mapping (an unparseable timestamp throws
 * in `toProjectArtifact`) — is an empty feed, never a crash (a project with
 * no legs is legitimately empty; ruling 1).
 */
async function loadGalleryFeed(
  repository: DesignArtifactRepository,
  projectId: string,
): Promise<{ cards: ProjectArtifact[]; documentIds: Record<string, string> }> {
  try {
    const listed = await repository.list(projectId);
    return {
      cards: listed.map((item) => toProjectArtifact(item)),
      documentIds: Object.fromEntries(
        listed.map((item) => [item.id, item.documentId]),
      ),
    };
  } catch {
    return { cards: [], documentIds: {} };
  }
}

export default async function ProjectArtifactPage({
  params,
}: ProjectArtifactPageProps) {
  const { artifactId, projectId } = await params;
  const repository = backendRepository();
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
