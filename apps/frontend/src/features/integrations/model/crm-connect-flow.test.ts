import assert from "node:assert/strict";
import test from "node:test";
import {
  CRM_CONNECT_FLOW_CLOSED,
  crmChangeCopy,
  crmChooseCopy,
  crmConnectFlowReducer,
  crmFailureCopy,
  crmFinishCopy,
  crmReconnectCopy,
  type CrmConnectFlow,
} from "./crm-connect-flow";

const REQUEST = "5b7e1f7a-2c3d-4e5f-8a9b-0c1d2e3f4a5b";

function run(...events: Parameters<typeof crmConnectFlowReducer>[1][]): CrmConnectFlow {
  return events.reduce(crmConnectFlowReducer, CRM_CONNECT_FLOW_CLOSED);
}

test("Connect opens the choose dialog in connect mode", () => {
  assert.deepEqual(run({ type: "start_connect" }), { step: "choose", mode: "connect" });
});

test("Reconnect asks first, then waits for that CRM's sign-in in reconnect mode", () => {
  assert.deepEqual(run({ type: "start_reconnect", provider: "hubspot" }), {
    step: "confirm_reconnect",
    provider: "hubspot",
  });
  assert.deepEqual(
    run(
      { type: "start_reconnect", provider: "hubspot" },
      { type: "opened", mode: "reconnect", provider: "hubspot", requestId: REQUEST },
    ),
    { step: "waiting", mode: "reconnect", provider: "hubspot", requestId: REQUEST },
  );
});

test("Change CRM asks first, then chooses a CRM in switch mode", () => {
  assert.deepEqual(run({ type: "start_change" }), { step: "confirm_change" });
  assert.deepEqual(run({ type: "start_change" }, { type: "continue_change" }), {
    step: "choose",
    mode: "switch",
  });
});

test("a connect click waits for the sign-in, and the connection closes the flow", () => {
  const waiting = run(
    { type: "start_connect" },
    { type: "opened", mode: "connect", provider: "salesforce", requestId: REQUEST },
  );
  assert.deepEqual(waiting, {
    step: "waiting",
    mode: "connect",
    provider: "salesforce",
    requestId: REQUEST,
  });
  assert.deepEqual(crmConnectFlowReducer(waiting, { type: "connected" }), CRM_CONNECT_FLOW_CLOSED);
});

test("a failed sign-in keeps the request so Try again reuses it; cancel closes from anywhere", () => {
  const failed = run(
    { type: "start_connect" },
    { type: "opened", mode: "connect", provider: "hubspot", requestId: REQUEST },
    { type: "failed", mode: "connect", provider: "hubspot", message: "HubSpot didn’t connect." },
  );
  assert.deepEqual(failed, {
    step: "failed",
    mode: "connect",
    provider: "hubspot",
    requestId: REQUEST,
    message: "HubSpot didn’t connect.",
  });
  for (const state of [failed, run({ type: "start_change" }), run({ type: "start_connect" })]) {
    assert.deepEqual(crmConnectFlowReducer(state, { type: "cancel" }), CRM_CONNECT_FLOW_CLOSED);
  }
});

test("a refusal before any sign-in opened fails without a request", () => {
  assert.deepEqual(
    run(
      { type: "start_connect" },
      { type: "failed", mode: "connect", provider: "hubspot", message: "Only owners." },
    ),
    { step: "failed", mode: "connect", provider: "hubspot", requestId: null, message: "Only owners." },
  );
});

test("a late connection, link or failure after the flow was closed changes nothing", () => {
  assert.deepEqual(run({ type: "connected" }), CRM_CONNECT_FLOW_CLOSED);
  assert.deepEqual(
    run({ type: "opened", mode: "connect", provider: "hubspot", requestId: REQUEST }),
    CRM_CONNECT_FLOW_CLOSED,
  );
  assert.deepEqual(
    run({ type: "failed", mode: "connect", provider: "hubspot", message: "x" }),
    CRM_CONNECT_FLOW_CLOSED,
  );
});

test("dialog copy is the design's (board 06), per CRM", () => {
  assert.deepEqual(crmChooseCopy(), {
    title: "Connect your CRM",
    description: "Choose one CRM for this workspace. You’ll sign in securely in a new window.",
    providers: [
      { provider: "hubspot", name: "HubSpot", subtitle: "Connect a HubSpot portal" },
      { provider: "salesforce", name: "Salesforce", subtitle: "Connect a Salesforce organization" },
    ],
    note: "Only owners and admins can connect a CRM.",
  });
  assert.deepEqual(crmFinishCopy("hubspot"), {
    title: "Finish connecting in HubSpot",
    description: "A sign-in window is open. Choose your portal and approve access, then return here.",
    status: "Waiting for sign-in",
  });
  assert.equal(
    crmFinishCopy("salesforce").description,
    "A sign-in window is open. Choose your organization and approve access, then return here.",
  );
  assert.deepEqual(crmReconnectCopy("hubspot", "Portal 21436587"), {
    title: "Reconnect HubSpot",
    lines: [
      "Sign in to the same HubSpot account (Portal 21436587) to keep your permissions, pending cards, and history.",
      "If you choose another portal, Clue will ask you to confirm the change.",
    ],
  });
  assert.equal(
    crmReconnectCopy("salesforce", "Acme").lines[0],
    "Sign in to the same Salesforce organization (Acme) to keep your permissions, pending cards, and history.",
  );
  assert.deepEqual(crmChangeCopy("hubspot"), {
    title: "Change your CRM?",
    description: "Connect a different CRM, portal, or organization.",
    consequence:
      "Your “Always allow” permissions will be cleared. Changes Clue already made in HubSpot will stay there. Cards waiting in chats will be closed.",
    note: "Reconnecting the same portal keeps everything.",
  });
  assert.equal(crmChangeCopy("salesforce").note, "Reconnecting the same organization keeps everything.");
});

test("failure copy names the action and keeps the reassurance for an existing connection", () => {
  assert.deepEqual(crmFailureCopy("reconnect", "hubspot", "HubSpot didn’t connect. Try again."), {
    title: "Couldn’t reconnect HubSpot",
    message: "HubSpot didn’t connect. Try again.",
    note: "Your saved permissions and history are unchanged.",
  });
  assert.deepEqual(crmFailureCopy("connect", "salesforce", "Salesforce didn’t connect. Try again."), {
    title: "Couldn’t connect Salesforce",
    message: "Salesforce didn’t connect. Try again.",
    note: null,
  });
  assert.equal(
    crmFailureCopy("switch", "salesforce", "x").note,
    "Your saved permissions and history are unchanged.",
  );
});
