import assert from "node:assert/strict";
import test from "node:test";
import {
  gateResponseBodyDisplay,
  humanizeMessageBody,
} from "./chat-message-presentation";

const GATE_ID = "42f784b0-d602-5c65-b568-2a7fcc90b18b";
const DIGEST = "e59d747898d1e8213a574104f7d4805f37b64ff771b5ce06e4fe58bf8cc086e9";

test("a structured approval renders as a decision, never transport JSON", () => {
  const body = JSON.stringify({
    decision: "approved",
    expected_estimated_cost_cents: null,
    expected_subject_sha256: DIGEST,
    gate_id: GATE_ID,
    kind: "gate_response",
  });
  assert.deepEqual(gateResponseBodyDisplay(body), {
    detail: null,
    label: "Approved",
  });
});

test("a revision keeps the human request and discards backend authority fields", () => {
  const body = JSON.stringify({
    decision: "revised",
    expected_subject_sha256: DIGEST,
    gate_id: GATE_ID,
    kind: "gate_response",
    revision_request: "Focus on multi-site practices.",
  });
  const display = gateResponseBodyDisplay(body);
  assert.deepEqual(display, {
    detail: "Focus on multi-site practices.",
    label: "Changes requested",
  });
  assert.equal(JSON.stringify(display).includes(GATE_ID), false);
  assert.equal(JSON.stringify(display).includes(DIGEST), false);
});

test("assistant prose cannot repeat UUIDs, hashes, or tenant object ids", () => {
  const body =
    `Your approval responds to ICP gate \`${GATE_ID}\`. ` +
    `Workspace: ws_fixture_insight_health_browser. Digest ${DIGEST}.`;
  const display = humanizeMessageBody(body);
  assert.equal(display.includes(GATE_ID), false);
  assert.equal(display.includes(DIGEST), false);
  assert.equal(display.includes("ws_fixture"), false);
  assert.match(display, /saved profile proposal/);
  assert.match(display, /current workspace/);
});
