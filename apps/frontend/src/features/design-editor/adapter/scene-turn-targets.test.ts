import assert from "node:assert/strict";
import test from "node:test";
import { snapshotSceneTurnTargets } from "./scene-turn-targets";

test("a submission snapshots node ids before queued writes settle", async () => {
  const selectedIds = ["headline"];
  let release!: () => void;
  const settled = new Promise<void>((resolve) => {
    release = resolve;
  });
  const snapshotting = snapshotSceneTurnTargets({
    awaitWritesSettled: () => settled,
    documentId: "doc_ad",
    loadedVersion: 4,
    persistedVersion: () => 5,
    selectedIds,
  });

  selectedIds.splice(0, 1, "logo");
  release();

  assert.deepEqual(await snapshotting, {
    documentId: "doc_ad",
    documentVersion: 5,
    targetNodeIds: ["headline"],
  });
});
