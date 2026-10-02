import assert from "node:assert/strict";
import test from "node:test";
import { readAccountDirectory, getProjectAccountDirectory } from "./project-accounts.repository";
import { accountFixtures } from "./accounts.fixture";

// The cursor walk is the list read's own (`accounts.repository.ts` follows
// `meta.nextCursor` up to `ACCOUNTS_PAGE_CAP` pages and answers with
// `nextCursor: null`), so the directory is one call: it forwards the project
// and hands back that read's rows as they came.
test("the directory forwards the project and returns the list read's rows in one call", async () => {
  const queries: Array<unknown> = [];
  const rows = await readAccountDirectory({ projectId: "campaign" }, async (query) => {
    queries.push(query);
    return { data: [accountFixtures[0], accountFixtures[1]], meta: { total: 2, nextCursor: null } };
  });
  assert.deepEqual(queries, [{ projectId: "campaign" }]);
  assert.deepEqual(rows, [accountFixtures[0], accountFixtures[1]]);
});

// The default list read is the platform's own `getAccounts`, which chooses
// fixtures or the live HTTP adapter from the accounts fixture switch. The
// design build had no such switch, so this case pins it on explicitly rather
// than reaching for the network.
test("project members are excluded from the add-accounts picker", async (t) => {
  const previous = process.env.CLUE_ACCOUNTS_FIXTURE_MODE;
  process.env.CLUE_ACCOUNTS_FIXTURE_MODE = "true";
  t.after(() => {
    if (previous === undefined) delete process.env.CLUE_ACCOUNTS_FIXTURE_MODE;
    else process.env.CLUE_ACCOUNTS_FIXTURE_MODE = previous;
  });

  const { accounts, availableAccounts } = await getProjectAccountDirectory("custom-reports");
  assert.equal(accounts.length, 5);
  assert.ok(!accounts.some((member) => availableAccounts.some(({ id }) => id === member.id)));
  assert.equal(accounts.length + availableAccounts.length, accountFixtures.length);
});
