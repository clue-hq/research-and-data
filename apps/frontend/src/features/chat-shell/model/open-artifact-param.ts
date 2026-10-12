import type { ProjectArtifact } from "@/features/projects/model/project-workspace";
import { chatShellKindForCard } from "./artifact-kind";
import type { ChatShellOpenArtifact } from "./chat-shell";

/**
 * `?open=<artifactId>` (ratified 2026-09-15): read once at mount, resolved against the project's
 * own feed so a foreign or stale id opens nothing, never written back. The superseded `?artifact=`
 * stays forbidden; documents keep `?document=`.
 */
export function openArtifactFromParam({ openId, artifacts }: {
  openId: string | null;
  artifacts: readonly Pick<ProjectArtifact, "id" | "title" | "type" | "documentKind">[];
}): ChatShellOpenArtifact | null {
  if (!openId) return null;
  const match = artifacts.find((artifact) => artifact.id === openId);
  if (!match) return null;
  return { id: match.id, kind: chatShellKindForCard(match), title: match.title };
}
