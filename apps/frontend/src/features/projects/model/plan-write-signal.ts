import type { ChatStreamEvent } from "./chat-events";
import type { ChatTurn } from "./chat-turn";

/** One thread visit's Plan announcements, separate from rendering its replayed transcript. */
export class ProjectPlanWriteTracker {
  private readonly historyCursors = new Map<string, number>();
  private readonly seenParts = new Set<string>();

  seedHistory(turns: readonly Pick<ChatTurn, "turnId" | "lastEventId">[]): void {
    for (const turn of turns) {
      // Keep the first read's server cursor across reconnects. A later read may already
      // include a new write that the disconnected stream still owes this visit.
      if (!this.historyCursors.has(turn.turnId)) {
        this.historyCursors.set(turn.turnId, turn.lastEventId ?? 0);
      }
    }
  }

  observe(event: Pick<ChatStreamEvent, "type" | "part" | "eventId" | "turnId">): boolean {
    const { part, eventId } = event;
    if (
      eventId === null ||
      !["part.created", "part.updated", "part.completed"].includes(event.type) ||
      part?.kind !== "plan" ||
      part.planRef.objectType !== "project_document" ||
      !part.planRef.objectId
    ) return false;

    const seen = this.seenParts.has(part.partId);
    this.seenParts.add(part.partId);
    return !seen && eventId > (this.historyCursors.get(event.turnId) ?? 0);
  }
}
