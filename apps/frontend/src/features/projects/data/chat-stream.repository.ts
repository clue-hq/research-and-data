import { z } from "zod";
import {
  SseFrameReader,
  parseChatStreamEvent,
  type ChatStreamEvent,
} from "../model/chat-events";
import {
  ClueChatApiError,
  chatRequest,
  chatUrl,
  refusalOf,
  type ChatTransport,
} from "./chat-api";
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

const StreamTokenSchema = z
  .object({
    data: z.object({
      schema_version: z.string(),
      stream_token: z.string().min(1),
      turn_id: z.string().min(1),
    }),
  })
  .transform((wire) => wire.data.stream_token);

export interface ChatStreamHandle {
  close(): void;
}

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
  /** The turn reached a terminal event, or the server closed a finished stream. */
  onClosed?(): void;
}

export interface ChatStreamRepository {
  attach(attachment: ChatStreamAttachment): ChatStreamHandle;
}

const MAX_RECONNECT_ATTEMPTS = 6;
const BACKOFF_MS = [250, 500, 1000, 2000, 4000, 8000];

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
      const controller = new AbortController();
      let closed = false;
      // The cursor the *reducer* would send: the highest event actually
      // delivered to the consumer, not the highest the server mentioned.
      let cursor = attachment.lastEventId;
      let terminal = false;

      const close = () => {
        if (closed) return;
        closed = true;
        controller.abort();
      };

      void (async () => {
        for (let attempt = 0; attempt <= MAX_RECONNECT_ATTEMPTS; attempt += 1) {
          if (closed || terminal) break;
          try {
            const token = StreamTokenSchema.parse(
              await chatRequest(
                transport,
                turnPath(
                  attachment.projectId,
                  attachment.threadId,
                  attachment.turnId,
                  "/stream_token",
                ),
                { method: "POST", signal: controller.signal },
              ),
            );
            const headers = new Headers({ Accept: "text/event-stream" });
            if (cursor !== null && cursor > 0) {
              headers.set("Last-Event-ID", String(cursor));
            }
            const response = await fetch(
              chatUrl(
                transport,
                turnPath(
                  attachment.projectId,
                  attachment.threadId,
                  attachment.turnId,
                  "/events",
                ),
                { stream_token: token },
              ),
              { headers, cache: "no-store", signal: controller.signal },
            );
            if (!response.ok) throw await refusalOf(response);
            if (!response.body) throw new Error("the turn stream returned no body");

            attempt = -1; // a successful attach resets the backoff budget
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            const frames = new SseFrameReader();
            for (;;) {
              const chunk = await reader.read();
              if (chunk.done) break;
              for (const frame of frames.push(
                decoder.decode(chunk.value, { stream: true }),
              )) {
                const parsed = parseChatStreamEvent(safeJson(frame.data));
                if (!parsed.ok) {
                  if (parsed.fatal) throw new Error(parsed.reason);
                  attachment.onWarning?.(parsed.reason);
                  continue;
                }
                if (parsed.event.eventId !== null) {
                  cursor = Math.max(cursor ?? 0, parsed.event.eventId);
                }
                // A connect-time `stream.reset` restarts the backlog from zero,
                // so the reconnect cursor must go with it or the repaired
                // stream would resume past the events it was told to re-read.
                if (
                  parsed.event.type === "stream.reset" &&
                  parsed.event.eventId === null
                ) {
                  cursor = 0;
                }
                if (isTerminal(parsed.event)) terminal = true;
                attachment.onEvent(parsed.event);
              }
            }
            if (terminal || closed) break;
          } catch (error) {
            if (closed || isAbort(error)) break;
            if (
              error instanceof ClueChatApiError &&
              (error.status === 401 || error.status === 403 || error.status === 404)
            ) {
              attachment.onError?.(error);
              return;
            }
            if (attempt >= MAX_RECONNECT_ATTEMPTS) {
              attachment.onError?.(error);
              return;
            }
            await delay(BACKOFF_MS[Math.max(0, attempt)] ?? 8000);
          }
        }
        if (!closed) attachment.onClosed?.();
      })();

      return { close };
    },
  };
}

function isTerminal(event: ChatStreamEvent): boolean {
  return (
    event.type === "turn.completed" ||
    event.type === "turn.failed" ||
    event.type === "turn.cancelled" ||
    event.type === "turn.awaiting_input"
  );
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
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
        if (!closed) attachment.onClosed?.();
      })();

      return {
        close() {
          closed = true;
        },
      };
    },
  };
}
