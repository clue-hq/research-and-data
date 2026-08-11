import assert from "node:assert/strict";
import test from "node:test";
import {
  accountActivityActorLabel,
  accountActivityEventHref,
  accountActivityEventLabel,
  accountActivitySubjectLabel,
  accountActivitySummaryLabel,
} from "./account-activity";
import { formatIsoDateTime } from "./formatting";

test("activity labels are stable presentation mappings over machine values", () => {
  assert.equal(
    accountActivityEventLabel("research_view.section_stale"),
    "Research view needs review",
  );
  assert.equal(accountActivityActorLabel("system"), "Clue system");
  assert.equal(
    accountActivitySummaryLabel({
      state: "not_composed",
      paragraphs: [],
      researchOutcome: null,
    }),
    "Summary not composed",
  );
});

test("Account and governed Contact events derive different safe drill-downs", () => {
  const base = {
    id: "activity-1",
    kind: "research_view.updated" as const,
    occurredAt: "2026-08-12T09:02:00Z",
    actorCategory: "system" as const,
    project: { id: "project-1", name: "Project one" },
    projectRunId: "project-run-1",
    accountRunId: "account-run-1",
    reference: {
      target: "account_insights" as const,
      eventId: "event-1",
      snapshotId: "snapshot-1",
      reportId: null,
      sectionIds: [],
      itemIds: [],
    },
  };
  const accountEvent = {
    ...base,
    subject: { type: "account" as const, id: "account-1", name: "Account one" },
  };
  const contactEvent = {
    ...base,
    subject: { type: "contact" as const, id: "contact-1", name: null },
    reference: { ...base.reference, target: "contact_profile" as const },
  };

  assert.equal(
    accountActivityEventHref("account-1", accountEvent),
    "/accounts/account-1/insights",
  );
  assert.equal(
    accountActivityEventHref("account-1", contactEvent),
    "/accounts/account-1/contacts/contact-1",
  );
  assert.equal(accountActivitySubjectLabel(contactEvent), "Unnamed contact");
});

test("activity timestamps render as stable UTC values rather than relative fixture labels", () => {
  assert.equal(
    formatIsoDateTime("2026-08-12T09:02:00Z"),
    "12 Aug 2026, 09:02 UTC",
  );
  assert.equal(formatIsoDateTime("not-a-timestamp"), null);
});
