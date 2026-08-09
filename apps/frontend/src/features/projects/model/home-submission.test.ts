import assert from "node:assert/strict";
import test from "node:test";
import {
  HomeSubmissionCoordinator,
  parseHomeBootstrapDraft,
} from "./home-submission";

test("Home draft validation is local and preserves the exact message bytes", () => {
  assert.deepEqual(parseHomeBootstrapDraft({ brandId: "", message: "hello" }), {
    success: false,
    message: "Select a brand before starting a project.",
  });
  assert.deepEqual(parseHomeBootstrapDraft({ brandId: "brd_1", message: "   " }), {
    success: false,
    message: "Enter a message to start a project.",
  });
  const parsed = parseHomeBootstrapDraft({
    brandId: "brd_1",
    message: "  Start Northstar research  ",
  });
  assert.equal(parsed.success, true);
  if (parsed.success) {
    assert.equal(parsed.request.message, "  Start Northstar research  ");
    assert.deepEqual(parsed.request.contextRefs, []);
    assert.deepEqual(parsed.request.attachmentRefs, []);
  }
});

test("an unchanged failed Home draft retries with the same key", () => {
  const coordinator = new HomeSubmissionCoordinator();
  let key = 0;
  const first = coordinator.begin("draft-a", () => `key-${++key}`);
  assert.ok(first);
  assert.equal(coordinator.begin("draft-a", () => `key-${++key}`), null);
  coordinator.failed(first);
  const retry = coordinator.begin("draft-a", () => `key-${++key}`);
  assert.ok(retry);
  assert.equal(retry.idempotencyKey, first.idempotencyKey);
  assert.equal(key, 1);
});

test("editing after failure rotates the key and only blocks the exact in-flight draft", () => {
  const coordinator = new HomeSubmissionCoordinator();
  let key = 0;
  const first = coordinator.begin("draft-a", () => `key-${++key}`);
  assert.ok(first);
  coordinator.failed(first);
  coordinator.draftChanged();

  const changed = coordinator.begin("draft-b", () => `key-${++key}`);
  const originalAgain = coordinator.begin("draft-a", () => `key-${++key}`);
  assert.ok(changed);
  assert.ok(originalAgain);
  assert.notEqual(originalAgain.idempotencyKey, first.idempotencyKey);
  assert.equal(coordinator.isInFlight("draft-a"), true);
  assert.equal(coordinator.isInFlight("draft-b"), true);
});

test("only the latest concurrent successful draft owns navigation", () => {
  const coordinator = new HomeSubmissionCoordinator();
  const first = coordinator.begin("draft-a", () => "key-a");
  assert.ok(first);
  coordinator.draftChanged();
  const second = coordinator.begin("draft-b", () => "key-b");
  assert.ok(second);
  assert.deepEqual(coordinator.succeeded(first), { navigate: false });
  assert.deepEqual(coordinator.succeeded(second), { navigate: true });
});
