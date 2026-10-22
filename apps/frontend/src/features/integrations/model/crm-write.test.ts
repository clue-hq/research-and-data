import assert from "node:assert/strict";
import test from "node:test";
import {
  crmWriteAnswer,
  crmWriteCard,
  crmWriteDoneLine,
  crmWriteGroupOutcome,
  crmWriteRefusal,
  crmWriteRecordsCaption,
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
        always_allow: "adding contacts to Clue lists",
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
      { scope_key: "hubspot:list_membership:contact", phrase: "adding contacts to Clue lists", selected: false },
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
      "Always allow adding contacts to Clue lists",
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
