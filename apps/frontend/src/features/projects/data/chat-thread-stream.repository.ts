import {
  parseChatStreamEvent,
  type ChatStreamEvent,
  type ChatStreamEventType,
} from "../model/chat-events";
import type { ChatTransport } from "./chat-api";
import {
  ChatStreamProtocolError,
  openTokenStream,
  type ChatStreamHandle,
} from "./chat-sse";

/**
 * The thread stream (CRM trial 1, F2): one per open, visible chat.
 *
 * It carries only the lifecycle frames (`turn.*`) of any turn in the thread,
 * so the chat learns that a turn exists even when it did not start it — a
 * wake turn the server queued, a message sent from another tab, a teammate.
 * The chat then attaches that turn's own stream for its parts and text. The
 * stream never ends by itself; the caller closes it when the thread changes or
 * the tab is hidden, and reopens it from its cursor.
 */

export interface ChatThreadStreamAttachment {
  projectId: string;
  threadId: string;
  /** Open after this cursor; `null` starts at the thread's tail. */
  lastEventId: number | null;
  /** A lifecycle frame of a turn in this thread. */
  onTurnEvent(event: ChatStreamEvent): void;
  /** The cursor was too old to replay: the caller re-reads the thread. */
  onReset(): void;
  /** The stream stopped and will not resume by itself. */
  onError?(error: unknown): void;
}

export interface ChatThreadStreamRepository {
  open(attachment: ChatThreadStreamAttachment): ChatStreamHandle;
}

const LIFECYCLE_EVENTS: ReadonlySet<ChatStreamEventType> = new Set<ChatStreamEventType>([
  "turn.accepted",
  "turn.started",
  "turn.awaiting_input",
  "turn.completed",
  "turn.failed",
  "turn.cancelled",
  "turn.retrying",
]);

function threadPath(projectId: string, threadId: string, suffix: string): string {
  return `/projects/${encodeURIComponent(projectId)}/threads/${encodeURIComponent(
    threadId,
  )}${suffix}`;
}

function frameType(data: unknown): unknown {
  return data !== null && typeof data === "object"
    ? (data as { type?: unknown }).type
    : undefined;
}

export function createHttpChatThreadStreamRepository(
  transport: Extract<ChatTransport, { mode: "http" }>,
): ChatThreadStreamRepository {
  return {
    open(attachment) {
      return openTokenStream({
        transport,
        mintPath: threadPath(attachment.projectId, attachment.threadId, "/stream_token"),
        eventsPath: threadPath(attachment.projectId, attachment.threadId, "/events"),
        lastEventId: attachment.lastEventId,
        onFrame(frame) {
          // The two connect frames name the thread but no turn, so they are
          // read here rather than through the turn-frame parser.
          const type = frameType(frame.data);
          if (type === "stream.hello") return "continue";
          if (type === "stream.reset") {
            attachment.onReset();
            return "restart-cursor";
          }
          const parsed = parseChatStreamEvent(frame.data, frame.event);
          if (!parsed.ok) {
            if (parsed.fatal) throw new ChatStreamProtocolError(parsed.reason);
            return "continue";
          }
          const event = parsed.event;
          if (
            event.projectId === attachment.projectId &&
            event.threadId === attachment.threadId &&
            LIFECYCLE_EVENTS.has(event.type)
          ) {
            attachment.onTurnEvent(event);
          }
          return "continue";
        },
        onError(error) {
          attachment.onError?.(error);
        },
      });
    },
  };
}

/** Fixtures have no other tabs and no server-started turns: nothing to hear. */
export function createFixtureChatThreadStreamRepository(): ChatThreadStreamRepository {
  return {
    open() {
      return { close() {} };
    },
  };
}
