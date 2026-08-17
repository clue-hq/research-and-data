import type { Metadata } from "next";
import { fetchAuthenticatedClueBackend } from "@/auth/authenticated-backend";
import { EditorSurface } from "@/features/chat-shell/components/editor-surface";
import { httpDesignArtifactRepository } from "@/features/design-editor/data/artifact.repository";
import type { ChatShellArtifact } from "@/features/design-editor/model/artifact";

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
async function loadArtifact(
  projectId: string,
  artifactId: string,
): Promise<ChatShellArtifact | null> {
  try {
    const repository = httpDesignArtifactRepository({
      baseUrl: "",
      fetchImpl: (input, init) =>
        fetchAuthenticatedClueBackend(String(input), init),
    });
    return await repository.get(projectId, artifactId);
  } catch {
    return null;
  }
}

export default async function ProjectArtifactPage({
  params,
}: ProjectArtifactPageProps) {
  const { artifactId, projectId } = await params;
  const artifact = await loadArtifact(projectId, artifactId);

  return (
    <EditorSurface
      documentIds={
        artifact ? { [artifact.id]: artifact.documentId } : undefined
      }
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
