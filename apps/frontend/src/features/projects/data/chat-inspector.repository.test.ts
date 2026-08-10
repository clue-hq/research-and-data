import assert from "node:assert/strict";
import test from "node:test";
import { createChatRepositories } from "./chat-repositories";
import { createHttpChatInspectorRepository } from "./chat-inspector.repository";

/**
 * The inspector's transport seam.
 *
 * The property that matters most here is the frontend half of
 * production-unreachability: the drawer's affordance is rendered from a *probe*,
 * so a deployment that never registered the routes turns it off without any
 * component reading an environment variable. A client-side flag could disagree
 * with the server's; asking cannot.
 */

const TRANSPORT = { mode: "http", prefix: "/api/clue" } as const;
const SCOPE = { projectId: "p1", threadId: "t1", turnId: "turn-1" };

function withFetch(
  handler: (url: string) => Response | Promise<Response>,
): () => void {
  const original = globalThis.fetch;
  globalThis.fetch = (async (input: RequestInfo | URL) =>
    handler(String(input))) as typeof fetch;
  return () => {
    globalThis.fetch = original;
  };
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

test("a deployment without the inspector routes reports it unavailable, not broken", async () => {
  const restore = withFetch(() =>
    json({ error: { code: "NOT_FOUND", message: "no such route" } }, 404),
  );
  try {
    const probe = await createHttpChatInspectorRepository(TRANSPORT).probe({
      projectId: "p1",
      threadId: "t1",
    });
    // This is the production shape: the backend refuses to start with the flag
    // set, and with it unset never registers the routes — so every production
    // deployment answers exactly this, and no affordance is rendered.
    assert.equal(probe.available, false);
    assert.equal(probe.capability, null);
    assert.match(probe.reason ?? "", /development lens/);
  } finally {
    restore();
  }
});

test("a failure that is not a missing route is raised, never swallowed as 'off'", async () => {
  const restore = withFetch(() =>
    json({ error: { code: "SESSION_INVALID", message: "expired" } }, 401),
  );
  try {
    await assert.rejects(
      createHttpChatInspectorRepository(TRANSPORT).probe({
        projectId: "p1",
        threadId: "t1",
      }),
      /expired/,
    );
  } finally {
    restore();
  }
});

test("each tab is one GET under the turn's own inspector path", async () => {
  const seen: string[] = [];
  const restore = withFetch((url) => {
    seen.push(url);
    if (url.endsWith("/context")) return json({ data: null });
    if (url.endsWith("/rounds")) return json({ data: [] });
    if (url.endsWith("/plan")) {
      return json({
        data: {
          turn_id: SCOPE.turnId,
          plans: [],
          turn_events: [],
          budget_bytes: 512_000,
          truncated: false,
        },
      });
    }
    return json({
      data: {
        turn_id: SCOPE.turnId,
        calls: [],
        budget_bytes: 512_000,
        truncated: false,
      },
    });
  });
  try {
    const repository = createHttpChatInspectorRepository(TRANSPORT);
    assert.equal(await repository.context(SCOPE), null);
    assert.deepEqual(await repository.rounds(SCOPE), []);
    assert.deepEqual((await repository.plan(SCOPE)).plans, []);
    assert.deepEqual((await repository.tools(SCOPE)).calls, []);
    assert.deepEqual(seen, [
      "/api/clue/api/v1/projects/p1/threads/t1/turns/turn-1/inspector/context",
      "/api/clue/api/v1/projects/p1/threads/t1/turns/turn-1/inspector/rounds",
      "/api/clue/api/v1/projects/p1/threads/t1/turns/turn-1/inspector/plan",
      "/api/clue/api/v1/projects/p1/threads/t1/turns/turn-1/inspector/tools",
    ]);
  } finally {
    restore();
  }
});

test("the fixture transport carries an inspector, and it parses the same schemas", async () => {
  const repositories = createChatRepositories();
  const probe = await repositories.inspector.probe({ projectId: "p1", threadId: "t1" });
  assert.equal(probe.available, true);
  assert.equal(probe.capability?.budgetBytes, 512_000);

  // The fixture payloads go through the HTTP adapter's schemas — a fixture that
  // skipped validation would let the two drift, which is the failure this seam
  // exists to prevent.
  const context = await repositories.inspector.context(SCOPE);
  assert.ok(context);
  assert.equal(context.layers.length, 3);
  const tools = await repositories.inspector.tools(SCOPE);
  assert.equal(tools.calls.length, 2);
});
