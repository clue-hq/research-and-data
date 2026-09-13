import type { ProjectArtifact } from "@/features/projects/model/project-workspace";
import type { ChatShellOpenArtifact } from "./chat-shell";

/**
 * Agent-created or updated design files open beside Gallery (founder, 2026-09-14).
 * The feed identifies the document; a leg frame alone cannot. Seed IDs and update
 * timestamps at mount, then open each new file/version once. Cold backlog replay
 * and identical feed refreshes must not reopen a tab the user closed.
 */

/**
 * The slice of a feed card this decision reads. `ProjectArtifact` satisfies it
 * structurally — the narrow shape is so the rule states its own inputs and the
 * tests do not have to build whole gallery cards.
 */
export interface AutoOpenFeedArtifact {
  createdAt?: string;
  updatedAt?: string;
  id: string;
  originThreadId: string;
  title: string;
  type: ProjectArtifact["type"];
}

/** New/changed files from this chat only; newest update wins if several arrive together. */
export function artifactToAutoOpen({
  activeThreadId,
  artifacts,
  knownArtifactIds,
  knownUpdates,
}: {
  activeThreadId: string | null;
  artifacts: readonly AutoOpenFeedArtifact[];
  knownArtifactIds: ReadonlySet<string>;
  knownUpdates?: ReadonlyMap<string, string | undefined>;
}): ChatShellOpenArtifact | null {
  if (activeThreadId === null) return null;
  let winner: AutoOpenFeedArtifact | null = null;
  let winnerBornAt = Number.NEGATIVE_INFINITY;
  for (const artifact of artifacts) {
    if (knownArtifactIds.has(artifact.id) && (!artifact.updatedAt || !knownUpdates?.has(artifact.id) || knownUpdates.get(artifact.id) === artifact.updatedAt)) continue;
    if (artifact.originThreadId !== activeThreadId) continue;
    const bornAt = updatedAtOf(artifact);
    // Strictly greater: a tie leaves the earlier feed row in place.
    if (winner !== null && bornAt <= winnerBornAt) continue;
    winner = artifact;
    winnerBornAt = bornAt;
  }
  if (winner === null) return null;
  return {
    id: winner.id,
    kind: winner.type === "website" ? "web" : "ad",
    title: winner.title,
  };
}

/** Latest update, falling back to creation time; absent/unparseable ranks oldest. */
function updatedAtOf(artifact: AutoOpenFeedArtifact): number {
  const timestamp = artifact.updatedAt ?? artifact.createdAt;
  if (!timestamp) return Number.NEGATIVE_INFINITY;
  const parsed = Date.parse(timestamp);
  return Number.isNaN(parsed) ? Number.NEGATIVE_INFINITY : parsed;
}
