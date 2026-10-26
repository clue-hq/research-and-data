import assert from "node:assert/strict";
import test from "node:test";
import {
  crmWriteAnswer,
  crmWriteCard,
  crmWriteDoneLine,
  crmWriteGroupOutcome,
  crmWriteRefusal,
  crmWriteRecordsCaption,
  pausedCaption,
  groupTickState,
  initialSelection,
  selectedCount,
  toggleGroup,
  toggleRecord,
} from "./crm-write";

const W = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;

/** A card snapshot as `card_snapshot` (write_prepare.py) stores it on the gate. */
function snapshot(crm: "hubspot" | "salesforce" = "hubspot") {
  return {
    crm,
    project_name: "Q4 hotel groups",
    state: "asking",
    title: `Clue wants to update ${crm === "hubspot" ? "HubSpot" : "Salesforce"}`,
    description: 'For "Q4 hotel groups". Nothing is sent until you allow it.',
    groups: [
      {
        kind: "list_membership",
        object: "contact",
        field: null,
        field_label: null,
        list_ref: "Clue: Q4 hotel groups",
        title: 'Add 2 contacts to the list "Clue: Q4 hotel groups"',
        count: 2,
        value_summary: null,
        reason: "The buying committees found for the accounts.",
        records: [
          { write_id: W(1), record_ref: "c1", name: "ana@acme.com", before: false, after: true },
          { write_id: W(2), record_ref: "c2", name: "bo@acme.com", before: false, after: true },
        ],
        scope_key: "hubspot:list_membership:contact",
        always_allow: "adding records to Clue lists and campaigns",
        selected: true,
      },
      {
        kind: "field_update",
        object: "company",
        field: "icp_tier",
        field_label: "ICP tier",
        list_ref: null,
        title: 'Set "ICP tier" on 2 companies',
        count: 2,
        value_summary: "Empty today → Tier 1 (1), Tier 2 (1)",
        reason: "Tiers from the confirmed ICP.",
        records: [
          { write_id: W(3), record_ref: "co1", name: "Acme", before: null, after: "Tier 1" },
          { write_id: W(4), record_ref: "co2", name: "Contoso", before: null, after: "Tier 2" },
        ],
        scope_key: "hubspot:field_update:company:icp_tier",
        always_allow: 'setting "ICP tier" on companies',
        selected: true,
      },
    ],
    overwrites_heading: "1 change overwrites a value a person set",
    overwrites: [
      {
        write_id: W(5),
        record_ref: "co3",
        name: "Initech",
        field: "lifecyclestage",
        field_label: "Lifecycle stage",
        before: "Lead",
        after: "Opportunity",
        set_by: null,
        set_at: null,
        set_by_text: "Who set it isn't known",
        reason: "It has an open opportunity.",
        selected: false,
      },
    ],
    standing_permissions: [
      { scope_key: "hubspot:list_membership:contact", phrase: "adding records to Clue lists and campaigns", selected: false },
      { scope_key: "hubspot:field_update:company:icp_tier", phrase: 'setting "ICP tier" on companies', selected: false },
    ],
    allow_count: 4,
    caption: "Any member of this workspace can answer.",
  };
}

function card(crm: "hubspot" | "salesforce" = "hubspot") {
  const model = crmWriteCard(snapshot(crm));
  assert.ok(model, "the snapshot parses into a card");
  return model;
}

test("groups default ticked and overwrites unticked", () => {
  const model = card();
  const selection = initialSelection(model);
  assert.deepEqual([...selection].sort(), [W(1), W(2), W(3), W(4)]);
  assert.equal(selection.has(W(5)), false);
  assert.equal(selectedCount(selection), 4);
  assert.equal(groupTickState(model.groups[0]!, selection), "all");
  assert.deepEqual(
    model.standingPermissions.map((permission) => permission.label),
    [
      "Always allow adding records to Clue lists and campaigns",
      'Always allow setting "ICP tier" on companies',
    ],
  );
});

