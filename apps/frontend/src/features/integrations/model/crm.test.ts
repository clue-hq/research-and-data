import assert from "node:assert/strict";
import test from "node:test";
import { crmConnectCard, crmConnectionAnswersCard } from "./crm";

const REQUEST = "0b9d5f3e-7d6a-4a8e-9f0b-3c1d2e4f5a6b";
const ACTIVE = {
  provider: "hubspot" as const,
  status: "active" as const,
  connectedAt: "2026-10-20T10:00:00+00:00",
  connectedBy: "usr_1",
  connectedByName: "Aryan",
};

test("the card is read from the tool's reference values, with the connection it was shown for", () => {
  const card = crmConnectCard({
    reference_values: {
      state: "card",
      mode: "switch",
      request_id: REQUEST,
      providers: ["hubspot", "salesforce"],
      can_connect: true,
      connection: {
        provider: "hubspot",
        status: "active",
        connected_at: ACTIVE.connectedAt,
        connected_by_user_id: "usr_1",
      },
    },
  });
  assert.equal(card?.mode, "switch");
  assert.deepEqual(card?.initialConnection, {
    provider: "hubspot",
    status: "active",
    connectedAt: ACTIVE.connectedAt,
  });
});

test("a connect or reconnect card is answered by any active connection", () => {
  assert.deepEqual(crmConnectionAnswersCard(null, null, ACTIVE), {
    provider: "hubspot",
    connectedAt: ACTIVE.connectedAt,
    connectedByName: "Aryan",
  });
  assert.notEqual(crmConnectionAnswersCard("expired", ACTIVE.connectedAt, ACTIVE), null);
  assert.equal(crmConnectionAnswersCard(null, null, { status: "none" }), null);
  assert.equal(crmConnectionAnswersCard(null, null, { ...ACTIVE, status: "expired" }), null);
});

test("a switch card is answered only by a connection other than the one it was shown for", () => {
  assert.equal(crmConnectionAnswersCard("active", ACTIVE.connectedAt, ACTIVE), null);
  const switched = { ...ACTIVE, provider: "salesforce" as const, connectedAt: "2026-10-20T11:00:00+00:00" };
  assert.equal(crmConnectionAnswersCard("active", ACTIVE.connectedAt, switched)?.provider, "salesforce");
});
