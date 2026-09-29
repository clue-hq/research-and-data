import type {
  ChatPart,
  ChatTaskPart,
  TaskState,
} from "./chat-parts";

/**
 * The research-execution task model (Figma `136:2`, charter §3.4).
 *
 * The design rule this file exists to enforce: **a run remains one visible
 * research task whether it covers one account or 500.** Worker and
 * account-level jobs are aggregated behind that task, so scale changes the
 * counts and the expandable detail — never the visible hierarchy.
 *
 * The second rule is that progression is **event-driven**. The Figma prototype
 * advances Scoping → Light research → … on timeouts; those timings communicate
 * the intended feel and must not become the lifecycle. Nothing in this file
 * reads a clock: every state comes from a `task` part the backend emitted.
 */

export type ResearchActivity =
  | "queued"
  | "scoping"
  | "light_research"
  | "checkpoint"
  | "deep_research"
  | "synthesizing"
  | "complete"
  | "partial"
  | "needs_input"
  | "failed"
  | "suspended";

/** The eight activity states the component library draws, plus the three terminals. */
const ACTIVITY_BY_STATE: Record<TaskState, ResearchActivity> = {
  queued: "queued",
  scoping: "scoping",
  light_research: "light_research",
  checkpoint: "checkpoint",
  deep_research: "deep_research",
  synthesizing: "synthesizing",
  needs_input: "needs_input",
  partial: "partial",
  completed: "complete",
  failed: "failed",
  suspended: "suspended",
};

const ACTIVITY_LABELS: Record<ResearchActivity, string> = {
  queued: "Queued",
  scoping: "Scoping",
  light_research: "Light research",
  checkpoint: "Checkpoint",
  deep_research: "Deep research",
  synthesizing: "Synthesizing",
  complete: "Complete",
  partial: "Partial results preserved",
  needs_input: "Needs input",
  failed: "Failed",
  suspended: "Suspended",
};

/** The happy path, in order. Used for the progress rail, never for progression. */
export const RESEARCH_PHASES: readonly ResearchActivity[] = [
  "scoping",
  "light_research",
  "checkpoint",
  "deep_research",
  "synthesizing",
  "complete",
];

/** States where work is actually moving — the only place a loader may spin. */
const ACTIVE: ReadonlySet<ResearchActivity> = new Set([
  "queued",
  "scoping",
  "light_research",
  "deep_research",
  "synthesizing",
]);

/** States where the run is waiting on a human, not on a worker. */
const BLOCKED: ReadonlySet<ResearchActivity> = new Set([
  "checkpoint",
  "needs_input",
]);

export interface ResearchTaskStep {
  id: string;
  label: string;
  count: number;
  tone: "queued" | "running" | "complete" | "partial" | "blocked" | "failed";
}

export interface ResearchTaskModel {
  partId: string;
  runId: string | null;
  title: string;
  activity: ResearchActivity;
  label: string;
  /** True only while a worker is moving; drives the loader and Shimmer. */
  running: boolean;
  /** True when the run is waiting on the user (checkpoint / needs input). */
  blocked: boolean;
  terminal: boolean;
  /** Position on the happy-path rail, or `null` for a recovery state. */
  phaseIndex: number | null;
  total: number;
  steps: readonly ResearchTaskStep[];
  exceptionCount: number;
  /** "12 of 500 accounts complete" — the one line that scales to 500. */
  summary: string;
}

function accountWord(count: number): string {
  return count === 1 ? "account" : "accounts";
}

export function researchTaskModel(part: ChatTaskPart): ResearchTaskModel {
  const activity = ACTIVITY_BY_STATE[part.state];
  const counts = part.counts;
  const steps: ResearchTaskStep[] = (
    [
      { id: "queued", label: "Queued", count: counts.queued, tone: "queued" },
      { id: "running", label: "Researching", count: counts.running, tone: "running" },
      { id: "completed", label: "Complete", count: counts.completed, tone: "complete" },
      {
        id: "partial",
        label: "Partial",
        // The backend counts a reviewable subject apart from a shortfall; the card has one
        // designed row for "finished, but not with everything", so both land in it.
        count: counts.partial + counts.needsReview,
        tone: "partial",
      },
      { id: "blocked", label: "Blocked", count: counts.blocked, tone: "blocked" },
      { id: "failed", label: "Failed", count: counts.failed, tone: "failed" },
    ] as const
  )
    .filter((step) => step.count > 0)
    .map((step) => ({ ...step }));

  const phaseIndex = RESEARCH_PHASES.indexOf(activity);
  // Settled is every subject that stopped moving — a reviewable one has, so leaving it out would
  // stall the line at "2 of 3" on a run that has finished.
  const settled = counts.completed + counts.partial + counts.needsReview;
  const summary =
    counts.total > 0
      ? `${settled} of ${counts.total} ${accountWord(counts.total)} ${
          activity === "complete" ? "researched" : "settled"
        }`
      : ACTIVITY_LABELS[activity];

  return {
    partId: part.partId,
    runId: part.runRef.objectId,
    title: part.title,
    activity,
    label: ACTIVITY_LABELS[activity],
    running: ACTIVE.has(activity),
    blocked: BLOCKED.has(activity),
    terminal:
      activity === "complete" ||
      activity === "partial" ||
      activity === "failed" ||
      activity === "suspended",
    phaseIndex: phaseIndex === -1 ? null : phaseIndex,
    total: counts.total,
    steps,
    exceptionCount: part.exceptionRefs.length,
    summary,
  };
}

/**
 * Collapse every task part of a message into one visible task per run.
 *
 * Two parts can legitimately name the same run — a launch narration and a later
 * progress snapshot — and the design contract is one card, so the higher
 * revision wins and the order of first appearance is preserved.
 */
export function aggregateResearchTasks(
  parts: readonly ChatPart[],
): ResearchTaskModel[] {
  const byRun = new Map<string, ChatTaskPart>();
  const order: string[] = [];
  for (const part of parts) {
    if (part.kind !== "task") continue;
    const key = part.runRef.objectId ?? part.partId;
    const existing = byRun.get(key);
    if (!existing) order.push(key);
    if (!existing || existing.revision <= part.revision) byRun.set(key, part);
  }
  return order.map((key) => researchTaskModel(byRun.get(key) as ChatTaskPart));
}

export function researchActivityLabel(activity: ResearchActivity): string {
  return ACTIVITY_LABELS[activity];
}
