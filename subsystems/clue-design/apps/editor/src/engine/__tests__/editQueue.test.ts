import { describe, expect, it, vi } from "vitest";

import minimalSceneFixture from "../../../../../crates/lumen-core/fixtures/minimal_scene.json";
import type { Operation, Scene } from "../contracts";
import { createEditQueue, type ReconcileEvent } from "../editQueue";

const baseScene = minimalSceneFixture as unknown as Scene;

function cloneScene(scene: Scene): Scene {
  return JSON.parse(JSON.stringify(scene)) as Scene;
}

function operationBatch(label: string): Operation[] {
  return [
    {
      kind: "remove_node",
      node_id: `node_${label}`
    } as Operation
  ];
}

interface FakeServerOptions {
  scene?: Scene;
  failPostWith?: number;
  networkError?: boolean;
}

function fakeServer(options: FakeServerOptions = {}) {
  const scene = options.scene ?? cloneScene(baseScene);
  let version = 7;
  const posts: Array<{ url: string; body: Record<string, unknown> }> = [];
  let documentFetches = 0;

  const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (options.networkError) {
      throw new Error("network down");
    }
    if (init?.method === "POST") {
      posts.push({ url, body: JSON.parse(String(init.body)) as Record<string, unknown> });
      if (options.failPostWith) {
        return jsonResponse({ detail: { code: "edits.base_version_mismatch" } }, options.failPostWith);
      }
      version += 1;
      return jsonResponse({
        schema_version: 1,
        status: "applied",
        document: { id: "doc_test", current_version: version }
      });
    }
    documentFetches += 1;
    return jsonResponse({ id: "doc_test", current_version: version, scene });
  }) as unknown as typeof fetch;

  return {
    fetchImpl,
    posts,
    get version() {
      return version;
    },
    get documentFetches() {
      return documentFetches;
    }
  };
}

function jsonResponse(payload: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload
  } as Response;
}