test("unticking a record makes its group partial", () => {
  const model = card();
  const group = model.groups[1]!;
  let selection = toggleRecord(initialSelection(model), W(3));
  assert.equal(groupTickState(group, selection), "some");
  selection = toggleRecord(selection, W(4));
  assert.equal(groupTickState(group, selection), "none");
  // A partial or empty group ticks every record again; a full one unticks them all.
  selection = toggleGroup(selection, group);
  assert.equal(groupTickState(group, selection), "all");
  selection = toggleGroup(selection, group);
  assert.equal(groupTickState(group, selection), "none");
  assert.equal(selectedCount(selection), 2);
});

test("the answer lists exactly the ticked changes", () => {
  const model = card();
  let selection = toggleRecord(initialSelection(model), W(2));
  selection = toggleRecord(selection, W(5));
  const answer = crmWriteAnswer(
    model,
    selection,
    new Set(["hubspot:field_update:company:icp_tier", "not-offered"]),
  );
  // In the card's own order; overwrites ticked by hand are included; a scope the card never
  // offered is not.
  assert.deepEqual(answer, {
    selected_write_ids: [W(1), W(3), W(4), W(5)],
    always_allow: ["hubspot:field_update:company:icp_tier"],
  });
});

test("wording follows the CRM (list vs campaign, company vs account, singular)", () => {
  const hubspot = card("hubspot");
  const salesforce = crmWriteCard({
    ...snapshot("salesforce"),
    groups: snapshot("salesforce").groups.map((group) =>
      group.kind === "field_update" ? { ...group, object: "account" } : group,
    ),
  });
  assert.ok(salesforce);
  const all = { chosen: 2, done: 2, failed: 0, skipped: 0, pending: 0 };
  const one = { chosen: 1, done: 1, failed: 0, skipped: 0, pending: 0 };
  const some = { chosen: 2, done: 1, failed: 1, skipped: 0, pending: 0 };

  assert.equal(
    crmWriteDoneLine("hubspot", hubspot.groups[0]!, all),
    'Added 2 contacts to the list "Clue: Q4 hotel groups"',
  );
  assert.equal(
    crmWriteDoneLine("salesforce", salesforce.groups[0]!, one),
    'Added 1 contact to the campaign "Clue: Q4 hotel groups"',
  );
  assert.equal(
    crmWriteDoneLine("hubspot", hubspot.groups[1]!, some),
    'Set "ICP tier" on 1 of 2 companies',
  );
  assert.equal(
    crmWriteDoneLine("salesforce", salesforce.groups[1]!, one),
    'Set "ICP tier" on 1 account',
  );
  assert.equal(crmWriteRecordsCaption(hubspot.groups[1]!), "2 companies");
  assert.equal(crmWriteRecordsCaption(salesforce.groups[1]!), "2 accounts");
  assert.equal(
    crmWriteRecordsCaption({ ...hubspot.groups[0]!, records: hubspot.groups[0]!.records.slice(0, 1) }),
    "1 contact",
  );
  // The asking-state titles are the server's own words (card spec §5), shown as sent.
  assert.equal(hubspot.title, "Clue wants to update HubSpot");
  assert.equal(salesforce.title, "Clue wants to update Salesforce");
});

