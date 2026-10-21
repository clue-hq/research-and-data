import assert from "node:assert/strict";
import test from "node:test";
import type { ChatStreamEvent } from "../model/chat-events";
import { createHttpChatThreadStreamRepository } from "./chat-thread-stream.repository";
import { ClueChatApiError } from "./chat-api";
import { reconnectDelay } from "./chat-sse";

/**
 * The thread stream (CRM trial 1, F2): one per open chat, carrying the
 * lifecycle frames of any turn in the thread, so the chat can follow turns it
 * did not start. These tests drive it through a fake `fetch`.
 */

const encoder = new TextEncoder();
const TRANSPORT = { mode: "http", prefix: "/api/clue" } as const;

function hello(threadId = "th1", id?: number): string {
  const idLine = id === undefined ? "" : `id: ${id}\n`;
  return `${idLine}event: stream.hello\ndata: {"schema_version":"1","type":"stream.hello","project_id":"p1","thread_id":"${threadId}"}\n\n`;
}

function lifecycle(eventId: number, type: string, turnId: string, threadId = "th1"): string {
  return (
    `id: ${eventId}\nevent: ${type}\ndata: {"schema_version":"1","event_id":${eventId},"sequence":1,` +
    `"occurred_at":"2026-10-21T00:00:00Z","project_id":"p1","thread_id":"${threadId}",` +
    `"turn_id":"${turnId}","type":"${type}"}\n\n`
  );
}

function tokenResponse(token: string): Response {
  return new Response(
    JSON.stringify({ data: { schema_version: "1", stream_token: token, thread_id: "th1" } }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}

/** A response whose body sends `chunks`, then stays open unless `end` is set. */
function eventsResponse(chunks: string[], { end = false } = {}): Response {
  return new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
        if (end) controller.close();
      },
    }),
    { status: 200, headers: { "Content-Type": "text/event-stream" } },
  );
}

interface Recorded {
  url: string;
  headers: Headers;
}

/** Install a fake `fetch`: mint calls get a fresh token each, events calls get the next body. */
function fakeFetch(bodies: Array<() => Response>): {
  events: Recorded[];
  restore(): void;
} {
  const original = globalThis.fetch;
  const events: Recorded[] = [];
  let minted = 0;
  globalThis.fetch = async (input, init) => {
    const url = String(input);
    if (url.includes("/stream_token")) {
      minted += 1;
      return tokenResponse(`token-${minted}`);
    }
    events.push({ url, headers: new Headers(init?.headers) });
    const next = bodies[events.length - 1];
    if (!next) return new Promise<Response>(() => undefined); // hang: no more bodies
    return next();
  };
  return {
    events,
    restore() {
      globalThis.fetch = original;
    },
  };
}

function until(check: () => boolean, label: string, ms = 2000): Promise<void> {
  return new Promise((resolve, reject) => {
    const started = Date.now();
    const tick = () => {
      if (check()) return resolve();
      if (Date.now() - started > ms) return reject(new Error(`timed out: ${label}`));
      setTimeout(tick, 5);
    };
    tick();
  });
}

test("test_lifecycle_frames_reach_on_turn_event", async () => {
  const fake = fakeFetch([() => eventsResponse([hello(), lifecycle(5, "turn.accepted", "turn-a")])]);
  const seen: ChatStreamEvent[] = [];
  try {
    const handle = createHttpChatThreadStreamRepository(TRANSPORT).open({
      projectId: "p1",
      threadId: "th1",
      lastEventId: null,
      onTurnEvent: (event) => seen.push(event),
      onReset: () => assert.fail("no reset expected"),
      onError: (error) => assert.fail(String(error)),
    });
    await until(() => seen.length === 1, "the lifecycle frame");
    handle.close();
    assert.equal(seen[0]?.type, "turn.accepted");
    assert.equal(seen[0]?.turnId, "turn-a");
    assert.equal(seen[0]?.eventId, 5);
    assert.match(fake.events[0]?.url ?? "", /\/projects\/p1\/threads\/th1\/events\?stream_token=token-1/);
    assert.equal(fake.events[0]?.headers.get("Last-Event-ID"), null);
  } finally {
    fake.restore();
  }
});

test("test_keepalive_comments_are_ignored", async () => {
  const fake = fakeFetch([
    () =>
      eventsResponse([
        hello(),
        ": keepalive\n\n",
        ": keepalive\n\n",
        lifecycle(6, "turn.started", "turn-a"),
      ]),
  ]);
  const seen: string[] = [];
  try {
    const handle = createHttpChatThreadStreamRepository(TRANSPORT).open({
      projectId: "p1",
      threadId: "th1",
      lastEventId: null,
      onTurnEvent: (event) => seen.push(event.type),
      onReset: () => assert.fail("no reset expected"),
      onError: (error) => assert.fail(String(error)),
    });
    await until(() => seen.length === 1, "the frame after the comments");
    handle.close();
    assert.deepEqual(seen, ["turn.started"]);
  } finally {
    fake.restore();
  }
});

