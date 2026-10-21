import assert from "node:assert/strict";
import test from "node:test";
import { JSDOM } from "jsdom";
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { AppRouterContext } from "next/dist/shared/lib/app-router-context.shared-runtime";
import { SearchParamsContext } from "next/dist/shared/lib/hooks-client-context.shared-runtime";
import { ProjectsTransportProvider } from "@/features/projects/data/projects-transport";
import {
  useProjectChatController,
  type ProjectChatController,
} from "@/features/projects/hooks/use-project-chat-controller";

const PROJECT = "project-thread-stream";
const THREAD_A = "thread-a";
const THREAD_B = "thread-b";
const TRANSPORT = { mode: "http", prefix: "/api/clue" } as const;
const TIMESTAMP = "2026-10-21T12:00:00Z";

/**
 * CRM trial 1, F2: an open chat follows turns it did not start.
 *
 * Only `fetch` and the page's visibility are faked. The repositories, the SSE
 * readers and the controller's effects run for real. Each thread starts with
 * one finished turn ("done"); the server can add turns the chat never sent.
 */
function harness() {
  const dom = new JSDOM("<div id='root'></div>");
  let visibility: "visible" | "hidden" = "visible";
  Object.defineProperty(dom.window.document, "visibilityState", {
    configurable: true,
    get: () => visibility,
  });
  const originals = new Map<string, PropertyDescriptor | undefined>();
  for (const [key, value] of Object.entries({
    window: dom.window,
    document: dom.window.document,
    navigator: dom.window.navigator,
    IS_REACT_ACT_ENVIRONMENT: true,
  })) {
    originals.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
    Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
  }
  const oldFetch = globalThis.fetch;
  const encoder = new TextEncoder();
  const server = {
    turns: new Map<string, Array<{ turn_id: string; state: string }>>([
      [THREAD_A, [{ turn_id: "done", state: "completed" }]],
      [THREAD_B, [{ turn_id: "done-b", state: "completed" }]],
    ]),
    turnReads: new Map<string, number>(),
    threadReads: 0,
  };
  const turnStreams = new Map<string, ReadableStreamDefaultController<Uint8Array>>();
  /** Every thread-stream open, in order: its thread, cursor header, abort signal and body. */
  const threadOpens: Array<{
    threadId: string;
    lastEventId: string | null;
    signal: AbortSignal | undefined;
    body: ReadableStreamDefaultController<Uint8Array> | null;
  }> = [];
  let latest: ProjectChatController | null = null;

  globalThis.fetch = async (input, init) => {
    const url = new URL(String(input), "https://clue.invalid");
    const path = url.pathname;
    const prefix = `/api/clue/api/v1/projects/${PROJECT}/threads`;
    const threadStream = path.match(/\/threads\/([^/]+)\/(stream_token|events)$/);
    if (threadStream) {
      const [, threadId, operation] = threadStream;
      if (operation === "stream_token") {
        return Response.json({ data: { schema_version: "1", thread_id: threadId, stream_token: `t-${threadOpens.length}` } });
      }
      const open = {
        threadId: threadId!,
        lastEventId: new Headers(init?.headers).get("Last-Event-ID"),
        signal: init?.signal ?? undefined,
        body: null as ReadableStreamDefaultController<Uint8Array> | null,
      };
      threadOpens.push(open);
      return new Response(new ReadableStream<Uint8Array>({
        start(controller) {
          open.body = controller;
          controller.enqueue(encoder.encode(
            `event: stream.hello\ndata: {"schema_version":"1","type":"stream.hello","project_id":"${PROJECT}","thread_id":"${threadId}"}\n\n`,
          ));
        },
      }), { headers: { "Content-Type": "text/event-stream" } });
    }
    const turnStream = path.match(/\/turns\/([^/]+)\/(stream_token|events)$/);
    if (turnStream) {
      const [, turnId, operation] = turnStream;
      if (operation === "stream_token") {
        return Response.json({ data: { schema_version: "1", turn_id: turnId, stream_token: `token-${turnId}` } });
      }
      return new Response(new ReadableStream<Uint8Array>({
        start(controller) { turnStreams.set(turnId!, controller); },
      }), { headers: { "Content-Type": "text/event-stream" } });
    }
    if (path === prefix) {
      server.threadReads += 1;
      return Response.json({ data: [THREAD_A, THREAD_B].map((id) => ({
        id, title: id, href: `/projects/${PROJECT}/chats/${id}`, status: "idle", pinned: false,
        project_id: PROJECT, created_at: TIMESTAMP, updated_at: TIMESTAMP, discovery: null,
      })), meta: { next_cursor: null } });
    }
    const turnsList = path.match(/\/threads\/([^/]+)\/turns$/);
    if (turnsList) {
      const threadId = turnsList[1]!;
      server.turnReads.set(threadId, (server.turnReads.get(threadId) ?? 0) + 1);
      return Response.json({ data: (server.turns.get(threadId) ?? []).map(({ turn_id, state }) => ({
        turn_id, thread_id: threadId, project_id: PROJECT, state,
        requested_at: TIMESTAMP, last_event_id: null, generation_attempts: 1, submission_message: null,
      })), meta: { thread_status: "idle" } });
    }
    if (/\/threads\/[^/]+\/(messages|gates)$/.test(path)) {
      return Response.json({ data: [], meta: { next_cursor: null } });
    }
    assert.fail(`unexpected request: ${path}`);
  };

  const root = createRoot(dom.window.document.getElementById("root")!);
  function Probe({ threadId }: { threadId: string }) {
    latest = useProjectChatController({
      projectId: PROJECT,
      initialThreadId: threadId,
      projectTitle: "Named project",
    });
    return null;
  }
  async function flushUntil(predicate: () => boolean, what: string) {
    for (let attempt = 0; attempt < 40; attempt += 1) {
      await act(async () => { await new Promise<void>((resolve) => setImmediate(resolve)); });
      if (predicate()) return;
    }
    assert.fail(`controller did not reach: ${what}`);
  }
  async function settle() {
    for (let attempt = 0; attempt < 10; attempt += 1) {
      await act(async () => { await new Promise<void>((resolve) => setImmediate(resolve)); });
    }
  }
  const unexpectedNavigation = () => assert.fail("no navigation is expected");
  async function mount(threadId: string) {
    await act(async () => {
      root.render(createElement(AppRouterContext.Provider, {
        value: {
          back: unexpectedNavigation, forward: unexpectedNavigation, refresh: unexpectedNavigation,
          push: unexpectedNavigation, replace: unexpectedNavigation, prefetch: async () => {},
        },
      }, createElement(SearchParamsContext.Provider, { value: new URLSearchParams() },
        // eslint-disable-next-line react/no-children-prop
        createElement(ProjectsTransportProvider, {
          transport: TRANSPORT,
          // A thread change is a remount (the workspace remount key), so the key follows it.
          children: createElement(Probe, { key: threadId, threadId }),
        }),
      )));
    });
    await flushUntil(
      () => threadOpens.some((open) => open.threadId === threadId && !open.signal?.aborted),
      `the thread stream of ${threadId} open`,
    );
  }
  /** Send one frame on the newest open thread stream. */
  async function emitOnThread(frame: { id?: number; type: string; turnId?: string; threadId?: string }) {
    const open = threadOpens.at(-1);
    assert.ok(open?.body, "a thread stream is open");
    const threadId = frame.threadId ?? open.threadId;
    const payload: Record<string, unknown> = {
      schema_version: "1", type: frame.type, project_id: PROJECT, thread_id: threadId,
    };
    if (frame.turnId) {
      Object.assign(payload, {
        event_id: frame.id, sequence: 1, occurred_at: TIMESTAMP, turn_id: frame.turnId,
      });
    } else {
      Object.assign(payload, { reason: "cursor_older_than_horizon", rehydrate: "transcript" });
    }
    const idLine = frame.id === undefined ? "" : `id: ${frame.id}\n`;
    await act(async () => {
      open.body!.enqueue(encoder.encode(`${idLine}event: ${frame.type}\ndata: ${JSON.stringify(payload)}\n\n`));
    });
  }
  async function setVisibility(next: "visible" | "hidden") {
    visibility = next;
    await act(async () => {
      dom.window.document.dispatchEvent(new dom.window.Event("visibilitychange"));
    });
  }
  async function teardown() {
    await act(async () => { root.unmount(); });
    globalThis.fetch = oldFetch;
    dom.window.close();
    for (const [key, descriptor] of originals) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else Reflect.deleteProperty(globalThis, key);
    }
  }
  return {
    server, turnStreams, threadOpens, mount, emitOnThread, setVisibility, flushUntil, settle, teardown,
    controller(): ProjectChatController {
      assert.ok(latest, "controller is mounted");
      return latest;
    },
  };
}