test("a list Clue creates and a company list are worded by what they hold (Phase 3)", () => {
  const base = snapshot("hubspot").groups[0]!;
  const create = (crm: "hubspot" | "salesforce") =>
    crmWriteCard({
      ...snapshot(crm),
      groups: [
        {
          ...base,
          kind: "list_create",
          object: crm === "hubspot" ? "list" : "campaign",
          list_ref: null,
          title: `Create the ${crm === "hubspot" ? "list" : "campaign"} "Clue: Q4"`,
          count: 1,
          records: [{ write_id: W(9), record_ref: null, name: "Clue: Q4", after: { name: "Clue: Q4" } }],
          scope_key: "kind:list_create",
          always_allow: `creating Clue ${crm === "hubspot" ? "lists" : "campaigns"}`,
        },
        {
          ...base,
          object: "company",
          list_ref: "Clue: Conduit AI hotel operators",
          title: 'Add 2 companies to the list "Clue: Conduit AI hotel operators"',
        },
      ],
    });
  const hubspot = create("hubspot");
  const salesforce = create("salesforce");
  assert.ok(hubspot && salesforce);
  const one = { chosen: 1, done: 1, failed: 0, skipped: 0, pending: 0 };
  const two = { chosen: 2, done: 2, failed: 0, skipped: 0, pending: 0 };

  assert.equal(hubspot.groups[0]!.title, 'Create the list "Clue: Q4"');
  assert.equal(hubspot.groups[0]!.alwaysAllowPhrase, "creating Clue lists");
  assert.equal(salesforce.groups[0]!.title, 'Create the campaign "Clue: Q4"');
  assert.equal(salesforce.groups[0]!.alwaysAllowPhrase, "creating Clue campaigns");
  assert.equal(crmWriteDoneLine("hubspot", hubspot.groups[0]!, one), 'Created the list "Clue: Q4"');
  assert.equal(
    crmWriteDoneLine("salesforce", salesforce.groups[0]!, one),
    'Created the campaign "Clue: Q4"',
  );
  assert.equal(crmWriteRecordsCaption(hubspot.groups[0]!), "1 list");
  assert.equal(crmWriteRecordsCaption(salesforce.groups[0]!), "1 campaign");
  // A HubSpot company list holds companies, not contacts.
  assert.equal(
    crmWriteDoneLine("hubspot", hubspot.groups[1]!, two),
    'Added 2 companies to the list "Clue: Conduit AI hotel operators"',
  );
  assert.equal(crmWriteRecordsCaption(hubspot.groups[1]!), "2 companies");
});

test("a card names lists, campaigns and companies by the names the server sends (R-12.13)", () => {
  const base = snapshot("salesforce").groups[0]!;
  const model = crmWriteCard({
    ...snapshot("salesforce"),
    groups: [
      {
        ...base,
        list_ref: "Clue: US employer benefits",
        title: 'Add 4 contacts to the campaign "Clue: US employer benefits"',
        count: 4,
      },
      {
        ...snapshot("hubspot").groups[1]!,
        object: "contact",
        field: "associatedcompanyid",
        field_label: "Primary Associated Company ID",
        title: 'Set "Primary Associated Company ID" on 1 contact',
        count: 1,
        value_summary: "Empty today → Atrium Hospitality (1)",
        records: [
          {
            write_id: W(7),
            record_ref: "201",
            name: "Holly Herrera",
            before: null,
            after: "Atrium Hospitality",
          },
        ],
      },
    ],
  });
  assert.ok(model);
  const [campaign, company] = model.groups;
  assert.equal(campaign!.title, 'Add 4 contacts to the campaign "Clue: US employer benefits"');
  assert.equal(
    crmWriteDoneLine("salesforce", campaign!, { chosen: 4, done: 4, failed: 0, skipped: 0, pending: 0 }),
    'Added 4 contacts to the campaign "Clue: US employer benefits"',
  );
  assert.equal(company!.title, 'Set "Primary Associated Company ID" on 1 contact');
  assert.equal(company!.valueSummary, "Empty today → Atrium Hospitality (1)");
  assert.ok(!JSON.stringify(model).includes('"17"'));
});

test("a list create that did not happen never reads as created", () => {
  const model = crmWriteCard({
    ...snapshot("salesforce"),
    groups: [
      {
        ...snapshot("salesforce").groups[0]!,
        kind: "list_create",
        object: "campaign",
        list_ref: null,
        title: 'Create the campaign "Clue: Q4"',
        count: 1,
        records: [{ write_id: W(9), record_ref: null, name: "Clue: Q4", after: { name: "Clue: Q4" } }],
        scope_key: "kind:list_create",
        always_allow: "creating Clue campaigns",
      },
    ],
  });
  assert.ok(model);
  const group = model.groups[0]!;
  // Salesforce refused it (the user is not a Marketing User).
  assert.deepEqual(
    crmWriteGroupOutcome("salesforce", group, { chosen: 1, done: 0, failed: 1, skipped: 0, pending: 0 }),
    { mark: "failed", line: 'Could not create the campaign "Clue: Q4" — 1 failed' },
  );
  // Skipped: the CRM already had one of that name.
  assert.deepEqual(
    crmWriteGroupOutcome("salesforce", group, { chosen: 1, done: 0, failed: 0, skipped: 1, pending: 0 }),
    { mark: "failed", line: 'Did not create the campaign "Clue: Q4" — 1 skipped' },
  );
  assert.deepEqual(
    crmWriteGroupOutcome("salesforce", group, { chosen: 1, done: 1, failed: 0, skipped: 0, pending: 0 }),
    { mark: "done", line: 'Created the campaign "Clue: Q4"' },
  );
});

