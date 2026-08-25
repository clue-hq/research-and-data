import { Agent, type Dispatcher } from "undici";

/**
 * The undici dispatcher the server-side SSE proxies fetch under.
 *
 * ── WHY THIS EXISTS ─────────────────────────────────────────────────────────
 * Both `/api/clue/[...path]` and `/api/clue/design/[...path]` proxy a backend
 * `text/event-stream` through a server-side `fetch`. That fetch is Node's
 * built-in undici, whose DEFAULT `bodyTimeout` is 300s — measured from the last
 * byte received, not from the start of the request. An SSE stream is idle by
 * design between events, so a long design run (generation is minutes; the
 * platform chat stream sends no keepalive comment) reliably went quiet for five
 * minutes and undici aborted the body with `UND_ERR_BODY_TIMEOUT`.
 *
 * The response headers are long since flushed to the browser by then, so the
 * client does not see an HTTP error — it sees a truncated body, i.e. the stream
 * simply dying every ~5 minutes for the life of the run.
 *
 * A body timeout is meaningful for a request/response call and is exactly wrong
 * for a stream: "no bytes for N seconds" is the NORMAL state of an event
 * stream. So streaming requests run under a dispatcher with the body timeout
 * disabled. `headersTimeout` is deliberately LEFT at its default — an SSE
 * endpoint that cannot produce response headers within it really is hung, and
 * that is a timeout worth keeping.
 *
 * ── WHY A MODULE SINGLETON ──────────────────────────────────────────────────
 * An `Agent` owns a connection pool. Constructing one per request would leak
 * pools and sockets for the process's lifetime, so it is built once, lazily
 * (nothing is allocated in deployments that never open a stream).
 */
let streamingAgent: Agent | null = null;

function streamingDispatcher(): Dispatcher {
  streamingAgent ??= new Agent({
    // 0 disables it. Verified against Node 24 / undici 7: a finite value here
    // reproduces UND_ERR_BODY_TIMEOUT on an idle event-stream body, and 0
    // survives indefinitely.
    bodyTimeout: 0,
  });
  return streamingAgent;
}

/** Whether a proxied request is asking for an event stream. */
export function wantsEventStream(headers: Headers): boolean {
  return headers.get("accept")?.includes("text/event-stream") ?? false;
}

/**
 * Extra `fetch` options for proxying this request: the no-body-timeout
 * dispatcher when it is an event stream, nothing otherwise.
 *
 * Spread into the outgoing init. `dispatcher` is an undici extension that the
 * DOM `RequestInit` type does not model, hence the single cast here rather than
 * one at every call site — Node's built-in `fetch` does honour it (verified).
 */
export function streamingFetchOptions(headers: Headers): RequestInit {
  if (!wantsEventStream(headers)) return {};
  return { dispatcher: streamingDispatcher() } as RequestInit;
}
