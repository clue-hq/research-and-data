import assert from "node:assert/strict";
import test from "node:test";
import { AccountDetailSchema } from "../model/account-detail";
import { formatFieldKeyLabel } from "../model/formatting";
import { prosePresentation } from "../model/prose";

const copy = {
  emptyNote: "No written account summary has been composed yet.",
  restrictedNote: "The account summary is unavailable for display.",
};

test("available prose presents live paragraphs without consulting adjacent status", () => {
  const presentation = prosePresentation(
    {
        state: "available",
        paragraphs: ["Completed live synthesis."],
        researchOutcome: "completed",
    },
    { empty: copy.emptyNote, restricted: copy.restrictedNote },
  );

  assert.deepEqual(presentation, {
    kind: "paragraphs",
    paragraphs: ["Completed live synthesis."],
  });
});

test("not-composed and restricted prose have distinct honest recovery copy", () => {
  const notComposed = prosePresentation(
    {
        state: "not_composed",
        paragraphs: [],
        researchOutcome: null,
    },
    { empty: copy.emptyNote, restricted: copy.restrictedNote },
  );
  assert.deepEqual(notComposed, {
    kind: "message",
    message: "No written account summary has been composed yet.",
  });

  const restricted = prosePresentation(
    {
        state: "restricted",
        paragraphs: [],
        researchOutcome: null,
    },
    { empty: copy.emptyNote, restricted: copy.restrictedNote },
  );
  assert.deepEqual(restricted, {
    kind: "message",
    message: "The account summary is unavailable for display.",
  });
});

test("dynamic research gaps use registry descriptions instead of raw keys", () => {
  const account = AccountDetailSchema.parse({
    id: "account-1",
    name: "Acme",
    coverage: {
      researchedFieldCount: 2,
      unresolvedFieldKeys: ["healthcare.npi"],
      unresolvedFields: [
        {
          fieldKey: "healthcare.npi",
          description:
            "National Provider Identifier (deterministic registry id; tier-1).",
        },
      ],
    },
  });
  const field = account.coverage.unresolvedFields[0];
  assert.equal(formatFieldKeyLabel(field?.fieldKey ?? ""), "Npi");
  assert.equal(
    field?.description,
    "National Provider Identifier (deterministic registry id; tier-1).",
  );
});
