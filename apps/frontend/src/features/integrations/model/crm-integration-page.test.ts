import assert from "node:assert/strict";
import test from "node:test";
import { crmIntegrationFixture, withFixtureVariants } from "../data/crm-settings.fixtures";
import {
  crmConnectionView,
  crmDisconnectCopy,
  crmOverwritesView,
  crmPermissionsView,
  crmProviderPageRedirect,
  crmResearchView,
  crmRevokeCopy,
  CRM_OVERWRITE_CONFIRM_COPY,
} from "./crm-integration-page";
import type { CrmIntegration } from "./crm-settings";

const ready = crmIntegrationFixture("ready", "hubspot");
const member = (integration: CrmIntegration) => withFixtureVariants(integration, ["member"]);

test("the provider page shows only the connected CRM; everything else goes back to the overview", () => {
  assert.equal(crmProviderPageRedirect("hubspot", ready), null);
  assert.equal(
    crmProviderPageRedirect("hubspot", withFixtureVariants(ready, ["expired"])),
    null,
  );
  assert.equal(crmProviderPageRedirect("salesforce", ready), "/settings/integrations");
  assert.equal(
    crmProviderPageRedirect("hubspot", crmIntegrationFixture("not_connected", "hubspot")),
    "/settings/integrations",
  );
  const disconnected: CrmIntegration = {
    ...ready,
    connection: { ...ready.connection!, status: "disconnected" },
  };
  assert.equal(crmProviderPageRedirect("hubspot", disconnected), "/settings/integrations");
});

test("the connection section names the account the CRM's way and offers managers every action", () => {
  const hubspot = crmConnectionView(ready);
  assert.equal(hubspot.name, "HubSpot");
  assert.deepEqual(hubspot.badge, { label: "Connected", tone: "neutral" });
  assert.equal(hubspot.accountFieldLabel, "Portal");
  assert.equal(hubspot.accountLabel, "Portal 21436587");
  assert.equal(hubspot.connectedBy, "Aryan");
  assert.equal("connectedOn" in hubspot, false);
  assert.deepEqual(hubspot.actions, ["reconnect", "change", "disconnect"]);
  // No note under a manager's buttons (founder 2026-10-26).
  assert.equal(hubspot.note, null);
  assert.equal(hubspot.expired, null);

  const salesforce = crmConnectionView(crmIntegrationFixture("ready", "salesforce"));
  assert.equal(salesforce.accountFieldLabel, "Organization");
  assert.equal(salesforce.note, null);
});

test("a member sees the connection without reconnect, change or disconnect, and is told who can", () => {
  const view = crmConnectionView(member(ready));
  assert.deepEqual(view.actions, []);
  assert.equal(view.note, "Ask an owner or admin to reconnect, change, or disconnect this CRM.");
});

test("an expired connection reads as expired and offers managers only Reconnect", () => {
  const view = crmConnectionView(withFixtureVariants(ready, ["expired"]));
  assert.deepEqual(view.badge, { label: "Expired", tone: "warning" });
  assert.deepEqual(view.expired, {
    warning: "Your connection expired. Clue can’t read or write until you reconnect.",
    note: "Permissions, fields, and change history are kept when you reconnect the same portal.",
  });
  assert.deepEqual(view.actions, ["reconnect"]);
  assert.deepEqual(crmConnectionView(withFixtureVariants(ready, ["expired", "member"])).actions, []);
});

test("Review request opens the setup card's chat when there is one", () => {
  const view = crmResearchView(crmIntegrationFixture("approval_needed", "hubspot"));
  assert.deepEqual(view.badge, { label: "Approval needed", tone: "warning" });
  assert.deepEqual(view.action, {
    label: "Review request",
    href: "/projects/prj_fixture/chats/thr_fixture",
  });
});

test("Review request without a pending card, and every Ask Clue action, prefill a new chat", () => {
  const approval = crmIntegrationFixture("approval_needed", "salesforce");
  const declined: CrmIntegration = {
    ...approval,
    research: { ...approval.research, reviewChat: null },
  };
  assert.deepEqual(crmResearchView(declined).action, {
    label: "Review request",
    href: `/projects/prj_fixture?prompt=${encodeURIComponent("Set up Clue’s fields in Salesforce.")}`,
  });
  assert.deepEqual(crmResearchView(crmIntegrationFixture("couldnt_finish", "hubspot")).action, {
    label: "Ask Clue to retry",
    href: `/projects/prj_fixture?prompt=${encodeURIComponent("Finish setting up Clue’s fields in HubSpot.")}`,
  });
  assert.deepEqual(crmResearchView(crmIntegrationFixture("needs_attention", "hubspot")).action, {
    label: "Ask Clue to restore",
    href: `/projects/prj_fixture?prompt=${encodeURIComponent("Restore Clue’s “Clue research link” field in HubSpot.")}`,
  });
});

test("with no project to open, the research action is not shown", () => {
  for (const state of ["couldnt_finish", "approval_needed"] as const) {
    const integration = crmIntegrationFixture(state, "hubspot");
    const noProject: CrmIntegration = {
      ...integration,
      askClueProjectId: null,
      research: { ...integration.research, reviewChat: null },
    };
    assert.equal(crmResearchView(noProject).action, null);
  }
  // A pending card's chat still opens without a fallback project.
  const pending = { ...crmIntegrationFixture("approval_needed", "hubspot"), askClueProjectId: null };
  assert.equal(crmResearchView(pending).action?.href, "/projects/prj_fixture/chats/thr_fixture");
});

