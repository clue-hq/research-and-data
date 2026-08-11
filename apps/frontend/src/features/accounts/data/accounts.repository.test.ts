import assert from "node:assert/strict";
import test from "node:test";
import { createHttpAccountsRepository } from "./accounts.repository";

test("the Accounts repository always reads the live endpoint", async () => {
  let requestedPath = "";
  let requestedOptions: unknown;
  const repository = createHttpAccountsRepository(async (path, options) => {
    requestedPath = path;
    requestedOptions = options;
    return {
      data: [],
      meta: { total: 0, nextCursor: null },
    };
  });

  const response = await repository.list({
    cursor: "cursor-1",
    limit: 25,
    projectId: "project-1",
  });

  assert.equal(requestedPath, "/accounts");
  assert.deepEqual(requestedOptions, {
    searchParams: {
      cursor: "cursor-1",
      limit: 25,
      projectId: "project-1",
    },
  });
  assert.deepEqual(response, {
    data: [],
    meta: { total: 0, nextCursor: null },
  });
});

test("the live repository rejects a malformed wire response", async () => {
  const repository = createHttpAccountsRepository(async () => ({
    data: [{ id: "missing-required-account-fields" }],
    meta: { total: 1, nextCursor: null },
  }));

  await assert.rejects(repository.list(), /name/);
});
