import assert from "node:assert/strict";
import test from "node:test";
import { AccountSchema } from "./account";
import { AccountDetailSchema } from "./account-detail";
import {
  UNASSIGNED_OWNER_LABEL,
  resolveAccountOwner,
  workspaceProfileOwner,
} from "./account-owner";
import { createLocalAccount } from "./create-account";
import { workspaceProfileFixture } from "../data/workspace-profile.fixture";
import { zafranAccountDetailFixture } from "../data/zafran/account";
import { accountFixtures } from "../data/accounts.fixture";

const creator = { id: "creator", name: "Sam Lee" };
const owner = { id: "assigned", name: "Alex Kim", avatarUrl: "/avatar.svg" };

test("an assigned account owner always wins over the creator", () => {
  assert.deepEqual(resolveAccountOwner({ owner, createdBy: creator }), owner);
});
test("an unassigned account belongs to its recorded creator, not a later viewer", () => {
  assert.deepEqual(resolveAccountOwner({ owner: null, createdBy: creator }), creator);
});
test("missing ownership is unassigned — never the current viewer (ruling R6)", () => {
  const before = JSON.stringify(zafranAccountDetailFixture);
  assert.equal(resolveAccountOwner(zafranAccountDetailFixture), null);
  assert.equal(JSON.stringify(zafranAccountDetailFixture), before);
  assert.equal(resolveAccountOwner({ owner: null, createdBy: null }), null);
  assert.equal(UNASSIGNED_OWNER_LABEL, "Unassigned");
});
test("workspace profile changes flow through without a hard-coded person or avatar", () => {
  assert.deepEqual(workspaceProfileOwner({ ...workspaceProfileFixture, id: "viewer", fullName: "Priya Shah", avatarUrl: "/priya.svg" }), { id: "viewer", name: "Priya Shah", avatarUrl: "/priya.svg" });
  assert.equal(workspaceProfileOwner(workspaceProfileFixture).name, workspaceProfileFixture.fullName);
});
test("list and detail contracts retain creator and nullable owner metadata", () => {
  assert.deepEqual(AccountSchema.parse({ ...accountFixtures[0], owner: null, createdBy: creator }).createdBy, creator);
  assert.deepEqual(AccountDetailSchema.parse({ ...zafranAccountDetailFixture, owner: null, createdBy: creator }).createdBy, creator);
});
test("new accounts capture their creator and invent no score or fit band", () => {
  const account = AccountSchema.parse(createLocalAccount("New company", "https://example.com", creator));
  assert.deepEqual(account.owner, creator);
  assert.deepEqual(account.createdBy, creator);
  assert.deepEqual(resolveAccountOwner(account), creator);
  assert.equal(account.fitScore, null);
  assert.equal(account.overallFit, null);
  assert.equal(account.logoPath, null);
  assert.equal(account.researchStatusLabel, "Not started");
});
