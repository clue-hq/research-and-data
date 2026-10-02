/**
 * When does the rail open the Target accounts surface by itself? (spec 2026-09-12 §4)
 *
 * The moment the stream delivers a **completed** `launch_arv2_discovery` tool part on this
 * thread — the same discipline as `artifact-auto-open`: the caller banks every tool call id it
 * has seen, so a cold load's replayed backlog opens nothing and a launch opens the surface once.
 * A refused launch (`output-error`/`output-denied`) produces no run and opens nothing.
 */
export const DISCOVERY_LAUNCH_TOOL = "launch_arv2_discovery";

/** The slice of a transcript message this decision reads; `TranscriptMessage` satisfies it. */
export interface LaunchSignalMessage {
  parts: readonly {
    kind: string;
    toolName?: string;
    toolCallId?: string;
    state?: string;
  }[];
}

/**
 * The tool call id of a launch that should open the surface, or `null` — the resting answer.
 *
 * The scan is transcript order and the first match wins: a thread with two fresh launches
 * opens one surface, not a stack of them, and the caller banks the rest.
 */
export function discoveryLaunchToOpen({
  transcript,
  knownToolCallIds,
}: {
  transcript: readonly LaunchSignalMessage[];
  knownToolCallIds: ReadonlySet<string>;
}): string | null {
  for (const message of transcript) {
    for (const part of message.parts) {
      if (part.kind !== "tool" || part.toolName !== DISCOVERY_LAUNCH_TOOL)
        continue;
      if (part.state !== "output-available" || !part.toolCallId) continue;
      if (knownToolCallIds.has(part.toolCallId)) continue;
      return part.toolCallId;
    }
  }
  return null;
}
