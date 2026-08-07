import assert from "node:assert/strict";
import test from "node:test";
import {
  getAccountPreviewRows,
  getAccounts,
} from "./accounts.repository";

test("account preview reuses the same rows as the accounts table", async () => {
  const [accountsResponse, previewRows] = await Promise.all([
    getAccounts(),
    getAccountPreviewRows(),
  ]);

  assert.deepEqual(
    previewRows.map(({ id, name }) => ({ id, name })),
    accountsResponse.data.map(({ id, name }) => ({ id, name })),
  );
});

test("accounts can be filtered and sorted by project", async () => {
  const response = await getAccounts({
    projectId: "custom-reports",
    sort: "project_asc",
  });

  assert.deepEqual(
    response.data.map((account) => account.name),
    ["Antigravity", "Cursor", "Midjourney", "Mistral AI", "Perplexity AI"],
  );
  assert.equal(response.meta.total, 5);
});
