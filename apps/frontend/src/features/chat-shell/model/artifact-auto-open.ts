import type { ProjectArtifact } from "@/features/projects/model/project-workspace";
import { chatShellKindForCard } from "./artifact-kind";
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
  documentKind?: ProjectArtifact["documentKind"];
  updatedAt?: string;
  id: string;
  originThreadId: string;
  title: string;
  type: ProjectArtifact["type"];
}

/**
 * Every new/changed file from this chat, oldest-born first.
 *
 * One chat message can birth MANY documents on one design leg (one per target
 * account), so this returns the whole set rather than a single winner: each
 * born document gets its own tab. The order is the order they were born, and
 * documents born in the same instant keep the order the feed served them (the
 * sort is stable) — so the tab strip reads like the leg's own history.
 */
export function artifactsToAutoOpen({
  activeThreadId,
  artifacts,
  knownArtifactIds,
  knownUpdates,
  openArtifactIds,
}: {
  activeThreadId: string | null;
  artifacts: readonly AutoOpenFeedArtifact[];
  knownArtifactIds: ReadonlySet<string>;
  knownUpdates?: ReadonlyMap<string, string | undefined>;
  /**
   * The tabs already open. An UPDATED document that is already open needs no
   * opening — its canvas reloads on its own — and opening it again is not
   * harmless: the shell's `open-artifact` resets edit mode and the inspector
   * selection, so a person's own edit (which bumps the document's version and
   * therefore re-lists it as "updated") threw them out of edit mode on every
   * change (2026-09-20). A NEW document is never in this set, so births open
   * exactly as before.
   */
  openArtifactIds?: ReadonlySet<string>;
}): ChatShellOpenArtifact[] {
  if (activeThreadId === null) return [];
  const opening: AutoOpenFeedArtifact[] = [];
  for (const artifact of artifacts) {
    if (knownArtifactIds.has(artifact.id) && (!artifact.updatedAt || !knownUpdates?.has(artifact.id) || knownUpdates.get(artifact.id) === artifact.updatedAt)) continue;
    if (artifact.originThreadId !== activeThreadId) continue;
    if (openArtifactIds?.has(artifact.id)) continue;
    opening.push(artifact);
  }
  return opening
    .sort((left, right) => updatedAtOf(left) - updatedAtOf(right))
    .map((artifact) => ({
      id: artifact.id,
      kind: chatShellKindForCard(artifact),
      title: artifact.title,
    }));
}

/** Latest update, falling back to creation time; absent/unparseable ranks oldest. */
function updatedAtOf(artifact: AutoOpenFeedArtifact): number {
  const timestamp = artifact.updatedAt ?? artifact.createdAt;
  if (!timestamp) return Number.NEGATIVE_INFINITY;
  const parsed = Date.parse(timestamp);
  return Number.isNaN(parsed) ? Number.NEGATIVE_INFINITY : parsed;
}
