import assert from "node:assert/strict";
import test from "node:test";
import {
  CRM_RESEARCH_STATES,
  CrmIntegrationSchema,
  researchStateCopy,
  setupItemStatusLabel,
  type CrmResearchState,
  type CrmSetupItem,
} from "./crm-settings";
import { crmIntegrationFixture } from "../data/crm-settings.fixtures";

/** The backend's own example (task-3 report, fix round 1), verbatim. */
const BACKEND_EXAMPLE = {
  connection: {
    provider: "hubspot",
    status: "active",
    accountLabel: "Portal 111",
    connectedByName: "Seeded test principal",
    connectedAt: "2026-10-25T18:52:09.106166+00:00",
  },
  canManage: true,
  research: {
    state: "permission_needed",
    failedField: null,
    reason: "The connected HubSpot user doesn’t have permission to create fields on company records.",
    reviewChat: null,
    items: [
      {
        key: "company_research_links",
        title: "Company research links",
        description: "A link on each company record to its research in Clue.",
        status: "permission_needed",
      },
      {
        key: "contact_profile_links",
        title: "Contact profile links",
        description: "A link on each contact record to the person’s Clue profile.",
        status: "pending",
      },
      {
        key: "contact_buying_roles",
        title: "Contacts’ buying roles",
        description: "The person’s role in the buying decision, saved on their contact record.",
        status: "pending",
      },
      {
        key: "company_fit",
        title: "Company fit",
        description: "High, Medium, or Low fit, saved in the “Clue fit level” field.",
        status: "pending",
      },
    ],
  },
  permissions: [
    {
      grantId: "dad429b8-988a-4af5-b450-9da88a7ae87a",
      description: "Always set Clue fit level on companies",
      grantedByName: "Seeded test principal",
      grantedAt: "2026-10-25T18:52:09.106166+00:00",
    },
  ],
  overwrites: "ask",
  askClueProjectId: "prj_2059f30cfe74431d958fbf2ffc5c9961",
};

test("the backend's own GET /crm/integration example parses", () => {
  const parsed = CrmIntegrationSchema.parse(BACKEND_EXAMPLE);
  assert.equal(parsed.research.state, "permission_needed");
  assert.equal(parsed.permissions[0]?.description, "Always set Clue fit level on companies");
});

test("a fixture of every research state parses, for both CRMs", () => {
  for (const provider of ["hubspot", "salesforce"] as const) {
    for (const state of CRM_RESEARCH_STATES) {
      const parsed = CrmIntegrationSchema.parse(crmIntegrationFixture(state, provider));
      assert.equal(parsed.research.state, state);
      assert.equal(parsed.research.items.length, 4);
      if (state === "not_connected") assert.equal(parsed.connection, null);
      else assert.equal(parsed.connection?.provider, provider);
    }
  }
});

test("a review chat outside approval_needed is refused (Task 3 ruling)", () => {
  const wrong = structuredClone(BACKEND_EXAMPLE);
  (wrong.research as { reviewChat: unknown }).reviewChat = { projectId: "p", threadId: "t" };
  assert.equal(CrmIntegrationSchema.safeParse(wrong).success, false);

  const approval = crmIntegrationFixture("approval_needed", "hubspot");
  assert.ok(CrmIntegrationSchema.parse(approval).research.reviewChat);
});

test("a disconnected connection and a nameless person still parse", () => {
  const payload = structuredClone(BACKEND_EXAMPLE);
  payload.connection.status = "disconnected";
  (payload.connection as { connectedByName: string | null }).connectedByName = null;
  (payload.permissions[0] as { grantedByName: string | null }).grantedByName = null;
  assert.equal(CrmIntegrationSchema.parse(payload).connection?.status, "disconnected");
});

test("an unknown research state or overwrite mode fails loudly", () => {
  const badState = structuredClone(BACKEND_EXAMPLE);
  badState.research.state = "done";
  assert.equal(CrmIntegrationSchema.safeParse(badState).success, false);
  const badMode = structuredClone(BACKEND_EXAMPLE);
  badMode.overwrites = "always";
  assert.equal(CrmIntegrationSchema.safeParse(badMode).success, false);
});

function items(statuses: Partial<Record<string, CrmSetupItem["status"]>>): CrmSetupItem[] {
  return crmIntegrationFixture("approval_needed", "hubspot").research.items.map((item) => ({
    ...item,
    status: statuses[item.key] ?? "created",
  }));
}

