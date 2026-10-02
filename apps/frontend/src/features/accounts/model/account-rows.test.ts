import assert from "node:assert/strict";
import test from "node:test";
import { accountFixtures } from "../data/accounts.fixture";
import { reconcileAccountRows } from "./account-rows";
import { createLocalAccount } from "./create-account";

test("a refreshed empty project shows newly added members", () => {
  const member = { ...accountFixtures[0], projects: [{ id: "project-1", name: "Project" }] };
  assert.deepEqual(reconcileAccountRows([], [member]), [member]);
});

test("server refreshes replace membership and research data, and remove absent persisted rows", () => {
  const original = accountFixtures[0];
  const refreshed = { ...original, projects: [{ id: "new-project", name: "New project" }], fitScore: 91 };
  const removed = { ...accountFixtures[1], id: "removed-account" };
  assert.deepEqual(reconcileAccountRows([original, removed], [refreshed]), [refreshed]);
  assert.deepEqual(reconcileAccountRows([refreshed], []), []);
});

test("a refresh preserves local drafts but gives a served row ownership of its id", () => {
  const draft = createLocalAccount("Draft", "https://example.com", { id: "owner", name: "Owner" });
  const served = accountFixtures[0];
  assert.deepEqual(reconcileAccountRows([draft], [served]), [draft, served]);
  const saved = { ...served, id: draft.id };
  assert.deepEqual(reconcileAccountRows([draft], [saved]), [saved]);
});
