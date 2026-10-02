import assert from "node:assert/strict";
import test from "node:test";
import { JSDOM } from "jsdom";
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { AppRouterContext } from "next/dist/shared/lib/app-router-context.shared-runtime";
import { SearchParamsContext } from "next/dist/shared/lib/hooks-client-context.shared-runtime";
import { ProjectsTransportProvider } from "@/features/projects/data/projects-transport";
import {
  composerRunControl,
  useProjectChatController,
  type ProjectChatController,
} from "@/features/projects/hooks/use-project-chat-controller";

const PROJECT = "project-discovery";
const THREAD = "thread-discovery";
const RUN = "run-discovery-1";
const PREFIX = `/api/clue/api/v1/projects/${PROJECT}/threads`;
const STOP_DISCOVERY = `/api/clue/api/v1/projects/${PROJECT}/discovery-runs/${RUN}/stop`;
const TRANSPORT = { mode: "http", prefix: "/api/clue" } as const;
const TIMESTAMP = "2026-09-30T12:00:00Z";

/**
 * Agent-authored discovery, task 10: a discovery run keeps its chat thread busy
 * and the composer's Stop stops it.
 *
 * Only `fetch` is replaced: the schemas, the HTTP and SSE repositories, the
 * controller's effects and the composer's run control all run for real. The
 * thread holds one finished launching turn and one message the human sent
 * while the discovery ran, which the backend holds `queued`.
 */
