import assert from "node:assert/strict";
import { test } from "node:test";
import { createAssetUploadQueue } from "./asset-upload-queue";
import type { AssetRepository } from "../data/asset.repository";

const tick = () => new Promise(resolve => setTimeout(resolve, 0));
test("upload slots refill independently, mixed failure retains key and successful files", async () => {
  const calls: Array<{key: string; resolve: (value: {assetId: string}) => void; reject: (error: Error) => void}> = [];
  const repository: AssetRepository = {
    async capabilities() {return {max_bytes: 10000000, formats: ["png"]};},
    upload: request => new Promise((resolve, reject) => calls.push({key: request.key, resolve, reject})),
    async readMetadata() {return {};}, async save() {}, async retry() {}, async archive() {},
  };
  let refreshed = 0;
  const queue = createAssetUploadQueue(repository, () => refreshed++);
  queue.add(Array.from({length: 7}, (_, index) => new File(["pixels"], `${index}.png`, {type: "image/png"})));
  queue.editAll({creative_type: "ad"});
  queue.start(); assert.equal(calls.length, 3);
  // A second click cannot offer duplicates, and the request's metadata cannot drift mid-transfer.
  queue.start(); queue.edit(queue.getSnapshot()[0].id, {creative_type: "logo"});
  assert.equal(calls.length, 3); assert.equal(queue.getSnapshot()[0].overrides.creative_type, "ad");
  calls[1].resolve({assetId: "asset_second"}); await tick(); assert.equal(calls.length, 4);
  calls[0].reject(new Error("Response lost")); await tick(); assert.equal(calls.length, 5);
  const failed = queue.getSnapshot()[0];
  assert.equal(failed.state, "failed");
  calls[2].resolve({assetId: "asset_third"}); calls[3].resolve({assetId: "asset_fourth"}); calls[4].resolve({assetId: "asset_fifth"});
  await tick(); assert.equal(calls.length, 7);
  calls[5].resolve({assetId: "asset_sixth"}); calls[6].resolve({assetId: "asset_seventh"}); await tick();
  queue.retry(failed.id); assert.equal(calls[7].key, calls[0].key);
  calls[7].resolve({assetId: "asset_first"}); await tick();
  assert.equal(refreshed, 7); assert.equal(queue.getSnapshot().filter(row => row.state === "uploaded").length, 7);
});
