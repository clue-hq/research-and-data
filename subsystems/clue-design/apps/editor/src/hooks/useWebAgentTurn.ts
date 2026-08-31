import { useCallback, useEffect, useRef, useState } from "react";

import { editorApiBaseUrl } from "@/engine/editorConfig";
import { openRunEventStream, type RunStreamTarget } from "@/engine/runEventStream";
import { fetchWebRunSnapshot, startWebTurn } from "@/engine/webDocuments";

/**
 * The website-mode turn hook — a lean cousin of the scene editor's
 * `useAgentTurn`. Website turns are one-shot and server-durable: POST the
 * prompt, then follow the run's Server-Sent Events for progress until a `done`
 * envelope. There is no Accept/Reject preview here (the server applies the turn
 * and the shell re-renders), so this hook only owns the run's lifecycle.
 *
 * State machine: idle → running → done | error. Exactly one run at a time.
 * The component passes an `onDone` callback (it captures the envelope's status
 * to distinguish an applied turn from a failed one, and to trigger the render
 * refetch). Browser APIs are wrapped, never stored bare
 * (docs/frontend-practices.md rule 8): `startWebTurn` wraps `fetch`, and the
 * event stream is built through an injectable factory (default =
 * `openRunEventStream`, tests pass a fake).
 */

const MAX_EVENTS = 200;

/** One streamed progress event (contract 2, event name "progress"). */
export interface WebRunEvent {
  seq: number;
  type: string;
  data: Record<string, unknown>;
  created_at?: string;
}

/** The terminal result envelope (contract 2, event name "done"). */
export interface WebTurnDoneEnvelope {
  status: "applied" | "failed" | "conflicted";
  summary?: string;
  doc_kind?: string;
  [key: string]: unknown;
}

export type WebTurnPhase = "idle" | "running" | "done" | "error";

/** The minimal event-stream surface this hook depends on — injectable so jsdom
 * tests drive the stream with a fake, and so the browser API is never stored
 * bare. D7: the default is `openRunEventStream` (token handshake + reconnect),
 * not the native `EventSource`, so the factory takes the run's address. */
export interface WebEventSourceLike {
  addEventListener(type: string, listener: (event: { data: string }) => void): void;
  close(): void;
  onerror: ((event: unknown) => void) | null;
}

export type WebEventSourceFactory = (target: RunStreamTarget) => WebEventSourceLike;

function defaultEventSourceFactory(target: RunStreamTarget): WebEventSourceLike {
  return openRunEventStream(target);
}

export interface UseWebAgentTurnOptions {
  documentId: string;
  /** Invoked once with the terminal envelope on `done` — the component reads
   * `status` (applied vs failed) and kicks the render/meta refetch. */
  onDone?: (envelope: WebTurnDoneEnvelope) => void;
  /** Override the API base (default: read at call time from editorConfig). */
  apiBaseUrl?: string;
  /** Injectable for tests; defaults to the real POST wrapper. */
  startTurn?: typeof startWebTurn;
  /** Injectable for tests; defaults to `openRunEventStream`. */
  eventSourceFactory?: WebEventSourceFactory;
  /** Injectable for tests; defaults to the real GET /agent/runs/{id} wrapper. */
  fetchRunSnapshot?: typeof fetchWebRunSnapshot;
}

export interface WebAgentTurn {
  phase: WebTurnPhase;
  events: WebRunEvent[];
  summary: string | null;
  error: string | null;
  start: (
    prompt: string,
    baseVersion: number,
    model?: string | null,
    targetNodeIds?: string[]
  ) => void;
}

/** Coerce a parsed progress payload into a WebRunEvent, tolerating missing
 * fields — a malformed event should never break the stream. */
function toRunEvent(raw: unknown): WebRunEvent | null {
  if (!raw || typeof raw !== "object") {
    return null;
  }
  const record = raw as Partial<WebRunEvent>;
  return {
    seq: typeof record.seq === "number" ? record.seq : 0,
    type: typeof record.type === "string" ? record.type : "progress",
    data:
      record.data && typeof record.data === "object"
        ? (record.data as Record<string, unknown>)
        : {},
    created_at: typeof record.created_at === "string" ? record.created_at : undefined
  };
}