test("test_reconnect_after_drop_mints_a_fresh_token_and_resumes_from_the_cursor", async () => {
  const fake = fakeFetch([
    () => eventsResponse([hello(), lifecycle(9, "turn.accepted", "turn-a")], { end: true }),
    () => eventsResponse([hello(), lifecycle(12, "turn.completed", "turn-a")]),
  ]);
  const seen: number[] = [];
  try {
    const handle = createHttpChatThreadStreamRepository(TRANSPORT).open({
      projectId: "p1",
      threadId: "th1",
      lastEventId: 3,
      onTurnEvent: (event) => seen.push(event.eventId ?? -1),
      onReset: () => assert.fail("no reset expected"),
      onError: (error) => assert.fail(String(error)),
    });
    await until(() => seen.length === 2, "the frame after the reconnect");
    handle.close();
    assert.deepEqual(seen, [9, 12]);
    assert.equal(fake.events.length, 2);
    assert.equal(fake.events[0]?.headers.get("Last-Event-ID"), "3");
    assert.match(fake.events[1]?.url ?? "", /stream_token=token-2/);
    assert.equal(fake.events[1]?.headers.get("Last-Event-ID"), "9");
  } finally {
    fake.restore();
  }
});

test("test_a_reset_calls_on_reset", async () => {
  const reset =
    'event: stream.reset\ndata: {"schema_version":"1","type":"stream.reset","project_id":"p1",' +
    '"thread_id":"th1","reason":"cursor_older_than_horizon","rehydrate":"transcript"}\n\n';
  const fake = fakeFetch([() => eventsResponse([hello(), reset, lifecycle(40, "turn.accepted", "turn-b")])]);
  let resets = 0;
  const seen: string[] = [];
  try {
    const handle = createHttpChatThreadStreamRepository(TRANSPORT).open({
      projectId: "p1",
      threadId: "th1",
      lastEventId: 2,
      onTurnEvent: (event) => seen.push(event.turnId),
      onReset: () => {
        resets += 1;
      },
      onError: (error) => assert.fail(String(error)),
    });
    await until(() => seen.length === 1, "the frame after the reset");
    handle.close();
    assert.equal(resets, 1);
    assert.deepEqual(seen, ["turn-b"]);
  } finally {
    fake.restore();
  }
});

test("test_frames_for_another_thread_are_dropped", async () => {
  const fake = fakeFetch([
    () =>
      eventsResponse([
        hello(),
        lifecycle(7, "turn.accepted", "turn-x", "th-other"),
        lifecycle(8, "turn.accepted", "turn-a"),
      ]),
  ]);
  const seen: string[] = [];
  try {
    const handle = createHttpChatThreadStreamRepository(TRANSPORT).open({
      projectId: "p1",
      threadId: "th1",
      lastEventId: null,
      onTurnEvent: (event) => seen.push(event.turnId),
      onReset: () => assert.fail("no reset expected"),
      onError: (error) => assert.fail(String(error)),
    });
    await until(() => seen.length >= 1, "the thread's own frame");
    handle.close();
    assert.deepEqual(seen, ["turn-a"]);
  } finally {
    fake.restore();
  }
});

test("test_the_hello_cursor_is_kept_for_a_reconnect", async () => {
  // Review finding #1: a connection dropped before any turn frame must still resume from the
  // start point the server named, including 0 for a thread with no frames yet.
  const fake = fakeFetch([
    () => eventsResponse([hello("th1", 0)], { end: true }),
    () => eventsResponse([hello("th1", 0)]),
  ]);
  const cursors: number[] = [];
  try {
    const handle = createHttpChatThreadStreamRepository(TRANSPORT).open({
      projectId: "p1",
      threadId: "th1",
      lastEventId: null,
      onTurnEvent: () => assert.fail("no turn frame expected"),
      onCursor: (eventId) => cursors.push(eventId),
      onReset: () => assert.fail("no reset expected"),
      onError: (error) => assert.fail(String(error)),
    });
    await until(() => fake.events.length === 2, "the reconnect");
    handle.close();
    assert.equal(fake.events[1]?.headers.get("Last-Event-ID"), "0");
    assert.deepEqual(cursors.slice(0, 1), [0]);
  } finally {
    fake.restore();
  }
});

test("test_the_thread_stream_never_runs_out_of_retries", () => {
  // Review finding #3: the thread stream lives as long as the tab; a long outage or a token
  // the server refused must not end it for good.
  const outage = new Error("network down");
  assert.equal(reconnectDelay(6, outage, { retryForever: false }), null);
  assert.equal(reconnectDelay(6, outage, { retryForever: true }), 8000);
  assert.equal(reconnectDelay(50, outage, { retryForever: true }), 8000);
  const refusedToken = new ClueChatApiError("used", { status: 401, code: "INVALID_STREAM_TOKEN", requestId: null });
  assert.equal(reconnectDelay(0, refusedToken, { retryForever: false }), null);
  assert.equal(reconnectDelay(0, refusedToken, { retryForever: true }), 250);
  const forbidden = new ClueChatApiError("no", { status: 403, code: "PERMISSION_DENIED", requestId: null });
  assert.equal(reconnectDelay(0, forbidden, { retryForever: true }), null);
  const gone = new ClueChatApiError("gone", { status: 404, code: "THREAD_NOT_FOUND", requestId: null });
  assert.equal(reconnectDelay(0, gone, { retryForever: true }), null);
});
