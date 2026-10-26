import {
  TERMINAL_TURN_EVENTS,
  parseChatStreamEvent,
  type ChatStreamEvent,
} from "../model/chat-events";
import type { ChatTransport } from "./chat-api";
import {
  ChatStreamProtocolError,
  openTokenStream,
  type ChatStreamHandle,
} from "./chat-sse";
import type { FixtureChatState } from "./chat-fixture-state";
import { fixtureLaunchEvents, fixtureTurnEvents } from "./chat.fixture";

/**
 * The one place Clue SSE events become an ordered event stream for the feature.
 *
 * **Why not `EventSource`.** The stream is authorized by a short-lived,
 * single-use, workspace- and turn-scoped token that is *consumed* when the
 * stream opens (Lane B contract §5.5, implemented in `chat/stream.py`).
 * `EventSource` reconnects by re-requesting the same URL, which would present
 * the already-consumed token and be refused — its automatic reconnect is
 * structurally incompatible with a single-use token. So this reader owns the
 * loop: it mints a **fresh** token per attach, reads the body itself, and sends
 * `Last-Event-ID` as a header on the reconnect, which is the same cursor
 * `EventSource` would have sent and which the BFF explicitly forwards.
 *
 * **What the reader guarantees** (charter §§3.2/3.6):
 *
 * - *attach by cursor* — the first attach starts from the caller's cursor (the
 *   `last_event_id` the submissions-union read already gave it), so a cold load
 *   never replays a turn's whole history;
 * - *reconnect* — a dropped connection re-mints and re-attaches from the
 *   highest cursor actually applied, with bounded backoff, until the turn
 *   reaches a terminal event or the caller closes;
 * - *at-least-once* — duplicate frames are expected and are deduplicated by
 *   `event_id` in the reducer, not here, so a duplicate delivered across two
 *   different connections is handled identically to one delivered twice on one;
 * - *stream loss is never authoritative* — a fatal frame or an exhausted retry
 *   budget surfaces as a stream error, and the durable message read repairs the
 *   transcript. Nothing here can change a turn's outcome.
 */

export type { ChatStreamHandle };

export type ChatStreamCloseReason = "terminal" | "reset";

export interface ChatStreamAttachment {
  projectId: string;
  threadId: string;
  turnId: string;
  /** Attach *after* this cursor. `null` replays the turn from its first frame. */
  lastEventId: number | null;
  onEvent(event: ChatStreamEvent): void;
  /** Non-fatal frames this build could not read; the stream continues. */
  onWarning?(reason: string): void;
  /** The stream stopped and will not resume by itself. */
  onError?(error: unknown): void;
  /** The turn reached a terminal event, or reset requires durable rehydration. */
  onClosed?(reason: ChatStreamCloseReason): void;
}

export interface ChatStreamRepository {
  attach(attachment: ChatStreamAttachment): ChatStreamHandle;
}

function turnPath(
  projectId: string,
  threadId: string,
  turnId: string,
  suffix: string,
): string {
  return `/projects/${encodeURIComponent(projectId)}/threads/${encodeURIComponent(
    threadId,
  )}/turns/${encodeURIComponent(turnId)}${suffix}`;
}

export function createHttpChatStreamRepository(
  transport: Extract<ChatTransport, { mode: "http" }>,
): ChatStreamRepository {
  return {
    attach(attachment) {
      let terminal = false;
      return openTokenStream({
        transport,
        mintPath: turnPath(
          attachment.projectId,
          attachment.threadId,
          attachment.turnId,
          "/stream_token",
        ),
        eventsPath: turnPath(
          attachment.projectId,
          attachment.threadId,
          attachment.turnId,
          "/events",
        ),
        lastEventId: attachment.lastEventId,
        onFrame(frame) {
          const parsed = parseChatStreamEvent(frame.data, frame.event);
          if (!parsed.ok) {
            if (parsed.fatal) throw new ChatStreamProtocolError(parsed.reason);
            attachment.onWarning?.(parsed.reason);
            return "continue";
          }
          if (
            parsed.event.projectId !== attachment.projectId ||
            parsed.event.threadId !== attachment.threadId ||
            parsed.event.turnId !== attachment.turnId
          ) {
            throw new ChatStreamProtocolError("turn-stream frame identity mismatch");
          }
          // A connect-time `stream.reset` restarts the backlog from zero, and
          // the durable read repairs the transcript, so the stream ends here.
          const reset =
            parsed.event.type === "stream.reset" && parsed.event.eventId === null;
          terminal = isTerminal(parsed.event);
          attachment.onEvent(parsed.event);
          return terminal || reset ? "stop" : "continue";
        },
        onError(error) {
          attachment.onError?.(error);
        },
        onStopped() {
          attachment.onClosed?.(terminal ? "terminal" : "reset");
        },
      });
    },
  };
}

function isTerminal(event: ChatStreamEvent): boolean {
  return TERMINAL_TURN_EVENTS.has(event.type);
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * The fixture stream.
 *
 * The delay between frames is **transport simulation**, not a lifecycle model:
 * it stands in for network arrival so the streaming presentation can be seen
 * without a backend. Every state the surface renders still comes from a frame
 * — nothing here advances a phase because time passed, which is precisely the
 * Figma doc's rule that prototype timeouts must not become the lifecycle.
 */
export function createFixtureChatStreamRepository(
  state: FixtureChatState,
  { frameDelayMs = 45 }: { frameDelayMs?: number } = {},
): ChatStreamRepository {
  return {
    attach(attachment) {
      let closed = false;
      // Which script a turn plays is decided by what was *submitted*, never by
      // how many times it has been attached: a replayed backlog must reproduce
      // the same frames, or reconnect would be a different conversation.
      const script =
        state.scripts.get(attachment.turnId) === "launch"
          ? fixtureLaunchEvents(attachment.turnId)
          : fixtureTurnEvents(attachment.turnId);

      void (async () => {
        for (const payload of script) {
          if (closed) return;
          await delay(frameDelayMs);
          if (closed) return;
          const parsed = parseChatStreamEvent(payload);
          if (!parsed.ok) {
            attachment.onWarning?.(parsed.reason);
            continue;
          }
          const eventId = parsed.event.eventId;
          if (
            attachment.lastEventId !== null &&
            eventId !== null &&
            eventId <= attachment.lastEventId
          ) {
            continue; // attach by cursor, exactly as the backlog read does
          }
          attachment.onEvent(parsed.event);
        }
        if (!closed) attachment.onClosed?.("terminal");
      })();

      return {
        close() {
          closed = true;
        },
      };
    },
  };
}
