import assert from "node:assert/strict";
import test from "node:test";
import { getAccountPreviewRows, getAccounts } from "./accounts.repository";

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

test("projectId filters by membership, and rows keep their full projects array", async () => {
  const response = await getAccounts({ projectId: "custom-reports" });

  assert.deepEqual(
    response.data.map((account) => account.name),
    ["Perplexity AI", "Mistral AI", "Antigravity", "Midjourney", "Cursor"],
  );
  assert.equal(response.meta.total, 5);
  // Cursor is targeted by two projects; filtering by one still returns both.
  const cursor = response.data.find((account) => account.id === "cursor");
  assert.equal(cursor?.projects.length, 2);
});

test("an unknown project is an empty page, not an error", async () => {
  const response = await getAccounts({ projectId: "no-such-project" });

  assert.deepEqual(response.data, []);
  assert.equal(response.meta.total, 0);
  assert.equal(response.meta.nextCursor, null);
});

test("a membership-less account still parses with every enrichment field absent", async () => {
  const response = await getAccounts();
  const neuralink = response.data.find((account) => account.id === "neuralink");

  assert.ok(neuralink);
  assert.equal(neuralink.domain, null);
  assert.equal(neuralink.employeeCount, null);
  assert.equal(neuralink.revenueBand, null);
  assert.equal(neuralink.logoUrl, null);
  assert.equal(neuralink.primaryProjectId, null);
  assert.deepEqual(neuralink.projects, []);
  assert.deepEqual(neuralink.scores, []);
  assert.deepEqual(neuralink.researchStatus, []);
});
