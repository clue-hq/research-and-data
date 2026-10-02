import assert from "node:assert/strict";
import test from "node:test";
import {
  ClueChatApiError,
  PROJECTS_API_BASE_URL_VAR,
  chatUrl,
  newIdempotencyKey,
  resolveChatTransport,
} from "./chat-api";
import { createChatRepositories } from "./chat-repositories";
import { createHttpChatStreamRepository } from "./chat-stream.repository";
import { FIXTURE_PROJECT_ID, FIXTURE_THREAD_ID } from "./chat.fixture";

/** The seam: the flag, the same-origin rule, and the fixture default. */

test(`${PROJECTS_API_BASE_URL_VAR} unset means fixtures`, () => {
  assert.deepEqual(resolveChatTransport(undefined), { mode: "fixture" });
  assert.deepEqual(resolveChatTransport("  "), { mode: "fixture" });
});

test("the flag is an origin-relative BFF prefix, and anything else is refused", () => {
  assert.deepEqual(resolveChatTransport("/api/clue"), {
    mode: "http",
    prefix: "/api/clue",
  });
  assert.deepEqual(resolveChatTransport("/api/clue/"), {
    mode: "http",
    prefix: "/api/clue",
  });
  // A cross-origin value would mean the browser calling FastAPI directly with
  // no session — structurally forbidden, so it fails loudly at configuration.
  assert.throws(
    () => resolveChatTransport("https://api.example.com"),
    /origin-relative/,
  );
});

