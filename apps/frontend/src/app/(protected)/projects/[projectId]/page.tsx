import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { ProjectWorkspaceShell } from "@/features/projects/components/project-workspace-shell";
import { getProjectWorkspace } from "@/features/projects/data/project-workspace.repository";
import { projectChatHref } from "@/features/chat-shell/model/chat-shell-routes";

export const metadata: Metadata = {
  title: "Project workspace",
};

interface ProjectPageProps {
  params: Promise<{ projectId: string }>;
  searchParams: Promise<{
    edit?: string;
    handoff?: string;
    selection?: string;
    surface?: string;
    thread?: string;
  }>;
}

// Phase R (ruling R1): /projects/{id} is the legacy absorber. A `?thread=`
// deep link redirects server-side to the canonical chats path before any
// fetch; a threadless visit renders the workspace, whose canonicalization
// rewrites the URL to /chats/{resolved} client-side — carrying the full
// query (including `surface=gallery`, the threadless-gallery intent per the
// R-4 amendment) through threadRouteHref.
export default async function ProjectPage({
  params,
  searchParams,
}: ProjectPageProps) {
  const [{ projectId }, query] = await Promise.all([params, searchParams]);

  if (query.thread) {
    redirect(
      projectChatHref(projectId, query.thread, {
        edit: query.edit,
        handoff: query.handoff,
        selection: query.selection,
        surface: query.surface,
      }),
    );
  }

  const workspace = await getProjectWorkspace(projectId);

  return (
    <ProjectWorkspaceShell
      initial={{
        edit: query.edit,
        handoffId: query.handoff,
        selection: query.selection,
        surface: query.surface,
      }}
      projectId={projectId}
      workspace={workspace}
    />
  );
}
