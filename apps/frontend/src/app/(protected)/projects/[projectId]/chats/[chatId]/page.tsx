import type { Metadata } from "next";
import { ProjectWorkspaceShell } from "@/features/projects/components/project-workspace-shell";
import { getProjectWorkspace } from "@/features/projects/data/project-workspace.repository";

export const metadata: Metadata = {
  title: "Project chat",
};

interface ProjectChatPageProps {
  params: Promise<{ chatId: string; projectId: string }>;
  searchParams: Promise<{
    edit?: string;
    handoff?: string;
    selection?: string;
    surface?: string;
  }>;
}

export default async function ProjectChatPage({
  params,
  searchParams,
}: ProjectChatPageProps) {
  const [{ chatId, projectId }, query] = await Promise.all([
    params,
    searchParams,
  ]);
  // R2: surface/edit/selection are the ratified pane-state vocabulary. Only
  // surface=gallery is wired here; web|ad, edit, and selection are reserved
  // for the design-editor split view and intentionally unused in Phase R.
  const workspace = await getProjectWorkspace(projectId);

  return (
    <ProjectWorkspaceShell
      initial={{
        focusPane: query.surface === "gallery" ? "artifacts" : undefined,
        handoffId: query.handoff,
        threadId: chatId,
      }}
      projectId={projectId}
      workspace={workspace}
    />
  );
}
