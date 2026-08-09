import assert from "node:assert/strict";
import test from "node:test";
import {
  PROJECTS_API_BASE_URL_VAR,
  chatUrl,
  newIdempotencyKey,
  resolveChatTransport,
} from "./chat-api";
import { createChatRepositories } from "./chat-repositories";
import { FIXTURE_PROJECT_ID, FIXTURE_THREAD_ID } from "./chat.fixture";
import { createSidebarProjectsRepository } from "./sidebar-projects.repository";

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
  const sidebar = createSidebarProjectsRepository(createChatRepositories());
  const response = await sidebar.list();
  assert.equal(response.meta.total, response.data.length);
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
      onClosed: resolve,
    });
  });
  assert.equal(types[0], "turn.accepted");
  assert.equal(types.at(-1), "turn.awaiting_input");
  assert.ok(types.filter((type) => type === "text.delta").length > 1);
});