test("states without an action, and the member view, show no research button", () => {
  assert.equal(crmResearchView(ready).action, null);
  assert.equal(crmResearchView(crmIntegrationFixture("preparing", "hubspot")).action, null);
  const view = crmResearchView(member(crmIntegrationFixture("approval_needed", "hubspot")));
  assert.equal(view.action, null);
  assert.equal(view.body, "Clue is waiting for an owner or admin to approve preparation in chat.");
  assert.equal(
    view.expandedBody,
    "Clue is waiting for an owner or admin to approve preparation in chat.",
  );
});

test("the research details list each preparation with its progress, refused ones in warning", () => {
  const view = crmResearchView(crmIntegrationFixture("permission_needed", "hubspot"));
  assert.deepEqual(view.badge, { label: "Permission needed", tone: "warning" });
  assert.equal(view.expandedBody, "Clue couldn’t finish preparing contact fields.");
  assert.deepEqual(
    view.rows.map((row) => [row.title, row.progress, row.tone]),
    [
      ["Company research links", "Created", "subtle"],
      ["Contact profile links", "Created", "subtle"],
      ["Contacts’ buying roles", "Permission needed", "warning"],
      ["Company fit", "Created", "subtle"],
    ],
  );
  assert.equal(view.details.blocking?.heading, "What’s blocking completion");
  assert.deepEqual(crmResearchView(ready).badge, { label: "Ready", tone: "neutral" });
  assert.deepEqual(crmResearchView(crmIntegrationFixture("preparing", "hubspot")).badge, {
    label: "Preparing",
    tone: "neutral",
  });
  const missing = crmResearchView(crmIntegrationFixture("needs_attention", "hubspot")).rows[0];
  assert.deepEqual([missing.progress, missing.tone], ["Deleted in HubSpot", "warning"]);
});

test("standing permissions read who allowed them and when; an empty list says Clue asks each time", () => {
  const view = crmPermissionsView(ready);
  assert.deepEqual(view.rows[0], {
    grantId: "6f1d6c39-5b1a-4a43-9d3f-6a1c2b7e8f01",
    description: "Always set Clue fit level on companies",
    meta: "Allowed by Aryan · 22 Oct 2026",
  });
  const unnamed = crmPermissionsView({
    ...ready,
    permissions: [{ ...ready.permissions[0], grantedByName: null }],
  });
  assert.equal(unnamed.rows[0].meta, "Allowed 22 Oct 2026");
  const empty = crmPermissionsView({ ...ready, permissions: [] });
  assert.deepEqual(empty.rows, []);
  assert.equal(empty.empty, "No standing permissions. Clue asks on a card each time.");
  assert.equal(
    view.description,
    "Standing permissions granted on approval cards. Any member can revoke them.",
  );
});

test("the revoke dialog says what Clue will ask about again", () => {
  assert.equal(
    crmRevokeCopy({ ...ready.permissions[0] }).body,
    "Clue will ask on a card before setting Clue fit level on companies again. Changes already made stay in your CRM.",
  );
  assert.equal(
    crmRevokeCopy({ ...ready.permissions[1] }).body,
    "Clue will ask on a card before adding records to Clue lists and campaigns again. Changes already made stay in your CRM.",
  );
  assert.equal(
    crmRevokeCopy({ ...ready.permissions[0], description: "Always allow these changes" }).body,
    "Clue will ask on a card before making these changes again. Changes already made stay in your CRM.",
  );
  assert.equal(crmRevokeCopy(ready.permissions[0]).title, "Revoke this permission?");
});

test("managers choose the overwrite mode; members read it", () => {
  const manager = crmOverwritesView(ready);
  assert.equal(manager.editable, true);
  assert.equal(manager.title, "Overwrites");
  assert.equal(manager.description, "When Clue would change a value a person set in HubSpot:");
  assert.deepEqual(
    manager.options.map((option) => [option.mode, option.label, option.selected]),
    [
      ["ask", "Always ask me", true],
      ["follow_grants", "Follow “Always allow”", false],
    ],
  );
  assert.equal(manager.note, "Owners and admins can change this setting. Changes save automatically.");

  const read = crmOverwritesView(member({ ...ready, overwrites: "follow_grants" }));
  assert.equal(read.editable, false);
  assert.equal(read.title, "Overwrites · Follow “Always allow”");
  assert.equal(
    read.note,
    "Only owners and admins can change this setting. You can still revoke standing permissions.",
  );
  assert.equal(CRM_OVERWRITE_CONFIRM_COPY.title, "Allow changes to people’s values?");
});

test("the disconnect dialog names the CRM and its account word", () => {
  assert.deepEqual(crmDisconnectCopy("hubspot"), {
    title: "Disconnect HubSpot?",
    description: "Clue will stop reading from and writing to this portal.",
    consequence:
      "Your “Always allow” permissions will be cleared. Changes Clue already made in HubSpot will stay there. Cards waiting in chats will be closed.",
  });
  assert.equal(
    crmDisconnectCopy("salesforce").description,
    "Clue will stop reading from and writing to this organization.",
  );
});
