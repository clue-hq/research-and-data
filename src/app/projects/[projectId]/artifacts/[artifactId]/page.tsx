import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ProjectWorkspaceShell } from "@/features/projects/components/project-workspace-shell";
import { getProjectWorkspace } from "@/features/projects/data/project-workspace.repository";

export const metadata: Metadata = {
  title: "Project artifact",
};

interface ProjectArtifactPageProps {
  params: Promise<{ artifactId: string; projectId: string }>;
  searchParams: Promise<{ thread?: string }>;
}

export default async function ProjectArtifactPage({
  params,
  searchParams,
}: ProjectArtifactPageProps) {
  const [{ artifactId, projectId }, query] = await Promise.all([params, searchParams]);
  const workspace = await getProjectWorkspace(projectId);

  if (!workspace.artifacts.some((artifact) => artifact.id === artifactId)) {
    notFound();
  }

  return (
    <ProjectWorkspaceShell
      initial={{
        artifactId,
        phase: "complete",
        surface: "artifact",
        threadId: query.thread,
      }}
      workspace={workspace}
    />
  );
}