test(`${PROJECTS_API_BASE_URL_VAR} makes project fixtures unreachable on HTTP failure`, async () => {
  const originalFetch = globalThis.fetch;
  const requested: string[] = [];
  globalThis.fetch = async (input) => {
    requested.push(String(input));
    return Response.json(
      {
        error: {
          code: "UPSTREAM_UNAVAILABLE",
          message: "backend unavailable",
          requestId: "req-r7",
        },
      },
      { status: 503 },
    );
  };

  try {
    const repositories = createChatRepositories(
      resolveChatTransport("/api/clue"),
    );
    const outcomes = await Promise.allSettled([
      repositories.home.get(),
      repositories.projects.get(FIXTURE_PROJECT_ID),
      repositories.sidebar.list(),
    ]);

    assert.equal(repositories.transport.mode, "http");
    for (const outcome of outcomes) {
      if (outcome.status !== "rejected") assert.fail("HTTP failure used a fixture");
      assert.ok(outcome.reason instanceof ClueChatApiError);
      assert.equal(outcome.reason.code, "UPSTREAM_UNAVAILABLE");
    }
    assert.deepEqual(requested.sort(), [
      "/api/clue/api/v1/home",
      `/api/clue/api/v1/projects/${FIXTURE_PROJECT_ID}`,
      "/api/clue/api/v1/projects/sidebar",
    ].sort());
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("every request is mounted under the chat surface's own prefix", () => {
  const transport = { mode: "http", prefix: "/api/clue" } as const;
  assert.equal(
    chatUrl(transport, "/projects/p1/threads", { limit: 25, cursor: undefined }),
    "/api/clue/api/v1/projects/p1/threads?limit=25",
  );
});

test("an idempotency key is stable per act and distinct across acts", () => {
  const first = newIdempotencyKey("turn");
  assert.notEqual(first, newIdempotencyKey("turn"));
  assert.match(first, /^turn:/);
});

test("new chat creation carries the transfer act's idempotency key", async () => {
  const originalFetch = globalThis.fetch;
  let request: RequestInit | undefined;
  globalThis.fetch = async (_input, init) => {
    request = init;
    return Response.json({
      data: {
        id: "thread-1",
        title: null,
        href: "/projects/project-1/chats/thread-1",
        status: "idle",
        pinned: false,
        project_id: "project-1",
        created_at: "2026-08-13T00:00:00Z",
        updated_at: "2026-08-13T00:00:00Z",
      },
    });
  };
  try {
    const repositories = createChatRepositories({ mode: "http", prefix: "/api/clue" });
    await repositories.threads.create({
      idempotencyKey: "add-to-chat-thread:stable",
      projectId: "project-1",
      title: null,
    });
    assert.equal(
      new Headers(request?.headers).get("idempotency-key"),
      "add-to-chat-thread:stable",
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("stopping a discovery posts to its run's stop route and reads the receipt", async () => {
  const originalFetch = globalThis.fetch;
  const requests: { url: string; method: string | undefined; body: unknown }[] = [];
  globalThis.fetch = async (input, init) => {
    requests.push({ url: String(input), method: init?.method, body: init?.body });
    return Response.json({ data: { run_id: "run 7", stop_requested: true } });
  };
  try {
    const repositories = createChatRepositories({ mode: "http", prefix: "/api/clue" });
    const receipt = await repositories.discoveries.stop({
      projectId: "project 1",
      runId: "run 7",
    });
    assert.deepEqual(receipt, { runId: "run 7", stopRequested: true });
    assert.deepEqual(requests, [
      {
        url: "/api/clue/api/v1/projects/project%201/discovery-runs/run%207/stop",
        method: "POST",
        body: undefined,
      },
    ]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("the fixture discovery stop resolves without a network", async () => {
  const repositories = createChatRepositories();
  assert.deepEqual(
    await repositories.discoveries.stop({ projectId: FIXTURE_PROJECT_ID, runId: "run-1" }),
    { runId: "run-1", stopRequested: true },
  );
});

test("the fixture repositories serve a whole conversation", async () => {
  const repositories = createChatRepositories();
  const threads = await repositories.threads.list({ projectId: FIXTURE_PROJECT_ID });
  assert.ok(threads.threads.length >= 2);

  const messages = await repositories.messages.list({
    projectId: FIXTURE_PROJECT_ID,
    threadId: FIXTURE_THREAD_ID,
  });
  assert.equal(messages.messages[0].role, "user");
  assert.ok(messages.messages[1].body);

  const bodyFree = await repositories.messages.list({
    projectId: FIXTURE_PROJECT_ID,
    threadId: FIXTURE_THREAD_ID,
    includeBodies: false,
  });
  assert.equal(bodyFree.messages[1].body, null);

  const gates = await repositories.gates.list({
    projectId: FIXTURE_PROJECT_ID,
    threadId: FIXTURE_THREAD_ID,
  });
  assert.equal(gates.available, true);
  assert.equal(gates.gates.length, 1);
});

test("a duplicate submission under one idempotency key replays the same turn", async () => {
  const repositories = createChatRepositories();
  const submit = () =>
    repositories.turns.submit({
      projectId: FIXTURE_PROJECT_ID,
      threadId: FIXTURE_THREAD_ID,
      submission: { kind: "message", message: "again" },
      idempotencyKey: "fixed-key",
    });
  const first = await submit();
  const second = await submit();
  assert.equal(second.turnId, first.turnId);
  assert.equal(first.replayed, false);
  assert.equal(second.replayed, true);
});

test("a submitted turn is immediately visible as queued", async () => {
  const repositories = createChatRepositories();
  const accepted = await repositories.turns.submit({
    projectId: FIXTURE_PROJECT_ID,
    threadId: FIXTURE_THREAD_ID,
    submission: { kind: "message", message: "queue me" },
    idempotencyKey: "queued-key",
  });
  const page = await repositories.turns.list({
    projectId: FIXTURE_PROJECT_ID,
    threadId: FIXTURE_THREAD_ID,
  });
  const submitted = page.turns.find((turn) => turn.turnId === accepted.turnId);
  assert.equal(submitted?.state, "queued");
  assert.equal(page.threadRunning, true);
});

test("archiving a thread flips its status rather than deleting it", async () => {
  const repositories = createChatRepositories();
  const archived = await repositories.threads.archive({
    projectId: FIXTURE_PROJECT_ID,
    threadId: FIXTURE_THREAD_ID,
  });
  assert.equal(archived.status, "archived");
  const active = await repositories.threads.list({ projectId: FIXTURE_PROJECT_ID });
  assert.equal(
    active.threads.some((thread) => thread.id === FIXTURE_THREAD_ID),
    false,
  );
  const listed = await repositories.threads.list({
    projectId: FIXTURE_PROJECT_ID,
    status: "archived",
  });
  assert.ok(listed.threads.some((thread) => thread.id === FIXTURE_THREAD_ID));
});

test("the sidebar reads through its repository, never a fixture import", async () => {
  const response = await createChatRepositories().sidebar.list();
  assert.equal(response.meta.nextCursor, null);
  assert.ok(
    response.data.every((project) =>
      project.conversations.every((conversation) =>
        conversation.href.startsWith(project.href),
      ),
    ),
  );
});

test("the fixture stream delivers the scripted turn in order", async () => {
  const repositories = createChatRepositories();
  const types: string[] = [];
  await new Promise<void>((resolve) => {
    repositories.stream.attach({
      projectId: FIXTURE_PROJECT_ID,
      threadId: FIXTURE_THREAD_ID,
      turnId: "scripted",
      lastEventId: null,
      onEvent(event) {
        types.push(event.type);
      },
      onClosed() {
        resolve();
      },
    });
  });
  assert.equal(types[0], "turn.accepted");
  assert.equal(types.at(-1), "turn.awaiting_input");
  assert.ok(types.filter((type) => type === "text.delta").length > 1);
});

test("the HTTP stream cancels its reader and closes immediately on terminal", async () => {
  const originalFetch = globalThis.fetch;
  const types: string[] = [];
  let requestCount = 0;
  let readerCancelled = false;
  const encoder = new TextEncoder();

  globalThis.fetch = async () => {
    requestCount += 1;
    if (requestCount === 1) {
      return new Response(
        JSON.stringify({
          data: { schema_version: "1", stream_token: "token-1", turn_id: "turn-1" },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }
    return new Response(
      new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(
            encoder.encode(
              'event: stream.hello\ndata: {"schema_version":"1","project_id":"p1","thread_id":"th1","turn_id":"turn-1","type":"stream.hello"}\n\n' +
                'id: 7\nevent: turn.completed\ndata: {"schema_version":"1","event_id":7,"sequence":2,"occurred_at":"2026-08-10T00:00:00Z","project_id":"p1","thread_id":"th1","turn_id":"turn-1","type":"turn.completed","status":"completed"}\n\n',
            ),
          );
        },
        cancel() {
          readerCancelled = true;
        },
      }),
      { status: 200, headers: { "Content-Type": "text/event-stream" } },
    );
  };

  try {
    const repository = createHttpChatStreamRepository({
      mode: "http",
      prefix: "/api/clue",
    });
    const closeReason = await Promise.race([
      new Promise<string>((resolve, reject) => {
        repository.attach({
          projectId: "p1",
          threadId: "th1",
          turnId: "turn-1",
          lastEventId: null,
          onEvent(event) {
            types.push(event.type);
          },
          onError: reject,
          onClosed: resolve,
        });
      }),
      new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error("terminal stream did not close")), 1000),
      ),
    ]);
    assert.equal(closeReason, "terminal");
    assert.deepEqual(types, ["stream.hello", "turn.completed"]);
    assert.equal(readerCancelled, true);
    assert.equal(requestCount, 2, "terminal must not mint a reconnect token");
  } finally {
    globalThis.fetch = originalFetch;
  }
});
