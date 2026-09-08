import assert from "node:assert/strict";
import test from "node:test";
import {
  createAccountColumnDefinitions,
  defaultAccountColumnOrder,
  defaultAccountColumns,
  getFirstScrollableAccountColumn,
  type AccountColumnKey,
} from "./account-table-view";
import type { Account } from "./account";

test("the first visible scrolling column owns no divider beside the pinned company column", () => {
  assert.equal(
    getFirstScrollableAccountColumn(
      defaultAccountColumns,
      defaultAccountColumnOrder,
    ),
    "owner",
  );

  assert.equal(
    getFirstScrollableAccountColumn(
      {
        ...defaultAccountColumns,
        owner: false,
        industry: false,
        research: false,
        fit: false,
      },
      defaultAccountColumnOrder,
    ),
    "score",
  );

  assert.equal(
    getFirstScrollableAccountColumn(
      defaultAccountColumns,
      [
        "company",
        "revenue",
        "research",
        "fit",
        "score",
        "headcount",
        "locations",
        "website",
        "linkedin",
        "twitter",
        "facebook",
        "instagram",
        "created",
        "modified",
      ],
    ),
    "revenue",
  );
});

test("expanded account metrics are available as selectable table columns", () => {
  const keys = createAccountColumnDefinitions([]).map((column) => column.key);
  const expected: AccountColumnKey[] = [
    "owner",
    "industry",
    "headcount",
    "website",
    "linkedin",
    "twitter",
    "facebook",
    "instagram",
    "created",
    "modified",
  ];

  assert.deepEqual(expected.filter((column) => !keys.includes(column)), []);
});

test("workspace account variables become table columns", () => {
  const account = {
    customFields: [
      {
        id: "recall-fit",
        label: "Recall fit",
        presentation: "badge",
        primary: true,
        value: "Medium",
      },
    ],
  } as Account;

  const definitions = createAccountColumnDefinitions([account]);
  const recallFit = definitions.find(
    (column) => column.key === "variable:recall-fit",
  );

  assert.equal(recallFit?.label, "Recall fit");
  assert.equal(recallFit?.kind, "variable");
  assert.equal(recallFit?.variableId, "recall-fit");
});