describe("editQueue", () => {
  it("persists batches in order with chained base versions", async () => {
    const localScene = cloneScene(baseScene);
    const server = fakeServer({ scene: localScene });
    const events: ReconcileEvent[] = [];
    const queue = createEditQueue({
      apiBaseUrl: "http://api.test",
      documentId: "doc_test",
      localScene: () => localScene,
      onReconcile: (event) => events.push(event),
      fetchImpl: server.fetchImpl
    });

    queue.enqueueOperations(operationBatch("a"));
    queue.enqueueOperations(operationBatch("b"));
    queue.enqueueOperations(operationBatch("c"));
    await queue.idle();

    expect(server.posts.map((post) => post.body.operations)).toEqual([
      operationBatch("a"),
      operationBatch("b"),
      operationBatch("c")
    ]);
    // First batch learns version 7 from the document; subsequent batches
    // chain the version returned by each accepted batch.
    expect(server.posts.map((post) => post.body.base_version)).toEqual([7, 8, 9]);
    expect(server.posts.every((post) => post.body.source === "editor")).toBe(true);
    expect(queue.persistedBatches).toBe(3);
    // Matching scenes at drain: no reconcile events.
    expect(events).toEqual([]);
  });

  it("reconciles only when the queue drains", async () => {
    const localScene = cloneScene(baseScene);
    const server = fakeServer({ scene: localScene });
    const queue = createEditQueue({
      apiBaseUrl: "http://api.test",
      documentId: "doc_test",
      localScene: () => localScene,
      onReconcile: () => undefined,
      fetchImpl: server.fetchImpl
    });

    queue.enqueueOperations(operationBatch("a"));
    queue.enqueueOperations(operationBatch("b"));
    await queue.idle();

    // One fetch to learn the base version + one drain-time reconcile —
    // never one per batch.
    expect(server.documentFetches).toBe(2);
  });

  it("surfaces divergence as a diagnostic with the server scene", async () => {
    const serverScene = cloneScene(baseScene);
    serverScene.meta.title = "Server truth";
    const server = fakeServer({ scene: serverScene });
    const events: ReconcileEvent[] = [];
    const localScene = cloneScene(baseScene);
    const queue = createEditQueue({
      apiBaseUrl: "http://api.test",
      documentId: "doc_test",
      localScene: () => localScene,
      onReconcile: (event) => events.push(event),
      fetchImpl: server.fetchImpl
    });

    queue.enqueueOperations(operationBatch("a"));
    await queue.idle();

    expect(events).toHaveLength(1);
    expect(events[0].kind).toBe("divergence");
    expect(events[0].diagnostic.code).toBe("EDITOR_WASM_RECONCILE_DIVERGENCE");
    expect(events[0].serverScene?.meta.title).toBe("Server truth");
  });

  it("does not flag divergence for key-order differences", async () => {
    const localScene = cloneScene(baseScene);
    // Same content, different top-level key order than the fixture.
    const reordered = JSON.parse(
      JSON.stringify({
        export_profiles: localScene.export_profiles,
        slots: localScene.slots,
        nodes: localScene.nodes,
        pages: localScene.pages,
        meta: localScene.meta,
        assets: localScene.assets,
        schema_version: localScene.schema_version
      })
    ) as Scene;
    const server = fakeServer({ scene: reordered });
    const events: ReconcileEvent[] = [];
    const queue = createEditQueue({
      apiBaseUrl: "http://api.test",
      documentId: "doc_test",
      localScene: () => localScene,
      onReconcile: (event) => events.push(event),
      fetchImpl: server.fetchImpl
    });

    queue.enqueueOperations(operationBatch("a"));
    await queue.idle();
    expect(events).toEqual([]);
  });

  it("recovers the server scene when a batch is rejected", async () => {
    const serverScene = cloneScene(baseScene);
    serverScene.meta.title = "Server truth";
    const server = fakeServer({ scene: serverScene, failPostWith: 409 });
    const events: ReconcileEvent[] = [];
    const queue = createEditQueue({
      apiBaseUrl: "http://api.test",
      documentId: "doc_test",
      localScene: () => cloneScene(baseScene),
      onReconcile: (event) => events.push(event),
      fetchImpl: server.fetchImpl
    });

    queue.enqueueOperations(operationBatch("a"));
    queue.enqueueOperations(operationBatch("b"));
    await queue.idle();

    expect(events).toHaveLength(1);
    expect(events[0].kind).toBe("rejected");
    expect(events[0].diagnostic.code).toBe("EDITOR_WASM_EDIT_REJECTED");
    expect(events[0].serverScene?.meta.title).toBe("Server truth");
    // The queue halts after rejection: the second batch is not sent.
    expect(server.posts).toHaveLength(1);
  });

  it("reports request failures and stops persisting", async () => {
    const server = fakeServer({ networkError: true });
    const events: ReconcileEvent[] = [];
    const queue = createEditQueue({
      apiBaseUrl: "http://api.test",
      documentId: "doc_test",
      localScene: () => cloneScene(baseScene),
      onReconcile: (event) => events.push(event),
      fetchImpl: server.fetchImpl
    });

    queue.enqueueOperations(operationBatch("a"));
    await queue.idle();

    expect(events).toHaveLength(1);
    expect(events[0].kind).toBe("request_failed");
    expect(events[0].diagnostic.code).toBe("EDITOR_WASM_EDIT_PERSIST_FAILED");
    expect(queue.persistedBatches).toBe(0);
  });

  it("stamps a checkpoint label onto exactly the batch that carries it (2d)", async () => {
    const localScene = cloneScene(baseScene);
    const server = fakeServer({ scene: localScene });
    const queue = createEditQueue({
      apiBaseUrl: "http://api.test",
      documentId: "doc_test",
      localScene: () => localScene,
      onReconcile: () => {},
      fetchImpl: server.fetchImpl
    });

    queue.enqueueOperations(operationBatch("a"), { checkpoint: "agent-turn-run_1" });
    queue.enqueueOperations(operationBatch("b"));
    await queue.idle();

    expect(server.posts[0].body.checkpoint).toBe("agent-turn-run_1");
    // Unlabeled batches carry NO checkpoint field at all.
    expect("checkpoint" in server.posts[1].body).toBe(false);
  });

  it("resync re-arms base_version after an external server write (2d revert)", async () => {
    const localScene = cloneScene(baseScene);
    const server = fakeServer({ scene: localScene });
    const queue = createEditQueue({
      apiBaseUrl: "http://api.test",
      documentId: "doc_test",
      localScene: () => localScene,
      onReconcile: () => {},
      fetchImpl: server.fetchImpl
    });

    queue.enqueueOperations(operationBatch("a"));
    await queue.idle();
    expect(server.posts[0].body.base_version).toBe(7);

    // A checkpoint revert bumped the server to version 42 behind the
    // queue's back; without resync the next batch would POST base_version 8
    // (stale) and be rejected as a concurrent write.
    queue.resync(42);
    queue.enqueueOperations(operationBatch("b"));
    await queue.idle();
    expect(server.posts[1].body.base_version).toBe(42);
  });
});
