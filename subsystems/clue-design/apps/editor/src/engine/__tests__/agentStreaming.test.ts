import { afterEach, describe, expect, it, vi } from "vitest";
import { minimalScene } from "@/fixtures/minimalScene";
import {
  createStreamingAgentRunner,
  subscribeToAgentRun,
  type AgentRunEvent,
  type EventSourceLike
} from "../agentRunner";
import { agentChecklist, agentEventLabel } from "../agentChecklist";

afterEach(() => {
  vi.unstubAllGlobals();
});

/** A scriptable EventSource: the test drives frames with emit(). */
class FakeEventSource implements EventSourceLike {
  onerror: ((event: unknown) => void) | null = null;
  closed = false;
  readonly url: string;
  private listeners = new Map<string, (event: { data: string }) => void>();

  constructor(url: string) {
    this.url = url;
  }

  addEventListener(type: string, listener: (event: { data: string }) => void): void {
    this.listeners.set(type, listener);
  }

  emit(type: string, data: unknown): void {
    this.listeners.get(type)?.({ data: JSON.stringify(data) });
  }

  close(): void {
    this.closed = true;
  }
}

describe("streaming agent runner", () => {
  it("POSTs /agent/turns, forwards run id + progress events, resolves on done", async () => {
    const fetchMock = vi.fn(
      async (_url: string | URL) => new Response(JSON.stringify({ run_id: "run_stream_1" }))
    );
    vi.stubGlobal("fetch", fetchMock);

    let source: FakeEventSource | null = null;
    const runner = createStreamingAgentRunner({
      apiBaseUrl: "http://api.test",
      eventSourceFactory: (url) => {
        source = new FakeEventSource(url);
        return source;
      }
    });

    const events: AgentRunEvent[] = [];
    const resultPromise = runner({
      prompt: "make a poster",
      scene: minimalScene,
      documentId: undefined,
      activePageId: "page_a4",
      diagnostics: [],
      onEvent: (event) => events.push(event)
    });

    // Let the POST resolve and the subscription open.
    await vi.waitFor(() => expect(source).not.toBeNull());
    expect(fetchMock.mock.calls[0][0].toString()).toContain("/agent/turns");
    expect(source!.url).toContain("/agent/runs/run_stream_1/events");
    // The synthetic run_started frame carries the run id for reload-resume.
    expect(events.find((event) => event.type === "run_started")?.data.run_id).toBe("run_stream_1");

    source!.emit("progress", { seq: 1, type: "dsl_compiled", data: { iteration: 1 } });
    source!.emit("done", {
      status: "proposed",
      summary: "Poster proposed.",
      operations: [],
      diagnostics: []
    });

    const result = await resultPromise;
    expect(result.status).toBe("proposed");
    expect(result.summary).toBe("Poster proposed.");
    expect(source!.closed).toBe(true);
    expect(events.some((event) => event.type === "dsl_compiled")).toBe(true);
  });

  it("subscribeToAgentRun resolves from a replayed done frame (resume path)", async () => {
    const source = new FakeEventSource("");
    const promise = subscribeToAgentRun({
      apiBaseUrl: "http://api.test",
      runId: "run_resume",
      eventSourceFactory: () => source
    });
    // A run that finished while away replays its terminal frame immediately.
    source.emit("done", { status: "failed", summary: "budget reached", operations: [] });
    const result = await promise;
    expect(result.status).toBe("failed");
    expect(source.closed).toBe(true);
  });
});

describe("agent checklist derivation", () => {
  const event = (seq: number, type: string, iteration?: number): AgentRunEvent => ({
    seq,
    type,
    data: iteration ? { iteration } : {}
  });

  it("shows the first stage warming up while running with no events yet", () => {
    const steps = agentChecklist([], true);
    expect(steps).toEqual([{ key: "plan", label: "Planning the design", status: "active" }]);
    expect(agentChecklist([], false)).toEqual([]);
  });

  it("ticks stages forward and marks the latest active while running", () => {
    const steps = agentChecklist(
      [event(1, "run_started"), event(2, "dsl_block_produced", 1), event(3, "preflight_completed", 1)],
      true
    );
    expect(steps.map((step) => step.key)).toEqual(["plan", "author", "apply", "preflight"]);
    expect(steps.slice(0, 3).every((step) => step.status === "done")).toBe(true);
    expect(steps.at(-1)?.status).toBe("active");
  });

  it("marks every reached stage done once the run settles", () => {
    const steps = agentChecklist([event(1, "run_started"), event(2, "critique_result", 2)], false);
    expect(steps.every((step) => step.status === "done")).toBe(true);
  });

  it("never regresses a stage when a repair re-authors after review", () => {
    const steps = agentChecklist(
      [event(1, "critique_result", 1), event(2, "dsl_block_produced", 2)],
      true
    );
    // review was reached in pass 1; a pass-2 re-author must not un-tick it.
    expect(steps.map((step) => step.key)).toEqual(["plan", "author", "apply", "preflight", "review"]);
  });

  it("humanizes event labels with the pass number", () => {
    expect(agentEventLabel(event(2, "dsl_compiled", 3))).toBe("Compiled the design · pass 3");
    expect(agentEventLabel(event(1, "run_started"))).toBe("Started the design run");
  });
});
