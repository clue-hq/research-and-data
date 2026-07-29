import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { WebRunSnapshot } from "@/engine/webDocuments";
import {
  useWebAgentTurn,
  type WebEventSourceLike,
  type WebTurnDoneEnvelope
} from "../useWebAgentTurn";

/** Fake EventSource capturing listeners so tests drive the stream directly. */
class FakeEventSource implements WebEventSourceLike {
  onerror: ((event: unknown) => void) | null = null;
  closed = false;
  private listeners = new Map<string, (event: { data: string }) => void>();

  addEventListener(type: string, listener: (event: { data: string }) => void): void {
    this.listeners.set(type, listener);
  }

  close(): void {
    this.closed = true;
  }

  emit(type: string, data: unknown): void {
    this.listeners.get(type)?.({ data: JSON.stringify(data) });
  }

  error(): void {
    this.onerror?.({});
  }
}

function setup(snapshot: () => Promise<WebRunSnapshot>) {
  const source = new FakeEventSource();
  const onDone = vi.fn<(envelope: WebTurnDoneEnvelope) => void>();
  const fetchRunSnapshot = vi.fn(snapshot);
  const hook = renderHook(() =>
    useWebAgentTurn({
      documentId: "doc_web",
      apiBaseUrl: "http://api.test",
      onDone,
      startTurn: vi.fn().mockResolvedValue({ runId: "run_1" }),
      eventSourceFactory: () => source,
      fetchRunSnapshot
    })
  );
  return { hook, source, onDone, fetchRunSnapshot };
}

async function startTurn(hook: ReturnType<typeof setup>["hook"]) {
  await act(async () => {
    hook.result.current.start("Build me a landing page", 7);
  });
}

describe("useWebAgentTurn", () => {
  it("streams progress then settles on the done envelope", async () => {
    const { hook, source, onDone } = setup(() =>
      Promise.reject(new Error("unused"))
    );
    await startTurn(hook);
    expect(hook.result.current.phase).toBe("running");

    await act(async () => {
      source.emit("progress", { seq: 1, type: "web_turn_started", data: {} });
      source.emit("done", { status: "applied", summary: "Shipped." });
    });

    expect(hook.result.current.phase).toBe("done");
    expect(hook.result.current.summary).toBe("Shipped.");
    expect(hook.result.current.events).toHaveLength(1);
    expect(onDone).toHaveBeenCalledWith(
      expect.objectContaining({ status: "applied" })
    );
    expect(source.closed).toBe(true);
  });

  it("keeps streaming through a transient blip while the run is alive", async () => {
    const { hook, source, fetchRunSnapshot } = setup(() =>
      Promise.resolve({ status: "running", result: null })
    );
    await startTurn(hook);

    await act(async () => {
      source.error();
    });

    // Run is alive server-side: no settle, EventSource is left open to
    // auto-reconnect and replay from Last-Event-ID.
    expect(fetchRunSnapshot).toHaveBeenCalledWith(
      { apiBaseUrl: "http://api.test" },
      "run_1"
    );
    expect(hook.result.current.phase).toBe("running");
    expect(source.closed).toBe(false);

    await act(async () => {
      source.emit("done", { status: "applied", summary: "Recovered." });
    });
    expect(hook.result.current.phase).toBe("done");
  });

  it("settles from the durable row when a restart orphaned the run", async () => {
    // The API's startup sweep marks orphans failed; the stream died before a
    // `done` frame, so the probe must deliver the terminal envelope instead.
    const { hook, source, onDone } = setup(() =>
      Promise.resolve({
        status: "failed",
        result: {
          status: "failed",
          summary: "The turn was interrupted by an API server restart and did not finish."
        }
      })
    );
    await startTurn(hook);

    await act(async () => {
      source.error();
    });

    expect(hook.result.current.phase).toBe("done");
    expect(hook.result.current.summary).toContain("interrupted by an API server restart");
    expect(onDone).toHaveBeenCalledWith(
      expect.objectContaining({ status: "failed" })
    );
    expect(source.closed).toBe(true);
  });

  it("reports a lost connection only when the probe itself fails", async () => {
    const { hook, source } = setup(() =>
      Promise.reject(new Error("connection refused"))
    );
    await startTurn(hook);

    await act(async () => {
      source.error();
    });

    expect(hook.result.current.phase).toBe("error");
    expect(hook.result.current.error).toBe("Lost connection to the website agent.");
  });
});