test("approval needed: board 07 2310:2501, member view 2310:2552", () => {
  const copy = researchStateCopy("approval_needed", "hubspot");
  assert.equal(copy.sectionTitle, "Research in HubSpot");
  assert.equal(copy.statusLabel, "Approval needed");
  assert.equal(copy.title, "Clue needs permission to prepare HubSpot for your research.");
  assert.equal(
    copy.body,
    "An owner or admin can review the request in chat. Once approved, Clue creates and checks the required fields.",
  );
  assert.equal(
    copy.memberBody,
    "Clue is waiting for an owner or admin to approve preparation in chat.",
  );
  assert.deepEqual(copy.action, {
    kind: "review_request",
    label: "Review request",
    askClueMessage: "Set up Clue’s fields in HubSpot.",
  });
  assert.equal(copy.showDetailsLabel, "View details ▾");
  assert.equal(copy.hideDetailsLabel, "Hide details ▴");

  const sf = researchStateCopy("approval_needed", "salesforce");
  assert.equal(sf.sectionTitle, "Research in Salesforce");
  assert.equal(sf.title, "Clue needs permission to prepare Salesforce for your research.");
  assert.equal(sf.action?.askClueMessage, "Set up Clue’s fields in Salesforce.");
});

test("preparing: board 07 2310:2518", () => {
  const copy = researchStateCopy("preparing", "hubspot");
  assert.equal(copy.statusLabel, "Preparing");
  assert.equal(copy.title, "Clue is preparing HubSpot…");
  assert.equal(
    copy.body,
    "Clue is creating and checking the fields for your research. We’ll show you when HubSpot is ready.",
  );
  assert.equal(copy.action, null);
  assert.equal(researchStateCopy("preparing", "salesforce").title, "Clue is preparing Salesforce…");
});

test("needs attention names the deleted item: board 07 2310:2535", () => {
  const copy = researchStateCopy(
    "needs_attention",
    "hubspot",
    items({ company_research_links: "missing" }),
    "Clue research link",
  );
  assert.equal(copy.statusLabel, "Needs attention");
  assert.equal(copy.title, "Company research links can’t be saved.");
  assert.equal(
    copy.body,
    "The field Clue uses for company research links was deleted in HubSpot. Ask Clue to propose restoring it; an owner or admin approves the request in chat.",
  );
  assert.deepEqual(copy.action, {
    kind: "ask_clue",
    label: "Ask Clue to restore",
    askClueMessage: "Restore Clue’s “Clue research link” field in HubSpot.",
  });

  const sf = researchStateCopy(
    "needs_attention",
    "salesforce",
    items({ contact_buying_roles: "missing" }),
    "Clue committee role",
  );
  assert.equal(sf.title, "Contacts’ buying roles can’t be saved.");
  assert.match(sf.body, /^The field Clue uses for contacts’ buying roles was deleted in Salesforce\./);
});

test("needs attention for a field outside the four items still reads plainly", () => {
  const copy = researchStateCopy("needs_attention", "hubspot", items({}), "Clue id");
  assert.equal(copy.title, "A field Clue uses can’t be saved.");
  assert.equal(
    copy.body,
    "Clue’s “Clue id” field was deleted in HubSpot. Ask Clue to propose restoring it; an owner or admin approves the request in chat.",
  );
});

test("couldn't finish: board 07 2310:2591", () => {
  const copy = researchStateCopy("couldnt_finish", "hubspot");
  assert.equal(copy.statusLabel, "Couldn’t finish");
  assert.equal(copy.title, "Clue couldn’t finish preparing HubSpot.");
  assert.equal(
    copy.body,
    "Some fields are ready. Clue can retry the remaining setup, with owner or admin approval in chat.",
  );
  assert.deepEqual(copy.action, {
    kind: "ask_clue",
    label: "Ask Clue to retry",
    askClueMessage: "Finish setting up Clue’s fields in HubSpot.",
  });
});