test("a group where nothing succeeded is shown as failed, with its count", () => {
  const model = card();
  assert.deepEqual(
    crmWriteGroupOutcome("hubspot", model.groups[1]!, {
      chosen: 2, done: 0, failed: 2, skipped: 0, pending: 0,
    }),
    { mark: "failed", line: 'Set "ICP tier" on 0 of 2 companies — 2 failed' },
  );
  assert.deepEqual(
    crmWriteGroupOutcome("hubspot", model.groups[1]!, {
      chosen: 2, done: 1, failed: 1, skipped: 0, pending: 0,
    }),
    { mark: "done", line: 'Set "ICP tier" on 1 of 2 companies' },
  );
});

test("a stale card says it can no longer be answered, never to try again", () => {
  const message = crmWriteRefusal("GATE_SUBJECT_STALE");
  assert.match(message, /can no longer be answered/);
  assert.doesNotMatch(message, /try again/i);
});

test("the paused card says a reconnect does not resume the unsent changes (R-11.10)", () => {
  const caption = pausedCaption("HubSpot");
  assert.equal(
    caption,
    "If you reconnect HubSpot, the changes not yet sent are not sent; Clue will propose them again.",
  );
  assert.doesNotMatch(caption, /carries on/i);
});

test("a click that lost the race says someone answered first (final review M-1)", () => {
  assert.equal(crmWriteRefusal("CRM_WRITE_ALREADY_ANSWERED"), "Someone answered this card first.");
});

test("a refusal says what happened, never what Clue will do next", () => {
  for (const code of ["GATE_SUBJECT_STALE", "CRM_CONNECTION_CHANGED", "CRM_WRITE_ALREADY_ANSWERED"]) {
    assert.doesNotMatch(crmWriteRefusal(code), /propose/i, code);
  }
});

// --- setting up Clue's own fields (CRM integration Phase 4, Task 2) -------

const SALESFORCE_LINE =
  "Creates a 'Clue fields' permission set and gives your connected Salesforce user access to these fields.";

/** A setup card as `clue_fields_setup_snapshot` (write_prepare.py) stores it on the gate. */
function setupSnapshot() {
  return {
    crm: "salesforce",
    project_name: "Q4 hotel groups",
    state: "asking",
    title: "Clue wants to set up its own fields in Salesforce",
    description:
      'For "Q4 hotel groups". Nothing changes in Salesforce until a workspace owner or admin allows it.',
    groups: [
      {
        kind: "clue_fields_setup",
        object: "clue_fields",
        field: null,
        field_label: null,
        list_ref: null,
        title: "Set up Clue's fields in Salesforce",
        count: 1,
        value_summary: null,
        reason: "So Clue can write its research into fields of its own.",
        records: [{ write_id: W(9), record_ref: null, name: "Clue's fields", before: null, after: null }],
        scope_key: "kind:clue_fields_setup",
        always_allow: "",
        selected: true,
        setup_fields: [
          { object: "Account", label: "Clue fit level", type: "Dropdown" },
          { object: "Contact", label: "Clue id", type: "Text" },
        ],
        setup_notes: [SALESFORCE_LINE, "Clue never deletes these; an admin can remove them in Salesforce."],
      },
    ],
    overwrites_heading: null,
    overwrites: [],
    standing_permissions: [],
    allow_count: 1,
    caption: "Only a workspace owner or admin can allow this.",
  };
}

