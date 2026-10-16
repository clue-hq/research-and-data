import assert from "node:assert/strict";
import { test } from "node:test";
import { siteVersionOptions } from "./site-versions";

test("versions read newest first with the menu's designed labels", () => {
  assert.deepEqual(
    siteVersionOptions([
      { actorKind: "human", batchId: "batch_9", createdAt: "2026-10-11T10:09:00Z", intent: null, version: 9 },
      { actorKind: "agent", batchId: "batch_8", createdAt: "2026-10-11T10:08:00Z", intent: null, version: 8 },
      { actorKind: "agent", batchId: "batch_5", createdAt: "2026-10-11T10:05:00Z", intent: null, version: 5 },
    ]),
    [
      { id: "batch_9", label: "Current version" },
      { id: "batch_8", label: "Version 8" },
      { id: "batch_5", label: "Version 5" },
    ],
  );
  assert.deepEqual(siteVersionOptions([]), []);
});
