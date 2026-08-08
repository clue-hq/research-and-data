import assert from "node:assert/strict";
import test from "node:test";
import {
  defaultAccountColumnOrder,
  defaultAccountColumns,
  getFirstScrollableAccountColumn,
} from "./account-table-view";

test("the first visible scrolling column owns no divider beside the pinned company column", () => {
  assert.equal(
    getFirstScrollableAccountColumn(
      defaultAccountColumns,
      defaultAccountColumnOrder,
    ),
    "research",
  );

  assert.equal(
    getFirstScrollableAccountColumn(
      {
        ...defaultAccountColumns,
        research: false,
      },
      defaultAccountColumnOrder,
    ),
    "score",
  );

  assert.equal(
    getFirstScrollableAccountColumn(defaultAccountColumns, [
      "company",
      "revenue",
      "research",
      "score",
      "size",
      "projects",
    ]),
    "revenue",
  );
});