export function useWebAgentTurn(options: UseWebAgentTurnOptions): WebAgentTurn {
  const {
    documentId,
    onDone,
    apiBaseUrl,
    startTurn = startWebTurn,
    eventSourceFactory = defaultEventSourceFactory,
    fetchRunSnapshot = fetchWebRunSnapshot
  } = options;

  const [phase, setPhase] = useState<WebTurnPhase>("idle");
  const [events, setEvents] = useState<WebRunEvent[]>([]);
  const [summary, setSummary] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const sourceRef = useRef<WebEventSourceLike | null>(null);
  // The current run reached a terminal state (done or error) — later stream
  // callbacks (notably a benign post-`done` onerror) short-circuit on this.
  const settledRef = useRef(false);
  const runningRef = useRef(false);
  const mountedRef = useRef(true);
  // Keep the latest onDone without re-arming `start` every render.
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;

  const closeSource = useCallback(() => {
    if (sourceRef.current) {
      sourceRef.current.close();
      sourceRef.current = null;
    }
  }, []);

  // Never leak a stream across unmount.
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      closeSource();
    };
  }, [closeSource]);

  const start = useCallback(
    (
      prompt: string,
      baseVersion: number,
      model?: string | null,
      targetNodeIds?: string[]
    ) => {
      const trimmed = prompt.trim();
      if (!trimmed || runningRef.current) {
        return;
      }
      runningRef.current = true;
      settledRef.current = false;
      closeSource();
      setEvents([]);
      setSummary(null);
      setError(null);
      setPhase("running");

      const settleError = (message: string) => {
        if (settledRef.current) {
          return;
        }
        settledRef.current = true;
        runningRef.current = false;
        closeSource();
        if (!mountedRef.current) {
          return;
        }
        setError(message);
        setPhase("error");
      };

      const settleDone = (envelope: WebTurnDoneEnvelope) => {
        if (settledRef.current) {
          return;
        }
        settledRef.current = true;
        runningRef.current = false;
        closeSource();
        if (mountedRef.current) {
          setSummary(typeof envelope.summary === "string" ? envelope.summary : null);
          setPhase("done");
        }
        onDoneRef.current?.(envelope);
      };

      const base = apiBaseUrl ?? editorApiBaseUrl();
      void startTurn(
        { apiBaseUrl: base },
        documentId,
        trimmed,
        baseVersion,
        model ?? null,
        targetNodeIds
      )
        .then(({ runId }) => {
          if (!mountedRef.current || settledRef.current) {
            return;
          }
          let source: WebEventSourceLike;
          try {
            // No workspace in the url: the stream client mints a token over a header-authed POST
            // and the server reads the tenant off the token row (D7).
            source = eventSourceFactory({ apiBaseUrl: base, runId });
          } catch (cause) {
            settleError(
              cause instanceof Error ? cause.message : "Could not open the event stream."
            );
            return;
          }
          sourceRef.current = source;

          source.addEventListener("progress", (event) => {
            const parsed = (() => {
              try {
                return toRunEvent(JSON.parse(event.data));
              } catch {
                // Malformed payload — skip rather than break the stream.
                return null;
              }
            })();
            if (!parsed || !mountedRef.current) {
              return;
            }
            setEvents((current) => {
              const next = [...current, parsed];
              return next.length > MAX_EVENTS ? next.slice(next.length - MAX_EVENTS) : next;
            });
          });

          source.addEventListener("done", (event) => {
            if (settledRef.current) {
              return;
            }
            let envelope: WebTurnDoneEnvelope;
            try {
              envelope = JSON.parse(event.data) as WebTurnDoneEnvelope;
            } catch {
              envelope = {
                status: "failed",
                summary: "The turn finished with an unreadable result."
              };
            }
            settleDone(envelope);
          });

          // A stream error is ambiguous: a benign post-`done` close, a
          // transient blip the client will recover from on its own, an API
          // restart that orphaned the run (the startup sweep marks it failed),
          // or the API being gone. The durable run row disambiguates — only a
          // failed probe settles as a lost connection.
          let probing = false;
          source.onerror = () => {
            if (settledRef.current || probing) {
              return;
            }
            probing = true;
            void fetchRunSnapshot({ apiBaseUrl: base }, runId)
              .then((snapshot) => {
                if (settledRef.current) {
                  return;
                }
                if (snapshot.status === "queued" || snapshot.status === "running") {
                  // Run is alive server-side — `queued` just means no fleet
                  // worker has claimed it yet (D5). Let the stream client
                  // reconnect and replay from Last-Event-ID.
                  return;
                }
                settleDone(
                  (snapshot.result as WebTurnDoneEnvelope | null) ?? {
                    status: "failed",
                    summary: "The run ended without a readable result."
                  }
                );
              })
              .catch(() => {
                settleError("Lost connection to the website agent.");
              })
              .finally(() => {
                probing = false;
              });
          };
        })
        .catch((cause: unknown) => {
          settleError(
            cause instanceof Error ? cause.message : "The website turn could not be started."
          );
        });
    },
    [apiBaseUrl, closeSource, documentId, eventSourceFactory, startTurn]
  );

  return { phase, events, summary, error, start };
}
