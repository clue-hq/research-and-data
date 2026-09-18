import assert from "node:assert/strict";
import test from "node:test";
import { JSDOM } from "jsdom";
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { AppRouterContext } from "next/dist/shared/lib/app-router-context.shared-runtime";
import { SearchParamsContext } from "next/dist/shared/lib/hooks-client-context.shared-runtime";
import { ProjectsTransportProvider } from "@/features/projects/data/projects-transport";
import { agentRunLockForThread } from "@/features/chat-shell/model/agent-run-lock";
import {
  useProjectChatController,
  type ProjectChatController,
} from "@/features/projects/hooks/use-project-chat-controller";

const PROJECT = "project-lock-regression";
const THREAD = "thread-lock-regression";
const PREFIX = `/api/clue/api/v1/projects/${PROJECT}/threads`;
const TRANSPORT = { mode: "http", prefix: "/api/clue" } as const;
const TIMESTAMP = "2026-09-07T12:00:00Z";

// Catch a missing controller lock fold or the stale opener surviving a real
// terminal stream + list refresh. Only fetch is replaced: schemas, HTTP/SSE
// repositories, controller effects, transcript and lock selector all run.
for (const replayOrder of ["opener-first", "design-first"] as const) {
  test(`the mounted controller releases a failed Design after ${replayOrder} replay and stale reads`, async () => {
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
    let eventId = 0;
    let stale = true;
    let conversationReads = 0;
    let threadReads = 0;
    let latest: ProjectChatController | null = null;

    globalThis.fetch = async (input, init) => {
      const url = new URL(String(input), "https://clue.invalid");
      const path = url.pathname;
      const turnMatch = path.match(/\/turns\/(opener|design)\/(stream_token|events)$/);
      if (turnMatch) {
        const [, turnId, operation] = turnMatch;
        if (operation === "stream_token") {
          assert.equal(init?.method, "POST");
          return Response.json({ data: { schema_version: "1", turn_id: turnId, stream_token: `token-${turnId}` } });
        }
        assert.equal(init?.method ?? "GET", "GET");
        assert.equal(new Headers(init?.headers).get("Last-Event-ID"), null);
        return new Response(new ReadableStream<Uint8Array>({
          start(controller) { streams.set(turnId, controller); },
        }), { headers: { "Content-Type": "text/event-stream" } });
      }
      assert.equal(init?.method ?? "GET", "GET", "the test must not submit work");
      if (path === PREFIX) {
        threadReads += 1;
        return Response.json({ data: [{
          id: THREAD, title: "Design", href: `/projects/${PROJECT}/chats/${THREAD}`,
          status: stale ? "running" : "idle", pinned: false, project_id: PROJECT,
          created_at: TIMESTAMP, updated_at: TIMESTAMP,
          speaker: { role: "design", design_leg_id: "leg-1", design_leg_state: stale ? "running" : "open_awaiting_user" },
        }], meta: { next_cursor: null } });
      }
      if (path === `${PREFIX}/${THREAD}/turns`) {
        conversationReads += 1;
        return Response.json({ data: ["opener", "design"].map((turnId) => ({
          turn_id: turnId, thread_id: THREAD, project_id: PROJECT,
          state: turnId === "opener" ? "awaiting_input" : stale ? "running" : "failed",
          requested_at: TIMESTAMP, last_event_id: null, generation_attempts: 1, submission_message: null,
        })), meta: { thread_status: stale ? "running" : "idle" } });
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
    function locked() {
      const current = controller();
      return agentRunLockForThread({
        activeThreadId: current.activeThreadId, designLeg: current.designLeg,
        documentId: "doc-1", documentThreadId: THREAD,
        state: current.agentRunLock, threadBusy: current.threadBusy,
      }).locked;
    }
    async function flushUntil(predicate: () => boolean) {
      for (let attempt = 0; attempt < 30; attempt += 1) {
        await act(async () => { await new Promise<void>((resolve) => setImmediate(resolve)); });
        if (predicate()) return;
      }
      assert.fail("controller did not reach the expected state");
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
            ...(type.startsWith("leg.") ? { leg_id: "leg-1" } : {}),
          };
          stream.enqueue(new TextEncoder().encode(`id: ${eventId}\nevent: ${type}\ndata: ${JSON.stringify(payload)}\n\n`));
        }
      });
    }
    const unexpectedNavigation = () => assert.fail("no navigation is expected");
    async function mount(key: string) {
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
            children: createElement(Probe, { key }),
          }),
        )));
      });
      await flushUntil(() => streams.size === 2);
    }
    try {
      await mount("initial");
      assert.equal(locked(), true, "durable running floor engages before any stream frame");
      if (replayOrder === "opener-first") {
        await emit("opener", ["turn.accepted", "turn.started", "leg.opened", "turn.awaiting_input"]);
      }
      await emit("design", ["turn.accepted", "turn.started"]);
      assert.equal(locked(), true, "the live Design writer keeps the editor locked");
      const readsBeforeTerminal = conversationReads;
      await emit("design", ["leg.awaiting_user", "turn.failed"]);
      await flushUntil(() => conversationReads > readsBeforeTerminal);
      if (replayOrder === "design-first") {
        await emit("opener", ["turn.accepted", "turn.started", "leg.opened", "turn.awaiting_input"]);
      }
      assert.ok(controller().transcript.some((message) => message.turnId === "design" && message.state === "failed"));
      assert.equal(controller().threadBusy, false, "stream failure outranks the stale running turn list");
      assert.deepEqual(controller().designLeg, { kind: "open", running: true }, "the stale running leg snapshot really reached the controller");
      assert.equal(locked(), false, "the terminal writer and non-writing opener both retire");

      // A route reload reads the now-current lists, then replays both turns
      // from the first frame. It must not rebuild the stale opener lock.
      stale = false;
      const threadsBeforeRefresh = threadReads;
      streams.clear();
      await mount("reload");
      assert.ok(threadReads > threadsBeforeRefresh);
      assert.deepEqual(controller().designLeg, { kind: "open", running: false });
      const replayOpener = () => emit("opener", ["turn.accepted", "turn.started", "leg.opened", "turn.awaiting_input"]);
      const replayDesign = () => emit("design", ["turn.accepted", "turn.started", "leg.awaiting_user", "turn.failed"]);
      if (replayOrder === "opener-first") {
        await replayOpener();
        await replayDesign();
      } else {
        await replayDesign();
        await replayOpener();
      }
      assert.equal(locked(), false);
    } finally {
      await act(async () => { root.unmount(); });
      globalThis.fetch = oldFetch;
      dom.window.close();
      for (const [key, descriptor] of originals) {
        if (descriptor) Object.defineProperty(globalThis, key, descriptor);
        else Reflect.deleteProperty(globalThis, key);
      }
    }
  });
}