test("the setup card lists Clue's fields and what else changes, and offers no Always allow", () => {
  const model = crmWriteCard(setupSnapshot());
  assert.ok(model);
  assert.equal(model.caption, "Only a workspace owner or admin can allow this.");
  assert.deepEqual(model.standingPermissions, []);
  const [group] = model.groups;
  assert.ok(group);
  assert.equal(group.kind, "clue_fields_setup");
  assert.deepEqual(
    group.setupFields.map((field) => `${field.object} · ${field.label} (${field.type})`),
    ["Account · Clue fit level (Dropdown)", "Contact · Clue id (Text)"],
  );
  assert.ok(group.setupNotes.includes(SALESFORCE_LINE));
  // The one change is ticked; Allow sends it and grants nothing.
  const selection = initialSelection(model);
  assert.deepEqual(crmWriteAnswer(model, selection, new Set(["kind:clue_fields_setup"])), {
    selected_write_ids: [W(9)],
    always_allow: [],
  });
});

test("an ordinary group has no setup fields", () => {
  const model = card();
  assert.deepEqual(model.groups[0]!.setupFields, []);
  assert.deepEqual(model.groups[0]!.setupNotes, []);
});

test("the setup outcome says whether Clue's fields were set up", () => {
  const model = crmWriteCard(setupSnapshot());
  assert.ok(model);
  const group = model.groups[0]!;
  assert.deepEqual(
    crmWriteGroupOutcome("salesforce", group, { chosen: 1, done: 1, failed: 0, skipped: 0, pending: 0 }),
    { mark: "done", line: "Set up Clue's fields in Salesforce" },
  );
  assert.deepEqual(
    crmWriteGroupOutcome("salesforce", group, { chosen: 1, done: 0, failed: 1, skipped: 0, pending: 0 }),
    { mark: "failed", line: "Could not set up Clue's fields in Salesforce — 1 failed" },
  );
  // Skipped because the connection was already set up: not a failure.
  assert.deepEqual(
    crmWriteGroupOutcome("salesforce", group, { chosen: 1, done: 0, failed: 0, skipped: 1, pending: 0 }),
    { mark: "done", line: "Clue's fields were already set up in Salesforce" },
  );
});

test("an operator's Allow on the setup card is refused in plain words", () => {
  assert.equal(
    crmWriteRefusal("crm_setup_needs_admin"),
    "Only a workspace owner or admin can set up Clue's fields.",
  );
});

test("a duplicate link names both people and no record ids (Phase 4, R-6.13)", () => {
  const model = crmWriteCard({
    crm: "salesforce",
    project_name: "Q4",
    title: "Clue wants to update Salesforce",
    description: 'For "Q4". Nothing is sent until you allow it.',
    groups: [
      {
        kind: "link_duplicate",
        object: "contact",
        field: null,
        field_label: null,
        list_ref: null,
        title: "Mark 1 possible duplicate",
        count: 1,
        value_summary: null,
        reason: "Two Salesforce contacts for Nick",
        records: [
          {
            write_id: W(11),
            record_ref: "003A",
            name: "Nick Fisher and Nicholas Fisher (nick@zafran.io)",
            before: null,
            after: null,
          },
        ],
        scope_key: "kind:link_duplicate",
        always_allow: "marking possible duplicates",
      },
    ],
  });
  assert.ok(model);
  const group = model.groups[0]!;
  assert.equal(group.title, "Mark 1 possible duplicate");
  assert.deepEqual(
    group.records.map((record) => [record.name, record.change]),
    [["Nick Fisher and Nicholas Fisher (nick@zafran.io)", null]],
  );
  assert.equal(group.alwaysAllowPhrase, "marking possible duplicates");
  assert.deepEqual(
    crmWriteGroupOutcome("salesforce", group, { chosen: 1, done: 1, failed: 0, skipped: 0, pending: 0 }),
    { mark: "done", line: "Marked 1 possible duplicate" },
  );
});
