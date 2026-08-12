import assert from "node:assert/strict";
import test from "node:test";
import {
  CHAT_CONTEXT_HANDOFF_TTL_MS,
  createChatContextHandoff,
  deleteChatContextHandoff,
  readChatContextHandoff,
  updateChatContextHandoffEntities,
  writeChatContextHandoff,
} from "./chat-context-handoff";

class MemoryStorage {
  readonly values = new Map<string, string>();

  getItem(key: string) {
    return this.values.get(key) ?? null;
  }

  removeItem(key: string) {
    this.values.delete(key);
  }

  setItem(key: string, value: string) {
    this.values.set(key, value);
  }
}

const account = {
  id: "account-1",
  imagePath: "/logos/clue.svg",
  label: "Acme",
  secondaryLabel: "acme.example",
  type: "account" as const,
  version: 7,
};

test("an opaque handoff restores exact hydrated entities only in its project and thread", () => {
  const storage = new MemoryStorage();
  const handoff = createChatContextHandoff({
    entities: [account],
    handoffId: "bf2f36ee-cb26-4555-a614-b05a3dcc10bc",
    now: 1_000,
    projectId: "project-1",
    source: "accounts",
    threadId: "thread-1",
  });
  writeChatContextHandoff(storage, handoff);

  assert.deepEqual(
    readChatContextHandoff(storage, handoff.handoffId, {
      now: 1_001,
      projectId: "project-1",
      threadId: "thread-1",
    })?.entities,
    [account],
  );
  assert.equal(
    readChatContextHandoff(storage, handoff.handoffId, {
      now: 1_001,
      projectId: "project-2",
      threadId: "thread-1",
    }),
    null,
  );
});

test("expired, consumed, and emptied handoffs cannot silently pin context", () => {
  const storage = new MemoryStorage();
  const handoff = createChatContextHandoff({
    entities: [account],
    handoffId: "95b97e55-d15c-4391-9fcc-e31e5930db1f",
    now: 2_000,
    projectId: "project-1",
    source: "accounts",
    threadId: "thread-1",
  });
  writeChatContextHandoff(storage, handoff);
  assert.equal(
    readChatContextHandoff(storage, handoff.handoffId, {
      now: 2_000 + CHAT_CONTEXT_HANDOFF_TTL_MS,
      projectId: "project-1",
      threadId: "thread-1",
    }),
    null,
  );

  writeChatContextHandoff(storage, handoff);
  updateChatContextHandoffEntities(storage, handoff.handoffId, []);
  assert.equal(storage.values.size, 0);

  writeChatContextHandoff(storage, handoff);
  deleteChatContextHandoff(storage, handoff.handoffId);
  assert.equal(storage.values.size, 0);
});
