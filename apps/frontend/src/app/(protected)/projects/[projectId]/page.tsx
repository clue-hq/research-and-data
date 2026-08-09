import type { Metadata } from "next";
import { ProjectWorkspaceShell } from "@/features/projects/components/project-workspace-shell";
import { getProjectWorkspace } from "@/features/projects/data/project-workspace.repository";
import { resolveChatTransport } from "@/features/projects/data/chat-api";
import { ProjectPhaseSchema } from "@/features/projects/model/project-workspace";

export const metadata: Metadata = {
  title: "Project workspace",
};

interface ProjectPageProps {
  params: Promise<{ projectId: string }>;
  searchParams: Promise<{
    entities?: string;
    model?: string;
    phase?: string;
    prompt?: string;
    thread?: string;
  }>;
}

export default async function ProjectPage({ params, searchParams }: ProjectPageProps) {
  const [{ projectId }, query] = await Promise.all([params, searchParams]);
  const workspace = await getProjectWorkspace(projectId);
  const fixturePreview = resolveChatTransport().mode === "fixture";
  const phase = ProjectPhaseSchema.safeParse(
    fixturePreview ? query.phase : undefined,
  );

  return (
    <ProjectWorkspaceShell
      initial={{
        entityIds: fixturePreview
          ? query.entities?.split(",").filter(Boolean)
          : undefined,
        modelId: fixturePreview ? query.model : undefined,
        phase: phase.success ? phase.data : "conversation",
        prompt: fixturePreview ? query.prompt : undefined,
        surface: "gallery",
        threadId: query.thread,
      }}
      projectId={projectId}
      workspace={workspace && fixturePreview
        ? { ...workspace, prompt: query.prompt?.trim() || workspace.prompt }
        : workspace}
    />
  );
}
