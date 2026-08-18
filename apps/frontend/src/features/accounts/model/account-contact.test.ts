import assert from "node:assert/strict";
import test from "node:test";
import { AccountContactSummarySchema } from "./account-contact";

const base = {
  id: "contact-1",
  name: "Dana Buyer",
  title: "VP Finance",
  titleRestricted: false,
  persona: "economic_buyer",
  roleOnCommittee: {
    value: "economic_buyer",
    confidence: 0.8,
    reasoning: "Owns the financial approval for this workflow.",
  },
  linkedinUrl: "https://linkedin.example.test/in/dana",
  projectIds: ["project-1"],
  signals: { typeCount: 1 },
} as const;

test("email lookup is absent before the first durable request", () => {
  const parsed = AccountContactSummarySchema.parse(base);
  assert.equal(parsed.emailLookup, null);
  assert.equal(
    parsed.roleOnCommittee.reasoning,
    "Owns the financial approval for this workflow.",
  );
});

test("matching providers remain one email with both sources", () => {
  const parsed = AccountContactSummarySchema.parse({
    ...base,
    emailLookup: {
      lookupId: "lookup-1",
      state: "available",
      resolution: "matched",
      emails: [
        {
          value: "dana@example.com",
          sources: [
            { key: "exa_websets", label: "Exa" },
            { key: "sumble_people", label: "Sumble" },
          ],
        },
      ],
      retryable: false,
    },
  });
  assert.equal(parsed.emailLookup?.emails.length, 1);
  assert.deepEqual(
    parsed.emailLookup?.emails[0]?.sources.map((source) => source.label),
    ["Exa", "Sumble"],
  );
});

test("provider conflicts preserve both source-labelled addresses", () => {
  const parsed = AccountContactSummarySchema.parse({
    ...base,
    emailLookup: {
      lookupId: "lookup-1",
      state: "available",
      resolution: "conflict",
      emails: [
        {
          value: "dana@example.com",
          sources: [{ key: "exa_websets", label: "Exa" }],
        },
        {
          value: "dana@example.ai",
          sources: [{ key: "sumble_people", label: "Sumble" }],
        },
      ],
      retryable: false,
    },
  });
  assert.deepEqual(
    parsed.emailLookup?.emails.map((email) => [email.value, email.sources[0]?.label]),
    [
      ["dana@example.com", "Exa"],
      ["dana@example.ai", "Sumble"],
    ],
  );
});
