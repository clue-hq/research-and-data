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

const PROJECT = "project-prefetch";
const THREAD = "thread-prefetch";
const OTHER = "thread-other";
const PREFIX = `/api/clue/api/v1/projects/${PROJECT}/threads`;
const TRANSPORT = { mode: "http", prefix: "/api/clue" } as const;
const TIMESTAMP = "2026-10-15T12:00:00Z";

/**
 * Chat load speed (2026-10-15): a chat named in the address starts reading its conversation —
 * messages, turns, approval cards — at the same moment as the project's chat list, instead of
 * after it. What it reads is shown only once the chat list confirms this exact chat; a chat that
 * is not in the project is never shown, and its refused reads never surface as errors.
 *
 * Only `fetch` is replaced: the schemas, the HTTP repositories and the controller's effects run
 * for real. The chat list is held until the test releases it.
 */
function harness({ listed }: { listed: string[] }) {
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
  const requested: string[] = [];
  const replaced: string[] = [];
  let releaseList: () => void = () => {};
  const listHeld = new Promise<void>((resolve) => { releaseList = resolve; });
  let latest: ProjectChatController | null = null;

  globalThis.fetch = async (input) => {
    const url = new URL(String(input), "https://clue.invalid");
    const path = url.pathname;
    requested.push(path);
    if (path === PREFIX) {
      await listHeld;
      return Response.json({ data: listed.map((id) => ({
        id, title: id, href: `/projects/${PROJECT}/chats/${id}`,
        status: "idle", pinned: false, project_id: PROJECT,
        created_at: TIMESTAMP, updated_at: TIMESTAMP,
      })), meta: { next_cursor: null } });
    }
    const inProject = listed.includes(THREAD);
    if (!inProject && path.startsWith(`${PREFIX}/${THREAD}/`)) {
      return Response.json(
        { error: { code: "THREAD_NOT_FOUND", message: "no such thread in this project", requestId: "r" } },
        { status: 404 },
      );
    }
    if (path === `${PREFIX}/${THREAD}/messages`) {
      return Response.json({ data: [{
        id: "message-1", turn_id: "turn-1", thread_id: THREAD, sequence: 1, role: "assistant",
        body_artifact_key: "key-1", body_sha256: "sha-1", body: "Hello from the chat",
        created_at: TIMESTAMP, refs: [],
      }], meta: { next_cursor: null } });
    }
    if (path === `${PREFIX}/${THREAD}/turns`) {
      return Response.json({ data: [{
        turn_id: "turn-1", thread_id: THREAD, project_id: PROJECT, state: "completed",
        requested_at: TIMESTAMP, last_event_id: null, generation_attempts: 1, submission_message: null,
      }], meta: { thread_status: "idle" } });
    }
    if (path === `${PREFIX}/${THREAD}/gates`) {
      return Response.json({ data: [] });
    }
    assert.fail(`unexpected request: ${path}`);
  };

  const root = createRoot(dom.window.document.getElementById("root")!);
  function Probe() {
    latest = useProjectChatController({
      projectId: PROJECT,
      initialThreadId: THREAD,
      projectTitle: "Prefetch project",
    });
    return null;
  }
  function controller(): ProjectChatController {
    assert.ok(latest, "controller is mounted");
    return latest;
  }
  async function flush(times = 10) {
    for (let attempt = 0; attempt < times; attempt += 1) {
      await act(async () => { await new Promise<void>((resolve) => setImmediate(resolve)); });
    }
  }
  const unexpectedNavigation = () => assert.fail("no navigation is expected");
  async function mount() {
    await act(async () => {
      root.render(createElement(AppRouterContext.Provider, {
        value: {
          back: unexpectedNavigation, forward: unexpectedNavigation,
          refresh: unexpectedNavigation, push: unexpectedNavigation,
          replace: (href: string) => { replaced.push(href); },
          prefetch: async () => {},
        },
      }, createElement(SearchParamsContext.Provider, { value: new URLSearchParams() },
        // eslint-disable-next-line react/no-children-prop
        createElement(ProjectsTransportProvider, {
          transport: TRANSPORT,
          children: createElement(Probe),
        }),
      )));
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
  return { requested, replaced, releaseList, controller, flush, mount, teardown };
}

const count = (paths: string[], path: string) => paths.filter((item) => item === path).length;

test("the conversation is read alongside the chat list and shown once the list confirms the chat", async () => {
  const h = harness({ listed: [THREAD] });
  try {
    await h.mount();
    await h.flush();
    // The chat list is still held, yet the conversation's three reads have already gone out.
    assert.equal(count(h.requested, PREFIX), 1);
    assert.equal(count(h.requested, `${PREFIX}/${THREAD}/messages`), 1);
    assert.equal(count(h.requested, `${PREFIX}/${THREAD}/turns`), 1);
    assert.equal(count(h.requested, `${PREFIX}/${THREAD}/gates`), 1);
    // Nothing is shown before the list confirms this chat belongs to the project.
    assert.equal(h.controller().transcript.length, 0);

    h.releaseList();
    await h.flush();
    assert.ok(
      h.controller().transcript.some((message) => JSON.stringify(message).includes("Hello from the chat")),
      "the early read is what the transcript shows",
    );
    // The early read is used, not repeated.
    assert.equal(count(h.requested, `${PREFIX}/${THREAD}/messages`), 1);
    assert.equal(h.controller().error, null);
  } finally {
    await h.teardown();
  }
});

test("a chat that is not in the project is never shown and its refused reads raise nothing", async () => {
  const h = harness({ listed: [OTHER] });
  try {
    await h.mount();
    await h.flush();
    h.releaseList();
    await h.flush();
    // The project has another chat, so the route moves there; this chat's reads were discarded.
    assert.deepEqual(h.replaced, [`/projects/${PROJECT}/chats/${OTHER}`]);
    assert.equal(h.controller().transcript.length, 0);
    assert.equal(h.controller().error, null);
  } finally {
    await h.teardown();
  }
});

test("a chat in a project with no chats reports the route, not the refused early reads", async () => {
  const h = harness({ listed: [] });
  try {
    await h.mount();
    await h.flush();
    h.releaseList();
    await h.flush();
    assert.equal(h.controller().route?.code, "THREAD_NOT_FOUND");
    assert.equal(h.controller().transcript.length, 0);
    assert.equal(h.controller().error, null);
  } finally {
    await h.teardown();
  }
});
