import type { Metadata } from "next";
import { ProjectWorkspaceShell } from "@/features/projects/components/project-workspace-shell";
import { getProjectWorkspace } from "@/features/projects/data/project-workspace.repository";
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
  const phase = ProjectPhaseSchema.safeParse(query.phase);

  return (
    <ProjectWorkspaceShell
      initial={{
        entityIds: query.entities?.split(",").filter(Boolean),
        modelId: query.model,
        phase: phase.success ? phase.data : "conversation",
        prompt: query.prompt,
        surface: "gallery",
        threadId: query.thread,
      }}
      workspace={{
        ...workspace,
        prompt: query.prompt?.trim() || workspace.prompt,
      }}
    />
  );
}
