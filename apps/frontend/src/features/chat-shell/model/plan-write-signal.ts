export const PLAN_PART_OBJECT_TYPE = "project_document";

export interface PlanSignalMessage {
  id: string;
  parts: readonly { kind: string; partId: string; planRef?: { objectType: string | null } }[];
}

export function projectPlanPartIds(transcript: readonly PlanSignalMessage[]): string[] {
  return transcript.flatMap((message) => message.parts.flatMap((part) =>
    part.kind === "plan" && part.planRef?.objectType === PLAN_PART_OBJECT_TYPE ? [part.partId] : []));
}

/** Null means history has not yet been banked. Never infer plan writes from tool names. */
export function planWriteToOpen({ transcript, knownPlanPartIds, historyStartId }: {
  transcript: readonly PlanSignalMessage[]; knownPlanPartIds: ReadonlySet<string> | null;
  historyStartId?: string;
}): string | null {
  if (knownPlanPartIds === null) return null;
  // Pagination prepends old messages before the initial history boundary. Bank them without
  // mistaking their plan parts for a new write. An initially empty chat has no boundary.
  const start = historyStartId ? Math.max(0, transcript.findIndex((message) => message.id === historyStartId)) : 0;
  const ids = projectPlanPartIds(transcript.slice(start));
  return ids.findLast((id) => !knownPlanPartIds.has(id)) ?? null;
}
