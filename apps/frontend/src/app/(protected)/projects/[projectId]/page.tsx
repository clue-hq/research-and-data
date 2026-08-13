import type { Metadata } from "next";
import { ProjectWorkspaceShell } from "@/features/projects/components/project-workspace-shell";
import { getProjectWorkspace } from "@/features/projects/data/project-workspace.repository";

export const metadata: Metadata = {
  title: "Project workspace",
};

interface ProjectPageProps {
  params: Promise<{ projectId: string }>;
  searchParams: Promise<{ handoff?: string; thread?: string }>;
}

export default async function ProjectPage({ params, searchParams }: ProjectPageProps) {
  const [{ projectId }, query] = await Promise.all([params, searchParams]);
  const workspace = await getProjectWorkspace(projectId);

  return (
    <ProjectWorkspaceShell
      initial={{
        handoffId: query.handoff,
        threadId: query.thread,
      }}
      projectId={projectId}
      workspace={workspace}
    />
  );
}
