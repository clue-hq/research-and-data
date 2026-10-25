"use client";
import { useDirectMail } from "../hooks/use-direct-mail";
import { ProjectMailPlan } from "./project-mail-plan";

/** A linked mailer is a physical-send record, not a design-editor artifact. */
export function DirectMailProjectLink({ projectId }: { projectId?: string; threadId?: string | null }) {
  const c = useDirectMail();
  if (!c.enabled || !projectId || !c.data) return null;
  const mailers = c.data.mailers.filter((m) => m.projectId === projectId);
  if (!mailers.length) return null;
  return <ProjectMailPlan controller={c} projectId={projectId} compact />;
}
