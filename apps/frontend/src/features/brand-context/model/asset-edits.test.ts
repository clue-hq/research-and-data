import assert from "node:assert/strict";
import { test } from "node:test";
import type { AssetPatch } from "../data/asset.repository";
import { createAssetEdits } from "./asset-edits";

const tick = () => new Promise(resolve => setTimeout(resolve, 0));

test("rapid text changes are debounced into the latest field values", async () => {
  const calls: AssetPatch[] = [];
  const edits = createAssetEdits(async (_, patch) => {calls.push(patch);}, 5);
  edits.stage("a", {title: "A"});
  edits.stage("a", {title: "A new title"});
  edits.stage("a", {description: "Description"});
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.deepEqual(calls, [{title: "A new title", description: "Description"}]);
  assert.equal(edits.getSnapshot().a.saved, true);
});

test("slow writes cannot overwrite newer text or rapid checkbox edits", async () => {
  const calls: Array<{id: string; patch: AssetPatch; resolve: () => void}> = [];
  const edits = createAssetEdits((id, patch) => new Promise(resolve => calls.push({id, patch, resolve})), 10000);
  edits.stage("a", {title: "First", usage_roles: ["card_image"]});
  const flushed = edits.flush("a");
  edits.stage("a", {title: "Second", usage_roles: ["card_image", "hero_image"]});
  edits.stage("a", {title: "First", user_note: "Latest note"});
  assert.equal(calls.length, 1);
  calls[0].resolve(); await tick();
  assert.equal(calls.length, 2);
  assert.deepEqual(calls[1].patch, {title: "First", usage_roles: ["card_image", "hero_image"], user_note: "Latest note"});
  assert.equal(edits.getSnapshot().a.saved, false);
  calls[1].resolve(); assert.equal(await flushed, true);
  assert.deepEqual(edits.getSnapshot().a.patch, {});
  await edits.flush("a");
});

test("failed saves retain the exact draft and prevent closing until retry succeeds", async () => {
  let fail = true;
  const edits = createAssetEdits(async () => {if (fail) throw new Error("Offline");}, 10000);
  edits.stage("a", {description: "Keep this draft"});
  assert.equal(await edits.flush("a"), false);
  assert.equal(edits.getSnapshot().a.error, "Offline");
  assert.equal(edits.getSnapshot().a.patch.description, "Keep this draft");
  fail = false;
  assert.equal(await edits.flush("a"), true);
  assert.equal(edits.getSnapshot().a.error, null);
  assert.equal(edits.getSnapshot().a.saved, true);
});

test("edits to different assets and workspace-owned queues stay separate", async () => {
  const records: Array<[string, AssetPatch]> = [];
  const one = createAssetEdits(async (id, patch) => {records.push([id, patch]);}, 10000);
  const two = createAssetEdits(async () => {throw new Error("wrong workspace");}, 10000);
  one.stage("a", {title: "Asset A"}); one.stage("b", {title: "Asset B"});
  await Promise.all([one.flush("a"), one.flush("b")]);
  assert.deepEqual(records, [["a", {title: "Asset A"}], ["b", {title: "Asset B"}]]);
  assert.deepEqual(two.getSnapshot(), {});
});

test("reset and assignment intents never send conflicting fields", async () => {
  const calls: AssetPatch[] = [];
  const edits = createAssetEdits(async (_, patch) => {calls.push(patch);}, 10000);
  edits.stage("a", {title: "Local", description: "Description"});
  edits.stage("a", {reset_fields: ["title"]});
  await edits.flush("a");
  assert.deepEqual(calls[0], {description: "Description", reset_fields: ["title"]});
  edits.stage("a", {reset_fields: ["title", "description"]});
  edits.stage("a", {title: "New title"});
  await edits.flush("a");
  assert.deepEqual(calls[1], {title: "New title", reset_fields: ["description"]});
});

test("closing flushes a pending debounce exactly once, and empty flushes do nothing", async () => {
  let calls = 0;
  const edits = createAssetEdits(async () => {calls++;}, 5);
  edits.stage("a", {user_note: "Closing now"});
  assert.equal(await edits.flush("a"), true);
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.equal(calls, 1);
  await edits.flush("a"); await edits.flush("missing");
  assert.equal(calls, 1);
});
