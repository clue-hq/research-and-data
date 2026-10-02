import type { ChatClarificationPart } from "./chat-parts";
import type { TranscriptMessage } from "./chat-transcript";
import type { TurnContextReference } from "./chat-turn";

/**
 * The client half of the clarification cards (spec 2026-09-20 §2.2–§2.3).
 *
 * Two questions live here, and nothing else: **which questions are still open**
 * — i.e. does the composer owe an answer right now — and **what the user's
 * answers read like as one ordinary chat message**.
 *
 * Both are pure functions over the transcript the surface already has, because
 * the answer is not a new backend verb: the card composes a normal message with
 * a `design_document` context ref per answered document and submits it through
 * the ordinary composer. Routing stays the exit judge's.
 */

/** One answer to one question, as the card collected it. */
export type ClarificationAnswer =
  | { kind: "option"; value: string }
  | { kind: "freeform"; value: string }
  | { kind: "skipped"; default: string };

/** The questions the composer owes an answer to, and the turn that asked them. */
export interface OpenClarification {
  turnId: string;
  parts: readonly ChatClarificationPart[];
}

/** A turn that is still producing may yet ask more; only a settled one is answerable. */
function isTerminal(state: TranscriptMessage["state"]): boolean {
  return state === "awaiting_input" || state === "completed";
}

/**
 * The clarification parts awaiting an answer, or `null` when none are.
 *
 * Open means all three of: the transcript's **last** message is the one that
 * asked (anything after it — the user's reply, a newer turn — closes the card,
 * which is how answering makes it disappear without a server round-trip), that
 * message is an assistant message whose turn has settled, and it carries at
 * least one clarification part. Older asking turns still render their parts,
 * read-only; they are simply never "open".
 */
export function openClarification(
  transcript: readonly TranscriptMessage[],
): OpenClarification | null {
  const last = transcript[transcript.length - 1];
  if (!last) return null;
  if (last.role !== "assistant") return null;
  if (!isTerminal(last.state)) return null;
  const parts = last.parts.filter(
    (part): part is ChatClarificationPart => part.kind === "clarification",
  );
  if (parts.length === 0) return null;
  return { turnId: last.turnId, parts };
}

/** The right-hand side of one bullet — the plan's Global Constraints, verbatim. */
function renderAnswer(answer: ClarificationAnswer): string {
  switch (answer.kind) {
    case "option":
      return answer.value;
    case "freeform":
      return `something else: ${answer.value}`;
    case "skipped":
      return `use your default (${answer.default})`;
  }
}

/**
 * The message the card sends, and the context refs that tell the agent which
 * documents it is about.
 *
 * ```
 * For "<title>":
 * - <question> — <answer>
 * - <question> — something else: <typed text>
 * - <question> — use your default (<default>)
 * ```
 *
 * Documents are separated by one blank line and keep the order they were given
 * in; each contributes one `design_document` ref in that same order. Questions
 * render in the part's own order, and a question with no entry in `answers` is
 * left out entirely — a document that answered nothing contributes neither a
 * block nor a ref, so the message never claims an answer that was not given.
 */
export function composeClarificationReply(
  items: ReadonlyArray<{
    part: ChatClarificationPart;
    answers: ReadonlyMap<string, ClarificationAnswer>;
  }>,
): { text: string; contextRefs: TurnContextReference[] } {
  const blocks: string[] = [];
  const contextRefs: TurnContextReference[] = [];

  for (const { part, answers } of items) {
    const lines: string[] = [];
    for (const question of part.questions) {
      const answer = answers.get(question.id);
      if (!answer) continue;
      lines.push(`- ${question.question} — ${renderAnswer(answer)}`);
    }
    if (lines.length === 0) continue;
    blocks.push([`For "${part.documentTitle}":`, ...lines].join("\n"));
    contextRefs.push({
      objectId: part.documentId,
      objectType: "design_document",
      version: null,
    });
  }

  return { text: blocks.join("\n\n"), contextRefs };
}
