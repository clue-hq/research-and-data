import type { ChatPart } from "./chat-parts";
import type { TranscriptTurnState } from "./chat-transcript";

/** One disclosure per response; the stream reducer still owns part identity/retries. */
export function presentChatReasoning(
  parts: readonly ChatPart[],
  turnState: TranscriptTurnState,
) {
  const rounds = parts.filter((part) => part.kind === "reasoning");
  const running = turnState === "running";
  return {
    active: running && rounds.some((part) => part.state === "active"),
    running,
    // Preserve the provider's text verbatim, including Markdown punctuation.
    text: rounds.flatMap((part) => part.text?.trim() ? [part.text] : []).join("\n\n"),
    ephemeral: rounds.some((part) => Boolean(part.text) && part.textEphemeral),
  };
}
