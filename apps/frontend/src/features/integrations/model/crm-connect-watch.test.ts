import assert from "node:assert/strict";
import test from "node:test";
import { crmWatchMessage, crmWatchPlan } from "./crm-connect-watch";

const REQUEST = "5b7e1f7a-2c3d-4e5f-8a9b-0c1d2e3f4a5b";

test("with no request yet the watch reads, listens and polls nothing", () => {
  assert.deepEqual(crmWatchPlan(null, "hubspot", false), { read: false, listen: false, poll: false });
  assert.deepEqual(crmWatchPlan(null, null, false), { read: false, listen: false, poll: false });
});

test("with a request it reads and listens; it polls only while a sign-in is open", () => {
  assert.deepEqual(crmWatchPlan(REQUEST, null, false), { read: true, listen: true, poll: false });
  assert.deepEqual(crmWatchPlan(REQUEST, "salesforce", false), { read: true, listen: true, poll: true });
});

test("once connected it stops listening and polling", () => {
  assert.deepEqual(crmWatchPlan(REQUEST, "hubspot", true), { read: true, listen: false, poll: false });
});

test("the callback tab's word: another request is ignored, failed fails, the rest re-read", () => {
  assert.equal(crmWatchMessage({ requestId: "other", outcome: "failed", provider: null }, REQUEST), "ignore");
  assert.equal(crmWatchMessage(undefined, REQUEST), "ignore");
  assert.equal(crmWatchMessage({ requestId: REQUEST, outcome: "failed", provider: "hubspot" }, REQUEST), "failed");
  assert.equal(crmWatchMessage({ requestId: REQUEST, outcome: "connected", provider: "hubspot" }, REQUEST), "reread");
  assert.equal(crmWatchMessage({ requestId: REQUEST, outcome: "stale", provider: null }, REQUEST), "reread");
});
