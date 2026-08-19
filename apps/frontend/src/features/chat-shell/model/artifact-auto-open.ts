import type { ProjectArtifact } from "@/features/projects/model/project-workspace";
import type { ChatShellOpenArtifact } from "./chat-shell";

/**
 * Founder ruling F2 **(b)**, 2026-08-19 — superseding option (a) for v1: when a
 * design leg births its web document, the artifact tab opens **by itself** next
 * to the Gallery, so the user watches the page land instead of hunting for the
 * card. This module is the whole decision; the chat surface only transports it.
 *
 * The crux is what the rule may key off. The `leg.opened` frame carries only
 * `{leg_id}` — it names no document — so the frame cannot say *what* to open.
 * What it does do (slice 3) is refresh the gallery feed, and the born document
 * arrives in the page's `artifacts` props on its own. So the trigger is the
 * feed, not the frame: **an artifact id that was not in the feed when this page
 * mounted**.
 *
 * That distinction is load-bearing, not stylistic. On a cold load the replayed
 * backlog re-fires `leg.opened` and one redundant `router.refresh()`; keying off
 * the frame would re-open the tab on every single page load of a design thread.
 * Keying off "new since mount" is correct on both cold load and live birth, and
 * it handles `leg.reopened` for free — a reopen births no document, so the feed
 * it refreshes contains nothing this page has not already seen.
 */

/**
 * The slice of a feed card this decision reads. `ProjectArtifact` satisfies it
 * structurally — the narrow shape is so the rule states its own inputs and the
 * tests do not have to build whole gallery cards.
 */
export interface AutoOpenFeedArtifact {
  createdAt?: string;
  id: string;
  originThreadId: string;
  title: string;
  type: ProjectArtifact["type"];
}

/**
 * The artifact tab to open by itself, or `null` — the resting answer.
 *
 * Three conditions, all required: there is an active thread; the artifact was
 * **not** in the feed at mount (`knownArtifactIds`, which the caller also grows
 * with everything it has since seen, so one document opens at most once and a
 * tab the user closed stays closed); and the artifact belongs to the active
 * thread (`originThreadId`) — a sibling thread's document must never steal this
 * pane.
 *
 * When more than one document is new at once the pick is deterministic: the
 * newest `createdAt` wins; a card with no usable timestamp ranks oldest (it
 * still opens when it is the only candidate); an exact tie is broken by feed
 * order, first wins — the feed is served newest-updated-first, so the first row
 * of a tie is the most recently touched one. Only one opens: auto-opening a
 * fistful of tabs is not "watch the page land".
 *
 * The kind derivation is the gallery's own (`website` → web, else ad) rather
 * than a second copy of the rule.
 */
export function artifactToAutoOpen({
  activeThreadId,
  artifacts,
  knownArtifactIds,
}: {
  activeThreadId: string | null;
  artifacts: readonly AutoOpenFeedArtifact[];
  knownArtifactIds: ReadonlySet<string>;
}): ChatShellOpenArtifact | null {
  if (activeThreadId === null) return null;
  let winner: AutoOpenFeedArtifact | null = null;
  let winnerBornAt = Number.NEGATIVE_INFINITY;
  for (const artifact of artifacts) {
    if (knownArtifactIds.has(artifact.id)) continue;
    if (artifact.originThreadId !== activeThreadId) continue;
    const bornAt = bornAtOf(artifact);
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

/** `createdAt` as a comparable instant; absent or unparseable ranks oldest. */
function bornAtOf(artifact: AutoOpenFeedArtifact): number {
  if (artifact.createdAt === undefined) return Number.NEGATIVE_INFINITY;
  const parsed = Date.parse(artifact.createdAt);
  return Number.isNaN(parsed) ? Number.NEGATIVE_INFINITY : parsed;
}
