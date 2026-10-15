import assert from "node:assert/strict";
import test from "node:test";
import { clearChatPrefetch, startChatPrefetch, takeChatPrefetch } from "./chat-prefetch";
import type { ChatRepositories } from "./chat-repositories";

/** A repositories stand-in that records each read and answers (or refuses) on demand. */
function fakeRepositories(fail = false) {
  const calls: string[] = [];
  const answer = (name: string) => {
    calls.push(name);
    return fail ? Promise.reject(new Error(`${name} refused`)) : Promise.resolve({ name });
  };
  const repositories = {
    threads: { list: () => answer("threads") },
    messages: { list: () => answer("messages") },
    turns: { list: () => answer("turns") },
    gates: { list: () => answer("gates") },
  } as unknown as ChatRepositories;
  return { calls, repositories };
}

test("a chat's reads start once, are taken once, and only by the same chat", async () => {
  clearChatPrefetch();
  const { calls, repositories } = fakeRepositories();
  startChatPrefetch(repositories, "prj", "thr", 1_000);
  startChatPrefetch(repositories, "prj", "thr", 1_500); // a second start reuses the first
  assert.deepEqual(calls.sort(), ["gates", "messages", "threads", "turns"]);
  assert.equal(takeChatPrefetch("prj", "other", 2_000), null);
  const taken = takeChatPrefetch("prj", "thr", 2_000);
  assert.ok(taken);
  assert.deepEqual(await taken.threads, { name: "threads" });
  assert.deepEqual(await taken.conversation.messages, { name: "messages" });
  assert.equal(takeChatPrefetch("prj", "thr", 2_000), null, "taken only once");
});

test("reads nobody takes in time expire, and refused reads never go unhandled", async () => {
  clearChatPrefetch();
  const { repositories } = fakeRepositories(true);
  startChatPrefetch(repositories, "prj", "thr", 1_000);
  assert.equal(takeChatPrefetch("prj", "thr", 1_000 + 30_000), null, "too old to use");
  // The refused reads were started and dropped; reaching here without an unhandled rejection
  // (node:test fails the run on one) is the assertion.
  await new Promise((resolve) => setImmediate(resolve));

  startChatPrefetch(repositories, "prj", "thr", 50_000);
  const taken = takeChatPrefetch("prj", "thr", 50_100);
  assert.ok(taken);
  await assert.rejects(taken.conversation.gates, /gates refused/, "a taken read still rejects where awaited");
});
