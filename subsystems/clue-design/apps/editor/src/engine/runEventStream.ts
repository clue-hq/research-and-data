import { lumenFetch, runEventsUrl, runStreamTokenUrl } from "./editorConfig";

/**
 * The design run's SSE client (design-integration Part II, D7).
 *
 * Replaces the browser's native `EventSource` for one specific reason: the stream is now opened
 * with a single-use token, and `EventSource` cannot send the `X-Workspace-Id` header the mint call
 * needs — that limitation is exactly why the old stream took `?workspace_id=`, a tenant *claim*
 * anyone could make. The handshake is:
 *
 *   1. `POST /agent/runs/{id}/stream-token` through `lumenFetch` (workspace header attached),
 *   2. `GET  /agent/runs/{id}/events?stream_token=…` as a `fetch` stream,
 *   3. on drop, re-mint and reconnect with `Last-Event-ID` so replay stays gapless.
 *
 * Tokens are single-use, so step 3 always re-mints. The cursor — not the token — carries replay
 * state, which is what keeps single-use and gapless reconnect compatible.
 *
 * The public surface is deliberately the `EventSource` subset the editor already depended on
 * (`addEventListener("progress" | "done")`, `close()`, `onerror`), so both call sites and their
 * fakes are unchanged in shape. Unknown event names are ignored rather than dispatched: the
 * platform's own stream frames `stream.hello` / `stream.reset` around its payload events, and this
 * client will point at that stream when the editor mounts in the platform shell (Part IV).
 */

/** The minimal EventSource surface the editor depends on. */
export interface RunEventStream {
  addEventListener(type: string, listener: (event: { data: string }) => void): void;
  close(): void;
  onerror: ((event: unknown) => void) | null;
}

export interface RunStreamTarget {
  apiBaseUrl: string;
  runId: string;
}

/** Matches the server's `retry: 1000` hint and the old EventSource reconnect delay. */
const RECONNECT_DELAY_MS = 1000;

async function mintStreamToken(target: RunStreamTarget): Promise<string> {
  const response = await lumenFetch(runStreamTokenUrl(target.apiBaseUrl, target.runId), {
    method: "POST"
  });
  if (!response.ok) {
    throw new Error(`Could not open the run stream (HTTP ${response.status}).`);
  }
  const body = (await response.json()) as { stream_token?: unknown };
  if (typeof body.stream_token !== "string" || !body.stream_token) {
    throw new Error("The run stream token response carried no token.");
  }
  return body.stream_token;
}

/** One parsed SSE frame. `id` is absent on comment-only or id-less frames. */
interface StreamFrame {
  id?: string;
  event: string;
  data: string;
}

/**
 * Parse one `\n\n`-delimited SSE block. Returns null for keepalive comments (`: …`) and for blocks
 * with no `data:` line — both are wire-level noise the listeners must never see.
 */
export function parseSseBlock(block: string): StreamFrame | null {
  let id: string | undefined;
  let event = "message";
  const data: string[] = [];
  for (const rawLine of block.split("\n")) {
    const line = rawLine.replace(/\r$/, "");
    if (!line || line.startsWith(":")) {
      continue;
    }
    const separator = line.indexOf(":");
    const field = separator === -1 ? line : line.slice(0, separator);
    // Per the SSE grammar a single leading space after the colon is part of the delimiter.
    const value =
      separator === -1 ? "" : line.slice(separator + 1).replace(/^ /, "");
    if (field === "id") {
      id = value;
    } else if (field === "event") {
      event = value;
    } else if (field === "data") {
      data.push(value);
    }
    // `retry:` and unknown fields are ignored — this client owns its own reconnect delay.
  }
  if (data.length === 0) {
    return null;
  }
  return { id, event, data: data.join("\n") };
}

/**
 * Open a run's event stream. Resolves nothing — the caller drives it through listeners, exactly as
 * it drove `EventSource`. Reconnects itself on a dropped connection until `close()` is called or a
 * terminal `done` frame arrives (the callers close on `done`, and the closed flag stops the loop).
 */
export function openRunEventStream(target: RunStreamTarget): RunEventStream {
  const listeners = new Map<string, (event: { data: string }) => void>();
  let closed = false;
  let lastEventId: string | null = null;
  let controller: AbortController | null = null;

  const stream: RunEventStream = {
    onerror: null,
    addEventListener(type, listener) {
      listeners.set(type, listener);
    },
    close() {
      closed = true;
      controller?.abort();
      controller = null;
    }
  };

  const dispatch = (frame: StreamFrame) => {
    if (frame.id !== undefined) {
      lastEventId = frame.id;
    }
    // Unknown event names (the platform's stream.hello / stream.reset) are dropped here.
    listeners.get(frame.event)?.({ data: frame.data });
  };

  const readOnce = async () => {
    const token = await mintStreamToken(target);
    controller = new AbortController();
    const headers: Record<string, string> = {};
    if (lastEventId !== null) {
      headers["Last-Event-ID"] = lastEventId;
    }
    const response = await fetch(runEventsUrl(target.apiBaseUrl, target.runId, token), {
      headers,
      signal: controller.signal
    });
    if (!response.ok || !response.body) {
      throw new Error(`The run stream closed with HTTP ${response.status}.`);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffered = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) {
        return;
      }
      buffered += decoder.decode(value, { stream: true });
      let boundary = buffered.indexOf("\n\n");
      while (boundary !== -1) {
        const block = buffered.slice(0, boundary);
        buffered = buffered.slice(boundary + 2);
        const frame = parseSseBlock(block);
        if (frame) {
          dispatch(frame);
        }
        if (closed) {
          return;
        }
        boundary = buffered.indexOf("\n\n");
      }
    }
  };

  const run = async () => {
    while (!closed) {
      try {
        await readOnce();
      } catch (cause) {
        if (closed) {
          return;
        }
        // Same ambiguity the native EventSource had — a benign post-`done` close, a transient
        // blip, or an API that is gone. The callers disambiguate by probing the durable run row;
        // this client just keeps trying until it is closed.
        stream.onerror?.(cause);
      }
      if (closed) {
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, RECONNECT_DELAY_MS));
    }
  };

  void run();
  return stream;
}
