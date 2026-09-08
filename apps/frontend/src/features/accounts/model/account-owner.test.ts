import assert from "node:assert/strict";
import test from "node:test";
import { AccountSchema } from "./account";
import { AccountDetailSchema } from "./account-detail";
import { resolveAccountOwner, workspaceProfileOwner } from "./account-owner";
import { createLocalAccount } from "./create-account";
import { workspaceProfileFixture } from "../data/workspace-profile.fixture";
import { zafranAccountDetailFixture } from "../data/zafran/account";
import { accountFixtures } from "../data/accounts.fixture";

const viewer = { id: "viewer", name: "Priya Shah" };
const creator = { id: "creator", name: "Sam Lee" };
const owner = { id: "assigned", name: "Alex Kim", avatarUrl: "/avatar.svg" };

test("an assigned account owner always wins over creator and current viewer", () => {
  assert.deepEqual(resolveAccountOwner({ owner, createdBy: creator }, viewer), owner);
});
test("an unassigned account belongs to its recorded creator, not a later viewer", () => {
  assert.deepEqual(resolveAccountOwner({ owner: null, createdBy: creator }, viewer), creator);
});
test("missing ownership falls back to the current workspace profile without changing research", () => {
  const before = JSON.stringify(zafranAccountDetailFixture);
  assert.deepEqual(resolveAccountOwner(zafranAccountDetailFixture, viewer), viewer);
  assert.equal(JSON.stringify(zafranAccountDetailFixture), before);
  assert.deepEqual(resolveAccountOwner({ owner: null, createdBy: null }, viewer), viewer);
});
test("workspace profile changes flow through without a hard-coded person or avatar", () => {
  assert.deepEqual(workspaceProfileOwner({ ...workspaceProfileFixture, id: viewer.id, fullName: viewer.name, avatarUrl: "/priya.svg" }), { ...viewer, avatarUrl: "/priya.svg" });
  assert.equal(workspaceProfileOwner(workspaceProfileFixture).name, workspaceProfileFixture.fullName);
});
test("list and detail contracts retain creator and nullable owner metadata", () => {
  assert.deepEqual(AccountSchema.parse({ ...accountFixtures[0], owner: null, createdBy: creator }).createdBy, creator);
  assert.deepEqual(AccountDetailSchema.parse({ ...zafranAccountDetailFixture, owner: null, createdBy: creator }).createdBy, creator);
});
test("new accounts capture their creator and do not change owner when the viewer changes", () => {
  const account = AccountSchema.parse(createLocalAccount("New company", "https://example.com", creator));
  assert.deepEqual(account.owner, creator);
  assert.deepEqual(account.createdBy, creator);
  assert.deepEqual(resolveAccountOwner(account, viewer), creator);
});
