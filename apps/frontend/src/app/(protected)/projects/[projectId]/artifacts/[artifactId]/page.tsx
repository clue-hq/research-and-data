import type { Metadata } from "next";
import { EditorSurface } from "@/features/chat-shell/components/editor-surface";

export const metadata: Metadata = {
  title: "Project artifact",
};

interface ProjectArtifactPageProps {
  params: Promise<{ artifactId: string; projectId: string }>;
}

export default async function ProjectArtifactPage({
  params,
}: ProjectArtifactPageProps) {
  const { artifactId, projectId } = await params;

  // W1 lands the artifact→document read seam; until then the editor shell
  // mounts with the dummy's own empty-state web artifact (geometry stable,
  // "Empty web output canvas", no data wired).
  return (
    <EditorSurface
      initial={{
        artifactId,
        openArtifacts: [{ id: artifactId, kind: "web", title: "Web output" }],
        projectId,
      }}
    />
  );
}
