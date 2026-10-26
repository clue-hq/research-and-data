import assert from "node:assert/strict";
import test from "node:test";
import {
  ClueChatApiError,
  PAGE_WORKSPACE_HEADER,
  chatRequest,
  setWorkspaceChangedHandler,
} from "./chat-api";

async function withFetch(
  respond: (headers: Headers) => Response,
  action: (seen: Headers[]) => Promise<void>,
) {
  const previous = globalThis.fetch;
  const seen: Headers[] = [];
  globalThis.fetch = async (_input, init = {}) => {
    const headers = new Headers(init.headers);
    seen.push(headers);
    return respond(headers);
  };
  try {
    await action(seen);
  } finally {
    globalThis.fetch = previous;
  }
}

test("a chat request names the workspace its page was loaded for (L4-4)", async () => {
  await withFetch(
    () => Response.json({ ok: true }),
    async (seen) => {
      await chatRequest({ mode: "http", prefix: "/api/clue", workspaceId: "ws_a" }, "/threads");
      assert.equal(seen[0].get(PAGE_WORKSPACE_HEADER), "ws_a");
      await chatRequest({ mode: "http", prefix: "/api/clue" }, "/threads");
      assert.equal(seen[1].get(PAGE_WORKSPACE_HEADER), null);
    },
  );
});

test("a workspace changed under the page reloads it; other refusals do not", async () => {
  let reloads = 0;
  setWorkspaceChangedHandler(() => {
    reloads += 1;
  });
  const transport = { mode: "http", prefix: "/api/clue", workspaceId: "ws_a" } as const;
  await withFetch(
    () =>
      Response.json(
        { error: { code: "WORKSPACE_CHANGED", message: "changed" } },
        { status: 409 },
      ),
    async () => {
      await assert.rejects(chatRequest(transport, "/threads"), (error: unknown) => {
        assert(error instanceof ClueChatApiError);
        assert.equal(error.code, "WORKSPACE_CHANGED");
        return true;
      });
    },
  );
  assert.equal(reloads, 1);
  await withFetch(
    () =>
      Response.json({ error: { code: "THREAD_NOT_FOUND", message: "gone" } }, { status: 404 }),
    async () => {
      await assert.rejects(chatRequest(transport, "/threads"));
    },
  );
  assert.equal(reloads, 1);
});
