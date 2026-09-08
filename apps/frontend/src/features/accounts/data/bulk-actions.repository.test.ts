import assert from "node:assert/strict";
import test from "node:test";
import { addAccountsToProject } from "./bulk-actions.repository";
import { getAccountBulkCapabilities } from "./bulk-capabilities.repository";

const completed = {
  operationId: "operation-1",
  state: "completed",
  counts: {
    requested: 1,
    completed: 1,
    unchanged: 0,
    ineligible: 0,
    failed: 0,
  },
  items: [{ subjectId: "subject-1", outcome: "completed", reasonCode: null }],
};

test("the bulk capability read is explicit, typed, and workspace scoped", async () => {
  const paths: string[] = [];
  const read = async (path: string) => {
    paths.push(path);
    return {
      addToChat: { allowed: true, maxItems: 100 },
      addToProject: { allowed: true, maxItems: 100 },
      projects: [{ id: "project-1", name: "ABM", status: "active" }],
    };
  };

  const accounts = await getAccountBulkCapabilities(read);

  assert.equal(accounts.addToProject.maxItems, 100);
  assert.equal(accounts.addToChat.maxItems, 100);
  assert.deepEqual(accounts.projects, [
    { id: "project-1", name: "ABM", status: "active" },
  ]);
  assert.deepEqual(paths, ["/accounts/bulk-capabilities"]);
});

test("bulk mutations use the BFF, explicit ids, and idempotency headers", async () => {
  const originalFetch = globalThis.fetch;
  const calls: Array<{ input: string; init: RequestInit | undefined }> = [];
  globalThis.fetch = async (input, init) => {
    calls.push({ input: String(input), init });
    return Response.json(completed);
  };
  try {
    await addAccountsToProject({
      accountIds: ["account-1"],
      idempotencyKey: "attempt-1",
      projectId: "project-1",
    });
    assert.deepEqual(
      calls.map((call) => call.input),
      ["/api/clue/frontend/v1/accounts/bulk-actions/add-to-project"],
    );
    assert.deepEqual(
      calls.map((call) => new Headers(call.init?.headers).get("idempotency-key")),
      ["attempt-1"],
    );
    assert.deepEqual(JSON.parse(String(calls[0]?.init?.body)), {
      accountIds: ["account-1"],
      projectId: "project-1",
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});
