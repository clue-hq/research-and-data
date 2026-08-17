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
  // R2: surface/edit/selection are the ratified pane-state vocabulary,
  // wired into the chat surface's artifact rail since Phase C (C-3):
  // surface=gallery opens the rail on the gallery, web|ad on the artifact
  // surface (?edit=1 → editing, ?selection= → inspector selection).
  const workspace = await getProjectWorkspace(projectId);

  return (
    <ProjectWorkspaceShell
      initial={{
        edit: query.edit,
        handoffId: query.handoff,
        selection: query.selection,
        surface: query.surface,
        threadId: chatId,
      }}
      projectId={projectId}
      workspace={workspace}
    />
  );
}
