import assert from "node:assert/strict";
import test from "node:test";
import { crmIntegrationFixture } from "../data/crm-settings.fixtures";
import type { CrmIntegration } from "./crm-settings";
import { connectedSince, crmOverviewCard } from "./crm-settings-overview";

const NOW = new Date("2026-10-25T12:00:00+00:00");

function withConnection(
  patch: Partial<NonNullable<CrmIntegration["connection"]>> | null,
  canManage = true,
): CrmIntegration {
  const base = crmIntegrationFixture("ready", "hubspot");
  return {
    ...base,
    canManage,
    connection: patch === null ? null : { ...base.connection!, ...patch },
  };
}

test("not connected (board 01): both marks, the CRM row and Connect for a manager", () => {
  const card = crmOverviewCard(crmIntegrationFixture("not_connected", "hubspot"), NOW);
  assert.deepEqual(card, {
    state: "not_connected",
    logos: ["hubspot", "salesforce"],
    title: "CRM",
    badge: null,
    lines: [{ text: "Connect HubSpot or Salesforce to read your CRM and write research back.", tone: "subtle" }],
    actions: ["connect"],
    manageHref: null,
  });
});

test("a disconnected connection reads as not connected", () => {
  const card = crmOverviewCard(withConnection({ status: "disconnected" }), NOW);
  assert.equal(card.state, "not_connected");
  assert.deepEqual(card.actions, ["connect"]);
  assert.equal(card.manageHref, null);
});

test("connected (board 04): provider, Connected badge, account line and Manage", () => {
  const card = crmOverviewCard(
    withConnection({ accountLabel: "Clue workspace", connectedAt: "2026-10-22T09:30:00+00:00" }),
    NOW,
  );
  assert.deepEqual(card, {
    state: "connected",
    logos: ["hubspot"],
    title: "HubSpot",
    badge: { label: "Connected", tone: "neutral" },
    lines: [{ text: "Clue workspace · Connected by Aryan · 3 days ago", tone: "subtle" }],
    actions: ["manage"],
    manageHref: "/settings/integrations/hubspot",
  });
});

test("expired (board 05): Needs attention, the warning line, Reconnect and Manage", () => {
  const card = crmOverviewCard(
    withConnection({
      provider: "salesforce",
      status: "expired",
      accountLabel: "Acme",
      connectedAt: "2026-10-22T09:30:00+00:00",
    }),
    NOW,
  );
  assert.deepEqual(card, {
    state: "expired",
    logos: ["salesforce"],
    title: "Salesforce",
    badge: { label: "Needs attention", tone: "warning" },
    lines: [
      { text: "Acme · Connected by Aryan · 3 days ago", tone: "subtle" },
      { text: "Your connection expired. Reconnect to continue.", tone: "warning" },
    ],
    actions: ["reconnect", "manage"],
    manageHref: "/settings/integrations/salesforce",
  });
});

test("a member sees the same cards with no connect or reconnect, and still Manage", () => {
  assert.deepEqual(crmOverviewCard(withConnection(null, false), NOW).actions, []);
  assert.deepEqual(crmOverviewCard(withConnection({}, false), NOW).actions, ["manage"]);
  assert.deepEqual(
    crmOverviewCard(withConnection({ status: "expired" }, false), NOW).actions,
    ["manage"],
  );
});

test("the account line leaves out the name when nobody is recorded", () => {
  const card = crmOverviewCard(
    withConnection({ connectedByName: null, connectedAt: "2026-10-25T08:00:00+00:00" }),
    NOW,
  );
  assert.equal(card.lines[0]?.text, "Portal 21436587 · Connected today");
});

test("connectedSince: today, yesterday, days ago within a week, then the date", () => {
  assert.equal(connectedSince("2026-10-25T01:00:00+00:00", NOW), "today");
  assert.equal(connectedSince("2026-10-24T11:00:00+00:00", NOW), "yesterday");
  assert.equal(connectedSince("2026-10-22T09:30:00+00:00", NOW), "3 days ago");
  assert.equal(connectedSince("2026-10-19T09:30:00+00:00", NOW), "6 days ago");
  assert.equal(connectedSince("2026-10-18T09:30:00+00:00", NOW), "18 Oct 2026");
  assert.equal(connectedSince("not a date", NOW), null);
});
