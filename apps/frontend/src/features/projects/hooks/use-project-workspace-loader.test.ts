import assert from "node:assert/strict";
import test from "node:test";
import { JSDOM } from "jsdom";
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { ProjectsTransportProvider } from "@/features/projects/data/projects-transport";
import { clearChatPrefetch, takeChatPrefetch } from "@/features/projects/data/chat-prefetch";
import { clearProjectWorkspaceCache } from "@/features/projects/data/project-workspace-cache";
import { useProjectWorkspaceLoader } from "@/features/projects/hooks/use-project-workspace-loader";

/**
 * Chat switches within one project (2026-10-15): the chat page remounts per chat by design, and
 * every remount used to show "Loading project…" until the project was read again (~0.8 s). The
 * project a previous mount read is now shown at once and refreshed in the background — the latest
 * read still wins, and a refresh that fails reports the failure and forgets the cached project.
 */
const TRANSPORT = { mode: "http", prefix: "/api/clue" } as const;

function projectWire(id: string, title: string) {
  return {
    data: {
      id, title, brand_id: "brd_1", product_id: null, status: "active",
      created_at: "2026-10-15T12:00:00Z", context_entities: [], agent_profiles: [],
      default_agent_profile_id: null,
      composer_capabilities: { context_refs: true, attachments: false, agent_profile_selection: false },
      artifacts: [],
    },
  };
}

function environment() {
  const dom = new JSDOM("<div id='root'></div>");
  const originals = new Map<string, PropertyDescriptor | undefined>();
  for (const [key, value] of Object.entries({
    window: dom.window, document: dom.window.document, navigator: dom.window.navigator,
    IS_REACT_ACT_ENVIRONMENT: true,
  })) {
    originals.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
    Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
  }
  const oldFetch = globalThis.fetch;
  const server = {
    titles: new Map<string, string>(), reads: [] as string[], failing: new Set<string>(),
    chatReads: [] as string[],
  };
  globalThis.fetch = async (input) => {
    const path = new URL(String(input), "https://clue.invalid").pathname;
    if (path.includes("/threads")) {
      server.chatReads.push(path);
      return Response.json({ data: [], meta: { next_cursor: null } });
    }
    const id = path.split("/").at(-1)!;
    server.reads.push(id);
    if (server.failing.has(id)) {
      return Response.json({ error: { code: "PROJECT_NOT_FOUND", message: "Project not found", requestId: "r" } }, { status: 404 });
    }
    return Response.json(projectWire(id, server.titles.get(id) ?? "Untitled"));
  };
  const seen: Array<{ loading: boolean; title: string | null; error: string | null }> = [];
  let root: Root | null = null;
  function Probe({ projectId, threadId }: { projectId: string; threadId?: string }) {
    const state = useProjectWorkspaceLoader({ initialWorkspace: null, projectId, threadId });
    seen.push({ loading: state.loading, title: state.workspace?.title ?? null, error: state.error });
    return null;
  }
  async function mount(projectId: string, threadId?: string) {
    seen.length = 0;
    root = createRoot(dom.window.document.getElementById("root")!);
    await act(async () => {
      // eslint-disable-next-line react/no-children-prop
      root!.render(createElement(ProjectsTransportProvider, { transport: TRANSPORT, children: createElement(Probe, { projectId, threadId }) }));
    });
    for (let attempt = 0; attempt < 10; attempt += 1) {
      await act(async () => { await new Promise<void>((resolve) => setImmediate(resolve)); });
    }
  }
  async function unmount() {
    await act(async () => { root?.unmount(); });
  }
  function teardown() {
    globalThis.fetch = oldFetch;
    dom.window.close();
    for (const [key, descriptor] of originals) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else Reflect.deleteProperty(globalThis, key);
    }
  }
  return { server, seen, mount, unmount, teardown };
}

test("a second visit shows the project at once and still refreshes it", async () => {
  clearProjectWorkspaceCache();
  const env = environment();
  try {
    env.server.titles.set("prj_a", "First title");
    await env.mount("prj_a");
    assert.equal(env.seen[0].loading, true, "the first visit waits for the project");
    assert.equal(env.seen.at(-1)?.title, "First title");
    await env.unmount();

    env.server.titles.set("prj_a", "Renamed elsewhere");
    await env.mount("prj_a");
    assert.deepEqual(env.seen[0], { loading: false, title: "First title", error: null }, "no loading state on a repeat visit");
    assert.equal(env.seen.at(-1)?.title, "Renamed elsewhere", "the background refresh wins");
    assert.deepEqual(env.server.reads, ["prj_a", "prj_a"], "the project is still read on every visit");
    await env.unmount();

    // Another project is never shown from this one's read.
    env.server.titles.set("prj_b", "Other project");
    await env.mount("prj_b");
    assert.equal(env.seen[0].loading, true);
    assert.equal(env.seen[0].title, null);
    await env.unmount();
  } finally {
    env.teardown();
  }
});

test("a refresh that fails reports the failure and forgets the cached project", async () => {
  clearProjectWorkspaceCache();
  const env = environment();
  try {
    env.server.titles.set("prj_a", "Doomed");
    await env.mount("prj_a");
    await env.unmount();

    env.server.failing.add("prj_a");
    await env.mount("prj_a");
    assert.equal(env.seen[0].title, "Doomed", "the cached project shows while the refresh runs");
    assert.deepEqual(env.seen.at(-1), { loading: false, title: null, error: "Project not found" });
    await env.unmount();

    env.server.failing.delete("prj_a");
    await env.mount("prj_a");
    assert.equal(env.seen[0].loading, true, "nothing cached after the failure");
    await env.unmount();
  } finally {
    env.teardown();
  }
});


test("the first visit starts the chat's reads alongside the project read", async () => {
  // Chat load speed: before the project arrives the chat view does not exist, so the loader
  // starts the chat's reads and leaves them for the chat controller to take.
  clearProjectWorkspaceCache();
  clearChatPrefetch();
  const env = environment();
  try {
    env.server.titles.set("prj_c", "Chat project");
    await env.mount("prj_c", "thr_c");
    const base = "/api/clue/api/v1/projects/prj_c/threads";
    assert.deepEqual([...env.server.chatReads].sort(), [
      base, `${base}/thr_c/gates`, `${base}/thr_c/messages`, `${base}/thr_c/turns`,
    ]);
    assert.ok(takeChatPrefetch("prj_c", "thr_c"), "left for the chat controller");
    await env.unmount();

    // With the project already cached the chat view mounts at once and reads for itself, so the
    // loader starts nothing that would only duplicate those reads.
    env.server.chatReads.length = 0;
    await env.mount("prj_c", "thr_c");
    assert.deepEqual(env.server.chatReads, []);
    assert.equal(takeChatPrefetch("prj_c", "thr_c"), null);
    await env.unmount();
  } finally {
    env.teardown();
  }
});
