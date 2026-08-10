import { afterEach, describe, expect, it, vi } from "vitest";

import { openRunEventStream, parseSseBlock } from "../runEventStream";

afterEach(() => {
  vi.unstubAllGlobals();
});

function sseResponse(frames: string[]): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      const encoder = new TextEncoder();
      for (const frame of frames) {
        controller.enqueue(encoder.encode(frame));
      }
      controller.close();
    }
  });
  return new Response(body, { status: 200 });
}

const progressFrame = (seq: number, type: string) =>
  `id: ${seq}\nevent: progress\ndata: ${JSON.stringify({ seq, type, data: {}, created_at: "t" })}\n\n`;

describe("parseSseBlock", () => {
  it("reads id / event / multi-line data and ignores keepalive comments", () => {
    expect(parseSseBlock("id: 7\nevent: progress\ndata: {}")).toEqual({
      id: "7",
      event: "progress",
      data: "{}"
    });
    expect(parseSseBlock("data: a\ndata: b")).toEqual({ event: "message", data: "a\nb" });
    expect(parseSseBlock(": keepalive")).toBeNull();
    expect(parseSseBlock("retry: 1000")).toBeNull();
  });
});

describe("openRunEventStream", () => {
  it("mints a token, opens the events url with it, and dispatches progress then done", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string | URL, init?: RequestInit) => {
        calls.push({ url: url.toString(), init });
        if (calls.length === 1) {
          return new Response(JSON.stringify({ stream_token: "tok_1" }));
        }
        return sseResponse([
          "retry: 1000\n\n",
          progressFrame(11, "dsl_compiled"),
          // An unknown platform frame must be ignored, not dispatched.
          'event: stream.hello\ndata: {"run_id":"run_x"}\n\n',
          `id: 12\nevent: done\ndata: ${JSON.stringify({ status: "proposed" })}\n\n`
        ]);
      })
    );

    const stream = openRunEventStream({ apiBaseUrl: "http://api.test", runId: "run_x" });
    const progress: unknown[] = [];
    let done: unknown = null;
    stream.addEventListener("progress", (event) => progress.push(JSON.parse(event.data)));
    stream.addEventListener("done", (event) => {
      done = JSON.parse(event.data);
    });

    await vi.waitFor(() => expect(done).not.toBeNull());
    expect(calls[0].url).toBe("http://api.test/agent/runs/run_x/stream-token");
    expect(calls[0].init?.method).toBe("POST");
    // The workspace never appears in the stream url — only the minted token does.
    expect(calls[1].url).toBe("http://api.test/agent/runs/run_x/events?stream_token=tok_1");
    expect(calls[1].url).not.toContain("workspace_id");
    expect(progress).toEqual([{ seq: 11, type: "dsl_compiled", data: {}, created_at: "t" }]);
    expect(done).toEqual({ status: "proposed" });
    stream.close();
  });

  it("re-mints and resumes from Last-Event-ID when the connection drops", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string | URL, init?: RequestInit) => {
        calls.push({ url: url.toString(), init });
        if (url.toString().includes("/stream-token")) {
          return new Response(JSON.stringify({ stream_token: `tok_${calls.length}` }));
        }
        // First connect delivers one event then ends; the second must resume after it.
        return calls.filter((call) => call.url.includes("/events")).length === 1
          ? sseResponse([progressFrame(20, "dsl_block_produced")])
          : sseResponse([
              `id: 21\nevent: done\ndata: ${JSON.stringify({ status: "proposed" })}\n\n`
            ]);
      })
    );

    const stream = openRunEventStream({ apiBaseUrl: "http://api.test", runId: "run_y" });
    let done: unknown = null;
    stream.addEventListener("done", (event) => {
      done = JSON.parse(event.data);
    });

    await vi.waitFor(() => expect(done).not.toBeNull(), { timeout: 5000 });
    const eventCalls = calls.filter((call) => call.url.includes("/events"));
    expect(eventCalls).toHaveLength(2);
    // A fresh connect sends no cursor; the reconnect resumes from the last seq it saw, and
    // carries a NEW token because tokens are single-use.
    expect((eventCalls[0].init?.headers as Record<string, string>)["Last-Event-ID"]).toBeUndefined();
    expect((eventCalls[1].init?.headers as Record<string, string>)["Last-Event-ID"]).toBe("20");
    expect(eventCalls[0].url).not.toBe(eventCalls[1].url);
    stream.close();
  });

  it("reports a refused mint through onerror instead of throwing", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("nope", { status: 401 }))
    );
    const stream = openRunEventStream({ apiBaseUrl: "http://api.test", runId: "run_z" });
    const errors: unknown[] = [];
    stream.onerror = (cause) => errors.push(cause);
    await vi.waitFor(() => expect(errors.length).toBeGreaterThan(0));
    stream.close();
  });
});