test("test_a_turn_the_server_started_attaches_without_a_reload", async () => {
  const h = harness();
  try {
    await h.mount(THREAD_A);
    const reads = h.server.turnReads.get(THREAD_A) ?? 0;
    // The server queued a wake turn this chat never sent.
    h.server.turns.get(THREAD_A)!.push({ turn_id: "wake", state: "running" });
    await h.emitOnThread({ id: 20, type: "turn.accepted", turnId: "wake" });
    await h.flushUntil(() => h.turnStreams.has("wake"), "the wake turn attached");
    assert.equal(h.server.turnReads.get(THREAD_A), reads + 1, "one re-read found it");
  } finally {
    await h.teardown();
  }
});

test("test_one_reread_per_unknown_turn", async () => {
  const h = harness();
  try {
    await h.mount(THREAD_A);
    const reads = h.server.turnReads.get(THREAD_A) ?? 0;
    h.server.turns.get(THREAD_A)!.push({ turn_id: "wake", state: "running" });
    await h.emitOnThread({ id: 20, type: "turn.accepted", turnId: "wake" });
    await h.emitOnThread({ id: 21, type: "turn.started", turnId: "wake" });
    await h.emitOnThread({ id: 22, type: "turn.retrying", turnId: "wake" });
    await h.flushUntil(() => h.turnStreams.has("wake"), "the wake turn attached");
    await h.settle();
    assert.equal(h.server.turnReads.get(THREAD_A), reads + 1);
  } finally {
    await h.teardown();
  }
});

