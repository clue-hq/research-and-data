import assert from "node:assert/strict";
import { test } from "node:test";
import { siteHistoryActionFromEvent, siteHistoryDisabled } from "./site-history";

test("the header menu's undo and redo reach the site lane only for a site", () => {
  assert.equal(siteHistoryActionFromEvent({ action: "undo", kind: "site" }), "undo");
  assert.equal(siteHistoryActionFromEvent({ action: "redo", kind: "site" }), "redo");
  assert.equal(siteHistoryActionFromEvent({ action: "undo", kind: "web" }), null);
  assert.equal(siteHistoryActionFromEvent({ action: "archive", kind: "site" }), null);
  assert.equal(siteHistoryActionFromEvent(null), null);
});

test("undo and redo are offered only with a step to take and no agent at work", () => {
  assert.equal(siteHistoryDisabled({ depth: 0, locked: false }), true);
  assert.equal(siteHistoryDisabled({ depth: 3, locked: false }), false);
  assert.equal(siteHistoryDisabled({ depth: 3, locked: true }), true);
});
