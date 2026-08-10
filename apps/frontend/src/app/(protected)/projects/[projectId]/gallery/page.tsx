import type { Metadata } from "next";
import { ProjectWorkspaceShell } from "@/features/projects/components/project-workspace-shell";
import { getProjectWorkspace } from "@/features/projects/data/project-workspace.repository";

export const metadata: Metadata = {
  title: "Project gallery",
};

interface ProjectGalleryPageProps {
  params: Promise<{ projectId: string }>;
  searchParams: Promise<{ thread?: string }>;
}

export default async function ProjectGalleryPage({
  params,
  searchParams,
}: ProjectGalleryPageProps) {
  const [{ projectId }, query] = await Promise.all([params, searchParams]);
  const workspace = await getProjectWorkspace(projectId);

  return (
    <ProjectWorkspaceShell
      initial={{
        threadId: query.thread,
      }}
      projectId={projectId}
      workspace={workspace}
    />
  );
}