function harness({ stoppable }: { stoppable: boolean }) {
  const dom = new JSDOM("<div id='root'></div>");
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
  const streams = new Map<string, ReadableStreamDefaultController<Uint8Array>>();
  const sequences = new Map<string, number>();
  const posts: string[] = [];
  const server = {
    discovery: { run_id: RUN, stoppable } as { run_id: string; stoppable: boolean } | null,
    heldState: "queued",
    threadReads: 0,
  };
  let eventId = 0;
  let latest: ProjectChatController | null = null;

  globalThis.fetch = async (input, init) => {
    const url = new URL(String(input), "https://clue.invalid");
    const path = url.pathname;
    const turnMatch = path.match(/\/turns\/(launch|held)\/(stream_token|events)$/);
    if (turnMatch) {
      const [, turnId, operation] = turnMatch;
      if (operation === "stream_token") {
        return Response.json({ data: { schema_version: "1", turn_id: turnId, stream_token: `token-${turnId}` } });
      }
      return new Response(new ReadableStream<Uint8Array>({
        start(controller) { streams.set(turnId, controller); },
      }), { headers: { "Content-Type": "text/event-stream" } });
    }
    if ((init?.method ?? "GET") === "POST") {
      posts.push(path);
      if (path === STOP_DISCOVERY) {
        return Response.json({ data: { run_id: RUN, stop_requested: true } });
      }
      if (path === `${PREFIX}/${THREAD}/turns/held/stop`) {
        return Response.json({ data: {
          turn_id: "held", control_id: "control-1", requested_at: TIMESTAMP, already_requested: false,
        } });
      }
      assert.fail(`unexpected POST: ${path}`);
    }
    if (path === PREFIX) {
      server.threadReads += 1;
      return Response.json({ data: [{
        id: THREAD, title: "Discovery", href: `/projects/${PROJECT}/chats/${THREAD}`,
        status: "running", pinned: false, project_id: PROJECT,
        created_at: TIMESTAMP, updated_at: TIMESTAMP,
        discovery: server.discovery,
      }], meta: { next_cursor: null } });
    }
    if (path === `${PREFIX}/${THREAD}/turns`) {
      return Response.json({ data: [
        { turn_id: "launch", state: "completed" },
        { turn_id: "held", state: server.heldState },
      ].map(({ turn_id, state }) => ({
        turn_id, thread_id: THREAD, project_id: PROJECT, state,
        requested_at: TIMESTAMP, last_event_id: null, generation_attempts: 1, submission_message: null,
      })), meta: { thread_status: "running" } });
    }
    if (path === `${PREFIX}/${THREAD}/messages` || path === `${PREFIX}/${THREAD}/gates`) {
      return Response.json({ data: [], meta: { next_cursor: null } });
    }
    assert.fail(`unexpected request: ${path}`);
  };

  const root = createRoot(dom.window.document.getElementById("root")!);
  function Probe() {
    latest = useProjectChatController({
      projectId: PROJECT,
      initialThreadId: THREAD,
      projectTitle: "Named project",
    });
    return null;
  }
  function controller(): ProjectChatController {
    assert.ok(latest, "controller is mounted");
    assert.equal(latest.error, null);
    return latest;
  }
  async function flushUntil(predicate: () => boolean, what: string) {
    for (let attempt = 0; attempt < 30; attempt += 1) {
      await act(async () => { await new Promise<void>((resolve) => setImmediate(resolve)); });
      if (predicate()) return;
    }
    assert.fail(`controller did not reach: ${what}`);
  }
  async function emit(turnId: string, types: string[]) {
    const stream = streams.get(turnId);
    assert.ok(stream, `attached ${turnId}`);
    await act(async () => {
      for (const type of types) {
        eventId += 1;
        const sequence = (sequences.get(turnId) ?? 0) + 1;
        sequences.set(turnId, sequence);
        const payload = {
          schema_version: "1", event_id: eventId, sequence, occurred_at: TIMESTAMP,
          project_id: PROJECT, thread_id: THREAD, turn_id: turnId,
          message_id: `message-${turnId}`, type,
        };
        stream.enqueue(new TextEncoder().encode(`id: ${eventId}\nevent: ${type}\ndata: ${JSON.stringify(payload)}\n\n`));
      }
    });
  }
  const unexpectedNavigation = () => assert.fail("no navigation is expected");
  async function mount() {
    await act(async () => {
      root.render(createElement(AppRouterContext.Provider, {
        value: {
          back: unexpectedNavigation, forward: unexpectedNavigation,
          refresh: unexpectedNavigation,
          push: unexpectedNavigation, replace: unexpectedNavigation,
          prefetch: async () => {},
        },
      }, createElement(SearchParamsContext.Provider, { value: new URLSearchParams() },
        // The createElement overload requires the provider's children prop.
        // eslint-disable-next-line react/no-children-prop
        createElement(ProjectsTransportProvider, {
          transport: TRANSPORT,
          children: createElement(Probe),
        }),
      )));
    });
    await flushUntil(() => streams.size === 2, "both turns attached");
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
  return { server, posts, controller, flushUntil, emit, mount, teardown };
}

test("a discovery keeps the composer running, Stop stops the run, and the turn state takes over once it is gone", async () => {
  const h = harness({ stoppable: true });
  try {
    await h.mount();
    assert.equal(h.controller().runningTurn, null, "no turn is running");
    assert.equal(h.controller().discoveryRunId, RUN);
    assert.equal(composerRunControl(h.controller()).running, true, "the discovery holds the composer running");

    await act(async () => { composerRunControl(h.controller()).onStop(); });
    await h.flushUntil(() => h.posts.length > 0, "the stop request");
    assert.deepEqual(h.posts, [STOP_DISCOVERY], "Stop went to the discovery run, not to a turn");

    // The run ended and its wake released the thread: the thread list no
    // longer names a discovery. A turn frame for this thread re-reads it.
    h.server.discovery = null;
    h.server.heldState = "running";
    const readsBefore = h.server.threadReads;
    await h.emit("held", ["turn.accepted", "turn.started"]);
    await h.flushUntil(
      () => h.server.threadReads > readsBefore && h.controller().discoveryRunId === null,
      "the thread re-read without its discovery",
    );
    assert.equal(h.controller().runningTurn?.turnId, "held");
    assert.equal(composerRunControl(h.controller()).running, true, "the running turn now holds it");

    await act(async () => { composerRunControl(h.controller()).onStop(); });
    await h.flushUntil(() => h.posts.length > 1, "the turn stop request");
    assert.deepEqual(h.posts.slice(1), [`${PREFIX}/${THREAD}/turns/held/stop`], "with a running turn, Stop stops the turn");

    h.server.heldState = "completed";
    await h.emit("held", ["turn.completed"]);
    await h.flushUntil(() => h.controller().runningTurn === null, "the turn ended");
    assert.equal(composerRunControl(h.controller()).running, false, "with no discovery and no turn, nothing runs");
  } finally {
    await h.teardown();
  }
});

test("a discovery that can no longer stop still holds the composer, and Stop sends nothing", async () => {
  const h = harness({ stoppable: false });
  try {
    await h.mount();
    assert.equal(h.controller().discoveryRunId, RUN);
    assert.equal(composerRunControl(h.controller()).running, true);
    await act(async () => { composerRunControl(h.controller()).onStop(); });
    await h.flushUntil(() => true, "a settled render");
    assert.deepEqual(h.posts, [], "no stop request for a run that has already ended");
    assert.equal(composerRunControl(h.controller()).running, true);
  } finally {
    await h.teardown();
  }
});
