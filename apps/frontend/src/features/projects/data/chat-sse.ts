import { z } from "zod";
import { SseFrameReader } from "../model/chat-events";
import {
  ClueChatApiError,
  chatRefusalOf,
  chatRequest,
  chatUrl,
  withPageWorkspace,
  type ChatTransport,
} from "./chat-api";

/**
 * The token → fetch → parse → reconnect loop shared by the turn stream and the
 * thread stream (CRM trial 1, F2).
 *
 * Both streams are authorized by a short-lived, single-use token that is
 * consumed when the stream opens, so `EventSource` cannot be used: its
 * automatic reconnect re-presents the consumed token. This loop mints a fresh
 * token per connect, reads the body itself, and sends `Last-Event-ID` as a
 * header on the reconnect.
 *
 * - Frames are handed to `onFrame` in order. It decides what each means and
 *   answers `"continue"` or `"stop"` (the stream is done; no reconnect). It
 *   may throw {@link ChatStreamProtocolError} for a frame that must end the
 *   stream.
 * - A dropped or cleanly ended connection reconnects from the highest event id
 *   delivered, with bounded backoff. A connection that stayed open for
 *   {@link HEALTHY_CONNECTION_MS} restarts the backoff, so a long-lived stream
 *   cut by a proxy now and then never runs out of retries; one that keeps
 *   failing at once gives up and calls `onError`.
 * - 401/403/404 and protocol errors are final: `onError`, no retry. A stream
 *   that lives as long as its tab (`retryForever`, the thread stream) never runs
 *   out of retries, and treats a refused token as one more reason to reconnect
 *   with a fresh one; only an access refusal or a missing thread ends it.
 */

export interface ChatStreamHandle {
  close(): void;
}

export class ChatStreamProtocolError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ChatStreamProtocolError";
  }
}

export interface TokenStreamFrame {
  /** The SSE `event:` name, when the frame had one. */
  event: string | null;
  /** The `data:` payload parsed as JSON (`null` when it was not JSON). */
  data: unknown;
  /** The SSE `id:` cursor, when the frame had one. */
  id: number | null;
}

export type TokenStreamVerdict = "continue" | "stop";

export interface TokenStreamOptions {
  transport: Extract<ChatTransport, { mode: "http" }>;
  /** POST here mints a single-use token. */
  mintPath: string;
  /** GET here, with `?stream_token=`, opens the stream. */
  eventsPath: string;
  /** Open *after* this cursor; `null` lets the server choose its start. */
  lastEventId: number | null;
  onFrame(frame: TokenStreamFrame): TokenStreamVerdict;
  /** The stream stopped and will not resume by itself. */
  onError(error: unknown): void;
  /** `onFrame` answered `"stop"` and the connection is closed. */
  onStopped?(): void;
  /** Keep reconnecting for as long as the stream is open (see {@link reconnectDelay}). */
  retryForever?: boolean;
}

const StreamTokenSchema = z
  .object({ data: z.object({ stream_token: z.string().min(1) }) })
  .transform((wire) => wire.data.stream_token);

const MAX_RECONNECT_ATTEMPTS = 6;
const BACKOFF_MS = [250, 500, 1000, 2000, 4000, 8000];
export const HEALTHY_CONNECTION_MS = 10_000;

/**
 * How long to wait before reconnect attempt `attempt + 1` after `error`, or
 * `null` when the stream must stop and report the error.
 */
export function reconnectDelay(
  attempt: number,
  error: unknown,
  { retryForever }: { retryForever: boolean },
): number | null {
  if (error instanceof ChatStreamProtocolError) return null;
  if (error instanceof ClueChatApiError && [401, 403, 404].includes(error.status)) {
    // A token can be refused for a reason that a fresh one cures (a proxy
    // retried the request); an access refusal or a missing thread cannot be.
    const refusedToken = error.status === 401 && error.code === "INVALID_STREAM_TOKEN";
    if (!(retryForever && refusedToken)) return null;
  }
  if (!retryForever && attempt >= MAX_RECONNECT_ATTEMPTS) return null;
  return BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)] ?? 8000;
}

class StreamEnded extends Error {
  constructor() {
    super("the stream ended");
    this.name = "StreamEnded";
  }
}

export function openTokenStream(options: TokenStreamOptions): ChatStreamHandle {
  const controller = new AbortController();
  let closed = false;
  // The highest event actually handed to `onFrame`, not the highest the
  // server mentioned: a reconnect resumes after what the consumer has seen.
  let cursor = options.lastEventId;

  const close = () => {
    if (closed) return;
    closed = true;
    controller.abort();
  };

  void (async () => {
    let attempt = 0;
    while (!closed) {
      let openedAt: number | null = null;
      try {
        const token = StreamTokenSchema.parse(
          await chatRequest(options.transport, options.mintPath, {
            method: "POST",
            signal: controller.signal,
          }),
        );
        const headers = new Headers({ Accept: "text/event-stream" });
        if (cursor !== null && cursor >= 0) {
          headers.set("Last-Event-ID", String(cursor));
        }
        const response = await fetch(
          chatUrl(options.transport, options.eventsPath, { stream_token: token }),
          {
            headers: withPageWorkspace(options.transport, headers),
            cache: "no-store",
            signal: controller.signal,
          },
        );
        if (!response.ok) throw await chatRefusalOf(response);
        if (!response.body) throw new Error("the stream returned no body");
        openedAt = Date.now();

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        const frames = new SseFrameReader();
        let stopped = false;
        readLoop: for (;;) {
          const chunk = await reader.read();
          if (chunk.done) break;
          for (const frame of frames.push(decoder.decode(chunk.value, { stream: true }))) {
            const id = frame.id === null ? null : Number(frame.id);
            const eventId = id !== null && Number.isFinite(id) ? id : null;
            let verdict: TokenStreamVerdict;
            try {
              verdict = options.onFrame({ event: frame.event, data: safeJson(frame.data), id: eventId });
            } catch (error) {
              await reader.cancel().catch(() => undefined);
              throw error;
            }
            if (eventId !== null) cursor = Math.max(cursor ?? 0, eventId);
            if (verdict === "stop") {
              // The frame itself says the stream is over. Do not wait for a
              // proxy or TCP timeout before telling the caller.
              await reader.cancel().catch(() => undefined);
              stopped = true;
              break readLoop;
            }
          }
        }
        if (stopped) {
          if (!closed) options.onStopped?.();
          return;
        }
        throw new StreamEnded();
      } catch (error) {
        if (closed || isAbort(error)) return;
        if (openedAt !== null && Date.now() - openedAt >= HEALTHY_CONNECTION_MS) {
          attempt = 0;
        }
        const wait = reconnectDelay(attempt, error, {
          retryForever: options.retryForever ?? false,
        });
        if (wait === null) {
          options.onError(error);
          return;
        }
        await delay(wait);
        attempt += 1;
      }
    }
  })();

  return { close };
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
