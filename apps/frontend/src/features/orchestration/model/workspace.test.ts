import test from "node:test";
import assert from "node:assert/strict";
import { createWorkspaceFixture,parseWorkspace } from "../data/workspace.fixture";
import { setAccountOwner,validateWorkspaceLinks } from "./workspace";
test("project fixture has valid links and contains no email infrastructure", () => {
  const state = createWorkspaceFixture();
  assert.equal(state.accounts.length,1000);
  assert.equal(new Set(state.accounts.map((a) => a.id)).size,1000);
  assert.deepEqual(validateWorkspaceLinks(state),[]);
  assert.equal("emails" in state,false);
  assert.ok(state.accounts.slice(6).every((a) => a.researchStatus === "pending" && a.fit === null && !a.insight));
});
test("legacy preview keeps owner edits and removes the retired email records", () => {
  const state = createWorkspaceFixture(6),account = state.accounts[0];
  const migrated = parseWorkspace({ ...state,version:2,accounts:[{...account,ownerId:"jamie",revision:7}],emails:[{id:"retired"}] });
  assert.equal(migrated.accounts[0].ownerId,"jamie");
  assert.equal(migrated.accounts[0].revision,7);
  assert.equal(migrated.accounts.length,1000);
  assert.equal("emails" in migrated,false);
  assert.throws(() => setAccountOwner(migrated,account.id,1,"alex"),/changed/);
});