test("permission needed: board 07 2338:2403 collapsed, 2338:2477 expanded", () => {
  const copy = researchStateCopy(
    "permission_needed",
    "hubspot",
    items({ contact_buying_roles: "permission_needed" }),
  );
  assert.equal(copy.statusLabel, "Permission needed");
  assert.equal(copy.title, "Clue needs help from your HubSpot admin.");
  assert.equal(
    copy.body,
    "The connected HubSpot user can’t create fields on contact records. Your admin needs to grant that access before Clue can finish preparing HubSpot.",
  );
  assert.equal(copy.expandedBody, "Clue couldn’t finish preparing contact fields.");
  assert.equal(copy.details.heading, "What Clue has prepared");
  assert.deepEqual(copy.details.blocking, {
    heading: "What’s blocking completion",
    body: "The connected HubSpot user doesn’t have permission to create contact fields.",
  });
  assert.deepEqual(copy.details.nextSteps, {
    heading: "What happens next",
    body: "Ask your HubSpot admin to grant that user permission to create fields on contact records. An owner or admin can then ask Clue to retry. Clue performs the setup; you don’t need to create fields yourself.",
  });
  assert.equal(copy.action?.label, "Ask Clue to retry");
  assert.equal(copy.action?.askClueMessage, "Finish setting up Clue’s fields in HubSpot.");

  const sf = researchStateCopy(
    "permission_needed",
    "salesforce",
    items({ company_research_links: "permission_needed" }),
  );
  assert.equal(
    sf.body,
    "The connected Salesforce user can’t create fields on account records. Your admin needs to grant that access before Clue can finish preparing Salesforce.",
  );
  assert.equal(sf.expandedBody, "Clue couldn’t finish preparing account fields.");
});

test("permission needed with no refused item names no records it cannot know", () => {
  const copy = researchStateCopy("permission_needed", "salesforce", items({}));
  assert.equal(
    copy.body,
    "The connected Salesforce user can’t create fields on these records. Your admin needs to grant that access before Clue can finish preparing Salesforce.",
  );
  assert.equal(copy.expandedBody, "Clue couldn’t finish preparing Salesforce.");
});

test("ready: board 07 2338:2427 (HubSpot) and 2338:2538 (Salesforce)", () => {
  const hs = researchStateCopy("ready", "hubspot");
  assert.equal(hs.statusLabel, "Ready");
  assert.equal(hs.title, "HubSpot is ready to receive your research.");
  assert.equal(hs.body, "Clue has prepared the fields for your research.");
  assert.equal(hs.action, null);
  assert.equal(hs.details.heading, "HubSpot preparation details");
  assert.equal(
    hs.details.intro,
    "Clue adds fields to your company and contact records so approved research can be saved there. Creating fields does not write research values.",
  );
  assert.deepEqual(hs.details.columns, { item: "What Clue is preparing", progress: "Progress" });
  assert.deepEqual(hs.details.whereToFind, {
    heading: "Where to find this in HubSpot",
    lines: ["Open a company or contact record and look for its Clue properties."],
  });
  assert.equal(
    hs.details.footer,
    "Details are read-only. Record updates follow your chat approvals and standing permissions.",
  );

  const sf = researchStateCopy("ready", "salesforce");
  assert.equal(sf.title, "Salesforce is ready to receive your research.");
  assert.equal(sf.details.heading, "Salesforce preparation details");
  assert.equal(
    sf.details.intro,
    "Clue adds fields to your account and contact records so approved research can be saved there. Creating fields does not write research values.",
  );
  assert.deepEqual(sf.details.whereToFind, {
    heading: "Where to find this in Salesforce",
    lines: [
      "Open an account or contact record and look for the fields labelled Clue.",
      "With your approval, Clue also grants the connected user access to these fields.",
    ],
  });
});

test("not connected has plain copy in the same voice (no board)", () => {
  const copy = researchStateCopy("not_connected", "hubspot");
  assert.equal(copy.statusLabel, "Not connected");
  assert.equal(copy.title, "Connect HubSpot to prepare it for your research.");
  assert.equal(copy.action, null);
});

test("no copy shows an API name or an id", () => {
  for (const provider of ["hubspot", "salesforce"] as const) {
    for (const state of CRM_RESEARCH_STATES) {
      const copy = researchStateCopy(
        state as CrmResearchState,
        provider,
        items({ company_fit: "permission_needed" }),
        "Clue fit level",
      );
      const text = JSON.stringify(copy);
      assert.doesNotMatch(text, /clue_[a-z_]+|__c\b|_id\b/, `${provider}/${state}`);
    }
  }
});

test("item progress labels read as the design's", () => {
  assert.equal(setupItemStatusLabel("created", "hubspot"), "Created");
  assert.equal(setupItemStatusLabel("permission_needed", "hubspot"), "Permission needed");
  assert.equal(setupItemStatusLabel("pending", "salesforce"), "Not created yet");
  assert.equal(setupItemStatusLabel("missing", "salesforce"), "Deleted in Salesforce");
});
