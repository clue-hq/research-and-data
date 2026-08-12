import assert from "node:assert/strict";
import test from "node:test";
import {
  addAccountsToProject,
  lookupContactEmails,
} from "./bulk-actions.repository";
import {
  getAccountBulkCapabilities,
  getContactBulkCapabilities,
} from "./bulk-capabilities.repository";

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
  items: [
    {
      subjectId: "subject-1",
      outcome: "completed",
      reasonCode: null,
      emailLookup: null,
    },
  ],
};

test("bulk capability reads are explicit, typed, and account scoped", async () => {
  const paths: string[] = [];
  const read = async (path: string) => {
    paths.push(path);
    return path.endsWith("bulk-capabilities") && path.includes("contacts")
      ? {
          addToChat: { allowed: true, maxItems: 100 },
          lookupWorkEmails: { allowed: true, maxItems: 20 },
        }
      : {
          addToChat: { allowed: true, maxItems: 100 },
          addToProject: { allowed: true, maxItems: 100 },
          projects: [{ id: "project-1", name: "ABM", status: "active" }],
        };
  };

  const accounts = await getAccountBulkCapabilities(read);
  const contacts = await getContactBulkCapabilities("account/1", read);

  assert.equal(accounts.addToProject.maxItems, 100);
  assert.equal(accounts.addToChat.maxItems, 100);
  assert.equal(contacts.lookupWorkEmails.maxItems, 20);
  assert.equal(contacts.addToChat.maxItems, 100);
  assert.deepEqual(paths, [
    "/accounts/bulk-capabilities",
    "/accounts/account%2F1/contacts/bulk-capabilities",
  ]);
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
    await lookupContactEmails({
      accountId: "account/1",
      contactIds: ["contact-1"],
      idempotencyKey: "attempt-2",
    });

    assert.deepEqual(
      calls.map((call) => call.input),
      [
        "/api/clue/frontend/v1/accounts/bulk-actions/add-to-project",
        "/api/clue/frontend/v1/accounts/account%2F1/contacts/bulk-actions/email-lookup",
      ],
    );
    assert.deepEqual(
      calls.map((call) => new Headers(call.init?.headers).get("idempotency-key")),
      ["attempt-1", "attempt-2"],
    );
    assert.deepEqual(JSON.parse(String(calls[0]?.init?.body)), {
      accountIds: ["account-1"],
      projectId: "project-1",
    });
    assert.deepEqual(JSON.parse(String(calls[1]?.init?.body)), {
      contactIds: ["contact-1"],
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});