test("test_a_hidden_tab_closes_the_stream_and_reopens_from_its_cursor", async () => {
  const h = harness();
  try {
    await h.mount(THREAD_A);
    // A frame for a turn the chat already has: it only moves the cursor.
    await h.emitOnThread({ id: 30, type: "turn.completed", turnId: "done" });
    await h.settle();
    const first = h.threadOpens.at(-1)!;
    assert.equal(first.lastEventId, null, "a fresh open starts at the tail");

    await h.setVisibility("hidden");
    await h.flushUntil(() => first.signal?.aborted === true, "the hidden tab closed its stream");
    const opensWhileHidden = h.threadOpens.length;
    await h.settle();
    assert.equal(h.threadOpens.length, opensWhileHidden, "nothing reopens while hidden");

    await h.setVisibility("visible");
    await h.flushUntil(() => h.threadOpens.length === opensWhileHidden + 1, "reopened when shown");
    assert.equal(h.threadOpens.at(-1)?.lastEventId, "30", "from the last frame it saw");
  } finally {
    await h.teardown();
  }
});

test("test_switching_threads_closes_the_old_stream", async () => {
  const h = harness();
  try {
    await h.mount(THREAD_A);
    const old = h.threadOpens.at(-1)!;
    await h.mount(THREAD_B);
    assert.equal(old.signal?.aborted, true, "thread A's stream closed");
    const readsOfA = h.server.turnReads.get(THREAD_A) ?? 0;
    // A late frame of thread A arrives on its closed stream.
    try {
      old.body?.enqueue(new TextEncoder().encode(
        `id: 40\nevent: turn.accepted\ndata: ${JSON.stringify({
          schema_version: "1", event_id: 40, sequence: 1, occurred_at: TIMESTAMP,
          project_id: PROJECT, thread_id: THREAD_A, turn_id: "late", type: "turn.accepted",
        })}\n\n`,
      ));
    } catch {
      // The reader is cancelled: the frame cannot even be queued.
    }
    await h.settle();
    assert.equal(h.server.turnReads.get(THREAD_A) ?? 0, readsOfA, "thread A is not re-read");
    assert.equal(h.turnStreams.has("late"), false, "nothing attaches to thread A's turn");
  } finally {
    await h.teardown();
  }
});

test("test_a_reset_rereads_the_thread", async () => {
  const h = harness();
  try {
    await h.mount(THREAD_A);
    const reads = h.server.turnReads.get(THREAD_A) ?? 0;
    const threadReads = h.server.threadReads;
    await h.emitOnThread({ type: "stream.reset" });
    await h.flushUntil(
      () => (h.server.turnReads.get(THREAD_A) ?? 0) > reads && h.server.threadReads > threadReads,
      "the thread re-read after the reset",
    );
  } finally {
    await h.teardown();
  }
});
